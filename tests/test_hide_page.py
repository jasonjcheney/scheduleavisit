#!/usr/bin/env python3
"""Hide my page drops a therapist from the directory and referrals, and is reversible."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fd, DBFILE = tempfile.mkstemp(suffix="-hide-page.db")
os.close(fd)
os.environ["SAV_DB"] = DBFILE
os.environ.setdefault("SAV_JASON_PASSWORD", "123456")
os.environ.setdefault("SAV_DEMO_PASSWORD", "demo1234")
os.environ.setdefault("SHOW_DEMO_COUNSELORS", "1")

TZ = ZoneInfo("America/Denver")


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def expect(cond, msg):
    if not cond:
        fail(msg)


def future_weekday():
    now = datetime.now(TZ)
    d = now.date() + timedelta(days=2)
    while d.isoweekday() > 5:
        d += timedelta(days=1)
    return d


def setup_body(**extra):
    body = {
        "name": "Jason Cheney",
        "credentials": "LPC",
        "title": "Counselor",
        "specialty": "Anxiety and life transitions",
        "about": "I meet with adults.",
        "clinic": "Front Range Counseling",
        "address": "Grand Junction, CO",
        "weekly_target_hours": 22,
        "buffer_hours": 3,
        "slot_start": 9,
        "slot_end": 17,
        "lunch": 12,
        "session_minutes": 50,
        "consult_minutes": 15,
        "consult_enabled": 1,
        "workdays": [1, 2, 3, 4, 5],
        "portal_kind": "none",
        "portal_url": "",
        "ical_url": "",
    }
    body.update(extra)
    return body


def main():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        os.system(f"{sys.executable} -m pip install -q httpx")
        from fastapi.testclient import TestClient

    from app import app
    from capacity import referral_candidates
    from db import connect, today

    with TestClient(app) as client:
        r = client.post("/api/auth/login", json={"email": "jasoncheney", "password": "123456"})
        expect(r.json().get("ok"), f"login {r.text}")
        r = client.post("/api/setup", json=setup_body())
        expect(r.json().get("ok"), f"setup {r.text}")

        setup_page = client.get("/setup")
        dash = client.get("/dashboard")
        expect("Hide my page" in setup_page.text, "setup form missing Hide my page")
        expect('name="page_hidden"' in setup_page.text, "setup missing the toggle")
        expect("Hide my page" in dash.text, "dashboard edit form missing Hide my page")
        expect('id="hide-page"' in dash.text, "dashboard missing the toggle")

        with connect() as conn:
            row = conn.execute(
                "SELECT page_hidden, weekly_target_hours, slot_end FROM users WHERE username='jasoncheney'"
            ).fetchone()
            elena = conn.execute(
                "SELECT page_hidden FROM users WHERE slug='elena-vasquez-lpc'"
            ).fetchone()
        expect(int(row["page_hidden"] or 0) == 0, "hide should default off")
        expect(int(elena["page_hidden"] or 0) == 0, "existing counselors should stay listed")
        expect(row["weekly_target_hours"] == 22, f"hours {row['weekly_target_hours']}")

        listed = client.get("/book?q=Jason")
        expect('href="/p/jason-cheney"' in listed.text, "Jason should be in search before hiding")

        with connect() as conn:
            jason = conn.execute("SELECT * FROM users WHERE username='jasoncheney'").fetchone()
            peers = [p["slug"] for p in referral_candidates(conn, jason, today(), "11:00", 50)]
        expect("james-okonkwo-lcsw" in peers, f"James should be referable before hide: {peers}")

        hidden = client.patch("/api/me", json={"page_hidden": 1})
        expect(hidden.status_code == 200 and hidden.json().get("ok"), f"hide {hidden.text}")
        with connect() as conn:
            row = conn.execute(
                "SELECT page_hidden, weekly_target_hours, slot_end, buffer_hours FROM users WHERE username='jasoncheney'"
            ).fetchone()
            jason = conn.execute("SELECT * FROM users WHERE username='jasoncheney'").fetchone()
            peers = [p["slug"] for p in referral_candidates(conn, jason, today(), "11:00", 50)]
        expect(int(row["page_hidden"]) == 1, "hide flag did not save")
        expect(row["weekly_target_hours"] == 22, "hiding changed the weekly target")
        expect(int(row["slot_end"]) == 17, "hiding changed day-end hour")
        expect(row["buffer_hours"] == 3, "hiding changed the buffer")
        expect("james-okonkwo-lcsw" in peers, "hiding Jason should not remove his colleagues")

        gone = client.get("/book?q=Jason")
        expect('href="/p/jason-cheney"' not in gone.text, "hidden page still in search")
        directory = client.get("/book")
        expect('href="/p/jason-cheney"' not in directory.text, "hidden page still on /book")

        with connect() as conn:
            james = conn.execute("SELECT * FROM users WHERE slug='james-okonkwo-lcsw'").fetchone()
            conn.execute("UPDATE users SET page_hidden=1 WHERE id=?", (james["id"],))
            conn.commit()
            jason = conn.execute("SELECT * FROM users WHERE username='jasoncheney'").fetchone()
            conn.execute("UPDATE users SET page_hidden=0 WHERE id=?", (jason["id"],))
            conn.commit()
            jason = conn.execute("SELECT * FROM users WHERE username='jasoncheney'").fetchone()
            peers = [p["slug"] for p in referral_candidates(conn, jason, today(), "11:00", 50)]
        expect("james-okonkwo-lcsw" not in peers, f"hidden James still offered as a referral: {peers}")

        day = future_weekday()
        refused_ref = client.post("/api/p/jason-cheney/book-referral", json={
            "peerSlug": "james-okonkwo-lcsw",
            "date": day.isoformat(),
            "time": "11:00",
            "name": "Pat Client",
            "email": "pat.hide@example.com",
        })
        expect(refused_ref.status_code == 400, f"referral status {refused_ref.status_code}")
        expect("isn't taking bookings right now" in (refused_ref.json().get("error") or ""), refused_ref.text)

        with connect() as conn:
            conn.execute("UPDATE users SET page_hidden=1 WHERE username='jasoncheney'")
            conn.execute("UPDATE users SET page_hidden=0 WHERE slug='james-okonkwo-lcsw'")
            conn.commit()

        page = client.get("/p/jason-cheney")
        expect(page.status_code == 200, f"public page {page.status_code}")
        expect('id="bookings-paused"' in page.text, "public page missing the paused message")
        expect("isn't taking bookings right now" in page.text, "public page missing the plain sentence")
        expect('id="schedule-card"' not in page.text, "hidden page still shows the time picker")
        refused = client.post("/api/p/jason-cheney/book", json={
            "date": day.isoformat(),
            "time": "10:00",
            "name": "Pat Client",
            "email": "pat.hide@example.com",
            "visitKind": "session",
        })
        expect(refused.status_code == 400, f"book status {refused.status_code}")
        expect("isn't taking bookings right now" in (refused.json().get("error") or ""), refused.text)

        shown = client.patch("/api/me", json={"page_hidden": 0})
        expect(shown.json().get("ok"), f"unhide {shown.text}")
        with connect() as conn:
            row = conn.execute(
                "SELECT page_hidden, weekly_target_hours FROM users WHERE username='jasoncheney'"
            ).fetchone()
        expect(int(row["page_hidden"]) == 0, "unhide did not clear the flag")
        expect(row["weekly_target_hours"] == 22, "unhide changed hours")
        back = client.get("/book?q=Jason")
        expect('href="/p/jason-cheney"' in back.text, "Jason should return to search")
        open_page = client.get("/p/jason-cheney")
        expect('id="schedule-card"' in open_page.text, "time picker should return")
        expect('id="bookings-paused"' not in open_page.text, "paused message stayed after unhide")
        booked = client.post("/api/p/jason-cheney/book", json={
            "date": day.isoformat(),
            "time": "10:00",
            "name": "Pat Client",
            "email": "pat.hide@example.com",
            "visitKind": "session",
        })
        expect(booked.json().get("ok"), f"booking after unhide failed: {booked.text}")
        print("OK hide my page is reversible and leaves hours alone")


if __name__ == "__main__":
    main()
