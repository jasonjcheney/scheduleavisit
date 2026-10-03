#!/usr/bin/env python3
"""QA round: directory completeness, calendar checks, signup guard, Google copy,
seed passwords, hidden sample counselors, and ID-only logs.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fd, DBFILE = tempfile.mkstemp(suffix="-qa-round1.db")
os.close(fd)
os.environ["SAV_DB"] = DBFILE
os.environ["SAV_JASON_PASSWORD"] = "123456"
os.environ["SAV_DEMO_PASSWORD"] = "demo1234"
os.environ["SHOW_DEMO_COUNSELORS"] = "1"

TZ = ZoneInfo("America/Denver")
BANNED = ("123456", "demo1234")
UNREACHABLE = "We can't reach your calendar. Reconnect it in Setup."
SAMPLE = "This is a sample profile"
GOOD_ICS = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Busy\nEND:VEVENT\nEND:VCALENDAR\n"


def next_open_day() -> str:
    day = datetime.now(TZ).date() + timedelta(days=1)
    while day.isoweekday() > 5:
        day += timedelta(days=1)
    return day.isoformat()


def fail(msg: str) -> None:
    print("FAIL:", msg)
    sys.exit(1)


def expect(cond: bool, msg: str) -> None:
    if not cond:
        fail(msg)


def comment_text(line: str) -> str:
    stripped = re.sub(r"(\".*?\"|'.*?')", "", line)
    if stripped.lstrip().startswith("#"):
        return stripped
    if "#" in stripped:
        return stripped.split("#", 1)[1]
    return ""


def test_password_literals_removed() -> None:
    skip = {".git", "tests", "data", "__pycache__", ".venv", "node_modules"}
    allowed_suffix = {".md", ".py", ".html", ".js", ".css", ".txt", ".yml", ".yaml"}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in skip]
        if any(part in skip for part in Path(dirpath).parts):
            continue
        for name in filenames:
            path = Path(dirpath) / name
            if path.suffix.lower() not in allowed_suffix:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for word in BANNED:
                expect(word not in text, f"{path.relative_to(ROOT)} still contains a demo password")
    for path in (ROOT / "tests").glob("*.py"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            note = comment_text(line)
            for word in BANNED:
                expect(word not in note, f"comment in {path.name}:{lineno} still contains a demo password")
    print("OK demo passwords are gone from docs and comments")


def test_seed_does_not_print_or_reset_passwords() -> None:
    script = r"""
import os, tempfile, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
fd, path = tempfile.mkstemp(suffix="-seed-quiet.db")
os.close(fd)
os.environ["SAV_DB"] = path
os.environ.pop("SAV_JASON_PASSWORD", None)
os.environ.pop("SAV_DEMO_PASSWORD", None)
os.environ["SHOW_DEMO_COUNSELORS"] = "0"
import db
conn = db.connect()
db.init_db(conn)
jason = conn.execute("SELECT password_hash FROM users WHERE slug='jason-cheney'").fetchone()
elena = conn.execute("SELECT password_hash, is_demo FROM users WHERE slug='elena-vasquez-lpc'").fetchone()
assert jason and jason["password_hash"]
assert not db.verify_password("123456", jason["password_hash"])
assert elena and int(elena["is_demo"] or 0) == 1
assert not db.verify_password("demo1234", elena["password_hash"])
conn.close()
"""
    proc = subprocess.run(
        [sys.executable, "-c", script, str(ROOT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    blob = (proc.stdout or "") + (proc.stderr or "")
    expect(proc.returncode == 0, f"quiet seed failed: {blob[-800:]}")
    for word in BANNED:
        expect(word not in blob, "seed printed a demo password")
    expect("Password:" not in blob, "seed printed a password label")
    print("OK seed passwords come from env or random and are not printed")


def main() -> None:
    test_password_literals_removed()
    test_seed_does_not_print_or_reset_passwords()

    try:
        from fastapi.testclient import TestClient
    except ImportError:
        os.system(f"{sys.executable} -m pip install -q httpx")
        from fastapi.testclient import TestClient

    import icalutil
    from app import app
    from db import add_link, connect, hash_password, init_db, now_iso

    with connect() as conn:
        init_db(conn)
        jason_before = conn.execute(
            "SELECT password_hash FROM users WHERE username='jasoncheney'"
        ).fetchone()["password_hash"]
        elena_before = conn.execute(
            "SELECT password_hash, is_demo FROM users WHERE slug='elena-vasquez-lpc'"
        ).fetchone()
        expect(int(elena_before["is_demo"] or 0) == 1, "Elena was not marked as a sample account")
        james = conn.execute(
            "SELECT is_demo FROM users WHERE slug='james-okonkwo-lcsw'"
        ).fetchone()
        maya = conn.execute(
            "SELECT is_demo FROM users WHERE slug='maya-chen-lmft'"
        ).fetchone()
        expect(int(james["is_demo"] or 0) == 1 and int(maya["is_demo"] or 0) == 1, "James or Maya missing demo flag")
        founder = conn.execute(
            "SELECT is_demo FROM users WHERE slug='jason-cheney'"
        ).fetchone()
        expect(int(founder["is_demo"] or 0) == 0, "founder account was marked as a sample")

    os.environ["SAV_JASON_PASSWORD"] = "different-founder-secret"
    os.environ["SAV_DEMO_PASSWORD"] = "different-demo-secret"
    with connect() as conn:
        init_db(conn)
        jason_after = conn.execute(
            "SELECT password_hash FROM users WHERE username='jasoncheney'"
        ).fetchone()["password_hash"]
        elena_after = conn.execute(
            "SELECT password_hash FROM users WHERE slug='elena-vasquez-lpc'"
        ).fetchone()["password_hash"]
    expect(jason_after == jason_before, "second boot changed the founder password")
    expect(elena_after == elena_before["password_hash"], "second boot changed a sample counselor password")
    os.environ["SAV_JASON_PASSWORD"] = "123456"
    os.environ["SAV_DEMO_PASSWORD"] = "demo1234"
    print("OK existing seed passwords are left alone")

    def add_counselor(conn, email, name, slug, target=25, workdays="[1,2,3,4,5]", slot_start=9, slot_end=17):
        conn.execute(
            """INSERT INTO users (
                 email, password_hash, name, specialty, about, clinic, address,
                 slug, weekly_target_hours, buffer_hours, workdays, slot_start, slot_end,
                 session_minutes, timezone, created_at, username, setup_complete, is_demo
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                email, hash_password("longpass1"), name,
                "Anxiety therapy for adults",
                "I meet with adults who want a steady hour.",
                "Open Practice", "Denver, CO",
                slug, target, 0, workdays, slot_start, slot_end,
                50, "America/Denver", now_iso(), slug.replace("-", "")[:24], 1, 0,
            ),
        )
        return int(conn.execute("SELECT id FROM users WHERE slug=?", (slug,)).fetchone()["id"])

    with connect() as conn:
        add_counselor(conn, "nora.blank@example.com", "Nora Blankhours", "nora-blankhours", workdays="[]")
        add_counselor(
            conn, "nora.zero@example.com", "Nora Zerohours", "nora-zerohours",
            slot_start=9, slot_end=9,
        )
        add_counselor(conn, "nora.open@example.com", "Nora Withhours", "nora-withhours")
        quinn_id = add_counselor(
            conn, "quinn.real@example.com", "Quinn Real", "quinn-real", target=0,
        )
        riley_id = add_counselor(conn, "riley.open@example.com", "Riley Open", "riley-open")
        james_id = int(conn.execute(
            "SELECT id FROM users WHERE slug='james-okonkwo-lcsw'"
        ).fetchone()["id"])
        add_link(conn, quinn_id, james_id)
        add_link(conn, james_id, riley_id)
        conn.commit()

    def listed(html: str, slug: str) -> bool:
        return f'class="person-card" href="/p/{slug}"' in html

    day = next_open_day()
    with TestClient(app) as client:
        book = client.get("/book")
        expect(book.status_code == 200, f"/book {book.status_code}")
        expect(not listed(book.text, "nora-blankhours"), "counselor with no weekly hours is listed")
        expect(not listed(book.text, "nora-zerohours"), "counselor with a zero-length day is listed")
        expect(listed(book.text, "nora-withhours"), "complete counselor is missing from /book")
        own = client.get("/p/nora-blankhours")
        expect(own.status_code == 200, "hidden counselor public page should stay up")
        expect("Nora Blankhours" in own.text, "hidden counselor page dropped the name")
        print("OK directory requires weekly hours")

        before = None
        with connect() as conn:
            before = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        honeypot = client.post(
            "/api/auth/signup",
            json={
                "name": "Bot Person",
                "email": "bot.person@example.com",
                "username": "botperson",
                "password": "longpass1",
                "company_website": "https://spam.example",
            },
            headers={"X-Forwarded-For": "203.0.113.77"},
        )
        expect(honeypot.status_code == 400, f"honeypot status {honeypot.status_code}")
        with connect() as conn:
            after = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        expect(after == before, "honeypot created an account")
        for n in range(1, 6):
            ok = client.post(
                "/api/auth/signup",
                json={
                    "name": f"Signup Person {n}",
                    "email": f"signup.person.{n}@example.com",
                    "username": f"signupperson{n}",
                    "password": "longpass1",
                },
                headers={"X-Forwarded-For": "203.0.113.77"},
            )
            expect(ok.status_code == 200 and ok.json().get("ok"), f"signup {n} failed: {ok.text}")
        blocked = client.post(
            "/api/auth/signup",
            json={
                "name": "Signup Person 6",
                "email": "signup.person.6@example.com",
                "username": "signupperson6",
                "password": "longpass1",
            },
            headers={"X-Forwarded-For": "203.0.113.77"},
        )
        expect(blocked.status_code == 429, f"sixth signup status {blocked.status_code} {blocked.text}")
        expect("about an hour" in (blocked.json().get("error") or ""), blocked.text)
        with connect() as conn:
            ghost = conn.execute(
                "SELECT 1 FROM users WHERE email='signup.person.6@example.com'"
            ).fetchone()
        expect(ghost is None, "rate-limited signup still created a row")
        print("OK signup honeypot and per-IP limit")

        os.environ["GOOGLE_CLIENT_ID"] = "qa-client.apps.googleusercontent.com"
        os.environ["GOOGLE_CLIENT_SECRET"] = "qa-not-a-real-secret"
        try:
            login = client.post("/api/auth/login", json={"email": "Elena", "password": "demo1234"})
            expect(login.status_code == 200 and login.json().get("ok"), f"Elena login {login.text}")
            dash = client.get("/dashboard")
            expect(dash.status_code == 200, f"Elena dashboard {dash.status_code}")
            expect('id="gcal-not-connected"' in dash.text, "missing not-connected marker")
            expect("Google Calendar: not connected" in dash.text, "missing not-connected sentence")
            expect("Connect Google Calendar" in dash.text, "missing Connect Google Calendar")
            print("OK dashboard says Google Calendar is not connected")
        finally:
            os.environ.pop("GOOGLE_CLIENT_ID", None)
            os.environ.pop("GOOGLE_CLIENT_SECRET", None)

        login = client.post("/api/auth/login", json={"email": "jasoncheney", "password": "123456"})
        expect(login.status_code == 200 and login.json().get("ok"), f"founder login {login.text}")
        orig_fetch = icalutil.fetch_ics

        def good_fetch(url, timeout=2.0):
            return GOOD_ICS

        def bad_fetch(url, timeout=2.0):
            return "this is not a calendar"

        try:
            icalutil.fetch_ics = good_fetch
            http_url = client.patch("/api/me", json={"ical_url": "http://example.com/cal.ics"})
            expect(http_url.status_code == 400, f"http calendar status {http_url.status_code}")
            expect("https://" in (http_url.json().get("error") or ""), http_url.text)
            with connect() as conn:
                saved = conn.execute(
                    "SELECT ical_url FROM users WHERE username='jasoncheney'"
                ).fetchone()["ical_url"]
            expect(not (saved or "").strip(), "http calendar URL was saved")

            icalutil.fetch_ics = bad_fetch
            broken = client.patch("/api/me", json={"ical_url": "https://example.com/broken.ics"})
            expect(broken.status_code == 400, f"broken calendar status {broken.status_code}")
            expect(broken.json().get("error") == UNREACHABLE, broken.text)
            with connect() as conn:
                saved = conn.execute(
                    "SELECT ical_url FROM users WHERE username='jasoncheney'"
                ).fetchone()["ical_url"]
            expect(not (saved or "").strip(), "unreadable calendar URL was saved")

            icalutil.fetch_ics = good_fetch
            setup = client.post("/api/setup", json={
                "name": "Jason Cheney",
                "specialty": "Counseling — anxiety and life transitions",
                "about": "I meet with adults.",
                "weekly_target_hours": 25,
                "buffer_hours": 3,
                "workdays": [1, 2, 3, 4, 5],
                "slot_start": 9,
                "slot_end": 17,
                "ical_url": "https://example.com/good.ics",
            })
            expect(setup.status_code == 200 and setup.json().get("ok"), f"setup {setup.text}")
            with connect() as conn:
                saved = conn.execute(
                    "SELECT ical_url FROM users WHERE username='jasoncheney'"
                ).fetchone()["ical_url"]
            expect(saved == "https://example.com/good.ics", f"valid calendar not saved: {saved}")

            icalutil.fetch_ics = bad_fetch
            with connect() as conn:
                conn.execute(
                    "UPDATE users SET ical_synced_at=? WHERE username='jasoncheney'",
                    ("2020-01-01T00:00:00-07:00",),
                )
                conn.commit()
            setup_page = client.get("/setup")
            dash = client.get("/dashboard")
            expect(setup_page.status_code == 200, f"setup page {setup_page.status_code}")
            expect(dash.status_code == 200, f"dashboard {dash.status_code} {dash.headers.get('location')}")
            expect(UNREACHABLE in setup_page.text, "setup missing calendar reconnect sentence")
            expect('id="calendar-unreachable"' in setup_page.text, "setup missing calendar alert")
            expect(UNREACHABLE in dash.text, "dashboard missing calendar reconnect sentence")
            expect('id="calendar-unreachable"' in dash.text, "dashboard missing calendar alert")
            print("OK calendar links must be reachable https feeds")
        finally:
            icalutil.fetch_ics = orig_fetch

        os.environ.pop("SHOW_DEMO_COUNSELORS", None)
        hidden = client.get("/book")
        expect(not listed(hidden.text, "elena-vasquez-lpc"), "Elena is listed while sample counselors are hidden")
        expect(not listed(hidden.text, "james-okonkwo-lcsw"), "James is listed while sample counselors are hidden")
        expect(not listed(hidden.text, "maya-chen-lmft"), "Maya is listed while sample counselors are hidden")
        expect(listed(hidden.text, "nora-withhours"), "a real counselor disappeared with the sample toggle")
        searched = client.get("/book?q=Elena")
        expect(not listed(searched.text, "elena-vasquez-lpc"), "Elena search still returns her card")
        home = client.get("/")
        expect("elena-vasquez-lpc" in home.text, "landing hero lost the sample calendar link")
        expect("James" in home.text and "Maya" in home.text, "landing hero lost the sample names")

        page = client.get("/p/elena-vasquez-lpc")
        expect(page.status_code == 200, f"sample page {page.status_code}")
        expect(SAMPLE in page.text, "sample page missing the friendly message")
        expect('id="sample-profile"' in page.text, "sample page missing the message marker")
        expect('id="schedule-card"' not in page.text, "sample page still offers a booking form")
        refused = client.post("/api/p/elena-vasquez-lpc/book", json={
            "date": day,
            "time": "11:00",
            "name": "Pat Client",
            "email": "pat.client@example.com",
        })
        expect(refused.status_code == 400, f"sample book status {refused.status_code}")
        expect(refused.json().get("error") == SAMPLE, refused.text)
        refused_wait = client.post("/api/p/james-okonkwo-lcsw/waitlist", json={
            "name": "Pat Client",
            "email": "pat.client@example.com",
        })
        expect(refused_wait.json().get("error") == SAMPLE, refused_wait.text)
        refused_ref = client.post("/api/p/quinn-real/book-referral", json={
            "peerSlug": "james-okonkwo-lcsw",
            "date": day,
            "time": "11:00",
            "name": "Pat Client",
            "email": "pat.client@example.com",
        })
        expect(refused_ref.json().get("error") == SAMPLE, refused_ref.text)

        overflow = client.post("/api/p/quinn-real/book", json={
            "date": day,
            "time": "10:00",
            "name": "Sam Overflow",
            "email": "sam.overflow@example.com",
            "category": "general",
        })
        expect(overflow.status_code == 200, f"overflow status {overflow.status_code} {overflow.text}")
        body = overflow.json()
        expect(body.get("full") is True, f"expected a full week: {body}")
        slugs = []
        if body.get("recommendation"):
            slugs.append(body["recommendation"].get("peerSlug"))
        for alt in body.get("alternatives") or []:
            slugs.append(alt.get("peerSlug"))
        for demo_slug in ("elena-vasquez-lpc", "james-okonkwo-lcsw", "maya-chen-lmft"):
            expect(demo_slug not in slugs, f"sample counselor offered as a referral: {slugs}")
        expect("riley-open" in slugs, f"real peer behind a sample counselor was dropped: {slugs}")
        print("OK sample counselors are hidden and their pages refuse new bookings")

        os.environ["SHOW_DEMO_COUNSELORS"] = "1"
        visible = client.get("/p/elena-vasquez-lpc")
        expect(SAMPLE not in visible.text, "sample message showed while the toggle is on")
        expect('id="schedule-card"' in visible.text, "booking form missing while sample counselors are shown")
        shown = client.get("/book")
        expect(listed(shown.text, "elena-vasquez-lpc"), "Elena missing when sample counselors are shown")

        def capture(call):
            buf = StringIO()
            with redirect_stdout(buf):
                resp = call()
            return resp, buf.getvalue()

        os.environ.pop("SHOW_DEMO_COUNSELORS", None)
        ref, ref_log = capture(lambda: client.post("/api/p/quinn-real/book-referral", json={
            "peerSlug": "riley-open",
            "date": day,
            "time": "10:00",
            "name": "PIIReferZed",
            "email": "pii.refer@example.com",
            "phone": "555019001",
        }))
        expect(ref.status_code == 200 and ref.json().get("ok"), f"referral book {ref.text}")
        booked, book_log = capture(lambda: client.post("/api/p/riley-open/book", json={
            "date": day,
            "time": "11:00",
            "name": "PIINameZed",
            "email": "pii.zed@example.com",
            "phone": "555019002",
        }))
        expect(booked.status_code == 200 and booked.json().get("ok"), f"direct book {booked.text}")
        waiting, wait_log = capture(lambda: client.post("/api/p/riley-open/waitlist", json={
            "name": "PIIWaitZed",
            "email": "pii.wait@example.com",
            "phone": "555019003",
        }))
        expect(waiting.status_code == 200 and waiting.json().get("ok"), f"waitlist {waiting.text}")
        logs = ref_log + book_log + wait_log
        for secret in (
            "PIIReferZed", "pii.refer@example.com",
            "PIINameZed", "pii.zed@example.com",
            "PIIWaitZed", "pii.wait@example.com",
            "555019001", "555019002", "555019003",
        ):
            expect(secret not in logs, f"server log included client data ({secret})")
        expect("appointment_id=" in book_log, f"book log missing an id: {book_log}")
        expect("client_id=" in book_log, f"book log missing client id: {book_log}")
        expect("appointment_id=" in ref_log, f"referral log missing an id: {ref_log}")
        expect("waitlist_id=" in wait_log, f"waitlist log missing an id: {wait_log}")
        expect("[notify]" in book_log and "user_id=" in book_log, f"notify log missing ids: {book_log}")
        expect("kind=booking" in book_log, book_log)
        with connect() as conn:
            note = conn.execute(
                "SELECT title, body FROM notifications WHERE kind='booking' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        expect(note and "PIINameZed" in (note["title"] + note["body"]), "in-app notification lost the client name")
        print("OK booking logs keep ids and leave client details out")

    print("ALL QA ROUND 1 TESTS PASSED")


if __name__ == "__main__":
    main()
