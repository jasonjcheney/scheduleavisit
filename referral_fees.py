"""Referral fee when a first booking comes from a colleague.

The receiving therapist pays a flat fee (default $20). The referring therapist
gets 25% ($5). ScheduleAVisit keeps 75% ($15). A client who books the
therapist's own page, with no referral, does not create this fee. The client
is not charged this amount. It is scheduling money between practices.

Money flow (Stripe Connect Express):

The therapists already connect Express accounts for the optional missed
first-visit fee. This fee reuses those accounts. It does not charge the
client's saved card.

1. The platform debits the receiving therapist's connected-account balance
   for the full fee (POST /v1/charges with source=acct_receiver). Stripe
   calls this an account debit. It creates a Payment on the platform (py_…)
   and moves that full amount onto the platform balance. An account debit
   cannot push the connected balance negative, so a therapist with less than
   the fee available is not charged and the visit still books.
2. The platform then transfers the referrer's share (POST /v1/transfers,
   destination=acct_referrer). The rest stays on the platform.

That is the Express pattern that matches "the receiver pays, then the money
is split." A destination charge with application_fee would need a cardholder.
The client is not the payer here.

If STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, and STRIPE_WEBHOOK_SECRET are
not all set, the visit still books. The fee is recorded as skipped and logged.
A Stripe error is the same: the visit stays booked, and the dashboard shows
the fee as owed.
"""
from __future__ import annotations

import os
import re

import fees
from capacity import first_name, uget
from db import notify, now_iso

ENV_FEE_CENTS = "REFERRAL_FEE_CENTS"
ENV_REFERRER_BPS = "REFERRAL_REFERRER_SHARE_BPS"
DEFAULT_FEE_CENTS = 2000
DEFAULT_REFERRER_BPS = 2500
MAX_FEE_CENTS = 10_000_000

_CHARGE_RE = re.compile(r"^(?:py|ch)_[A-Za-z0-9_]+$")
_TRANSFER_RE = re.compile(r"^tr_[A-Za-z0-9_]+$")
_INTENT_RE = re.compile(r"^pi_[A-Za-z0-9_]+$")

_DONE = {"charged", "charged_unsplit", "skipped"}


def log_referral(msg: str) -> None:
    print(f"[referral-fee] {fees.scrub(msg)}", flush=True)


def _int_env(name: str, default: int, low: int, high: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if value < low or value > high:
        return default
    return value


def referral_fee_cents() -> int:
    return _int_env(ENV_FEE_CENTS, DEFAULT_FEE_CENTS, 0, MAX_FEE_CENTS)


def referrer_share_bps() -> int:
    return _int_env(ENV_REFERRER_BPS, DEFAULT_REFERRER_BPS, 0, 10_000)


def split_amounts(fee_cents: int | None = None, bps: int | None = None) -> dict:
    """Integer split. referrer + platform always equals the fee.

    A remainder of a cent stays with the platform. The defaults ($20 and
    2500 bps) divide evenly into $5 and $15.
    """
    fee = referral_fee_cents() if fee_cents is None else int(fee_cents)
    share_bps = referrer_share_bps() if bps is None else int(bps)
    if fee < 0:
        fee = 0
    if share_bps < 0:
        share_bps = 0
    if share_bps > 10_000:
        share_bps = 10_000
    referrer = (fee * share_bps) // 10_000
    platform = fee - referrer
    return {
        "referral_fee_cents": fee,
        "referrer_share_bps": share_bps,
        "referrer_share_cents": referrer,
        "platform_share_cents": platform,
        "split": f"referrer:{referrer};platform:{platform};bps:{share_bps}",
    }


def _percent_label(bps: int) -> str:
    if bps % 100 == 0:
        return f"{bps // 100}%"
    whole, frac = divmod(bps, 100)
    return f"{whole}.{frac:02d}%"


def notice_text(parts: dict | None = None) -> str:
    """Plain-language price shown when someone joins a network."""
    parts = parts or split_amounts()
    fee = fees.money_label(parts["referral_fee_cents"])
    referrer = fees.money_label(parts["referrer_share_cents"])
    platform = fees.money_label(parts["platform_share_cents"])
    referrer_pct = _percent_label(parts["referrer_share_bps"])
    platform_pct = _percent_label(10_000 - parts["referrer_share_bps"])
    return (
        f"When a client’s first booking with you comes from a colleague’s referral, "
        f"you pay a {fee} referral fee from your Stripe balance. "
        f"{referrer} ({referrer_pct}) goes to the colleague who referred them. "
        f"{platform} ({platform_pct}) goes to ScheduleAVisit. "
        f"A client who books your own page does not add this fee, and the client is not charged it."
    )


def _user(conn, user_id: int):
    if not user_id:
        return None
    return conn.execute("SELECT * FROM users WHERE id=?", (int(user_id),)).fetchone()


def _account_id(user) -> str:
    if user is None:
        return ""
    account = (uget(user, "stripe_account_id", "") or "").strip()
    return account if fees.id_ok(account, "acct") else ""


def _is_first_referral(conn, appt) -> bool:
    if (appt["booked_via"] or "") != "referral":
        return False
    referrer_id = int(appt["referred_from_provider_id"] or 0)
    if referrer_id <= 0 or referrer_id == int(appt["provider_id"]):
        return False
    client_id = appt["client_id"]
    if not client_id:
        return False
    earlier = conn.execute(
        """SELECT 1 FROM appointments
           WHERE provider_id=? AND client_id=? AND id!=?
             AND status!='cancelled'
           LIMIT 1""",
        (appt["provider_id"], client_id, appt["id"]),
    ).fetchone()
    if earlier:
        return False
    prior_fee = conn.execute(
        """SELECT 1 FROM referral_fees f
           JOIN appointments a ON a.id = f.appointment_id
           WHERE f.receiver_id=? AND a.client_id=? AND f.appointment_id!=?
           LIMIT 1""",
        (appt["provider_id"], client_id, appt["id"]),
    ).fetchone()
    return prior_fee is None


def _insert_pending(conn, appt, parts: dict, referrer_id: int) -> None:
    conn.execute(
        """INSERT INTO referral_fees (
             appointment_id, referrer_id, receiver_id, referral_fee_cents,
             referrer_share_cents, platform_share_cents, referrer_share_bps, split,
             status, stripe_charge_id, stripe_transfer_id, stripe_payment_intent_id,
             receiver_account_id, referrer_account_id, error, created_at
           ) VALUES (?,?,?,?,?,?,?,?, 'pending', '', '', '', '', '', '', ?)""",
        (
            appt["id"],
            referrer_id,
            appt["provider_id"],
            parts["referral_fee_cents"],
            parts["referrer_share_cents"],
            parts["platform_share_cents"],
            parts["referrer_share_bps"],
            parts["split"],
            now_iso(),
        ),
    )


def _update(conn, appointment_id: int, **fields) -> None:
    cols = []
    vals = []
    for key, value in fields.items():
        cols.append(f"{key}=?")
        vals.append(value)
    vals.append(appointment_id)
    conn.execute(
        f"UPDATE referral_fees SET {', '.join(cols)} WHERE appointment_id=?",
        vals,
    )


def _as_charge_id(body: dict) -> str:
    value = str((body or {}).get("id") or "")
    return value if _CHARGE_RE.fullmatch(value) else ""


def _as_transfer_id(body: dict) -> str:
    value = str((body or {}).get("id") or "")
    return value if _TRANSFER_RE.fullmatch(value) else ""


def _as_intent_id(body: dict) -> str:
    value = (body or {}).get("payment_intent") or ""
    if isinstance(value, dict):
        value = value.get("id") or ""
    value = str(value or "")
    return value if _INTENT_RE.fullmatch(value) else ""


def _amount_ok(body: dict, expected: int) -> bool:
    if "amount" not in body or body.get("amount") is None:
        return True
    try:
        return int(body.get("amount")) == int(expected)
    except (TypeError, ValueError):
        return False


def _names(conn, appt, referrer_id: int) -> tuple[str, str, str]:
    client = None
    if appt["client_id"]:
        client = conn.execute("SELECT name FROM clients WHERE id=?", (appt["client_id"],)).fetchone()
    client_name = (client["name"] if client else "") or "A client"
    receiver = _user(conn, appt["provider_id"])
    referrer = _user(conn, referrer_id)
    receiver_first = first_name(receiver["name"]) if receiver else "your colleague"
    referrer_name = referrer["name"] if referrer else "your colleague"
    return client_name, receiver_first, referrer_name


def _notify_result(conn, appt, referrer_id: int, parts: dict, status: str) -> None:
    client_name, receiver_first, referrer_name = _names(conn, appt, referrer_id)
    fee = fees.money_label(parts["referral_fee_cents"])
    referrer_amt = fees.money_label(parts["referrer_share_cents"])
    platform_amt = fees.money_label(parts["platform_share_cents"])
    if status == "charged":
        notify(
            conn,
            appt["provider_id"],
            "referral_fee",
            f"Referral fee charged — {fee}",
            (
                f"{client_name}'s first booking came from {referrer_name}. "
                f"{referrer_amt} goes to {referrer_name}. {platform_amt} goes to ScheduleAVisit. "
                "The client was not charged this fee."
            ),
        )
        if parts["referrer_share_cents"] > 0:
            notify(
                conn,
                referrer_id,
                "referral_fee",
                f"Referral share — {referrer_amt}",
                (
                    f"{referrer_amt} from {client_name}'s first booking with {receiver_first} "
                    "is on the way to your Stripe account."
                ),
            )
        return
    if status == "charged_unsplit":
        notify(
            conn,
            appt["provider_id"],
            "referral_fee",
            f"Referral fee charged — {fee}",
            (
                f"{client_name}'s first booking came from {referrer_name}. "
                f"{platform_amt} is ScheduleAVisit's share. "
                f"The {referrer_amt} for {referrer_name} is still waiting to be sent. "
                "The client was not charged this fee."
            ),
        )
        return
    notify(
        conn,
        appt["provider_id"],
        "referral_fee",
        f"Referral fee owed — {fee}",
        (
            f"{client_name}'s first booking came from {referrer_name}. "
            f"The {fee} referral fee was not charged. "
            f"{referrer_amt} would go to {referrer_name} and {platform_amt} to ScheduleAVisit. "
            "The visit is still booked. The client was not charged this fee."
        ),
    )


def collect_for_appointment(conn, appointment_id: int) -> None:
    """Record and, when Stripe is ready, collect the referral fee. Never raises."""
    try:
        _collect(conn, int(appointment_id))
    except Exception as exc:
        log_referral(
            f"collector stopped {type(exc).__name__} appointment_id={appointment_id} booking kept"
        )


def _collect(conn, appointment_id: int) -> None:
    appt = conn.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone()
    if not appt:
        return
    if not _is_first_referral(conn, appt):
        if (appt["booked_via"] or "") == "referral":
            log_referral(
                f"not a first referral booking appointment_id={appointment_id} "
                f"provider_id={appt['provider_id']}"
            )
        return
    referrer_id = int(appt["referred_from_provider_id"])
    parts = split_amounts()
    if parts["referral_fee_cents"] <= 0:
        log_referral(
            f"skipped reason=fee_disabled appointment_id={appointment_id} "
            f"referrer_id={referrer_id} receiver_id={appt['provider_id']}"
        )
        return
    existing = conn.execute(
        "SELECT * FROM referral_fees WHERE appointment_id=?",
        (appointment_id,),
    ).fetchone()
    if existing and (existing["status"] or "") in _DONE:
        return
    if existing is None:
        _insert_pending(conn, appt, parts, referrer_id)
    else:
        parts = {
            "referral_fee_cents": int(existing["referral_fee_cents"]),
            "referrer_share_bps": int(existing["referrer_share_bps"]),
            "referrer_share_cents": int(existing["referrer_share_cents"]),
            "platform_share_cents": int(existing["platform_share_cents"]),
            "split": existing["split"] or "",
        }
    base = (
        f"appointment_id={appointment_id} referrer_id={referrer_id} "
        f"receiver_id={appt['provider_id']} fee_cents={parts['referral_fee_cents']} "
        f"split={parts['split']}"
    )
    if not fees.configured():
        reason = "Stripe is not set up on this server, so this charge was skipped."
        _update(conn, appointment_id, status="skipped", error=reason)
        log_referral(f"skipped reason=stripe_not_configured {base} booking kept")
        _notify_result(conn, appt, referrer_id, parts, "skipped")
        return
    receiver = _user(conn, appt["provider_id"])
    referrer = _user(conn, referrer_id)
    receiver_account = _account_id(receiver)
    referrer_account = _account_id(referrer)
    _update(
        conn,
        appointment_id,
        receiver_account_id=receiver_account,
        referrer_account_id=referrer_account,
    )
    if not receiver_account:
        reason = "Connect Stripe to pay this referral fee. Nothing was charged."
        _update(conn, appointment_id, status="owed", error=reason)
        log_referral(f"owed reason=no_receiver_account {base} booking kept")
        _notify_result(conn, appt, referrer_id, parts, "owed")
        return
    if parts["referrer_share_cents"] > 0 and not referrer_account:
        reason = (
            "The colleague who referred this client has not connected Stripe, "
            "so the fee was not charged."
        )
        _update(conn, appointment_id, status="owed", error=reason)
        log_referral(f"owed reason=no_referrer_account {base} booking kept")
        _notify_result(conn, appt, referrer_id, parts, "owed")
        return
    try:
        payment = fees.stripe_call(
            "POST",
            "/v1/charges",
            {
                "amount": str(parts["referral_fee_cents"]),
                "currency": "usd",
                "source": receiver_account,
                "description": f"Referral fee for first booking {appointment_id}"[:350],
                "metadata[appointment_id]": str(appointment_id),
                "metadata[referrer_id]": str(referrer_id),
                "metadata[receiver_id]": str(appt["provider_id"]),
                "metadata[purpose]": "referral_fee",
                "metadata[split]": parts["split"],
            },
            idempotency_key=f"referral-fee-{appointment_id}",
        )
    except fees.StripeError as exc:
        _update(conn, appointment_id, status="owed", error=exc.message)
        log_referral(
            f"charge failed code={exc.code} {base} booking kept"
        )
        _notify_result(conn, appt, referrer_id, parts, "owed")
        return
    charge_id = _as_charge_id(payment)
    intent_id = _as_intent_id(payment)
    paid = (payment.get("status") or "") in ("succeeded", "paid")
    if not charge_id or not paid or not _amount_ok(payment, parts["referral_fee_cents"]):
        _update(
            conn,
            appointment_id,
            status="owed",
            stripe_charge_id=charge_id,
            stripe_payment_intent_id=intent_id,
            error="Stripe did not confirm the referral fee. Nothing else was charged.",
        )
        log_referral(f"charge not confirmed {base} booking kept")
        _notify_result(conn, appt, referrer_id, parts, "owed")
        return
    if parts["referrer_share_cents"] <= 0:
        _update(
            conn,
            appointment_id,
            status="charged",
            stripe_charge_id=charge_id,
            stripe_payment_intent_id=intent_id,
            error="",
            charged_at=now_iso(),
        )
        log_referral(f"charged charge={charge_id} transfer=none {base}")
        _notify_result(conn, appt, referrer_id, parts, "charged")
        return
    try:
        transfer = fees.stripe_call(
            "POST",
            "/v1/transfers",
            {
                "amount": str(parts["referrer_share_cents"]),
                "currency": "usd",
                "destination": referrer_account,
                "description": f"Referral share for first booking {appointment_id}"[:350],
                "metadata[appointment_id]": str(appointment_id),
                "metadata[referrer_id]": str(referrer_id),
                "metadata[receiver_id]": str(appt["provider_id"]),
                "metadata[purpose]": "referral_fee_share",
                "metadata[split]": parts["split"],
            },
            idempotency_key=f"referral-fee-share-{appointment_id}",
        )
    except fees.StripeError as exc:
        _update(
            conn,
            appointment_id,
            status="charged_unsplit",
            stripe_charge_id=charge_id,
            stripe_payment_intent_id=intent_id,
            error=exc.message,
            charged_at=now_iso(),
        )
        log_referral(
            f"charged_unsplit charge={charge_id} transfer_failed code={exc.code} {base}"
        )
        _notify_result(conn, appt, referrer_id, parts, "charged_unsplit")
        return
    transfer_id = _as_transfer_id(transfer)
    if not transfer_id or not _amount_ok(transfer, parts["referrer_share_cents"]):
        _update(
            conn,
            appointment_id,
            status="charged_unsplit",
            stripe_charge_id=charge_id,
            stripe_payment_intent_id=intent_id,
            error="The referral fee was collected. The colleague's share was not confirmed.",
            charged_at=now_iso(),
        )
        log_referral(f"charged_unsplit charge={charge_id} transfer_unconfirmed {base}")
        _notify_result(conn, appt, referrer_id, parts, "charged_unsplit")
        return
    _update(
        conn,
        appointment_id,
        status="charged",
        stripe_charge_id=charge_id,
        stripe_transfer_id=transfer_id,
        stripe_payment_intent_id=intent_id,
        error="",
        charged_at=now_iso(),
    )
    log_referral(f"charged charge={charge_id} transfer={transfer_id} {base}")
    _notify_result(conn, appt, referrer_id, parts, "charged")


def dashboard_rows(conn, user_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT f.*, c.name AS client_name, r.name AS referrer_name
           FROM referral_fees f
           JOIN appointments a ON a.id = f.appointment_id
           LEFT JOIN clients c ON c.id = a.client_id
           JOIN users r ON r.id = f.referrer_id
           WHERE f.receiver_id=?
           ORDER BY f.id DESC
           LIMIT 20""",
        (int(user_id),),
    ).fetchall()
    out = []
    for row in rows:
        fee = fees.money_label(int(row["referral_fee_cents"] or 0))
        referrer_amt = fees.money_label(int(row["referrer_share_cents"] or 0))
        platform_amt = fees.money_label(int(row["platform_share_cents"] or 0))
        client_name = row["client_name"] or "A client"
        referrer_name = row["referrer_name"] or "A colleague"
        status = row["status"] or ""
        if status in ("charged", "charged_unsplit"):
            headline = f"Referral fee charged: {fee}"
        else:
            headline = f"Referral fee owed: {fee}"
        if status == "charged":
            detail = (
                f"{client_name}'s first booking from {referrer_name}. "
                f"{referrer_amt} goes to {referrer_name}. {platform_amt} goes to ScheduleAVisit."
            )
        elif status == "charged_unsplit":
            detail = (
                f"{client_name}'s first booking from {referrer_name}. "
                f"{platform_amt} is ScheduleAVisit's share. "
                f"The {referrer_amt} for {referrer_name} is still waiting to be sent."
            )
        elif status == "skipped":
            detail = (
                f"{client_name}'s first booking from {referrer_name}. "
                "Not charged. Stripe is not set up on this server, so this charge was skipped."
            )
        else:
            extra = (row["error"] or "").strip()
            detail = (
                f"{client_name}'s first booking from {referrer_name}. Not charged."
            )
            if extra:
                detail = f"{detail} {extra}"
        out.append({
            "id": row["id"],
            "status": status,
            "headline": headline,
            "detail": detail,
        })
    return out
