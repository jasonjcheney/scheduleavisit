#!/usr/bin/env python3
"""Missed first-visit fee. Stripe is mocked. Unconfigured booking stays unchanged."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fd, DBFILE = tempfile.mkstemp(suffix="-missed-fee.db")
os.close(fd)
os.environ["SAV_DB"] = DBFILE
os.environ.setdefault("SAV_JASON_PASSWORD", "123456")
os.environ.setdefault("SAV_DEMO_PASSWORD", "demo1234")
os.environ.pop("SHOW_DEMO_COUNSELORS", None)

SECRET = "sk_test_NEVERLOG_991"
PUBLISHABLE = "pk_test_NEVERLOG_992"
WEBHOOK = "whsec_NEVERLOG_993"

for _name in ("STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "STRIPE_WEBHOOK_SECRET"):
    os.environ.pop(_name, None)

TZ = ZoneInfo("America/Denver")


def fail(msg: str) -> None:
    print("FAIL:", msg)
    sys.exit(1)


def expect(cond: bool, msg: str) -> None:
    if not cond:
        fail(msg)


def future_slot(hour=10, days_ahead=8):
    d = datetime.now(TZ).date() + timedelta(days=days_ahead)
    while d.isoweekday() > 5:
        d += timedelta(days=1)
    return d, f"{hour:02d}:00"


def sign(payload: bytes) -> str:
    ts = int(time.time())
    mac = hmac.new(WEBHOOK.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def quiet(fn):
    buf = StringIO()
    with redirect_stdout(buf):
        result = fn()
    text = buf.getvalue()
    expect(SECRET not in text, "log included the secret key")
    expect(PUBLISHABLE not in text, "log included the publishable key")
    expect(WEBHOOK not in text, "log included the webhook secret")
    return result, text


def main() -> None:
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        os.system(f"{sys.executable} -m pip install -q httpx")
        from fastapi.testclient import TestClient

    import fees
    import httpx
    from app import app

    calls: list[dict] = []

    def fake_stripe(method, path, data=None, stripe_account="", idempotency_key=""):
        rec = {
            "method": method,
            "path": path,
            "data": dict(data or {}),
            "stripe_account": stripe_account,
            "idempotency_key": idempotency_key,
        }
        calls.append(rec)
        if method == "POST" and path == "/v1/accounts":
            expect(stripe_account == "", "account create should be on the platform")
            return {
                "id": "acct_test_123",
                "charges_enabled": False,
                "payouts_enabled": False,
                "details_submitted": False,
            }
        if method == "GET" and path.startswith("/v1/accounts/"):
            return {
                "id": "acct_test_123",
                "charges_enabled": True,
                "payouts_enabled": True,
                "details_submitted": True,
            }
        if method == "POST" and path == "/v1/account_links":
            return {"url": "https://connect.stripe.com/setup/e/test"}
        if method == "POST" and path == "/v1/customers":
            expect(stripe_account == "acct_test_123", "customer must be on the therapist account")
            return {"id": "cus_test_123"}
        if method == "POST" and path == "/v1/checkout/sessions":
            expect(data.get("mode") == "setup", f"checkout mode {data.get('mode')}")
            expect("{CHECKOUT_SESSION_ID}" in (data.get("success_url") or ""), "success url placeholder missing")
            expect("amount" not in data, "setup checkout must not charge")
            expect(stripe_account == "acct_test_123", "checkout must be on the therapist account")
            return {"id": "cs_test_123", "url": "https://checkout.stripe.com/c/pay/cs_test_123"}
        if method == "GET" and "/v1/checkout/sessions/" in path:
            hold = ""
            for older in reversed(calls):
                if older["method"] == "POST" and older["path"] == "/v1/checkout/sessions":
                    hold = older["data"].get("metadata[hold_token]") or ""
                    break
            expect(stripe_account == "acct_test_123", "session read must use the therapist account")
            return {
                "id": "cs_test_123",
                "mode": "setup",
                "status": "complete",
                "customer": "cus_test_123",
                "metadata": {"hold_token": hold, "purpose": "missed_intake_fee"},
                "setup_intent": {
                    "id": "seti_test_123",
                    "status": "succeeded",
                    "customer": "cus_test_123",
                    "payment_method": "pm_test_123",
                    "metadata": {"hold_token": hold},
                },
            }
        if method == "POST" and path == "/v1/payment_intents":
            expect(stripe_account == "acct_test_123", "charge must be on the therapist account")
            return {"id": "pi_test_123", "status": "succeeded"}
        fail(f"unexpected stripe call {method} {path}")

    fees.stripe_call = fake_stripe

    with TestClient(app) as c:
        _run(c, calls, fees, httpx, fake_stripe)


def _pi_count(calls) -> int:
    return sum(1 for c in calls if c["path"] == "/v1/payment_intents")


def _hold_token(calls) -> str:
    for older in reversed(calls):
        if older["method"] == "POST" and older["path"] == "/v1/checkout/sessions":
            return older["data"].get("metadata[hold_token]") or ""
    return ""


def _book(c, day, hhmm, name, email, consent=""):
    body = {
        "date": day.isoformat(),
        "time": hhmm,
        "name": name,
        "email": email,
        "visitKind": "session",
    }
    if consent:
        body["feeConsent"] = consent
    return c.post("/api/p/jason-cheney/book", json=body)


def _finish(c, calls):
    token = _hold_token(calls)
    expect(bool(token), "checkout did not record a hold token")
    done, log = quiet(lambda: c.get(
        f"/book/card-saved?hold={token}&session_id=cs_test_123",
        follow_redirects=False,
    ))
    expect(done.status_code in (302, 303), f"card return {done.status_code} {done.text[:240]}")
    loc = done.headers.get("location") or ""
    expect(loc.startswith("/booked/"), f"card return location {loc}")
    expect(SECRET not in log and "4242" not in (done.text or ""), "card return leaked a secret or a card number")
    return loc


def _run(c, calls, fees, httpx, fake_stripe) -> None:
    from db import connect

    with connect() as conn:
        conn.execute("UPDATE users SET setup_complete=1 WHERE slug='jason-cheney'")
        conn.commit()

    page, _log = quiet(lambda: c.get("/p/jason-cheney"))
    expect(page.status_code == 200, f"booking page {page.status_code}")
    expect('id="missed-fee-notice"' not in page.text, "unconfigured booking page showed the fee")
    expect(SECRET not in page.text and PUBLISHABLE not in page.text, "booking page leaked a Stripe key")

    day, hhmm = future_slot(10, 8)
    booked, _log = quiet(lambda: _book(c, day, hhmm, "Pat Unconfigured", "pat.unconfigured@example.com"))
    expect(booked.status_code == 200 and booked.json().get("ok"), f"unconfigured book {booked.text}")
    expect(booked.json().get("redirect", "").startswith("/booked/"), booked.text)
    expect("checkoutUrl" not in booked.json(), "unconfigured book opened checkout")
    expect(not calls, f"unconfigured book called Stripe: {calls}")

    missing, _log = quiet(lambda: c.post("/api/stripe/webhook", content=b"{}", headers={"stripe-signature": "t=1,v1=nope"}))
    expect(missing.status_code == 404, f"unconfigured webhook {missing.status_code}")

    login, _log = quiet(lambda: c.post("/api/auth/login", json={"email": "jasoncheney", "password": "123456"}))
    expect(login.status_code == 200 and login.json().get("ok"), f"login {login.text}")
    dash, _log = quiet(lambda: c.get("/dashboard"))
    setup, _log = quiet(lambda: c.get("/setup"))
    expect(dash.status_code == 200 and setup.status_code == 200, "dashboard or setup failed")
    expect('id="missed-fee-card"' not in dash.text, "unconfigured dashboard showed the fee")
    expect('id="missed-fee-card"' not in setup.text, "unconfigured setup showed the fee")
    hidden_api, _log = quiet(lambda: c.post("/api/me/fee", json={"enabled": "1", "amount": "80", "window_hours": 24}))
    expect(hidden_api.status_code == 404, f"unconfigured fee save {hidden_api.status_code}")
    print("OK fee stays hidden and booking is unchanged when Stripe is not configured")

    with connect() as conn:
        conn.execute(
            """UPDATE users SET missed_fee_enabled=1, missed_fee_cents=8000,
               missed_fee_window_hours=24, stripe_charges_enabled=1,
               stripe_account_id='acct_test_123'
               WHERE slug='jason-cheney'"""
        )
        conn.commit()
    os.environ["STRIPE_SECRET_KEY"] = SECRET
    os.environ["STRIPE_PUBLISHABLE_KEY"] = PUBLISHABLE
    still, _log = quiet(lambda: c.get("/p/jason-cheney"))
    expect('id="missed-fee-notice"' not in still.text, "fee went live without the webhook secret")
    day2, hhmm2 = future_slot(11, 8)
    still_book, _log = quiet(lambda: _book(c, day2, hhmm2, "Pat Partial", "pat.partial@example.com"))
    expect(still_book.json().get("ok") and "checkoutUrl" not in still_book.json(), still_book.text)
    os.environ["STRIPE_WEBHOOK_SECRET"] = WEBHOOK
    print("OK a partial Stripe config keeps the fee off")

    def boom(*_a, **_k):
        raise httpx.ConnectError(SECRET)

    real_request = fees.httpx.request
    fees.httpx.request = boom
    fees.stripe_call = fees.stripe_call.__wrapped__ if hasattr(fees.stripe_call, "__wrapped__") else None
    # Restore the real function, then confirm a network error does not log the key.
    import importlib
    importlib.reload(fees)
    fees.httpx.request = boom

    def network():
        try:
            fees.stripe_call("GET", "/v1/accounts/acct_test_123")
        except fees.StripeError as exc:
            expect(SECRET not in exc.message, "stripe error included the secret")
            return exc
        fail("network error was not raised")

    _err, net_log = quiet(network)
    expect("stripe network error" in net_log, f"network log missing: {net_log}")
    fees.httpx.request = real_request
    fees.stripe_call = fake_stripe
    print("OK a Stripe network error does not log the secret")

    with connect() as conn:
        conn.execute(
            """UPDATE users SET missed_fee_enabled=0, missed_fee_cents=0,
               stripe_charges_enabled=0, stripe_payouts_enabled=0, stripe_details_submitted=0,
               stripe_account_id=''
               WHERE slug='jason-cheney'"""
        )
        conn.commit()

    dash2, _log = quiet(lambda: c.get("/dashboard"))
    expect('id="missed-fee-card"' in dash2.text, "configured dashboard hid the fee")
    expect(SECRET not in dash2.text and WEBHOOK not in dash2.text, "dashboard leaked a Stripe secret")
    setup2, _log = quiet(lambda: c.get("/setup"))
    expect('id="missed-fee-card"' in setup2.text, "configured setup hid the fee")

    saved, _log = quiet(lambda: c.post("/api/me/fee", json={"enabled": "1", "amount": "80", "window_hours": 24}))
    expect(saved.status_code == 200 and saved.json().get("ok"), saved.text)
    expect(saved.json().get("live") is False, f"fee live before Connect: {saved.text}")
    early, _log = quiet(lambda: c.get("/p/jason-cheney"))
    expect('id="missed-fee-notice"' not in early.text, "booking page showed a fee before Connect")

    linked, _log = quiet(lambda: c.post("/api/me/stripe/connect", json={"next": "/dashboard"}))
    expect(linked.status_code == 200 and linked.json().get("url", "").startswith("https://connect.stripe.com/"), linked.text)
    expect(calls and calls[-1]["path"] == "/v1/account_links", f"connect calls {calls}")
    expect(calls[0]["data"].get("type") == "express", calls[0]["data"])
    expect(calls[0]["data"].get("country") == "US", calls[0]["data"])

    event = {
        "id": "evt_acct",
        "type": "account.updated",
        "data": {
            "object": {
                "id": "acct_test_123",
                "object": "account",
                "charges_enabled": True,
                "payouts_enabled": True,
                "details_submitted": True,
            }
        },
    }
    raw = json.dumps(event).encode()
    hooked, _log = quiet(lambda: c.post(
        "/api/stripe/webhook",
        content=raw,
        headers={"stripe-signature": sign(raw), "content-type": "application/json"},
    ))
    expect(hooked.status_code == 200, f"account webhook {hooked.status_code} {hooked.text}")
    bad, _log = quiet(lambda: c.post(
        "/api/stripe/webhook",
        content=raw,
        headers={"stripe-signature": "t=1,v1=deadbeef", "content-type": "application/json"},
    ))
    expect(bad.status_code == 400, f"bad signature {bad.status_code}")
    expect(SECRET not in bad.text and WEBHOOK not in bad.text, "webhook error echoed a secret")

    live_page, _log = quiet(lambda: c.get("/p/jason-cheney"))
    expect('id="missed-fee-notice"' in live_page.text, "live fee missing on the booking page")
    expect("$80" in live_page.text and "24 hours" in live_page.text, "amount or window missing")
    expect("not charged today" in live_page.text.lower(), "page did not say the card is not charged today")
    expect("paid to" in live_page.text.lower(), "page did not say who receives the money")
    print("OK therapist can set the fee, connect Stripe, and the booking page shows it")

    day3, hhmm3 = future_slot(14, 9)
    refused, _log = quiet(lambda: _book(c, day3, hhmm3, "No Consent", "no.consent@example.com"))
    expect(refused.status_code == 400, f"missing consent {refused.status_code} {refused.text}")
    expect("not charged today" in refused.json().get("error", "").lower(), refused.text)
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM appointments a JOIN clients c ON c.id=a.client_id WHERE c.email=?",
            ("no.consent@example.com",),
        ).fetchone()
        expect(row is None, "refused consent still created a visit")

    calls.clear()
    agreed, _log = quiet(lambda: _book(c, day3, hhmm3, "No Consent", "no.consent@example.com", consent="yes"))
    body = agreed.json()
    expect(agreed.status_code == 200 and body.get("checkoutUrl", "").startswith("https://checkout.stripe.com/"), agreed.text)
    expect("appointmentId" not in body, "visit was created before the card was saved")
    expect(_pi_count(calls) == 0, "setup mode created a charge")
    with connect() as conn:
        pending = conn.execute(
            "SELECT id FROM appointments a JOIN clients c ON c.id=a.client_id WHERE c.email=?",
            ("no.consent@example.com",),
        ).fetchone()
        expect(pending is None, "checkout created a visit before return")
    loc = _finish(c, calls)
    confirm, _log = quiet(lambda: c.get(loc))
    expect("You were not charged." in confirm.text, "confirmation did not say the card was not charged")
    expect('id="saved-card-note"' in confirm.text, "confirmation missing the saved-card notice")
    with connect() as conn:
        saved_row = conn.execute(
            """SELECT a.fee_cents, a.fee_window_hours, a.fee_state, a.fee_consent_text,
                      a.stripe_customer_id, a.stripe_payment_method_id, a.stripe_payment_intent_id
               FROM appointments a JOIN clients c ON c.id=a.client_id
               WHERE c.email=?""",
            ("no.consent@example.com",),
        ).fetchone()
        expect(saved_row["fee_state"] == "card_saved", saved_row["fee_state"])
        expect(saved_row["fee_cents"] == 8000, saved_row["fee_cents"])
        expect(saved_row["fee_window_hours"] == 24, saved_row["fee_window_hours"])
        expect(saved_row["stripe_customer_id"] == "cus_test_123", saved_row["stripe_customer_id"])
        expect(saved_row["stripe_payment_method_id"] == "pm_test_123", saved_row["stripe_payment_method_id"])
        expect(not saved_row["stripe_payment_intent_id"], "a charge id was stored before any charge")
        blob = " ".join(str(x or "") for x in saved_row)
        expect("4242" not in blob and "sk_" not in blob, f"stored card or secret: {blob}")
        expect("$80" in saved_row["fee_consent_text"] and "24 hours" in saved_row["fee_consent_text"], saved_row["fee_consent_text"])
    print("OK a first visit saves a card without charging, and only after agreement")

    day4, hhmm4 = future_slot(15, 9)
    calls.clear()
    again, _log = quiet(lambda: _book(c, day4, hhmm4, "No Consent", "no.consent@example.com"))
    expect(again.json().get("ok") and again.json().get("redirect", "").startswith("/booked/"), again.text)
    expect("checkoutUrl" not in again.json(), "returning client was sent to checkout")
    expect(not calls, "returning client called Stripe")
    print("OK a returning client books without saving another card")

    def card_visit(name, email, hour, days):
        calls.clear()
        slot_day, slot_time = future_slot(hour, days)
        made, _log = quiet(lambda: _book(c, slot_day, slot_time, name, email, consent="yes"))
        expect(made.json().get("checkoutUrl", "").startswith("https://checkout.stripe.com/"), made.text)
        _finish(c, calls)
        with connect() as conn:
            appt = conn.execute(
                """SELECT a.id, a.public_token, a.fee_cents FROM appointments a
                   JOIN clients c ON c.id=a.client_id
                   WHERE c.email=? ORDER BY a.id DESC LIMIT 1""",
                (email,),
            ).fetchone()
        return appt

    ontime = card_visit("On Time", "on.time@example.com", 10, 12)
    cancelled, _log = quiet(lambda: c.post(f"/api/booked/{ontime['public_token']}/cancel"))
    expect(cancelled.json().get("ok"), cancelled.text)
    with connect() as conn:
        state = conn.execute("SELECT fee_state FROM appointments WHERE id=?", (ontime["id"],)).fetchone()
        expect(state["fee_state"] == "waived", state["fee_state"])
    blocked, _log = quiet(lambda: c.post(f"/api/me/appointments/{ontime['id']}/charge-fee"))
    expect(blocked.status_code == 400, f"on-time cancel was chargeable: {blocked.text}")
    expect(_pi_count(calls) == 0, "on-time cancel created a charge")
    print("OK an on-time cancel cannot be charged")

    late = card_visit("Late Pat", "late.pat@example.com", 11, 13)
    soon = (datetime.now(TZ) + timedelta(hours=2)).replace(microsecond=0)
    with connect() as conn:
        conn.execute(
            "UPDATE appointments SET start_iso=? WHERE id=?",
            (soon.isoformat(timespec="seconds"), late["id"]),
        )
        conn.commit()
    c.post("/api/me/fee", json={"enabled": "1", "amount": "10", "window_hours": 24})
    late_cancel, _log = quiet(lambda: c.post(f"/api/booked/{late['public_token']}/cancel"))
    expect(late_cancel.json().get("ok"), late_cancel.text)
    confirm_late, _log = quiet(lambda: c.get(f"/booked/{late['public_token']}"))
    expect('id="late-cancel-fee"' in confirm_late.text, "late cancel page hid the fee")
    expect("$80" in confirm_late.text, "late cancel page did not repeat the agreed amount")
    calls.clear()
    charged, _log = quiet(lambda: c.post(f"/api/me/appointments/{late['id']}/charge-fee"))
    expect(charged.status_code == 200 and charged.json().get("ok"), charged.text)
    pi = [rec for rec in calls if rec["path"] == "/v1/payment_intents"]
    expect(len(pi) == 1, f"charge calls {calls}")
    expect(pi[0]["data"].get("amount") == "8000", pi[0]["data"])
    expect(pi[0]["data"].get("receipt_email") == "late.pat@example.com", pi[0]["data"])
    expect(pi[0]["data"].get("off_session") == "true" and pi[0]["data"].get("confirm") == "true", pi[0]["data"])
    expect(pi[0]["stripe_account"] == "acct_test_123", pi[0])
    expect("clinical" not in (pi[0]["data"].get("description") or "").lower(), pi[0]["data"])
    again_charge, _log = quiet(lambda: c.post(f"/api/me/appointments/{late['id']}/charge-fee"))
    expect(again_charge.status_code == 400, f"second charge {again_charge.text}")
    expect(_pi_count(calls) == 1, "a second charge hit Stripe")
    print("OK a late cancel can be charged once, for the amount the client agreed to")

    noshow = card_visit("No Show", "no.show@example.com", 16, 14)
    too_soon, _log = quiet(lambda: c.post(f"/api/me/appointments/{noshow['id']}/no-show"))
    expect(too_soon.status_code == 400, f"future no-show {too_soon.text}")
    past = (datetime.now(TZ) - timedelta(hours=1)).replace(microsecond=0)
    with connect() as conn:
        conn.execute(
            "UPDATE appointments SET start_iso=? WHERE id=?",
            (past.isoformat(timespec="seconds"), noshow["id"]),
        )
        conn.commit()
    marked, _log = quiet(lambda: c.post(f"/api/me/appointments/{noshow['id']}/no-show"))
    expect(marked.status_code == 200 and marked.json().get("ok"), marked.text)
    calls.clear()
    show_charge, _log = quiet(lambda: c.post(f"/api/me/appointments/{noshow['id']}/charge-fee"))
    expect(show_charge.status_code == 200 and show_charge.json().get("ok"), show_charge.text)
    expect(_pi_count(calls) == 1, "no-show charge missing")
    expect(calls[-1]["data"].get("receipt_email") == "no.show@example.com", calls[-1]["data"])
    print("OK a no-show can be charged once after the visit time")

    owned = card_visit("Therapist Cancel", "therapist.cancel@example.com", 9, 16)
    by_therapist, _log = quiet(lambda: c.post(f"/api/me/appointments/{owned['id']}/cancel"))
    expect(by_therapist.json().get("ok"), by_therapist.text)
    cannot, _log = quiet(lambda: c.post(f"/api/me/appointments/{owned['id']}/charge-fee"))
    expect(cannot.status_code == 400, f"therapist cancel was chargeable: {cannot.text}")
    print("OK a therapist cancel waives the fee")

    os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
    day5, hhmm5 = future_slot(13, 18)
    off_again, _log = quiet(lambda: _book(c, day5, hhmm5, "Off Again", "off.again@example.com"))
    expect(off_again.json().get("ok") and "checkoutUrl" not in off_again.json(), off_again.text)
    hidden, _log = quiet(lambda: c.get("/p/jason-cheney"))
    expect('id="missed-fee-notice"' not in hidden.text, "removing the webhook secret left the fee on the page")
    print("OK turning the config off hides the fee again")

    terms, _log = quiet(lambda: c.get("/terms"))
    expect("Card numbers stay with Stripe" in terms.text, "terms missing Stripe card line")
    expect("paid to the therapist" in terms.text, "terms missing who gets paid")
    expect("do not bill insurance" in terms.text, "terms dropped the insurance line")
    expect("do not take cards, copays" not in terms.text, "terms still say the site does not take cards")
    privacy = c.get("/privacy")
    expect("payment-method id" in privacy.text, "privacy missing the Stripe id line")
    expect("not the card number" in privacy.text, "privacy missing the no-card-number line")
    print("OK terms and privacy describe the optional fee")
    print("ALL MISSED INTAKE FEE TESTS PASSED")


if __name__ == "__main__":
    main()
