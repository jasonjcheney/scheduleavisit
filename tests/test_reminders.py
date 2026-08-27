#!/usr/bin/env python3
"""Appointment reminder rows, opt-in copies, cancel, and senders-missing booking."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fd, DBFILE = tempfile.mkstemp(suffix="-reminders.db")
os.close(fd)
os.environ["SAV_DB"] = DBFILE

# Booking must succeed when mail/SMS env is absent. Do not put real keys here.
for _k in (
    "RESEND_API_KEY",
    "MAILGUN_API_KEY",
    "SMTP_HOST",
    "SMTP_URL",
    "SMTP_SERVER",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_FROM",
):
    os.environ.pop(_k, None)

os.environ["REMINDER_TICK_SECRET"] = "tick-test-only"

TZ = ZoneInfo("America/Denver")


def fail(msg: str) -> None:
    print("FAIL:", msg)
    sys.exit(1)


def expect(cond: bool, msg: str) -> None:
    if not cond:
        fail(msg)


def future_weekday(hour=10, days_ahead=8):
    d = datetime.now(TZ).date() + timedelta(days=days_ahead)
    while d.isoweekday() > 5:
        d += timedelta(days=1)
    return d, f"{hour:02d}:00"


def reminders_for(conn, appt_id: int):
    return conn.execute(
        "SELECT * FROM reminders WHERE appointment_id=? ORDER BY id",
        (appt_id,),
    ).fetchall()


def main() -> None:
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        os.system(f"{sys.executable} -m pip install -q httpx")
        from fastapi.testclient import TestClient

    from app import app
    from db import connect, init_db, parse_iso
    from reminders import FOOTER, build_copy, reminder_times

    with connect() as conn:
        init_db(conn)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        expect("reminders" in tables, "reminders table missing after init_db")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        expect("phone" in cols and "reminders_opt_in" in cols, "users missing reminder columns")
        elena = conn.execute("SELECT reminders_opt_in FROM users WHERE slug='elena-vasquez-lpc'").fetchone()
        expect(int(elena["reminders_opt_in"] or 0) == 0, "Elena should default opt-in OFF")
        jason = conn.execute("SELECT reminders_opt_in FROM users WHERE username='jasoncheney'").fetchone()
        expect(int(jason["reminders_opt_in"] or 0) == 0, "Jason should default opt-in OFF")

    day, hhmm = future_weekday(10, 8)
    start = datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time(), tzinfo=TZ)
    times = reminder_times(start)
    expect(abs((times["day_before"] - (start - timedelta(hours=24))).total_seconds()) < 1, "day_before not ~24h before")
    expect(times["morning_of"].hour == 8 and times["morning_of"].minute == 0, "morning_of not 8:00")
    expect(times["morning_of"].date() == day, "morning_of wrong date")
    expect(str(times["morning_of"].tzinfo) == "America/Denver" or times["morning_of"].tzinfo == TZ, "morning_of tz")

    subj, body, sms = build_copy(
        "booked", "client",
        client_first="Pat",
        therapist_name="Jason Cheney",
        start=start,
        clinic="My practice",
        address="Boulder, CO",
    )
    blob = f"{subj}\n{body}\n{sms}".lower()
    expect("pat" in blob and "jason cheney" in blob, "copy missing names")
    expect("hipaa" not in blob and "phi" not in blob, "copy must not claim HIPAA")
    expect("diagnosis" not in blob and "clinical note" not in blob, "copy must stay scheduling-only")
    expect(FOOTER.lower() in blob, "copy missing scheduling-reminder footer")
    expect("boulder" in blob, "copy missing clinic address")

    c = TestClient(app)

    # Booking still 200 when senders are missing.
    r = c.post("/api/p/jason-cheney/book", json={
        "date": day.isoformat(),
        "time": hhmm,
        "name": "Pat Reminder",
        "email": "pat.reminder@example.com",
        "phone": "303-555-0142",
        "visitKind": "session",
    })
    expect(r.status_code == 200, f"book status {r.status_code}: {r.text}")
    body = r.json()
    expect(body.get("ok") is True, f"book failed when senders missing: {body}")
    appt_id = body["appointmentId"]

    with connect() as conn:
        rows = reminders_for(conn, appt_id)
        kinds = [row["kind"] for row in rows]
        audiences = {row["audience"] for row in rows}
        expect(len(rows) == 3, f"expected 3 client rows, got {len(rows)} {kinds}")
        expect(set(kinds) == {"booked", "day_before", "morning_of"}, f"kinds {kinds}")
        expect(audiences == {"client"}, f"default should be client-only, got {audiences}")
        by_kind = {row["kind"]: row for row in rows}
        db_start = parse_iso(
            conn.execute("SELECT start_iso FROM appointments WHERE id=?", (appt_id,)).fetchone()["start_iso"]
        )
        day_before = parse_iso(by_kind["day_before"]["send_at"])
        morning = parse_iso(by_kind["morning_of"]["send_at"])
        expect(abs((db_start - day_before).total_seconds() - 86400) < 2, f"day_before send_at {day_before}")
        expect(morning.hour == 8 and morning.minute == 0 and morning.date() == db_start.date(),
               f"morning_of send_at {morning}")
        client = conn.execute(
            "SELECT phone FROM clients WHERE email='pat.reminder@example.com'"
        ).fetchone()
        expect(client and "555" in (client["phone"] or ""), "client phone not stored")

    # Dashboard opt-in checkbox + save phone
    login = c.post("/api/auth/login", json={"email": "jasoncheney", "password": "123456"})
    expect(login.status_code == 200 and login.json().get("ok"), "jason login failed")
    setup = c.post("/api/setup", json={
        "name": "Jason Cheney",
        "credentials": "Therapist",
        "title": "Counselor",
        "clinic": "My practice",
        "address": "Boulder, CO",
        "weekly_target_hours": 25,
        "buffer_hours": 3,
        "workdays": [1, 2, 3, 4, 5],
        "phone": "303-555-0199",
        "reminders_opt_in": 1,
    })
    expect(setup.status_code == 200 and setup.json().get("ok"), f"setup failed: {setup.text}")
    dash = c.get("/dashboard")
    expect(dash.status_code == 200, f"dashboard {dash.status_code}")
    expect("Email me when clients book and before visits" in dash.text, "dashboard missing opt-in checkbox")
    expect('id="reminders-form"' in dash.text, "dashboard missing reminders form")

    me = c.get("/api/me").json()["user"]
    expect(int(me.get("reminders_opt_in") or 0) == 1, "opt-in not saved")
    expect("0199" in (me.get("phone") or ""), "therapist phone not saved")

    day2, hhmm2 = future_weekday(11, 9)
    r = c.post("/api/p/jason-cheney/book", json={
        "date": day2.isoformat(),
        "time": hhmm2,
        "name": "Sam Optin",
        "email": "sam.optin@example.com",
        "visitKind": "session",
    })
    expect(r.status_code == 200 and r.json().get("ok"), f"opt-in book failed: {r.text}")
    appt2 = r.json()["appointmentId"]
    with connect() as conn:
        rows = reminders_for(conn, appt2)
        kinds = {(row["kind"], row["audience"]) for row in rows}
        expect(len(rows) == 6, f"opt-in should add therapist copies, got {len(rows)}")
        expect(kinds == {
            ("booked", "client"), ("day_before", "client"), ("morning_of", "client"),
            ("booked", "therapist"), ("day_before", "therapist"), ("morning_of", "therapist"),
        }, f"opt-in kinds {kinds}")

    # Cancel removes pending leftovers
    r = c.post(f"/api/me/appointments/{appt2}/cancel")
    expect(r.status_code == 200 and r.json().get("ok"), f"cancel failed: {r.text}")
    with connect() as conn:
        pending = conn.execute(
            "SELECT id FROM reminders WHERE appointment_id=? AND status='pending'",
            (appt2,),
        ).fetchall()
        expect(len(pending) == 0, f"cancel left pending rows: {len(pending)}")
        cancelled = conn.execute(
            "SELECT id FROM reminders WHERE appointment_id=? AND status='cancelled'",
            (appt2,),
        ).fetchall()
        expect(len(cancelled) >= 2, "cancel should mark leftover scheduled reminders cancelled")

    # Reschedule: leftover cancelled, new set created
    day3, hhmm3 = future_weekday(14, 10)
    r = c.post("/api/p/jason-cheney/book", json={
        "date": day3.isoformat(),
        "time": hhmm3,
        "name": "Riley Move",
        "email": "riley.move@example.com",
        "visitKind": "session",
    })
    expect(r.status_code == 200 and r.json().get("ok"), f"reschedule-prep book failed: {r.text}")
    appt3 = r.json()["appointmentId"]
    with connect() as conn:
        before_ids = {row["id"] for row in reminders_for(conn, appt3)}
        expect(len(before_ids) == 6, f"pre-reschedule rows {len(before_ids)}")
    new_day, new_time = future_weekday(15, 11)
    r = c.post(f"/api/me/appointments/{appt3}/reschedule", json={"date": new_day.isoformat(), "time": new_time})
    expect(r.status_code == 200 and r.json().get("ok"), f"reschedule failed: {r.text}")
    with connect() as conn:
        rows = reminders_for(conn, appt3)
        pending = [row for row in rows if row["status"] == "pending"]
        cancelled = [row for row in rows if row["status"] == "cancelled"]
        expect(len(cancelled) >= 2, "reschedule should cancel leftover pending")
        new_pending_kinds = {(row["kind"], row["audience"]) for row in pending}
        expect(("day_before", "client") in new_pending_kinds, "reschedule missing new day_before")
        expect(("morning_of", "client") in new_pending_kinds, "reschedule missing new morning_of")
        new_start = parse_iso(conn.execute("SELECT start_iso FROM appointments WHERE id=?", (appt3,)).fetchone()["start_iso"])
        morning = next(parse_iso(row["send_at"]) for row in pending if row["kind"] == "morning_of" and row["audience"] == "client")
        expect(morning.date() == new_start.date() and morning.hour == 8, f"reschedule morning_of {morning}")

    # Referral book also creates the three client rows (James, opt-in still off)
    c.post("/api/auth/logout")
    day4, hhmm4 = future_weekday(9, 12)
    r = c.post("/api/p/elena-vasquez-lpc/book-referral", json={
        "peerSlug": "james-okonkwo-lcsw",
        "date": day4.isoformat(),
        "time": hhmm4,
        "name": "Sam Overflow",
        "email": "sam.overflow.remind@example.com",
        "phone": "303-555-0177",
    })
    expect(r.status_code == 200 and r.json().get("ok"), f"referral book failed: {r.text}")
    ref_id = r.json()["appointmentId"]
    with connect() as conn:
        rows = reminders_for(conn, ref_id)
        kinds = [row["kind"] for row in rows]
        expect(set(kinds) == {"booked", "day_before", "morning_of"}, f"referral kinds {kinds}")
        expect(all(row["audience"] == "client" for row in rows), "James default opt-in should be off")

    # Tick endpoint: secret header required; no-op senders still 200
    bare = c.post("/internal/reminders/tick")
    expect(bare.status_code == 403, f"tick without secret should 403, got {bare.status_code}")
    tick = c.post("/internal/reminders/tick", headers={"X-Reminder-Secret": "tick-test-only"})
    expect(tick.status_code == 200 and tick.json().get("ok"), f"tick failed: {tick.text}")

    print("ALL REMINDER TESTS PASSED")


if __name__ == "__main__":
    main()
