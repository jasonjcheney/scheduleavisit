#!/usr/bin/env python3
"""Imported iCal blocks fill the month grid, and marking them counts toward the weekly cap."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fd, DBFILE = tempfile.mkstemp(suffix="-ical-mark.db")
os.close(fd)
os.environ["SAV_DB"] = DBFILE


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
        os.system(f"{sys.executable} -m pip install -q httpx")
        from fastapi.testclient import TestClient

    from app import app
    from capacity import projected_hours
    from db import at_local, connect, new_public_token, now_iso, parse_iso, start_of_week, today
    from icalutil import _sync_ical, note_for, note_summary, note_uid

    with TestClient(app) as client:
        r = client.post("/api/auth/login", json={"email": "jasoncheney", "password": "123456"})
        expect(r.status_code == 200 and r.json().get("ok"), f"login failed: {r.text}")
        r = client.post("/api/setup", json={
            "name": "Jason Cheney",
            "credentials": "Therapist",
            "title": "Counselor",
            "specialty": "Counseling",
            "about": "Setup done for ical mark tests.",
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

        week = start_of_week(today())
        day = week + timedelta(days=2)
        start = at_local(day, "10:00")
        uid = "uid-dentist-1"
        summary = "Dentist"
        note = note_for(uid, summary)

        with connect() as conn:
            u = conn.execute("SELECT * FROM users WHERE username='jasoncheney'").fetchone()
            expect(u is not None, "jasoncheney missing")
            cur = conn.execute(
                """INSERT INTO appointments
                   (provider_id, client_id, start_iso, duration_minutes, status, booked_via,
                    created_at, visit_kind, note, public_token)
                   VALUES (?,?,?,?, 'booked', 'ical', ?, 'external', ?, ?)""",
                (u["id"], None, start.isoformat(timespec="seconds"), 60, now_iso(), note, new_public_token()),
            )
            appt_id = int(cur.lastrowid)
            conn.commit()
            info = projected_hours(conn, u, week, 0)
            expect(
                abs(info["scheduled"]) < 1e-6,
                f"unmarked ical minutes must not count: scheduled={info['scheduled']}",
            )

        cal = client.get("/api/calendar", params={"year": day.year, "month": day.month}).json()
        expect(cal.get("ok"), f"calendar get failed: {cal}")
        day_blocks = cal.get("days", {}).get(day.isoformat()) or []
        imported = next((b for b in day_blocks if b.get("id") == appt_id), None)
        expect(imported is not None, f"imported box missing: {day_blocks}")
        expect(imported.get("name") == "Dentist", f"name should come from summary, got {imported}")
        expect(imported.get("source") == "ical", f"source {imported}")
        expect(imported.get("markable") is True, f"markable {imported}")
        expect(imported.get("editable") is False, f"editable {imported}")
        expect(imported.get("countsTowardCap") is False, f"countsTowardCap {imported}")

        r = client.post(f"/api/calendar/block/{appt_id}/mark", json={"counts": True})
        expect(r.status_code == 200 and r.json().get("ok"), f"mark counts=true failed: {r.text}")
        expect(r.json().get("visit_kind") == "session", f"kind after mark: {r.json()}")
        expect(r.json().get("countsTowardCap") is True, f"counts after mark: {r.json()}")

        with connect() as conn:
            u = conn.execute("SELECT * FROM users WHERE username='jasoncheney'").fetchone()
            row = conn.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
            expect(row["visit_kind"] == "session", f"stored kind {row['visit_kind']}")
            expect((row["booked_via"] or "") == "ical", f"booked_via changed: {row['booked_via']}")
            info = projected_hours(conn, u, week, 0)
            expect(
                abs(info["scheduled"] - 1.0) < 1e-6,
                f"marked session should add 60 min: scheduled={info['scheduled']}",
            )

        r = client.post(
            f"/api/calendar/block/{appt_id}/mark",
            json={"counts": True, "name": "Sam Client"},
        )
        expect(r.status_code == 200 and r.json().get("ok"), f"mark with name failed: {r.text}")
        expect(r.json().get("name") == "Sam Client", f"block_label after name: {r.json()}")
        expect(r.json().get("clientName") == "Sam Client", f"clientName {r.json()}")

        with connect() as conn:
            row = conn.execute(
                """SELECT a.*, c.name AS client_name, c.id AS linked_id
                   FROM appointments a
                   LEFT JOIN clients c ON c.id = a.client_id
                   WHERE a.id=?""",
                (appt_id,),
            ).fetchone()
            expect(row["client_id"], "client_id not set after name")
            expect(row["client_name"] == "Sam Client", f"linked name {row['client_name']}")
            expect((row["booked_via"] or "") == "ical", "booked_via should stay ical")
            expect(row["visit_kind"] == "session", "kind should stay session")
            saved_client_id = row["client_id"]
            saved_kind = row["visit_kind"]

        cal = client.get("/api/calendar", params={"year": day.year, "month": day.month}).json()
        named = next((b for b in (cal.get("days", {}).get(day.isoformat()) or []) if b.get("id") == appt_id), None)
        expect(named is not None and named.get("name") == "Sam Client", f"calendar name {named}")
        expect(named.get("countsTowardCap") is True, f"marked box should count: {named}")
        expect("session" in (named.get("visit_kind") or ""), f"visit_kind {named}")

        # Re-sync same UID: keep mark + client; time/title may move.
        new_start = start.replace(hour=14, minute=0, second=0)
        ics = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            f"DTSTART;TZID=America/Denver:{new_start.strftime('%Y%m%dT%H%M%S')}\r\n"
            f"DTEND;TZID=America/Denver:{(new_start + timedelta(minutes=90)).strftime('%Y%m%dT%H%M%S')}\r\n"
            "SUMMARY:Dentist moved\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        import icalutil
        orig_fetch = icalutil.fetch_ics
        icalutil.fetch_ics = lambda url, timeout=2.0: ics
        try:
            with connect() as conn:
                u = conn.execute("SELECT * FROM users WHERE username='jasoncheney'").fetchone()
                _sync_ical(conn, u, "https://example.com/cal.ics", 2.0)
                row = conn.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
                expect(row is not None, "row vanished after sync")
                expect(row["visit_kind"] == saved_kind, f"sync wiped visit_kind: {row['visit_kind']}")
                expect(row["client_id"] == saved_client_id, f"sync wiped client_id: {row['client_id']}")
                expect((row["booked_via"] or "") == "ical", f"sync booked_via {row['booked_via']}")
                expect(row["duration_minutes"] == 90, f"duration not updated: {row['duration_minutes']}")
                expect("14:00" in (row["start_iso"] or ""), f"start not updated: {row['start_iso']}")
                expect(note_uid(row["note"]) == uid, f"uid lost: {row['note']}")
                expect(note_summary(row["note"]) == "Dentist moved", f"summary not updated: {row['note']}")
                info = projected_hours(conn, u, week, 0)
                expect(
                    abs(info["scheduled"] - 1.5) < 1e-6,
                    f"marked 90 min after sync should count: scheduled={info['scheduled']}",
                )
        finally:
            icalutil.fetch_ics = orig_fetch

        r = client.post(f"/api/calendar/block/{appt_id}/mark", json={"counts": False})
        expect(r.status_code == 200 and r.json().get("ok"), f"unmark failed: {r.text}")
        expect(r.json().get("visit_kind") == "external", f"kind after unmark: {r.json()}")
        expect(r.json().get("countsTowardCap") is False, f"counts after unmark: {r.json()}")
        expect(r.json().get("name") == "Dentist moved", f"display should return to calendar title: {r.json()}")

        with connect() as conn:
            u = conn.execute("SELECT * FROM users WHERE username='jasoncheney'").fetchone()
            row = conn.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
            expect(row["visit_kind"] == "external", f"unmark kind {row['visit_kind']}")
            expect(row["client_id"] is None, f"unmark should clear client_id, got {row['client_id']}")
            expect(row["status"] == "booked", "unmark must not delete the row")
            expect((row["note"] or "").startswith("__uid__:"), f"ical note lost: {row['note']}")
            info = projected_hours(conn, u, week, 0)
            expect(
                abs(info["scheduled"]) < 1e-6,
                f"unmarked hours should drop: scheduled={info['scheduled']}",
            )

        r = client.post("/api/calendar/block", json={
            "date": day.isoformat(),
            "time": "16:00",
            "name": "Casey Manual",
            "minutes": 50,
        })
        expect(r.json().get("ok"), f"manual block failed: {r.text}")
        manual_id = r.json()["id"]
        r = client.post(f"/api/calendar/block/{manual_id}/mark", json={"counts": True, "name": "Nope"})
        expect(not r.json().get("ok"), f"marking a non-ical block should fail: {r.text}")
        expect(r.status_code in (400, 403, 404, 409, 422) or r.json().get("error"), f"expected error status: {r.status_code} {r.text}")

        r = client.post("/api/p/jason-cheney/book", json={
            "date": (week + timedelta(days=3)).isoformat(),
            "time": "09:00",
            "name": "Pat Booked",
            "email": "pat.booked@example.com",
            "visitKind": "session",
        })
        if r.json().get("ok"):
            booked_id = r.json()["appointmentId"]
            r2 = client.post(f"/api/calendar/block/{booked_id}/mark", json={"counts": True})
            expect(not r2.json().get("ok"), f"marking a booked-via-link visit should fail: {r2.text}")

    print("ok")
    try:
        os.remove(DBFILE)
    except OSError:
        pass


if __name__ == "__main__":
    main()
