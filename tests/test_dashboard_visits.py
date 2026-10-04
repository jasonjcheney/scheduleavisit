#!/usr/bin/env python3
"""Upcoming visits show real bookings. Imported Google rows stay in a collapsed section."""
from __future__ import annotations

import os
import re
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fd, DBFILE = tempfile.mkstemp(suffix="-dash-visits.db")
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


def future_weekday(hour=10, minute=0):
    now = datetime.now(TZ)
    d = now.date() + timedelta(days=1)
    while d.isoweekday() > 5:
        d += timedelta(days=1)
    return d, f"{hour:02d}:{minute:02d}"


def main():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        os.system(f"{sys.executable} -m pip install -q httpx")
        from fastapi.testclient import TestClient

    from capacity import format_long, format_time
    from db import add_client, at_local, connect, new_public_token, now_iso
    from gcal import note_for_google
    from icalutil import note_for, note_summary

    gcal_id = "4k8s0longgoogleeventidabcXYZ"
    cal_email = "jasonjcheney@gmail.com"
    headway = note_for_google(cal_email, gcal_id, "Headway Patient Appointment")
    bills = note_for_google(cal_email, "evt-pay-bills-99", "Pay Bills")
    payroll = note_for("ical-uid-payroll-77", "Payroll")
    expect(note_summary(headway) == "Headway Patient Appointment", f"summary {note_summary(headway)}")
    expect("__gcal__" not in note_summary(headway), "summary still has the sentinel")
    expect(note_summary("__gcal__:cal:no-title") == "Busy", "missing title should fall back to Busy")
    expect(note_summary(payroll) == "Payroll", f"ical summary {note_summary(payroll)}")

    with TestClient(app_client()) as client:
        r = client.post("/api/auth/login", json={"email": "jasoncheney", "password": "123456"})
        expect(r.status_code == 200 and r.json().get("ok"), f"login {r.text}")
        r = client.post("/api/setup", json={
            "name": "Jason Cheney",
            "credentials": "Therapist",
            "title": "Counselor",
            "specialty": "Counseling",
            "about": "Setup done for the visits list.",
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
        expect(r.json().get("ok"), f"setup {r.text}")

        day, hhmm = future_weekday(10, 0)
        _, bills_hhmm = future_weekday(14, 30)
        _, payroll_hhmm = future_weekday(16, 0)
        start = at_local(day, hhmm)
        with connect() as conn:
            u = conn.execute("SELECT * FROM users WHERE username='jasoncheney'").fetchone()
            cid = add_client(conn, u["id"], "Ada Booked", "ada.booked@example.com")
            conn.execute(
                """INSERT INTO appointments
                   (provider_id, client_id, start_iso, duration_minutes, status, booked_via,
                    created_at, visit_kind, note, public_token)
                   VALUES (?,?,?,?, 'booked', 'direct', ?, 'consult', '', ?)""",
                (u["id"], cid, start.isoformat(timespec="seconds"), 15, now_iso(), new_public_token()),
            )
            for note, via, at_hhmm, minutes in (
                (headway, "google", "11:00", 60),
                (bills, "google", bills_hhmm, 30),
                (payroll, "ical", payroll_hhmm, 45),
            ):
                conn.execute(
                    """INSERT INTO appointments
                       (provider_id, client_id, start_iso, duration_minutes, status, booked_via,
                        created_at, visit_kind, note, public_token)
                       VALUES (?,?,?,?, 'booked', ?, ?, 'external', ?, ?)""",
                    (
                        u["id"], None, at_local(day, at_hhmm).isoformat(timespec="seconds"),
                        minutes, via, now_iso(), note, new_public_token(),
                    ),
                )
            gcal_token = conn.execute(
                "SELECT public_token FROM appointments WHERE note=?",
                (headway,),
            ).fetchone()["public_token"]
            conn.commit()

        dash = client.get("/dashboard")
        expect(dash.status_code == 200, f"dashboard {dash.status_code}")
        html = dash.text
        expect("__gcal__" not in html, "dashboard leaked a __gcal__ key")
        expect("__uid__" not in html, "dashboard leaked an __uid__ key")
        expect(gcal_id not in html, "dashboard leaked the Google event id")
        expect(cal_email not in html, "dashboard leaked the calendar id")
        expect("ical-uid-payroll-77" not in html, "dashboard leaked the iCal uid")

        other_at = html.find('id="other-calendar-events"')
        upcoming_at = html.find('id="upcoming-visits"')
        expect(upcoming_at != -1 and other_at != -1 and upcoming_at < other_at, "visit sections missing")
        tag = re.search(r"<details\b[^>]*id=\"other-calendar-events\"[^>]*>", html)
        expect(tag is not None and not re.search(r"\bopen\b", tag.group(0)), f"section should start collapsed: {tag}")
        upcoming_html = html[upcoming_at:other_at]
        other_end = html.find("</details>", other_at)
        other_html = html[other_at:other_end]
        when = f"{format_long(day)} · {format_time(hhmm)}"
        expect("Ada Booked" in upcoming_html, "real booking missing from upcoming visits")
        expect("15 min consult" in upcoming_html, f"consult label missing: {upcoming_html[:500]}")
        expect(when in upcoming_html, f"provider-local time missing: {when}")
        expect("Headway Patient Appointment" not in upcoming_html, "imported title leaked into upcoming visits")
        expect("Pay Bills" not in upcoming_html, "personal Google event leaked into upcoming visits")
        expect("Payroll" not in upcoming_html, "iCal event leaked into upcoming visits")
        expect(html.count("Headway Patient Appointment") == 1, "clean title should appear once")
        expect(html.count("Pay Bills") == 1, "Pay Bills should appear once")
        expect(html.count("Payroll") == 1, "Payroll should appear once")
        expect("Headway Patient Appointment" in other_html, "imported event missing from collapsed section")
        expect("Pay Bills" in other_html, "Pay Bills missing from collapsed section")
        expect("Payroll" in other_html, "Payroll missing from collapsed section")
        expect("Ada Booked" not in other_html, "real booking should not sit in other calendar events")
        expect("min" not in other_html, "other calendar events should show the title and time only")
        expect("2:30 pm" in other_html, "imported event time missing")

        cal = client.get("/api/calendar", params={"year": day.year, "month": day.month})
        expect(cal.status_code == 200 and cal.json().get("ok"), f"calendar {cal.text}")
        blob = cal.text
        expect("__gcal__" not in blob and gcal_id not in blob, "calendar API leaked the internal key")
        blocks = (cal.json().get("days") or {}).get(day.isoformat()) or []
        titles = {b.get("name") for b in blocks}
        expect("Headway Patient Appointment" in titles, f"calendar name {titles}")
        expect("Ada Booked" in titles, f"real booking missing on the month grid {titles}")

        confirm = client.get(f"/booked/{gcal_token}")
        expect(confirm.status_code == 200, f"confirm {confirm.status_code}")
        expect("__gcal__" not in confirm.text and gcal_id not in confirm.text, "confirm page leaked the internal key")
        print("OK upcoming visits hide imported calendar keys")


def app_client():
    from app import app
    return app


if __name__ == "__main__":
    main()
