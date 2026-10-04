"""Optional missed first-visit fee.

Stripe Checkout in setup mode saves a card and does not charge it. A later
no-show or late cancel can be charged once, on the therapist's Stripe Connect
Express account, so the money is paid to them. Card numbers never touch this
app. Receipts are Stripe's.

The feature stays off unless STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, and
STRIPE_WEBHOOK_SECRET are all set.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from datetime import timedelta
from urllib.parse import quote, urlparse

import httpx

from capacity import first_name, format_long, format_time, uget
from db import notify, now_dt, now_iso, parse_iso

ENV_SECRET = "STRIPE_SECRET_KEY"
ENV_PUBLISHABLE = "STRIPE_PUBLISHABLE_KEY"
ENV_WEBHOOK = "STRIPE_WEBHOOK_SECRET"

MIN_CENTS = 100
MAX_CENTS = 50_000
DEFAULT_WINDOW_HOURS = 24
MIN_WINDOW_HOURS = 1
MAX_WINDOW_HOURS = 168
HOLD_MINUTES = 45

_SECRET_RE = re.compile(
    r"\b(?:sk|rk|pk)_(?:test|live)_[A-Za-z0-9]+|\bwhsec_[A-Za-z0-9]+"
)
# Checkout session ids look like cs_test_… / cs_live_…. Other Stripe ids are
# prefix plus letters and digits. Allow underscores so both forms match.
_ID_RE = {
    "acct": re.compile(r"^acct_[A-Za-z0-9_]+$"),
    "cus": re.compile(r"^cus_[A-Za-z0-9_]+$"),
    "pm": re.compile(r"^pm_[A-Za-z0-9_]+$"),
    "seti": re.compile(r"^seti_[A-Za-z0-9_]+$"),
    "cs": re.compile(r"^cs_[A-Za-z0-9_]+$"),
    "pi": re.compile(r"^pi_[A-Za-z0-9_]+$"),
}


class StripeError(Exception):
    def __init__(self, message: str, code: str = "error"):
        self.message = scrub(message)[:240]
        self.code = code
        super().__init__(self.message)


def configured() -> bool:
    return bool(secret_key() and publishable_key() and webhook_secret())


def secret_key() -> str:
    return (os.environ.get(ENV_SECRET) or "").strip()


def publishable_key() -> str:
    return (os.environ.get(ENV_PUBLISHABLE) or "").strip()


def webhook_secret() -> str:
    return (os.environ.get(ENV_WEBHOOK) or "").strip()


def scrub(text: str) -> str:
    out = _SECRET_RE.sub("[redacted]", text or "")
    for env_name in (ENV_SECRET, ENV_PUBLISHABLE, ENV_WEBHOOK):
        val = os.environ.get(env_name) or ""
        if len(val) >= 8 and val in out:
            out = out.replace(val, "[redacted]")
    return out


def log_fee(msg: str) -> None:
    print(f"[fee] {scrub(msg)}", flush=True)


def money_label(cents: int) -> str:
    cents = int(cents)
    dollars, rem = divmod(abs(cents), 100)
    sign = "-" if cents < 0 else ""
    if rem == 0:
        return f"{sign}${dollars}"
    return f"{sign}${dollars}.{rem:02d}"


def parse_amount_cents(raw) -> int | None:
    """Dollars as typed by a therapist, such as 75 or 75.50. Not a card amount from Stripe."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        raw = str(raw)
    text = str(raw).strip().replace("$", "").replace(",", "")
    if not text or not re.fullmatch(r"\d+(\.\d{1,2})?", text):
        return None
    if "." in text:
        whole, frac = text.split(".", 1)
        frac = (frac + "00")[:2]
        cents = int(whole) * 100 + int(frac)
    else:
        cents = int(text) * 100
    if cents < MIN_CENTS or cents > MAX_CENTS:
        return None
    return cents


def parse_window_hours(raw) -> int | None:
    try:
        hours = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if hours < MIN_WINDOW_HOURS or hours > MAX_WINDOW_HOURS:
        return None
    return hours


def id_ok(value: str, kind: str) -> bool:
    pattern = _ID_RE.get(kind)
    return bool(pattern and pattern.fullmatch(value or ""))


def consent_checked(data: dict) -> bool:
    raw = data.get("feeConsent")
    if raw is None:
        raw = data.get("fee_consent")
    return str(raw or "").strip().lower() in ("1", "true", "yes", "on")


def policy_for(user) -> dict | None:
    """Public notice for a live fee. None means clients must not see or agree to one."""
    if not configured() or user is None:
        return None
    if int(uget(user, "missed_fee_enabled", 0) or 0) != 1:
        return None
    if int(uget(user, "stripe_charges_enabled", 0) or 0) != 1:
        return None
    account = (uget(user, "stripe_account_id", "") or "").strip()
    if not id_ok(account, "acct"):
        return None
    cents = int(uget(user, "missed_fee_cents", 0) or 0)
    if cents < MIN_CENTS or cents > MAX_CENTS:
        return None
    window = int(uget(user, "missed_fee_window_hours", 0) or 0)
    if window < MIN_WINDOW_HOURS or window > MAX_WINDOW_HOURS:
        return None
    name = (uget(user, "name", "") or "your therapist").strip()
    first = first_name(name)
    amount = money_label(cents)
    summary = (
        f"If this is your first visit or intake with {first}, you save a card on the next screen. "
        f"You are not charged today. "
        f"If you miss the visit, or cancel less than {window} hours before it starts, "
        f"{first} may charge that card {amount} once. "
        f"The money is paid to {first}. Stripe emails a receipt if that happens."
    )
    agreement = (
        f"I agree that if I miss my first visit or intake with {name}, "
        f"or I cancel less than {window} hours before it starts, "
        f"{name} may charge the card I save {amount} once. "
        f"I will not be charged today."
    )
    return {
        "amount": amount,
        "amountCents": cents,
        "windowHours": window,
        "summary": summary,
        "agreement": agreement,
    }


def cancel_is_late(start_iso: str, window_hours: int, now=None) -> bool:
    start = parse_iso(start_iso)
    moment = now or now_dt()
    deadline = start - timedelta(hours=int(window_hours))
    return moment > deadline


def _form_body(data: dict) -> str:
    parts = []
    for key, value in data.items():
        text = "" if value is None else str(value)
        if "{CHECKOUT_SESSION_ID}" in text:
            pre, post = text.split("{CHECKOUT_SESSION_ID}", 1)
            encoded = quote(pre, safe="") + "{CHECKOUT_SESSION_ID}" + quote(post, safe="")
        else:
            encoded = quote(text, safe="")
        parts.append(quote(str(key), safe="") + "=" + encoded)
    return "&".join(parts)


def _stripe_message(code: str) -> str:
    code = (code or "").lower()
    if code in {
        "card_declined",
        "generic_decline",
        "insufficient_funds",
        "expired_card",
        "incorrect_cvc",
        "incorrect_number",
        "processing_error",
    }:
        return "The card was declined. Nothing was charged. You can try again."
    if code in {"authentication_required", "card_declined_authentication_required"}:
        return "The bank needs the client to approve this charge. Nothing was charged."
    if "rate" in code:
        return "Stripe is busy. Nothing was charged. Try again in a minute."
    return "Stripe could not complete that. Nothing was charged."


def _safe_stripe_url(url: str) -> str:
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "stripe.com" or host.endswith(".stripe.com")):
        raise StripeError("Stripe returned an unexpected link.", "bad_url")
    return url


def stripe_call(
    method: str,
    path: str,
    data: dict | None = None,
    stripe_account: str = "",
    idempotency_key: str = "",
) -> dict:
    if not configured():
        raise StripeError("Stripe is not configured.", "unconfigured")
    key = secret_key()
    headers = {"Authorization": f"Bearer {key}"}
    if stripe_account:
        if not id_ok(stripe_account, "acct"):
            raise StripeError("Stripe account was not recognized.", "bad_account")
        headers["Stripe-Account"] = stripe_account
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key[:255]
    url = "https://api.stripe.com" + path
    kwargs: dict = {"headers": headers, "timeout": 20.0}
    if data:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        kwargs["content"] = _form_body(data).encode("utf-8")
    try:
        resp = httpx.request(method, url, **kwargs)
    except httpx.HTTPError:
        log_fee(f"stripe network error {method} {path.split('?', 1)[0]}")
        raise StripeError("Stripe could not be reached. Nothing was charged.", "network")
    try:
        body = resp.json()
    except Exception:
        log_fee(f"stripe bad response status={resp.status_code}")
        raise StripeError("Stripe returned an unexpected response.", "bad_response")
    if resp.status_code >= 400:
        err = body.get("error") if isinstance(body, dict) else {}
        err = err or {}
        code = str(err.get("code") or err.get("type") or "error")
        log_fee(f"stripe error status={resp.status_code} code={code}")
        raise StripeError(_stripe_message(code), code)
    if not isinstance(body, dict):
        raise StripeError("Stripe returned an unexpected response.", "bad_response")
    return body


def create_express_account(email: str, slug: str, provider_id: int) -> str:
    body = stripe_call(
        "POST",
        "/v1/accounts",
        {
            "type": "express",
            "country": "US",
            "email": email,
            "capabilities[card_payments][requested]": "true",
            "capabilities[transfers][requested]": "true",
            "business_profile[url]": f"https://scheduleavisit.com/p/{slug}",
            "business_profile[product_description]": (
                "Scheduling and an optional missed first-visit fee. No clinical notes."
            ),
            "metadata[provider_id]": str(provider_id),
            "metadata[purpose]": "missed_intake_fee",
        },
    )
    account = body.get("id") or ""
    if not id_ok(account, "acct"):
        raise StripeError("Stripe did not return an account.", "bad_account")
    return account


def create_account_link(account: str, refresh_url: str, return_url: str, details_submitted: bool) -> str:
    kind = "account_update" if details_submitted else "account_onboarding"
    body = stripe_call(
        "POST",
        "/v1/account_links",
        {
            "account": account,
            "refresh_url": refresh_url,
            "return_url": return_url,
            "type": kind,
        },
    )
    return _safe_stripe_url(body.get("url") or "")


def fetch_account(account: str) -> dict:
    body = stripe_call("GET", f"/v1/accounts/{account}")
    return {
        "charges_enabled": 1 if body.get("charges_enabled") else 0,
        "payouts_enabled": 1 if body.get("payouts_enabled") else 0,
        "details_submitted": 1 if body.get("details_submitted") else 0,
    }


def create_customer(account: str, email: str, name: str) -> str:
    body = stripe_call(
        "POST",
        "/v1/customers",
        {"email": email, "name": name, "metadata[purpose]": "missed_intake_fee"},
        stripe_account=account,
    )
    customer = body.get("id") or ""
    if not id_ok(customer, "cus"):
        raise StripeError("Stripe did not save the client record.", "bad_customer")
    return customer


def create_setup_session(
    account: str,
    customer: str,
    success_url: str,
    cancel_url: str,
    hold_token: str,
) -> tuple[str, str]:
    body = stripe_call(
        "POST",
        "/v1/checkout/sessions",
        {
            "mode": "setup",
            "customer": customer,
            "cancel_url": cancel_url,
            "success_url": success_url,
            "payment_method_types[0]": "card",
            "client_reference_id": hold_token[:200],
            "metadata[hold_token]": hold_token,
            "metadata[purpose]": "missed_intake_fee",
            "setup_intent_data[metadata][hold_token]": hold_token,
            "setup_intent_data[metadata][purpose]": "missed_intake_fee",
        },
        stripe_account=account,
    )
    session_id = body.get("id") or ""
    url = _safe_stripe_url(body.get("url") or "")
    if not id_ok(session_id, "cs"):
        raise StripeError("Stripe did not open the card page.", "bad_session")
    return session_id, url


def retrieve_setup_session(account: str, session_id: str) -> dict:
    if not id_ok(session_id, "cs"):
        raise StripeError("That checkout session was not recognized.", "bad_session")
    return stripe_call(
        "GET",
        f"/v1/checkout/sessions/{session_id}?expand%5B%5D=setup_intent",
        stripe_account=account,
    )


def _as_id(value, kind: str) -> str:
    if isinstance(value, dict):
        value = value.get("id") or ""
    value = str(value or "")
    return value if id_ok(value, kind) else ""


def payment_method_from_session(account: str, session: dict, hold_token: str) -> tuple[str, str, str]:
    if session.get("mode") != "setup" or session.get("status") != "complete":
        raise StripeError("The card was not saved. The visit was not booked.", "setup_incomplete")
    meta = session.get("metadata") or {}
    if (meta.get("hold_token") or "") != hold_token:
        raise StripeError("That checkout session does not match this booking.", "mismatch")
    setup = session.get("setup_intent")
    if isinstance(setup, str):
        if not id_ok(setup, "seti"):
            raise StripeError("The card was not saved.", "no_setup")
        setup = stripe_call("GET", f"/v1/setup_intents/{setup}", stripe_account=account)
    if not isinstance(setup, dict) or setup.get("status") != "succeeded":
        raise StripeError("The card was not saved. The visit was not booked.", "setup_incomplete")
    if ((setup.get("metadata") or {}).get("hold_token") or hold_token) != hold_token:
        raise StripeError("That checkout session does not match this booking.", "mismatch")
    customer = _as_id(session.get("customer"), "cus") or _as_id(setup.get("customer"), "cus")
    payment_method = _as_id(setup.get("payment_method"), "pm")
    setup_id = _as_id(setup.get("id"), "seti")
    if not customer or not payment_method or not setup_id:
        raise StripeError("The card was not saved. The visit was not booked.", "no_card")
    return customer, payment_method, setup_id


def create_off_session_charge(
    account: str,
    customer: str,
    payment_method: str,
    cents: int,
    receipt_email: str,
    description: str,
    appointment_id: int,
    idempotency_key: str,
) -> dict:
    body = stripe_call(
        "POST",
        "/v1/payment_intents",
        {
            "amount": str(int(cents)),
            "currency": "usd",
            "customer": customer,
            "payment_method": payment_method,
            "off_session": "true",
            "confirm": "true",
            "receipt_email": receipt_email,
            "description": description[:350],
            "metadata[appointment_id]": str(appointment_id),
            "metadata[purpose]": "missed_intake_fee",
        },
        stripe_account=account,
        idempotency_key=idempotency_key,
    )
    intent_id = _as_id(body.get("id"), "pi")
    if not intent_id:
        raise StripeError("Stripe did not confirm the charge. Nothing was charged.", "bad_charge")
    return {"id": intent_id, "status": body.get("status") or ""}


def verify_webhook(payload: bytes, header: str) -> dict:
    if not configured():
        raise StripeError("Stripe is not configured.", "unconfigured")
    secret = webhook_secret()
    timestamp = ""
    signatures: list[str] = []
    for item in (header or "").split(","):
        item = item.strip()
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        if key == "t":
            timestamp = value.strip()
        elif key == "v1":
            signatures.append(value.strip())
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        ts = 0
    if not ts or not signatures:
        raise StripeError("Webhook signature missing.", "bad_signature")
    if abs(int(time.time()) - ts) > 300:
        raise StripeError("Webhook signature expired.", "bad_signature")
    signed = f"{ts}.".encode("utf-8") + payload
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in signatures):
        raise StripeError("Webhook signature did not match.", "bad_signature")
    try:
        event = json.loads(payload.decode("utf-8"))
    except Exception:
        raise StripeError("Webhook body was not valid.", "bad_payload")
    if not isinstance(event, dict):
        raise StripeError("Webhook body was not valid.", "bad_payload")
    return event


def insert_hold(
    conn,
    token: str,
    provider_id: int,
    account: str,
    payload: dict,
    consent_text: str,
    cents: int,
    window_hours: int,
) -> None:
    created = now_dt()
    expires = created + timedelta(minutes=HOLD_MINUTES)
    conn.execute(
        """INSERT INTO fee_holds (
             token, provider_id, stripe_account_id, status, payload_json,
             consent_text, amount_cents, window_hours, created_at, expires_at
           ) VALUES (?,?,?, 'pending', ?, ?, ?, ?, ?, ?)""",
        (
            token,
            provider_id,
            account,
            json.dumps(payload),
            consent_text,
            int(cents),
            int(window_hours),
            created.isoformat(timespec="seconds"),
            expires.isoformat(timespec="seconds"),
        ),
    )


def remember_session(conn, token: str, session_id: str, customer_id: str) -> None:
    conn.execute(
        """UPDATE fee_holds
           SET stripe_session_id=?, stripe_customer_id=?
           WHERE token=? AND status='pending'""",
        (session_id, customer_id, token),
    )


def load_hold(conn, token: str):
    token = (token or "").strip()
    if not token:
        return None
    return conn.execute("SELECT * FROM fee_holds WHERE token=?", (token,)).fetchone()


def save_visit_fee(
    conn,
    appointment_id: int,
    cents: int,
    window_hours: int,
    consent_text: str,
    customer_id: str,
    payment_method_id: str,
    setup_intent_id: str,
) -> None:
    conn.execute(
        """UPDATE appointments SET
             fee_cents=?, fee_window_hours=?, fee_consent_at=?, fee_consent_text=?,
             stripe_customer_id=?, stripe_payment_method_id=?, stripe_setup_intent_id=?,
             fee_state='card_saved', fee_error=''
           WHERE id=?""",
        (
            int(cents),
            int(window_hours),
            now_iso(),
            consent_text,
            customer_id,
            payment_method_id,
            setup_intent_id,
            appointment_id,
        ),
    )


def settle_client_cancel(conn, appt) -> str:
    """Mark a saved card waived or eligible after the client cancels. Does not charge."""
    state = (uget(appt, "fee_state", "") or "").strip()
    if state != "card_saved":
        return ""
    payment_method = (uget(appt, "stripe_payment_method_id", "") or "").strip()
    consent = (uget(appt, "fee_consent_at", "") or "").strip()
    cents = int(uget(appt, "fee_cents", 0) or 0)
    window = int(uget(appt, "fee_window_hours", 0) or 0)
    if not payment_method or not consent or cents < MIN_CENTS or window < MIN_WINDOW_HOURS:
        conn.execute(
            "UPDATE appointments SET fee_state='waived', fee_error='' WHERE id=?",
            (appt["id"],),
        )
        return "waived"
    client = None
    if appt["client_id"]:
        client = conn.execute("SELECT name FROM clients WHERE id=?", (appt["client_id"],)).fetchone()
    who = client["name"] if client else "A client"
    start = parse_iso(appt["start_iso"])
    if cancel_is_late(appt["start_iso"], window):
        conn.execute(
            "UPDATE appointments SET fee_state='late_cancel', fee_error='' WHERE id=?",
            (appt["id"],),
        )
        notify(
            conn,
            appt["provider_id"],
            "fee",
            "Late cancel — card on file",
            (
                f"{who} cancelled inside the {window}-hour window for "
                f"{format_long(start.date())} at {format_time(start.strftime('%H:%M'))}. "
                f"You can charge the saved card {money_label(cents)} once from the dashboard. "
                "They are not charged until you do."
            ),
        )
        return "late"
    conn.execute(
        "UPDATE appointments SET fee_state='waived', fee_error='' WHERE id=?",
        (appt["id"],),
    )
    return "waived"


def waive_open_fee(conn, appointment_id: int) -> None:
    """Therapist cancelled, so the saved card must not be charged."""
    conn.execute(
        """UPDATE appointments SET fee_state='waived', fee_error=''
           WHERE id=? AND COALESCE(fee_state, '') IN ('card_saved', 'late_cancel', 'no_show', 'charge_failed')""",
        (appointment_id,),
    )


def apply_connect_event(conn, event: dict) -> None:
    obj = (event.get("data") or {}).get("object") or {}
    account = obj.get("id") or ""
    if not id_ok(account, "acct"):
        return
    conn.execute(
        """UPDATE users SET
             stripe_charges_enabled=?,
             stripe_payouts_enabled=?,
             stripe_details_submitted=?
           WHERE stripe_account_id=?""",
        (
            1 if obj.get("charges_enabled") else 0,
            1 if obj.get("payouts_enabled") else 0,
            1 if obj.get("details_submitted") else 0,
            account,
        ),
    )


def apply_payment_event(conn, event: dict) -> None:
    obj = (event.get("data") or {}).get("object") or {}
    meta = obj.get("metadata") or {}
    if (meta.get("purpose") or "") != "missed_intake_fee":
        return
    try:
        appointment_id = int(meta.get("appointment_id") or 0)
    except (TypeError, ValueError):
        return
    if appointment_id <= 0:
        return
    appt = conn.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone()
    if not appt:
        return
    provider = conn.execute("SELECT stripe_account_id FROM users WHERE id=?", (appt["provider_id"],)).fetchone()
    event_account = event.get("account") or ""
    if event_account and provider and event_account != (provider["stripe_account_id"] or ""):
        log_fee(f"payment event ignored account mismatch appointment_id={appointment_id}")
        return
    if not (uget(appt, "fee_consent_at", "") or "").strip():
        return
    intent_id = _as_id(obj.get("id"), "pi")
    kind = event.get("type") or ""
    if kind == "payment_intent.succeeded":
        try:
            amount = int(obj.get("amount") or -1)
        except (TypeError, ValueError):
            amount = -1
        if amount != int(uget(appt, "fee_cents", 0) or 0):
            log_fee(f"payment event ignored amount mismatch appointment_id={appointment_id}")
            return
        if (uget(appt, "fee_state", "") or "") == "charged":
            return
        if (uget(appt, "fee_state", "") or "") not in ("charging", "charge_failed", "late_cancel", "no_show"):
            return
        if not intent_id:
            return
        conn.execute(
            """UPDATE appointments SET
                 fee_state='charged', stripe_payment_intent_id=?, fee_charged_at=?, fee_error=''
               WHERE id=?""",
            (intent_id, now_iso(), appointment_id),
        )
        log_fee(f"charge recorded from webhook appointment_id={appointment_id}")
        return
    if kind == "payment_intent.payment_failed" and (uget(appt, "fee_state", "") or "") == "charging":
        conn.execute(
            """UPDATE appointments SET fee_state='charge_failed', fee_error=?
               WHERE id=? AND fee_state='charging'""",
            ("The card was declined. Nothing was charged. You can try again.", appointment_id),
        )
