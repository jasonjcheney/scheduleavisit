#!/usr/bin/env python3
"""Saving Setup still stores profile and hours when an already-connected calendar is down."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fd, DBFILE = tempfile.mkstemp(suffix="-setup-save.db")
os.close(fd)
os.environ["SAV_DB"] = DBFILE
os.environ.setdefault("SAV_JASON_PASSWORD", "123456")
os.environ.setdefault("SAV_DEMO_PASSWORD", "demo1234")
os.environ.setdefault("SHOW_DEMO_COUNSELORS", "1")
os.environ["GOOGLE_CLIENT_ID"] = "setup-save.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "setup-save-secret"

GOOD_ICS = "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:Dentist\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def expect(cond, msg):
    if not cond:
        fail(msg)


def setup_body(**extra):
    body = {
        "name": "Jason Cheney",
        "credentials": "LPC",
        "title": "Counselor",
        "specialty": "Anxiety and life transitions",
        "about": "I meet with adults.",
        "clinic": "Front Range Counseling",
        "address": "Grand Junction, CO",
        "weekly_target_hours": 25,
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

    import gcal
    import icalutil
    from app import app
    from db import connect

    with TestClient(app) as client:
        r = client.post("/api/auth/login", json={"email": "jasoncheney", "password": "123456"})
        expect(r.json().get("ok"), f"login {r.text}")
        first = client.post("/api/setup", json=setup_body())
        expect(first.json().get("ok"), f"first setup {first.text}")

        blob = gcal.encrypt_refresh_token("refresh-broken")
        with connect() as conn:
            conn.execute(
                """UPDATE users SET google_refresh_token=?, google_connected_email=?
                   WHERE username='jasoncheney'""",
                (blob, "jasonjcheney@gmail.com"),
            )
            conn.commit()

        orig_refresh = gcal.refresh_access_token
        orig_list = gcal.list_busy_events

        def refused(_rt):
            raise gcal.GoogleAPIError(400, "invalid_grant")

        gcal.refresh_access_token = refused
        gcal.list_busy_events = lambda *a, **k: []
        try:
            saved = client.post("/api/setup", json=setup_body(
                name="Jason J. Cheney",
                weekly_target_hours=18,
                buffer_hours=4,
            ))
            expect(saved.status_code == 200, f"broken Google should not block save: {saved.status_code} {saved.text}")
            body = saved.json()
            expect(body.get("ok") is True, f"save not ok: {body}")
            expect("can't reach" in (body.get("warning") or "").lower(), f"missing soft warning: {body}")
            expect("saved" in (body.get("warning") or "").lower(), f"warning should say the page was saved: {body}")
            expect("/auth/google/calendar" in (body.get("reconnectUrl") or ""), f"reconnect link {body}")
            expect(body.get("error") in (None, ""), f"warning was returned as a hard error: {body}")
            hours = client.patch("/api/me", json={"weekly_target_hours": 19, "buffer_hours": 2})
            expect(hours.status_code == 200 and hours.json().get("ok"), f"hours patch blocked: {hours.text}")
        finally:
            gcal.refresh_access_token = orig_refresh
            gcal.list_busy_events = orig_list

        with connect() as conn:
            row = conn.execute(
                "SELECT name, weekly_target_hours, buffer_hours FROM users WHERE username='jasoncheney'"
            ).fetchone()
        expect(row["name"] == "Jason J. Cheney", f"name not saved: {row['name']}")
        expect(row["weekly_target_hours"] == 19, f"hours not saved: {row['weekly_target_hours']}")
        expect(row["buffer_hours"] == 2, f"buffer not saved: {row['buffer_hours']}")

        orig_fetch = icalutil.fetch_ics

        def good_fetch(url, timeout=2.0):
            return GOOD_ICS

        def bad_fetch(url, timeout=2.0):
            return "this is not a calendar"

        try:
            icalutil.fetch_ics = good_fetch
            gcal.refresh_access_token = lambda _rt: {"access_token": "at-ok"}
            gcal.list_busy_events = lambda *a, **k: []
            linked = client.post("/api/setup", json=setup_body(
                name="Jason J. Cheney",
                weekly_target_hours=19,
                ical_url="https://example.com/mine.ics",
            ))
            expect(linked.json().get("ok"), f"valid ical setup {linked.text}")

            icalutil.fetch_ics = bad_fetch
            again = client.post("/api/setup", json=setup_body(
                name="Jason J. Cheney",
                clinic="Still Here Counseling",
                weekly_target_hours=19,
                ical_url="https://example.com/mine.ics",
            ))
            expect(again.status_code == 200 and again.json().get("ok"), f"unchanged feed blocked save: {again.text}")
            expect(again.json().get("error") in (None, ""), again.text)
            with connect() as conn:
                row = conn.execute(
                    "SELECT clinic, ical_url FROM users WHERE username='jasoncheney'"
                ).fetchone()
            expect(row["clinic"] == "Still Here Counseling", f"clinic not saved: {row['clinic']}")
            expect(row["ical_url"] == "https://example.com/mine.ics", f"feed changed: {row['ical_url']}")

            typed = client.post("/api/setup", json=setup_body(
                name="Should Not Stick",
                weekly_target_hours=19,
                ical_url="http://example.com/cal.ics",
            ))
            expect(typed.status_code == 400, f"http link should still be rejected: {typed.status_code} {typed.text}")
            expect("https://" in (typed.json().get("error") or ""), typed.text)
            unread = client.post("/api/setup", json=setup_body(
                name="Should Not Stick",
                weekly_target_hours=19,
                ical_url="https://example.com/new-broken.ics",
            ))
            expect(unread.status_code == 400, f"new unreadable feed should still be rejected: {unread.status_code}")
            with connect() as conn:
                row = conn.execute(
                    "SELECT name, ical_url FROM users WHERE username='jasoncheney'"
                ).fetchone()
            expect(row["name"] == "Jason J. Cheney", f"rejected save changed the name: {row['name']}")
            expect(row["ical_url"] == "https://example.com/mine.ics", f"rejected save changed the feed: {row['ical_url']}")
        finally:
            icalutil.fetch_ics = orig_fetch
            gcal.refresh_access_token = orig_refresh
            gcal.list_busy_events = orig_list
        print("OK setup save is not blocked by an unreachable calendar")


if __name__ == "__main__":
    main()
