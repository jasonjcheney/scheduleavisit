#!/usr/bin/env python3
"""Two-way Google Calendar: connect UI, busy import, write-back, iCal still works."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fd, DBFILE = tempfile.mkstemp(suffix="-google-cal.db")
os.close(fd)
os.environ["SAV_DB"] = DBFILE
os.environ.pop("GOOGLE_CLIENT_ID", None)
os.environ.pop("GOOGLE_CLIENT_SECRET", None)
os.environ.pop("GOOGLE_REDIRECT_URI", None)

TZ = ZoneInfo("America/Denver")


def fail(msg: str) -> None:
    print("FAIL:", msg)
    sys.exit(1)


def expect(cond: bool, msg: str) -> None:
    if not cond:
        fail(msg)


def future_weekday(hour=10):
    now = datetime.now(TZ)
    d = now.date() + timedelta(days=1)
    while d.isoweekday() > 5:
        d += timedelta(days=1)
    return d, f"{hour:02d}:00"


def finish_jason_setup(client):
    r = client.post("/api/auth/login", json={"email": "jasoncheney", "password": "123456"})
    expect(r.json().get("ok"), f"jason login failed: {r.text}")
    r = client.post("/api/setup", json={
        "name": "Jason Cheney",
        "credentials": "Therapist",
        "title": "Counselor",
        "specialty": "Counseling",
        "about": "Setup done for Google Calendar tests.",
        "clinic": "My practice",
        "address": "Boulder, CO",
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
    })
    expect(r.json().get("ok"), f"setup save failed: {r.text}")


def main() -> None:
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        os.system(f"{sys.executable} -m pip install -q httpx")
        from fastapi.testclient import TestClient

    import app as appmod
    import gcal
    from db import connect, hash_password, init_db, now_iso

    # --- migrate adds Google columns on an old-schema DB ---
    fd2, old_path = tempfile.mkstemp(suffix="-gcal-old.db")
    os.close(fd2)
    old = sqlite3.connect(old_path)
    old.executescript(
        """
        CREATE TABLE users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          email TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          name TEXT NOT NULL,
          credentials TEXT DEFAULT '',
          title TEXT DEFAULT '',
          specialty TEXT DEFAULT '',
          about TEXT DEFAULT '',
          clinic TEXT DEFAULT '',
          address TEXT DEFAULT '',
          slug TEXT UNIQUE NOT NULL,
          weekly_target_hours REAL NOT NULL DEFAULT 25,
          buffer_hours REAL NOT NULL DEFAULT 3,
          workdays TEXT NOT NULL DEFAULT '[1,2,3,4,5]',
          slot_start INTEGER NOT NULL DEFAULT 9,
          slot_end INTEGER NOT NULL DEFAULT 17,
          lunch INTEGER NOT NULL DEFAULT 12,
          session_minutes INTEGER NOT NULL DEFAULT 50,
          timezone TEXT NOT NULL DEFAULT 'America/Denver',
          created_at TEXT NOT NULL
        );
        CREATE TABLE appointments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          provider_id INTEGER NOT NULL,
          client_id INTEGER,
          start_iso TEXT NOT NULL,
          duration_minutes INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'booked',
          booked_via TEXT NOT NULL DEFAULT 'direct',
          referred_from_provider_id INTEGER,
          created_at TEXT NOT NULL,
          cancelled_at TEXT
        );
        CREATE TABLE clients (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          provider_id INTEGER NOT NULL,
          name TEXT NOT NULL,
          email TEXT DEFAULT '',
          phone TEXT DEFAULT '',
          created_at TEXT NOT NULL,
          dismissed_at TEXT
        );
        CREATE TABLE sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires_at TEXT NOT NULL);
        CREATE TABLE network_invites (
          id INTEGER PRIMARY KEY AUTOINCREMENT, from_user_id INTEGER NOT NULL,
          to_email TEXT NOT NULL, to_user_id INTEGER, status TEXT DEFAULT 'pending',
          token TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE network_links (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL, peer_id INTEGER NOT NULL, UNIQUE(user_id, peer_id)
        );
        CREATE TABLE notifications (
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
          created_at TEXT NOT NULL, read_at TEXT
        );
        """
    )
    old.execute(
        """INSERT INTO users (email, password_hash, name, slug, created_at)
           VALUES (?,?,?,?,?)""",
        ("elena@sageandstone.example", hash_password("demo1234"), "Elena Vasquez, LPC",
         "elena-vasquez-lpc", now_iso()),
    )
    old.commit()
    old.close()
    prev = os.environ["SAV_DB"]
    os.environ["SAV_DB"] = old_path
    conn = connect()
    init_db(conn)
    ucols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    acols = {r["name"] for r in conn.execute("PRAGMA table_info(appointments)").fetchall()}
    expect("google_refresh_token" in ucols, "migrate missing google_refresh_token")
    expect("google_write_calendar_id" in ucols, "migrate missing google_write_calendar_id")
    expect("google_busy_calendar_ids" in ucols, "migrate missing google_busy_calendar_ids")
    expect("google_event_id" in acols, "migrate missing appointments.google_event_id")
    conn.close()
    os.environ["SAV_DB"] = prev
    os.remove(old_path)
    print("OK migrate adds Google columns")

    with connect() as conn:
        init_db(conn)

    expect(gcal.visit_title("Pat First", "consult") == "Pat First · Consultation", "consult title")
    expect(gcal.visit_title("Pat First", "session") == "Pat First · Session", "session title")
    expect("clinical" not in gcal.visit_description("Pat", "session", 50, "Tuesday").lower() or
           "no clinical notes" in gcal.visit_description("Pat", "session", 50, "Tuesday").lower(),
           "description should stay scheduling-only")
    blob = gcal.encrypt_refresh_token("refresh-secret-value")
    expect("refresh-secret-value" not in blob, "refresh token stored in plaintext")
    expect(gcal.decrypt_refresh_token(blob) == "refresh-secret-value", "decrypt round-trip")
    print("OK token encryption and scheduling-only titles")

    c = TestClient(appmod.app)

    login = c.post("/api/auth/login", json={"email": "jasoncheney", "password": "123456"})
    expect(login.json().get("ok"), "jason login")
    setup = c.get("/setup")
    expect(setup.status_code == 200, f"/setup {setup.status_code}")
    expect("Connect Google Calendar" not in setup.text or "not set up on this server yet" in setup.text,
           "unconfigured setup should be honest")
    expect("not set up on this server yet" in setup.text, "setup missing honest Google copy")
    expect("iCal / ICS" in setup.text or "Other calendars" in setup.text, "setup missing iCal fallback")
    start = c.get("/auth/google/calendar", follow_redirects=False)
    expect(start.status_code != 500, f"unconfigured calendar start 500: {start.status_code}")
    expect("Traceback" not in (start.text or ""), "calendar start leaked traceback")
    expect("not set up on this server yet" in (start.text or ""), "calendar start missing calm message")
    print("OK unconfigured Google Calendar UI is honest")

    finish_jason_setup(c)
    dash = c.get("/dashboard")
    expect(dash.status_code == 200, f"dashboard {dash.status_code}")
    expect("not set up on this server yet" in dash.text, "dashboard missing honest Google copy")
    expect("Connect Google Calendar" not in dash.text, "dashboard should not offer a dead Connect button")
    print("OK unconfigured dashboard is honest")

    os.environ["GOOGLE_CLIENT_ID"] = "test-cal-client.apps.googleusercontent.com"
    os.environ["GOOGLE_CLIENT_SECRET"] = "test-cal-not-a-real-secret"
    os.environ["GOOGLE_REDIRECT_URI"] = "https://scheduleavisit.onrender.com/auth/google/calendar/callback"
    try:
        setup2 = c.get("/setup")
        expect("Connect Google Calendar" in setup2.text, "configured setup missing Connect button")
        expect("not set up on this server yet" not in setup2.text, "configured setup still says not set up")

        start = c.get("/auth/google/calendar?next=/setup#calendar-ical", follow_redirects=False)
        expect(start.status_code in (302, 303), f"configured calendar start should redirect, got {start.status_code}")
        loc = start.headers.get("location") or ""
        expect("accounts.google.com" in loc, f"calendar start should go to Google, got {loc}")
        q = parse_qs(urlparse(loc).query)
        expect(q.get("client_id") == ["test-cal-client.apps.googleusercontent.com"], "missing client_id")
        expect("calendar.readonly" in (q.get("scope") or [""])[0], "missing calendar.readonly scope")
        expect("calendar.events" in (q.get("scope") or [""])[0], "missing calendar.events scope")
        expect(q.get("access_type") == ["offline"], f"access_type {q.get('access_type')}")
        expect(q.get("prompt") == ["consent"], f"prompt {q.get('prompt')}")
        redir = (q.get("redirect_uri") or [""])[0]
        expect(redir.endswith("/auth/google/calendar/callback"), f"redirect_uri {redir}")
        expect("test-cal-not-a-real-secret" not in loc, "client secret leaked into authorize URL")
        state = (q.get("state") or [""])[0]
        expect(state, "calendar start missing state")
        print("OK connect redirects to Google with calendar scopes")

        orig_exchange = gcal.exchange_code
        orig_userinfo = gcal.fetch_userinfo
        orig_cals = gcal.fetch_calendar_list
        orig_sync = gcal.maybe_sync_google

        def fake_exchange(_code, _redirect):
            return {"refresh_token": "rt-live-value", "access_token": "at-live"}

        def fake_userinfo(_access):
            return {"email": "jason.gcal@example.com"}

        def fake_cals(_access):
            return [
                {"id": "primary", "summary": "Jason", "primary": True, "selected": True, "canWrite": True},
                {"id": "work@example.com", "summary": "Work", "primary": False, "selected": True, "canWrite": True},
            ]

        gcal.exchange_code = fake_exchange
        gcal.fetch_userinfo = fake_userinfo
        gcal.fetch_calendar_list = fake_cals
        gcal.maybe_sync_google = lambda *a, **k: None
        appmod.finish_google_calendar_connect = gcal.finish_connect
        appmod.maybe_sync_google = gcal.maybe_sync_google
        appmod.fetch_calendar_list = gcal.fetch_calendar_list
        try:
            cb = c.get(
                f"/auth/google/calendar/callback?code=fake-code&state={state}",
                follow_redirects=False,
            )
        finally:
            gcal.exchange_code = orig_exchange
            gcal.fetch_userinfo = orig_userinfo
            gcal.fetch_calendar_list = orig_cals
            gcal.maybe_sync_google = orig_sync
            appmod.maybe_sync_google = orig_sync
            appmod.fetch_calendar_list = orig_cals
        expect(cb.status_code in (302, 303), f"callback should redirect, got {cb.status_code} {cb.text[:240]}")
        loc2 = cb.headers.get("location") or ""
        expect("/setup" in loc2, f"after connect should return to setup, got {loc2}")
        with connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE username='jasoncheney'").fetchone()
            expect(row["google_refresh_token"], "refresh token not stored")
            expect("rt-live-value" not in (row["google_refresh_token"] or ""), "refresh token stored in plaintext")
            expect((row["google_connected_email"] or "") == "jason.gcal@example.com", f"email {row['google_connected_email']}")
            expect(gcal.decrypt_refresh_token(row["google_refresh_token"]) == "rt-live-value", "cannot decrypt stored token")
        me = c.get("/api/me").json()
        expect(me.get("ok"), f"/api/me failed {me}")
        expect(me.get("user", {}).get("google_refresh_token") in (None, ""), "/api/me leaked refresh token")
        expect(me.get("google", {}).get("connected") is True, f"google status {me.get('google')}")
        expect("rt-live-value" not in json.dumps(me), "/api/me body leaked raw refresh token")
        print("OK connect stores encrypted refresh token and hides it from /api/me")

        gcal.access_token_for = lambda user: "at-test"
        appmod.access_token_for = gcal.access_token_for
        gcal.fetch_calendar_list = fake_cals
        appmod.fetch_calendar_list = fake_cals
        setup3 = c.get("/setup")
        expect("Connected" in setup3.text, "setup missing Connected state")
        expect("jason.gcal@example.com" in setup3.text, "setup missing connected email")
        expect("Which calendars count as busy" in setup3.text, "setup missing busy picker")
        expect("Where new ScheduleAVisit bookings should appear" in setup3.text, "setup missing write picker")
        expect("Disconnect Google Calendar" in setup3.text, "setup missing disconnect")
        print("OK connected setup shows calendar choices")

        save = c.post("/api/me/google", json={
            "busy_calendar_ids": ["primary"],
            "write_calendar_id": "primary",
        })
        expect(save.status_code == 200 and save.json().get("ok"), f"save prefs failed: {save.text}")
        expect(save.json().get("busyCalendarIds") == ["primary"], f"busy ids {save.json()}")
        print("OK save calendar choices")

        day, hhmm = future_weekday(10)
        start_dt = datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time(), tzinfo=TZ)
        busy_ev = [{
            "id": "evt-dentist",
            "summary": "Dentist",
            "status": "confirmed",
            "start": {"dateTime": start_dt.isoformat()},
            "end": {"dateTime": (start_dt + timedelta(hours=1)).isoformat()},
        }]

        def fake_list(_token, _cal, _t0, _t1):
            return busy_ev

        orig_list = gcal.list_busy_events
        orig_access = gcal.access_token_for
        gcal.list_busy_events = fake_list
        gcal.access_token_for = lambda user: "at-test"
        appmod.access_token_for = gcal.access_token_for
        try:
            with connect() as conn:
                u = conn.execute("SELECT * FROM users WHERE username='jasoncheney'").fetchone()
                gcal.maybe_sync_google(conn, u, timeout=2.0, force=True)
                imported = conn.execute(
                    """SELECT * FROM appointments
                       WHERE provider_id=? AND booked_via='google' AND status='booked'""",
                    (u["id"],),
                ).fetchone()
                expect(imported is not None, "Google busy was not imported")
                expect((imported["visit_kind"] or "") == "external", f"kind {imported['visit_kind']}")
                expect("Dentist" in (imported["note"] or ""), f"note {imported['note']}")
        finally:
            gcal.list_busy_events = orig_list
        avail = c.get("/api/p/jason-cheney/availability", params={"date": day.isoformat(), "minutes": 50})
        expect(avail.json().get("ok"), f"availability {avail.text}")
        slot = next((s for s in (avail.json().get("slots") or []) if s.get("time") == hhmm), None)
        expect(slot is not None and slot.get("booked"), f"busy slot should be booked: {slot}")
        book_taken = c.post("/api/p/jason-cheney/book", json={
            "date": day.isoformat(),
            "time": hhmm,
            "name": "Should Fail",
            "email": "should.fail@example.com",
            "visitKind": "session",
        })
        expect(not book_taken.json().get("ok"), f"book over Google busy should fail: {book_taken.text}")
        expect(book_taken.json().get("taken") is True or "taken" in (book_taken.json().get("error") or "").lower(),
               f"expected taken: {book_taken.json()}")
        print("OK Google busy blocks availability and booking")

        later, later_hhmm = future_weekday(14)
        # If the 10:00 day is also 14:00-friendly, use it; else the helper already skipped weekend.
        if later == day:
            book_day, book_time = later, later_hhmm
        else:
            book_day, book_time = later, later_hhmm
        api_calls = []

        def fake_api(method, path, access_token, json_body=None, params=None, timeout=8.0):
            api_calls.append({"method": method, "path": path, "body": json_body})
            if method == "POST" and str(path).endswith("/events"):
                summary = (json_body or {}).get("summary") or ""
                expect("Pat Google" in summary, f"event title missing client: {summary}")
                expect("Session" in summary or "Consultation" in summary, f"event title missing kind: {summary}")
                desc = (json_body or {}).get("description") or ""
                expect("clinical notes" in desc.lower() or "Scheduling only" in desc, f"desc {desc}")
                expect("diagnosis" not in desc.lower(), "clinical wording in Google event")
                return {"id": "gcal-created-1"}
            if method == "PATCH":
                return {"id": "gcal-created-1"}
            if method == "DELETE":
                return {}
            if method == "POST" and str(path).endswith("/freeBusy"):
                return {"calendars": {"primary": {"busy": []}}}
            return {}

        orig_api = gcal.calendar_api
        orig_busy = gcal.slot_busy_on_google
        gcal.calendar_api = fake_api
        gcal.slot_busy_on_google = lambda *a, **k: False
        gcal.list_busy_events = lambda *a, **k: []
        gcal.access_token_for = lambda user: "at-test"
        appmod.access_token_for = gcal.access_token_for
        appmod.slot_busy_on_google = gcal.slot_busy_on_google
        try:
            booked = c.post("/api/p/jason-cheney/book", json={
                "date": book_day.isoformat(),
                "time": book_time,
                "name": "Pat Google",
                "email": "pat.google@example.com",
                "visitKind": "session",
            })
            expect(booked.json().get("ok"), f"book failed: {booked.text}")
            appt_id = booked.json()["appointmentId"]
            posts = [x for x in api_calls if x["method"] == "POST" and str(x["path"]).endswith("/events")]
            expect(posts, f"book did not create a Google event: {api_calls}")
            with connect() as conn:
                row = conn.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
                expect((row["google_event_id"] or "") == "gcal-created-1", f"google_event_id {row['google_event_id']}")

            moved_time = "15:00" if book_time != "15:00" else "16:00"
            api_calls.clear()
            moved = c.post(f"/api/me/appointments/{appt_id}/reschedule", json={
                "date": book_day.isoformat(),
                "time": moved_time,
            })
            expect(moved.json().get("ok"), f"reschedule failed: {moved.text}")
            patches = [x for x in api_calls if x["method"] == "PATCH"]
            expect(patches, f"reschedule did not PATCH Google: {api_calls}")

            api_calls.clear()
            cancelled = c.post(f"/api/me/appointments/{appt_id}/cancel")
            expect(cancelled.json().get("ok"), f"cancel failed: {cancelled.text}")
            deletes = [x for x in api_calls if x["method"] == "DELETE"]
            expect(deletes, f"cancel did not DELETE Google event: {api_calls}")
            print("OK book / reschedule / cancel write Google events")

            api_calls.clear()
            ref_day, ref_time = future_weekday(11)
            # Book on James via Elena-style referral from Jason's network (Jason is linked to James).
            referred = c.post("/api/p/jason-cheney/book-referral", json={
                "peerSlug": "james-okonkwo-lcsw",
                "date": ref_day.isoformat(),
                "time": ref_time,
                "name": "Ref Google",
                "email": "ref.google@example.com",
            })
            # James is not Google-connected, so no write is required; booking must still succeed.
            expect(referred.json().get("ok"), f"referral book failed: {referred.text}")
            print("OK referral book still works when peer has no Google")
        finally:
            gcal.calendar_api = orig_api
            gcal.slot_busy_on_google = orig_busy
            gcal.list_busy_events = orig_list
            gcal.access_token_for = orig_access
            appmod.access_token_for = orig_access
            appmod.slot_busy_on_google = orig_busy

        # iCal fallback still imports while Google is connected
        from icalutil import _sync_ical, note_uid
        ical_day = day + timedelta(days=1)
        while ical_day.isoweekday() > 5:
            ical_day += timedelta(days=1)
        ical_start = datetime.combine(ical_day, datetime.strptime("16:00", "%H:%M").time(), tzinfo=TZ)
        ics = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            "UID:uid-outlook-1\r\n"
            f"DTSTART;TZID=America/Denver:{ical_start.strftime('%Y%m%dT%H%M%S')}\r\n"
            f"DTEND;TZID=America/Denver:{(ical_start + timedelta(minutes=60)).strftime('%Y%m%dT%H%M%S')}\r\n"
            "SUMMARY:Outlook block\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        import icalutil
        orig_fetch = icalutil.fetch_ics
        icalutil.fetch_ics = lambda url, timeout=2.0: ics
        try:
            with connect() as conn:
                conn.execute(
                    "UPDATE users SET ical_url=? WHERE username='jasoncheney'",
                    ("https://example.com/outlook.ics",),
                )
                conn.commit()
                u = conn.execute("SELECT * FROM users WHERE username='jasoncheney'").fetchone()
                _sync_ical(conn, u, "https://example.com/outlook.ics", 2.0)
                row = conn.execute(
                    """SELECT * FROM appointments
                       WHERE provider_id=? AND booked_via='ical' AND status='booked'
                       ORDER BY id DESC LIMIT 1""",
                    (u["id"],),
                ).fetchone()
                expect(row is not None, "iCal fallback did not import")
                expect(note_uid(row["note"]) == "uid-outlook-1", f"iCal uid {row['note']}")
        finally:
            icalutil.fetch_ics = orig_fetch
        print("OK iCal fallback still works with Google connected")

        disc = c.post("/api/me/google/disconnect")
        expect(disc.json().get("ok"), f"disconnect failed: {disc.text}")
        with connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE username='jasoncheney'").fetchone()
            expect(not (row["google_refresh_token"] or "").strip(), "token not cleared on disconnect")
        me2 = c.get("/api/me").json()
        expect(me2.get("google", {}).get("connected") is False, f"still connected {me2.get('google')}")
        print("OK disconnect clears the Google login")
    finally:
        os.environ.pop("GOOGLE_CLIENT_ID", None)
        os.environ.pop("GOOGLE_CLIENT_SECRET", None)
        os.environ.pop("GOOGLE_REDIRECT_URI", None)

    r = c.post("/api/auth/login", json={"email": "Elena", "password": "demo1234"})
    expect(r.status_code == 200 and r.json().get("ok"), f"Elena password login failed: {r.text}")
    print("OK password login still works")

    print("ALL GOOGLE CALENDAR SMOKES PASSED")


if __name__ == "__main__":
    main()
