#!/usr/bin/env python3
"""Route smoke tests via TestClient (local app, not the live Render URL)."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fd, DBFILE = tempfile.mkstemp(suffix="-live-paths.db")
os.close(fd)
os.environ["SAV_DB"] = DBFILE


def fail(msg: str) -> None:
    print("FAIL:", msg)
    sys.exit(1)


def expect(cond: bool, msg: str) -> None:
    if not cond:
        fail(msg)


def main() -> None:
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        os.system(f"{sys.executable} -m pip install -q httpx")
        from fastapi.testclient import TestClient

    from app import app
    from db import init_db, connect

    # Seed demo providers into the temp DB before hitting routes.
    with connect() as conn:
        init_db(conn)

    c = TestClient(app)

    # —— Public pages ——
    cases = [
        ("/", 200, ["Book a visit in seconds", "Get your booking link", "Provider login", 'property="og:title"', "og:description"]),
        ("/book", 200, ["Book a visit", "Elena Vasquez", "Choose a professional"]),
        ("/p/jason-cheney", 200, ["Jason Cheney", "Pick a day", "Pick a time", 'property="og:title"', "Book with Jason Cheney"]),
        ("/p/elena-vasquez-lpc", 200, ["Elena Vasquez", "Free consultation", "Full session"]),
        ("/login", 200, ["Welcome back", "jasoncheney", "demo1234"]),
        ("/signup", 200, ["Set your name", "Create account", 'data-next="/setup"']),
    ]
    for path, status, needles in cases:
        r = c.get(path)
        expect(r.status_code == status, f"{path} expected {status}, got {r.status_code}")
        for n in needles:
            expect(n in r.text, f"{path} missing {n!r}")
        print(f"OK {path} {r.status_code}")

    # —— Auth gate ——
    for path in ("/setup", "/dashboard"):
        r = c.get(path, follow_redirects=False)
        expect(r.status_code in (302, 303), f"{path} should redirect when anon, got {r.status_code}")
        loc = r.headers.get("location", "")
        expect("/login" in loc, f"{path} should send to login, got {loc}")
        print(f"OK {path} redirects to login")

    # —— Jason login → setup/dashboard ——
    r = c.post("/api/auth/login", json={"email": "jasoncheney", "password": "123456"})
    expect(r.status_code == 200 and r.json().get("ok"), f"jason login failed: {r.text}")
    body = r.json()
    expect(body.get("redirect") in ("/setup", "/dashboard"), f"unexpected redirect {body.get('redirect')}")
    print(f"OK jason login → {body.get('redirect')}")

    setup = c.get("/setup", follow_redirects=False)
    # Incomplete Jason lands on setup; completed Jason may redirect to dashboard.
    if setup.status_code in (302, 303):
        expect("/dashboard" in setup.headers.get("location", ""), f"setup redirect odd: {setup.headers.get('location')}")
        print("OK /setup redirects (already complete)")
        dash = c.get("/dashboard")
    else:
        expect(setup.status_code == 200, f"/setup got {setup.status_code}")
        for n in ("Weekly", "portal", "setup-progress", "consult"):
            expect(n.lower() in setup.text.lower() or n in setup.text, f"/setup missing {n!r}")
        print("OK /setup 200")
        # Finish setup so dashboard is reachable in this fresh DB
        done = c.post(
            "/api/setup",
            json={
                "name": "Jason Cheney",
                "credentials": "LPC",
                "title": "Therapist",
                "specialty": "Counseling — anxiety and life transitions",
                "about": "A short about for smoke tests.",
                "clinic": "Cheney Counseling",
                "address": "Boulder, CO",
                "weekly_target_hours": 20,
                "buffer_hours": 2,
                "session_minutes": 50,
                "consult_enabled": True,
                "consult_minutes": 15,
                "portal_kind": "headway",
                "portal_url": "https://headway.co/example",
                "workdays": [1, 2, 3, 4, 5],
            },
        )
        expect(done.status_code == 200 and done.json().get("ok"), f"setup post failed: {done.text}")
        dash = c.get("/dashboard")

    expect(dash.status_code == 200, f"/dashboard got {dash.status_code}")
    for n in ("Hello", "Month calendar", "Your booking link", "Clients never see"):
        expect(n in dash.text, f"/dashboard missing {n!r}")
    expect("Scan to book" in dash.text, "/dashboard missing Scan to book QR label")
    expect("api.qrserver.com" in dash.text, "/dashboard missing QR image API src")
    print("OK /dashboard 200")

    # —— Elena login → dashboard client name filter ——
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"email": "Elena", "password": "demo1234"})
    expect(r.status_code == 200 and r.json().get("ok"), f"elena login failed: {r.text}")
    elena_dash = c.get("/dashboard")
    expect(elena_dash.status_code == 200, f"elena /dashboard got {elena_dash.status_code}")
    expect("client-filter" in elena_dash.text, "elena dashboard missing client-filter")
    print("OK elena dashboard client-filter")

    # —— Client dismiss then restore ——
    with connect() as conn:
        elena_row = conn.execute("SELECT id FROM users WHERE slug=?", ("elena-vasquez-lpc",)).fetchone()
        expect(elena_row is not None, "elena seed missing for dismiss/restore")
        marcus = conn.execute(
            "SELECT id, name FROM clients WHERE provider_id=? AND name=? AND dismissed_at IS NULL",
            (elena_row["id"], "Marcus Hale"),
        ).fetchone()
        expect(marcus is not None, "Marcus Hale should be an active Elena client")
        mid = int(marcus["id"])
    expect(f'data-dismiss="{mid}"' in elena_dash.text, "elena dashboard missing Marcus dismiss button")
    r = c.post(f"/api/me/clients/{mid}/dismiss")
    expect(r.status_code == 200 and r.json().get("ok"), f"dismiss failed: {r.text}")
    with connect() as conn:
        row = conn.execute("SELECT dismissed_at FROM clients WHERE id=?", (mid,)).fetchone()
        expect(row is not None and row["dismissed_at"], "dismiss should set dismissed_at")
    dismissed_dash = c.get("/dashboard")
    expect(dismissed_dash.status_code == 200, f"dashboard after dismiss got {dismissed_dash.status_code}")
    expect(f'data-dismiss="{mid}"' not in dismissed_dash.text, "dismissed client should leave active list")
    expect(f'data-restore="{mid}"' in dismissed_dash.text, "dismissed section missing Restore button")
    r = c.post(f"/api/me/clients/{mid}/restore")
    expect(r.status_code == 200 and r.json().get("ok"), f"restore failed: {r.text}")
    with connect() as conn:
        row = conn.execute("SELECT dismissed_at FROM clients WHERE id=?", (mid,)).fetchone()
        expect(row is not None and row["dismissed_at"] is None, "restore should clear dismissed_at")
    restored_dash = c.get("/dashboard")
    expect(restored_dash.status_code == 200, f"dashboard after restore got {restored_dash.status_code}")
    expect(f'data-dismiss="{mid}"' in restored_dash.text, "restored client should be active again")
    expect(f'data-restore="{mid}"' not in restored_dash.text, "restored client should leave dismissed section")
    print("OK client dismiss then restore")

    # —— Notifications list / mark-read API ——
    expect("mark-all-read" in elena_dash.text, "elena dashboard missing Mark all as read")
    expect("note-dot" in elena_dash.text or 'class="note unread"' in elena_dash.text
           or "notes-unread-badge" in elena_dash.text,
           "elena dashboard missing unread notification chrome")
    r = c.get("/api/me/notifications")
    expect(r.status_code == 200 and r.json().get("ok"), f"GET notifications failed: {r.text}")
    notes = r.json().get("notifications") or []
    expect(len(notes) >= 1, "elena should have at least one notification")
    # GET must not auto-mark as read
    expect(any(n.get("unread") for n in notes), "GET /api/me/notifications should leave unread intact")
    nid = notes[0]["id"]
    r = c.post(f"/api/me/notifications/{nid}/read")
    expect(r.status_code == 200 and r.json().get("ok"), f"individual mark-read failed: {r.text}")
    r = c.get("/api/me/notifications")
    one = next(n for n in r.json()["notifications"] if n["id"] == nid)
    expect(not one.get("unread"), "individual mark-read should clear unread")
    from db import notify
    with connect() as conn:
        elena = conn.execute("SELECT id FROM users WHERE slug=?", ("elena-vasquez-lpc",)).fetchone()
        notify(conn, elena["id"], "test", "Mark-all smoke", "Created for notifications API test")
        conn.commit()
    r = c.post("/api/me/notifications/read-all")
    expect(r.status_code == 200 and r.json().get("ok"), f"mark-all failed: {r.text}")
    r = c.get("/api/me/notifications")
    expect(r.json().get("unread") == 0, "mark-all should leave unread count at 0")
    expect(all(not n.get("unread") for n in r.json()["notifications"]), "mark-all should clear every unread")
    print("OK notifications mark-read API")

    # —— Elena booking page still has capacity copy hooks ——
    elena = c.get("/p/elena-vasquez-lpc")
    expect("see if it’s a fit" in elena.text or "see if it's a fit" in elena.text, "consult fit copy missing")
    expect('id="slot-grid"' in elena.text, "slot-grid missing")
    print("OK elena booking markup")

    # —— CSS mobile guards present in static file ——
    css = (ROOT / "static" / "styles.css").read_text()
    expect("@media (max-width: 480px)" in css, "missing 480px media query")
    expect("@media (max-width: 390px)" in css, "missing 390px media query")
    expect(".rec-card .row" in css, "missing referral card mobile row rules")
    expect("overflow-x: hidden" in css, "missing body overflow-x hidden")
    print("OK mobile CSS guards")

    # —— Booked confirmation .ics download ——
    from db import at_local, today as db_today
    from datetime import timedelta
    with connect() as conn:
        prov = conn.execute("SELECT id, address FROM users WHERE slug=?", ("elena-vasquez-lpc",)).fetchone()
        expect(prov is not None, "elena seed missing for ics test")
        cur = conn.execute(
            "INSERT INTO clients (provider_id, name, email, phone, created_at) VALUES (?,?,?,?,?)",
            (prov["id"], "ICS Test Client", "ics@example.com", "", "2026-08-22T01:00:00-06:00"),
        )
        client_id = int(cur.lastrowid)
        start = at_local(db_today() + timedelta(days=3), "10:00")
        cur = conn.execute(
            """INSERT INTO appointments
               (provider_id, client_id, start_iso, duration_minutes, status, booked_via,
                created_at, visit_kind, note)
               VALUES (?,?,?,?, 'booked', 'direct', ?, 'session', ?)""",
            (prov["id"], client_id, start.isoformat(timespec="seconds"), 50,
             "2026-08-22T01:00:00-06:00", ""),
        )
        appt_id = int(cur.lastrowid)
        conn.commit()

    for ics_path in (f"/booked/{appt_id}.ics", f"/api/booked/{appt_id}/ics"):
        r = c.get(ics_path)
        expect(r.status_code == 200, f"{ics_path} expected 200, got {r.status_code}")
        ctype = (r.headers.get("content-type") or "").lower()
        expect("text/calendar" in ctype, f"{ics_path} content-type {ctype}")
        expect("BEGIN:VEVENT" in r.text, f"{ics_path} missing BEGIN:VEVENT")
        expect("SUMMARY:" in r.text, f"{ics_path} missing SUMMARY")
        expect("DTSTART" in r.text and "DTEND" in r.text, f"{ics_path} missing DTSTART/DTEND")
        expect("LOCATION:" in r.text, f"{ics_path} missing LOCATION")
        print(f"OK {ics_path} 200 + VEVENT")

    booked_html = c.get(f"/booked/{appt_id}")
    expect(booked_html.status_code == 200, f"/booked/{appt_id} got {booked_html.status_code}")
    expect("Add to calendar" in booked_html.text, "booked.html missing Add to calendar")
    expect(f"/booked/{appt_id}.ics" in booked_html.text, "booked.html missing .ics href")
    print("OK booked.html Add to calendar link")

    print("ALL LIVE PATH SMOKES PASSED")


if __name__ == "__main__":
    main()
