#!/usr/bin/env python3
"""Smoke tests for Jason login, consult vs session, calendar blocks, capacity."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fd, DBFILE = tempfile.mkstemp(suffix=".db")
os.close(fd)
os.environ["SAV_DB"] = DBFILE

TZ = ZoneInfo("America/Denver")


def future_weekday(hour=10):
    now = datetime.now(TZ)
    d = now.date() + timedelta(days=1)
    while d.isoweekday() > 5:
        d += timedelta(days=1)
    return d, f"{hour:02d}:00"


def this_week_monday():
    now = datetime.now(TZ).date()
    return now - timedelta(days=now.isoweekday() - 1)


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def expect(cond, msg):
    if not cond:
        fail(msg)


def main():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        os.system(f"{sys.executable} -m pip install httpx")
        from fastapi.testclient import TestClient

    from app import app
    from db import connect, init_db, hash_password, now_iso

    # --- migrate on an EXISTING old-schema DB (separate file) ---
    fd2, old_path = tempfile.mkstemp(suffix="-old.db")
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
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    expect("username" in cols and "setup_complete" in cols and "ical_url" in cols, "migrate missing users columns")
    acols = {r["name"] for r in conn.execute("PRAGMA table_info(appointments)").fetchall()}
    expect("visit_kind" in acols and "note" in acols, "migrate missing appointment columns")
    jason = conn.execute("SELECT * FROM users WHERE username='jasoncheney'").fetchone()
    expect(jason is not None, "ensure_jason did not insert on existing Elena DB")
    expect(jason["setup_complete"] == 0, "new Jason should not skip setup")
    elena = conn.execute("SELECT * FROM users WHERE slug='elena-vasquez-lpc'").fetchone()
    expect(elena["username"] == "elena", "demo username not set")
    expect(elena["setup_complete"] == 1, "Elena should skip setup")
    pw_before = elena["password_hash"]
    init_db(conn)  # second boot must not reset Jason password
    jason2 = conn.execute("SELECT * FROM users WHERE username='jasoncheney'").fetchone()
    expect(jason2["password_hash"] == jason["password_hash"], "ensure_jason reset Jason's password")
    expect(elena["password_hash"] == pw_before, "Elena password changed")
    conn.close()
    os.environ["SAV_DB"] = prev
    os.remove(old_path)

    with TestClient(app) as client:
        r = client.post("/api/auth/login", json={"email": "jasoncheney", "password": "123456"})
        expect(r.status_code == 200 and r.json().get("ok"), f"jasoncheney login failed: {r.text}")
        expect(r.json().get("redirect") == "/setup", f"Jason should land on setup, got {r.json()}")

        r = client.post("/api/auth/login", json={"email": "jason", "password": "123456"})
        expect(r.json().get("ok"), "alias jason login failed")

        r = client.post("/api/auth/login", json={"email": "Elena", "password": "demo1234"})
        expect(r.json().get("ok"), "Elena first-name login broken")
        expect(r.json().get("redirect") == "/dashboard", "Elena should skip setup")

        # finish Jason setup so dashboard APIs behave like a live therapist
        r = client.post("/api/auth/login", json={"email": "jasoncheney", "password": "123456"})
        r = client.post("/api/setup", json={
            "name": "Jason Cheney",
            "credentials": "Therapist",
            "title": "Counselor",
            "specialty": "Counseling",
            "about": "Setup done for tests.",
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
            "portal_kind": "headway",
            "portal_url": "https://headway.co/example-jason",
            "ical_url": "",
        })
        expect(r.json().get("ok"), f"setup save failed: {r.text}")

        day, t1 = future_weekday(10)
        r = client.post("/api/p/jason-cheney/book", json={
            "date": day.isoformat(),
            "time": t1,
            "name": "Pat First",
            "email": "pat.first@example.com",
            "visitKind": "consult",
        })
        body = r.json()
        expect(body.get("ok"), f"consult book failed: {body}")
        expect(body.get("visitKind") == "consult", f"expected consult, got {body}")
        expect(body.get("minutes") == 15, f"consult minutes {body.get('minutes')}")
        expect(body.get("firstVisit") is True, "first visit flag")
        expect(body.get("portalUrl") == "https://headway.co/example-jason", f"portalUrl {body.get('portalUrl')}")
        consult_id = body["appointmentId"]

        r = client.get("/api/p/jason-cheney/availability", params={"date": day.isoformat(), "minutes": 15, "visit_kind": "consult"})
        expect(r.json().get("ok"), "availability failed")
        expect(r.json().get("minutes") == 15, "availability did not use consult duration")

        r = client.post("/api/p/jason-cheney/book", json={
            "date": day.isoformat(),
            "time": "11:00",
            "name": "Pat First",
            "email": "pat.first@example.com",
            "visitKind": "consult",
        })
        body = r.json()
        expect(body.get("ok"), f"returning book failed: {body}")
        expect(body.get("visitKind") == "session", f"returning client should be session, got {body}")
        expect(body.get("minutes") == 50, "returning visit should be 50 min")
        expect(body.get("portalUrl") in (None, ""), "portal should hide on returning visit")

        appts = client.get("/api/me/appointments").json().get("appointments") or []
        found = next((a for a in appts if a["id"] == consult_id), None)
        expect(found is not None, "consult appointment missing")
        expect(found.get("visit_kind") == "consult", f"stored visit_kind {found}")
        expect(found.get("duration_minutes") == 15, f"stored minutes {found}")

        me = client.get("/api/me").json()
        before = me["capacity"]["scheduled"]
        mon = this_week_monday()
        r = client.post("/api/calendar/block", json={
            "date": mon.isoformat(),
            "time": "16:00",
            "name": "Casey Manual",
            "minutes": 50,
        })
        expect(r.json().get("ok"), f"calendar block failed: {r.text}")

        me2 = client.get("/api/me").json()
        after = me2["capacity"]["scheduled"]
        expect(after + 1e-6 >= before + 50 / 60.0, f"capacity did not include manual block {before} -> {after}")

        clients = client.get("/api/me/clients").json().get("clients") or []
        expect(any(c["name"] == "Casey Manual" for c in clients), f"manual client missing: {clients}")

        cal = client.get("/api/calendar", params={"year": mon.year, "month": mon.month}).json()
        expect(cal.get("ok"), f"calendar get failed: {cal}")
        day_blocks = cal.get("days", {}).get(mon.isoformat()) or []
        expect(any(b.get("name") == "Casey Manual" and b.get("source") == "manual" for b in day_blocks),
               f"manual block not on calendar: {day_blocks}")

        r = client.get("/p/jason-cheney")
        expect(r.status_code == 200 and "Free consultation" in r.text, "booking page missing consult choice")

        r = client.get("/setup")
        expect(r.status_code == 200 and "After they book" in r.text and "Headway" in r.text, "setup page missing")

    print("ok")
    try:
        os.remove(DBFILE)
    except OSError:
        pass


if __name__ == "__main__":
    main()
