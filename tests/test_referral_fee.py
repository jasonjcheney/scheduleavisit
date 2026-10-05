#!/usr/bin/env python3
"""Referral fee: referred vs direct, soft-fail without Stripe, and the $20 split."""
from __future__ import annotations

import os
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fd, DBFILE = tempfile.mkstemp(suffix="-referral-fee.db")
os.close(fd)
os.environ["SAV_DB"] = DBFILE
os.environ.setdefault("SAV_JASON_PASSWORD", "123456")
os.environ.setdefault("SAV_DEMO_PASSWORD", "demo1234")
os.environ.pop("SHOW_DEMO_COUNSELORS", None)
for _name in (
    "STRIPE_SECRET_KEY",
    "STRIPE_PUBLISHABLE_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "REFERRAL_FEE_CENTS",
    "REFERRAL_REFERRER_SHARE_BPS",
):
    os.environ.pop(_name, None)

SECRET = "sk_test_NEVERLOG_991"
PUBLISHABLE = "pk_test_NEVERLOG_992"
WEBHOOK = "whsec_NEVERLOG_993"
TZ = ZoneInfo("America/Denver")
RECEIVER_ACCT = "acct_receiver_123"
REFERRER_ACCT = "acct_referrer_123"


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
    from referral_fees import referral_fee_cents, referrer_share_bps, split_amounts

    os.environ["REFERRAL_FEE_CENTS"] = "2001"
    os.environ["REFERRAL_REFERRER_SHARE_BPS"] = "2500"
    odd = split_amounts()
    expect(odd["referral_fee_cents"] == 2001, odd)
    expect(odd["referrer_share_cents"] == 500, odd)
    expect(odd["platform_share_cents"] == 1501, odd)
    expect(odd["referrer_share_cents"] + odd["platform_share_cents"] == 2001, odd)
    expect(odd["split"] == "referrer:500;platform:1501;bps:2500", odd["split"])
    explicit = split_amounts(2000, 2500)
    expect(explicit["referral_fee_cents"] == 2000, explicit)
    expect(explicit["referrer_share_cents"] == 500, explicit)
    expect(explicit["platform_share_cents"] == 1500, explicit)
    expect(explicit["split"] == "referrer:500;platform:1500;bps:2500", explicit["split"])
    os.environ["REFERRAL_FEE_CENTS"] = "nope"
    os.environ["REFERRAL_REFERRER_SHARE_BPS"] = "25000"
    expect(referral_fee_cents() == 2000, "bad fee env should use the default")
    expect(referrer_share_bps() == 2500, "bad bps env should use the default")
    os.environ.pop("REFERRAL_FEE_CENTS", None)
    os.environ.pop("REFERRAL_REFERRER_SHARE_BPS", None)
    default = split_amounts()
    expect(default["referral_fee_cents"] == 2000, default)
    expect(default["referrer_share_bps"] == 2500, default)
    expect(default["referrer_share_cents"] == 500, default)
    expect(default["platform_share_cents"] == 1500, default)
    print("OK split math is $5 and $15 on a $20 fee, and bad env falls back")

    from app import app
    from db import add_link, connect, hash_password, now_iso

    calls: list[dict] = []
    state = {"mode": "ok"}

    def fake_stripe(method, path, data=None, stripe_account="", idempotency_key=""):
        rec = {
            "method": method,
            "path": path,
            "data": dict(data or {}),
            "stripe_account": stripe_account,
            "idempotency_key": idempotency_key,
        }
        calls.append(rec)
        if state["mode"] == "boom" and method == "POST" and path == "/v1/charges":
            raise fees.StripeError("Stripe could not be reached. Nothing was charged.", "network")
        if method == "POST" and path == "/v1/charges":
            expect(stripe_account == "", "referral debit must be on the platform, not the connected account")
            expect(data.get("amount") == "2000", data)
            expect(data.get("currency") == "usd", data)
            expect(data.get("source") == RECEIVER_ACCT, data)
            expect(data.get("metadata[purpose]") == "referral_fee", data)
            expect("clinical" not in (data.get("description") or "").lower(), data)
            expect("@" not in str(data), "referral debit included an email")
            return {"id": "py_test_fee", "status": "succeeded", "amount": 2000}
        if method == "POST" and path == "/v1/transfers":
            expect(stripe_account == "", "referrer transfer must be on the platform")
            expect(data.get("amount") == "500", data)
            expect(data.get("destination") == REFERRER_ACCT, data)
            expect(data.get("metadata[purpose]") == "referral_fee_share", data)
            return {"id": "tr_test_share", "amount": 500}
        if method == "POST" and path == "/v1/customers":
            expect(stripe_account == RECEIVER_ACCT, "card setup must stay on the receiver")
            return {"id": "cus_test_123"}
        if method == "POST" and path == "/v1/checkout/sessions":
            expect(data.get("mode") == "setup", data)
            expect("amount" not in (data or {}), "missed-fee checkout must not charge")
            expect(stripe_account == RECEIVER_ACCT, data)
            return {"id": "cs_test_123", "url": "https://checkout.stripe.com/c/pay/cs_test_123"}
        if method == "GET" and "/v1/checkout/sessions/" in path:
            hold = ""
            for older in reversed(calls):
                if older["method"] == "POST" and older["path"] == "/v1/checkout/sessions":
                    hold = older["data"].get("metadata[hold_token]") or ""
                    break
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
        fail(f"unexpected stripe call {method} {path}")

    fees.stripe_call = fake_stripe

    def add_user(conn, email, name, slug):
        cur = conn.execute(
            """INSERT INTO users (
                 email, password_hash, name, credentials, title, specialty, about, clinic, address,
                 slug, weekly_target_hours, buffer_hours, workdays, slot_start, slot_end, lunch,
                 session_minutes, timezone, created_at, username, setup_complete, consult_enabled
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                email, hash_password("test1234"), name, "", "Counselor", "Counseling",
                "About", "Clinic", "Boulder, CO", slug, 25, 0, "[1,2,3,4,5]", 9, 17, 12,
                50, "America/Denver", now_iso(), slug.split("-")[0], 1, 0,
            ),
        )
        return int(cur.lastrowid)

    with TestClient(app) as c:
        with connect() as conn:
            origin_id = add_user(conn, "ada@example.com", "Ada Origin", "ada-origin")
            receiver_id = add_user(conn, "beau@example.com", "Beau Receiver", "beau-receiver")
            add_link(conn, origin_id, receiver_id)
            conn.commit()

        def book_direct(day, hhmm, name, email):
            return c.post("/api/p/beau-receiver/book", json={
                "date": day.isoformat(),
                "time": hhmm,
                "name": name,
                "email": email,
                "visitKind": "session",
            })

        def book_referral(day, hhmm, name, email, consent=""):
            body = {
                "peerSlug": "beau-receiver",
                "date": day.isoformat(),
                "time": hhmm,
                "name": name,
                "email": email,
            }
            if consent:
                body["feeConsent"] = consent
            return c.post("/api/p/ada-origin/book-referral", json=body)

        day, hhmm = future_slot(10, 8)
        direct, direct_log = quiet(lambda: book_direct(day, hhmm, "Dana Direct", "dana.direct@example.com"))
        expect(direct.status_code == 200 and direct.json().get("ok"), direct.text)
        expect("referral-fee" not in direct_log, f"direct booking logged a referral fee: {direct_log}")
        with connect() as conn:
            direct_row = conn.execute(
                """SELECT a.id FROM appointments a
                   JOIN clients cl ON cl.id=a.client_id
                   WHERE cl.email=?""",
                ("dana.direct@example.com",),
            ).fetchone()
            expect(direct_row is not None, "direct visit missing")
            fee = conn.execute(
                "SELECT id FROM referral_fees WHERE appointment_id=?",
                (direct_row["id"],),
            ).fetchone()
            expect(fee is None, "direct booking created a referral fee")
        print("OK a direct booking does not create a referral fee")

        day2, hhmm2 = future_slot(11, 9)
        referred, ref_log = quiet(lambda: book_referral(day2, hhmm2, "Riley Referred", "riley.referred@example.com"))
        expect(referred.status_code == 200 and referred.json().get("ok"), referred.text)
        expect(referred.json().get("redirect", "").startswith("/booked/"), referred.text)
        expect("stripe_not_configured" in ref_log, f"soft-fail log missing: {ref_log}")
        expect("booking kept" in ref_log, f"soft-fail log did not say the booking was kept: {ref_log}")
        expect(not calls, f"unconfigured Stripe was called: {calls}")
        with connect() as conn:
            skipped = conn.execute(
                """SELECT f.*, a.status AS appt_status, a.booked_via, a.provider_id, a.referred_from_provider_id
                   FROM referral_fees f
                   JOIN appointments a ON a.id=f.appointment_id
                   JOIN clients cl ON cl.id=a.client_id
                   WHERE cl.email=?""",
                ("riley.referred@example.com",),
            ).fetchone()
            expect(skipped is not None, "skipped referral fee was not stored")
            expect(skipped["status"] == "skipped", skipped["status"])
            expect(skipped["appt_status"] == "booked", skipped["appt_status"])
            expect(skipped["booked_via"] == "referral", skipped["booked_via"])
            expect(int(skipped["referral_fee_cents"]) == 2000, skipped["referral_fee_cents"])
            expect(int(skipped["referrer_share_cents"]) == 500, skipped["referrer_share_cents"])
            expect(int(skipped["platform_share_cents"]) == 1500, skipped["platform_share_cents"])
            expect(int(skipped["referrer_share_bps"]) == 2500, skipped["referrer_share_bps"])
            expect(skipped["split"] == "referrer:500;platform:1500;bps:2500", skipped["split"])
            expect(int(skipped["referrer_id"]) == origin_id, skipped["referrer_id"])
            expect(int(skipped["receiver_id"]) == receiver_id, skipped["receiver_id"])
            expect(int(skipped["referred_from_provider_id"]) == origin_id, "referrer was not the origin")
            expect(int(skipped["provider_id"]) == receiver_id, "receiver was not the visit provider")
            expect(not skipped["stripe_charge_id"], skipped["stripe_charge_id"])
            expect(not skipped["stripe_transfer_id"], skipped["stripe_transfer_id"])
        print("OK a referred booking without Stripe still books and records a skipped fee")

        os.environ["STRIPE_SECRET_KEY"] = SECRET
        os.environ["STRIPE_PUBLISHABLE_KEY"] = PUBLISHABLE
        os.environ["STRIPE_WEBHOOK_SECRET"] = WEBHOOK
        with connect() as conn:
            conn.execute(
                """UPDATE users SET stripe_account_id=?, stripe_charges_enabled=1,
                   stripe_payouts_enabled=1, stripe_details_submitted=1 WHERE id=?""",
                (RECEIVER_ACCT, receiver_id),
            )
            conn.execute(
                """UPDATE users SET stripe_account_id=?, stripe_charges_enabled=1,
                   stripe_payouts_enabled=1, stripe_details_submitted=1 WHERE id=?""",
                (REFERRER_ACCT, origin_id),
            )
            conn.commit()

        calls.clear()
        day3, hhmm3 = future_slot(14, 10)
        charged, charged_log = quiet(lambda: book_referral(day3, hhmm3, "Casey Client", "casey.client@example.com"))
        expect(charged.status_code == 200 and charged.json().get("ok"), charged.text)
        appt_id = charged.json().get("appointmentId")
        charge_calls = [rec for rec in calls if rec["path"] == "/v1/charges"]
        transfer_calls = [rec for rec in calls if rec["path"] == "/v1/transfers"]
        expect(len(charge_calls) == 1, calls)
        expect(len(transfer_calls) == 1, calls)
        expect(charge_calls[0]["idempotency_key"] == f"referral-fee-{appt_id}", charge_calls[0])
        expect(transfer_calls[0]["idempotency_key"] == f"referral-fee-share-{appt_id}", transfer_calls[0])
        expect("charged" in charged_log and "py_test_fee" in charged_log, charged_log)
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM referral_fees WHERE appointment_id=?",
                (appt_id,),
            ).fetchone()
            expect(row["status"] == "charged", row["status"])
            expect(int(row["referral_fee_cents"]) == 2000, row["referral_fee_cents"])
            expect(int(row["referrer_share_cents"]) == 500, row["referrer_share_cents"])
            expect(int(row["platform_share_cents"]) == 1500, row["platform_share_cents"])
            expect(row["split"] == "referrer:500;platform:1500;bps:2500", row["split"])
            expect(int(row["referrer_id"]) == origin_id, row["referrer_id"])
            expect(int(row["receiver_id"]) == receiver_id, row["receiver_id"])
            expect(row["stripe_charge_id"] == "py_test_fee", row["stripe_charge_id"])
            expect(row["stripe_transfer_id"] == "tr_test_share", row["stripe_transfer_id"])
            expect(row["receiver_account_id"] == RECEIVER_ACCT, row["receiver_account_id"])
            expect(row["referrer_account_id"] == REFERRER_ACCT, row["referrer_account_id"])
            expect(SECRET not in (row["error"] or ""), "stored error included the secret")
        print("OK a referred first booking debits $20 and transfers $5")

        calls.clear()
        day4, hhmm4 = future_slot(15, 11)
        again, again_log = quiet(lambda: book_referral(day4, hhmm4, "Casey Client", "casey.client@example.com"))
        expect(again.status_code == 200 and again.json().get("ok"), again.text)
        expect(not any(rec["path"] in ("/v1/charges", "/v1/transfers") for rec in calls), calls)
        expect("not a first referral booking" in again_log, again_log)
        with connect() as conn:
            count = conn.execute(
                """SELECT COUNT(*) AS n FROM referral_fees f
                   JOIN appointments a ON a.id=f.appointment_id
                   JOIN clients cl ON cl.id=a.client_id
                   WHERE cl.email=?""",
                ("casey.client@example.com",),
            ).fetchone()
            expect(int(count["n"]) == 1, "a later referral for the same client was charged again")
        print("OK a later booking for the same client is not charged again")

        logged = c.post("/api/auth/login", json={"email": "beau@example.com", "password": "test1234"})
        expect(logged.status_code == 200, logged.text)
        dash, _log = quiet(lambda: c.get("/dashboard"))
        expect(dash.status_code == 200, f"dashboard {dash.status_code}")
        expect('id="referral-fees"' in dash.text, "dashboard hid referral fees")
        expect("Referral fee charged: $20" in dash.text, dash.text)
        expect("Referral fee owed: $20" in dash.text, "skipped fee missing from the dashboard")
        expect("$5 goes to Ada Origin" in dash.text, "dashboard missing the referrer share")
        expect("$15 goes to ScheduleAVisit" in dash.text, "dashboard missing the platform share")
        expect("this charge was skipped" in dash.text, "dashboard missing the soft-fail sentence")
        expect('id="referral-fee-notice"' in dash.text, "dashboard missing the network fee notice")
        expect("$20" in dash.text and "25%" in dash.text and "75%" in dash.text, "notice missing the split")
        print("OK the receiving therapist's dashboard shows owed and charged fees")

        state["mode"] = "boom"
        calls.clear()
        day5, hhmm5 = future_slot(16, 12)
        failed, failed_log = quiet(lambda: book_referral(day5, hhmm5, "Frankie Fail", "frankie.fail@example.com"))
        expect(failed.status_code == 200 and failed.json().get("ok"), failed.text)
        expect(failed.json().get("redirect", "").startswith("/booked/"), failed.text)
        expect("booking kept" in failed_log, failed_log)
        expect(not any(rec["path"] == "/v1/transfers" for rec in calls), "a failed debit still transferred")
        with connect() as conn:
            owed = conn.execute(
                """SELECT f.status, f.error, a.status AS appt_status
                   FROM referral_fees f
                   JOIN appointments a ON a.id=f.appointment_id
                   JOIN clients cl ON cl.id=a.client_id
                   WHERE cl.email=?""",
                ("frankie.fail@example.com",),
            ).fetchone()
            expect(owed["status"] == "owed", owed["status"])
            expect(owed["appt_status"] == "booked", "failed charge cancelled the visit")
            expect("Nothing was charged" in (owed["error"] or ""), owed["error"])
            expect(SECRET not in (owed["error"] or ""), "owed error stored the secret")
        print("OK a Stripe error leaves the visit booked and the fee owed")

        state["mode"] = "ok"
        with connect() as conn:
            conn.execute("UPDATE users SET stripe_account_id='' WHERE id=?", (origin_id,))
            conn.commit()
        calls.clear()
        day6, hhmm6 = future_slot(10, 13)
        no_ref, _log = quiet(lambda: book_referral(day6, hhmm6, "No Account", "no.account@example.com"))
        expect(no_ref.status_code == 200 and no_ref.json().get("ok"), no_ref.text)
        expect(not calls, f"missing referrer account still called Stripe: {calls}")
        with connect() as conn:
            waiting = conn.execute(
                """SELECT f.status, f.error FROM referral_fees f
                   JOIN appointments a ON a.id=f.appointment_id
                   JOIN clients cl ON cl.id=a.client_id
                   WHERE cl.email=?""",
                ("no.account@example.com",),
            ).fetchone()
            expect(waiting["status"] == "owed", waiting["status"])
            expect("not connected Stripe" in (waiting["error"] or ""), waiting["error"])
            conn.execute(
                "UPDATE users SET stripe_account_id=? WHERE id=?",
                (REFERRER_ACCT, origin_id),
            )
            conn.execute(
                """UPDATE users SET missed_fee_enabled=1, missed_fee_cents=8000,
                   missed_fee_window_hours=24 WHERE id=?""",
                (receiver_id,),
            )
            joiner_id = add_user(conn, "cam@example.com", "Cam Joiner", "cam-joiner")
            conn.execute(
                """INSERT INTO network_invites
                   (from_user_id, to_email, status, token, created_at, category)
                   VALUES (?,?, 'pending', ?, ?, 'general')""",
                (origin_id, "cam@example.com", "invite-token-test", now_iso()),
            )
            conn.commit()
            expect(joiner_id > 0, "joiner missing")
        print("OK a referrer without Stripe is not charged, and the visit still books")

        c.post("/api/auth/logout")
        joined_login = c.post("/api/auth/login", json={"email": "cam@example.com", "password": "test1234"})
        expect(joined_login.status_code == 200, joined_login.text)
        invite = c.get("/invite/invite-token-test")
        expect(invite.status_code == 200, invite.status_code)
        expect('id="referral-fee-notice"' in invite.text, "join page missing the fee notice")
        expect("$20" in invite.text and "$5" in invite.text and "$15" in invite.text, invite.text)
        expect("25%" in invite.text and "75%" in invite.text, "join page missing the split")
        expect("ScheduleAVisit" in invite.text, "join page missing the platform share")
        expect("your own page" in invite.text, "join page did not say direct bookings are different")
        print("OK joining a network shows the $20 referral fee and the split")

        calls.clear()
        day7, hhmm7 = future_slot(11, 15)
        checkout, _log = quiet(lambda: book_referral(
            day7, hhmm7, "Casey Card", "casey.card@example.com", consent="yes",
        ))
        expect(checkout.status_code == 200, checkout.text)
        expect(checkout.json().get("checkoutUrl", "").startswith("https://checkout.stripe.com/"), checkout.text)
        expect(not any(rec["path"] == "/v1/charges" for rec in calls), "referral fee charged before the visit existed")
        hold = ""
        for older in reversed(calls):
            if older["path"] == "/v1/checkout/sessions":
                hold = older["data"].get("metadata[hold_token]") or ""
                break
        expect(bool(hold), "checkout did not record a hold token")
        done, _log = quiet(lambda: c.get(
            f"/book/card-saved?hold={hold}&session_id=cs_test_123",
            follow_redirects=False,
        ))
        expect(done.status_code in (302, 303), f"card return {done.status_code} {done.text[:240]}")
        with connect() as conn:
            both = conn.execute(
                """SELECT a.fee_state, a.booked_via, f.status, f.stripe_charge_id, f.stripe_transfer_id,
                          f.referral_fee_cents, f.referrer_share_cents, f.platform_share_cents
                   FROM appointments a
                   JOIN clients cl ON cl.id=a.client_id
                   JOIN referral_fees f ON f.appointment_id=a.id
                   WHERE cl.email=?""",
                ("casey.card@example.com",),
            ).fetchone()
            expect(both is not None, "card-saved referral did not record a referral fee")
            expect(both["booked_via"] == "referral", both["booked_via"])
            expect(both["fee_state"] == "card_saved", both["fee_state"])
            expect(both["status"] == "charged", both["status"])
            expect(int(both["referral_fee_cents"]) == 2000, both["referral_fee_cents"])
            expect(int(both["referrer_share_cents"]) == 500, both["referrer_share_cents"])
            expect(int(both["platform_share_cents"]) == 1500, both["platform_share_cents"])
            expect(both["stripe_charge_id"] == "py_test_fee", both["stripe_charge_id"])
            expect(both["stripe_transfer_id"] == "tr_test_share", both["stripe_transfer_id"])
        charge_paths = [rec["path"] for rec in calls]
        expect(charge_paths.count("/v1/charges") == 1, charge_paths)
        expect("/v1/payment_intents" not in charge_paths, "referral fee charged the client's saved card")
        print("OK a referred first visit can save a missed-visit card and still debit the $20 referral fee")

    print("OK referral fee")


if __name__ == "__main__":
    main()
