#!/usr/bin/env python3
"""Resend email (mocked) and no sample colleagues on real accounts."""
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

fd, DBFILE = tempfile.mkstemp(suffix="-email-demo.db")
os.close(fd)
os.environ["SAV_DB"] = DBFILE
os.environ.setdefault("SAV_JASON_PASSWORD", "123456")
os.environ.setdefault("SAV_DEMO_PASSWORD", "demo1234")
os.environ.pop("SHOW_DEMO_COUNSELORS", None)

SECRET = "re_test_key_do_not_log_991"
FROM = "ScheduleAVisit <hello@scheduleavisit.com>"

for _k in (
    "RESEND_API_KEY",
    "EMAIL_FROM",
    "MAIL_FROM",
    "RESEND_FROM",
    "SMTP_FROM",
    "MAILGUN_API_KEY",
    "MAILGUN_DOMAIN",
    "MAILGUN_API_DOMAIN",
    "SMTP_HOST",
    "SMTP_URL",
    "SMTP_SERVER",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_FROM",
):
    os.environ.pop(_k, None)

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


class Resp:
    def __init__(self, code=200):
        self.status_code = code
        self.text = ""


def row_says_emailed(html: str, email: str) -> bool:
    needle = f"<strong>{email}</strong>"
    i = html.find(needle)
    expect(i != -1, f"dashboard missing invite row for {email}")
    return "We emailed them" in html[i:i + 220]


def main() -> None:
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        os.system(f"{sys.executable} -m pip install -q httpx")
        from fastapi.testclient import TestClient

    import httpx
    from app import app

    posts: list[dict] = []
    status_code = {"code": 200}
    real_post = httpx.post

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
        posts.append({"url": url, "headers": headers or {}, "json": json or {}})
        return Resp(status_code["code"])

    with TestClient(app) as c:
        _run(c, posts, status_code, fake_post, httpx, real_post)


def _run(c, posts, status_code, fake_post, httpx, real_post) -> None:
    from capacity import referral_candidates
    from db import (
        DEMO_SLUGS,
        add_link,
        add_recommendation,
        connect,
        hash_password,
        init_db,
        now_iso,
        today,
    )
    from reminders import send_due

    day, hhmm = future_weekday(10, 8)
    buf = StringIO()
    with redirect_stdout(buf):
        skipped = c.post("/api/p/jason-cheney/book", json={
            "date": day.isoformat(),
            "time": hhmm,
            "name": "Pat Mailer",
            "email": "pat.mailer@example.com",
            "visitKind": "session",
        })
    log = buf.getvalue()
    expect(skipped.status_code == 200 and skipped.json().get("ok"), f"unconfigured book {skipped.text}")
    expect("RESEND_API_KEY is not set" in log, f"missing skip reason: {log}")
    expect(SECRET not in log, "unconfigured log included a key")
    print("OK booking succeeds and logs a skip when email is not configured")

    os.environ["RESEND_API_KEY"] = SECRET
    os.environ.pop("EMAIL_FROM", None)
    day_missing, hhmm_missing = future_weekday(11, 8)
    buf = StringIO()
    with redirect_stdout(buf):
        missing_from = c.post("/api/p/jason-cheney/book", json={
            "date": day_missing.isoformat(),
            "time": hhmm_missing,
            "name": "Pat Mailer",
            "email": "pat.mailer@example.com",
            "visitKind": "session",
        })
    log = buf.getvalue()
    expect(missing_from.status_code == 200 and missing_from.json().get("ok"), missing_from.text)
    expect("EMAIL_FROM is not set" in log, f"missing EMAIL_FROM reason: {log}")
    expect(SECRET not in log, "EMAIL_FROM skip log included the API key")
    print("OK a key without EMAIL_FROM skips and does not log the key")

    os.environ["EMAIL_FROM"] = FROM
    httpx.post = fake_post
    try:
        posts.clear()
        status_code["code"] = 200
        day2, hhmm2 = future_weekday(14, 9)
        buf = StringIO()
        with redirect_stdout(buf):
            sent = c.post("/api/p/jason-cheney/book", json={
                "date": day2.isoformat(),
                "time": hhmm2,
                "name": "Pat Mailer",
                "email": "pat.mailer@example.com",
                "visitKind": "session",
            })
        log = buf.getvalue()
        expect(sent.status_code == 200 and sent.json().get("ok"), f"configured book {sent.text}")
        expect(SECRET not in log, "send log included the API key")
        expect("sent via resend" in log, f"success log missing: {log}")
        expect(len(posts) >= 2, f"expected client and therapist emails, got {len(posts)}")
        for post in posts:
            expect(post["url"] == "https://api.resend.com/emails", post["url"])
            expect(post["json"].get("from") == FROM, post["json"].get("from"))
            auth = post["headers"].get("Authorization") or ""
            expect(auth.startswith("Bearer "), "resend auth header missing")
            expect(SECRET not in log, "key leaked beside the request")
        by_to = {tuple(p["json"].get("to") or []): p["json"] for p in posts}
        client_msg = by_to.get(("pat.mailer@example.com",))
        therapist_msg = by_to.get(("jasoncheney@scheduleavisit.example",))
        expect(client_msg is not None, f"client confirmation missing: {list(by_to)}")
        expect(therapist_msg is not None, f"therapist booking note missing: {list(by_to)}")
        client_text = f"{client_msg['subject']}\n{client_msg['text']}"
        therapist_text = f"{therapist_msg['subject']}\n{therapist_msg['text']}"
        for blob in (client_text, therapist_text):
            low = blob.lower()
            expect("pat" in low, f"missing first name: {blob}")
            expect("mailer" not in low, f"email included a last name: {blob}")
            expect("boulder" in low, f"missing clinic address: {blob}")
            expect("hipaa" not in low and "diagnosis" not in low, blob)
            expect("clinical note" not in low, blob)
            expect("pat.mailer@example.com" not in low, "email included the client address")
        expect("/booked/" in client_text, "client email missing the visit link")
        expect("/dashboard" in therapist_text, "therapist email missing the schedule link")
        expect("2 pm" in client_text, f"client email missing the time: {client_text}")
        print("OK mocked Resend receives the booking confirmation and the therapist note")

        posts.clear()
        status_code["code"] = 500
        day3, hhmm3 = future_weekday(15, 10)
        buf = StringIO()
        with redirect_stdout(buf):
            failed = c.post("/api/p/jason-cheney/book", json={
                "date": day3.isoformat(),
                "time": hhmm3,
                "name": "Pat Mailer",
                "email": "pat.mailer@example.com",
                "visitKind": "session",
            })
        log = buf.getvalue()
        expect(failed.status_code == 200 and failed.json().get("ok"), f"provider error blocked booking: {failed.text}")
        expect("resend http 500" in log, f"provider error not logged: {log}")
        expect(SECRET not in log, "provider error log included the API key")
        print("OK a Resend error does not block the booking")

        status_code["code"] = 200
        posts.clear()
        login = c.post("/api/auth/login", json={"email": "jasoncheney", "password": "123456"})
        expect(login.json().get("ok"), login.text)
        with connect() as conn:
            conn.execute("UPDATE users SET setup_complete=1 WHERE username='jasoncheney'")
            conn.commit()
        invited = c.post("/api/me/network/invite", json={
            "email": "colleague@clinic.com",
            "category": "general",
        })
        body = invited.json()
        expect(invited.status_code == 200 and body.get("ok"), invited.text)
        expect(body.get("emailed") is True, body)
        expect("We emailed" in (body.get("message") or ""), body)
        invite_posts = [p for p in posts if "colleague@clinic.com" in (p["json"].get("to") or [])]
        expect(invite_posts, "invite was marked emailed without a provider call")
        invite_text = invite_posts[0]["json"]["text"]
        expect("Accept the invite:" in invite_text, invite_text)
        expect(body["url"] in invite_text, "invite email missing the link")
        expect("hipaa" not in invite_text.lower(), invite_text)
        expect("clinical" not in invite_text.lower(), invite_text)
        dash = c.get("/dashboard")
        expect(dash.status_code == 200, dash.status_code)
        expect(row_says_emailed(dash.text, "colleague@clinic.com"), "dashboard hid a real send")
        print("OK the invite says we emailed them only after Resend accepts it")

        os.environ.pop("RESEND_API_KEY", None)
        os.environ.pop("EMAIL_FROM", None)
        posts.clear()
        quiet = c.post("/api/me/network/invite", json={
            "email": "other.colleague@clinic.com",
            "category": "general",
        })
        quiet_body = quiet.json()
        expect(quiet.status_code == 200 and quiet_body.get("ok"), quiet.text)
        expect(quiet_body.get("emailed") is False, quiet_body)
        expect("We emailed" not in (quiet_body.get("message") or ""), quiet_body)
        expect(posts == [], "unconfigured invite still called the provider")
        dash2 = c.get("/dashboard")
        expect(not row_says_emailed(dash2.text, "other.colleague@clinic.com"), dash2.text)
        expect(row_says_emailed(dash2.text, "colleague@clinic.com"), "a real send was forgotten")
        print("OK an unconfigured invite keeps the copy-link fallback")

        os.environ["RESEND_API_KEY"] = SECRET
        os.environ["EMAIL_FROM"] = FROM
        status_code["code"] = 500
        posts.clear()
        broken = c.post("/api/me/network/invite", json={
            "email": "third.colleague@clinic.com",
            "category": "general",
        })
        expect(broken.status_code == 200 and broken.json().get("ok"), broken.text)
        expect(broken.json().get("emailed") is False, broken.text)
        expect("We emailed" not in (broken.json().get("message") or ""), broken.text)
        print("OK a provider error does not block the invite")

        status_code["code"] = 200
        posts.clear()
        saved = c.post("/api/setup", json={
            "name": "Jason Cheney",
            "credentials": "Therapist",
            "title": "Counselor",
            "clinic": "My practice",
            "address": "Boulder, CO",
            "weekly_target_hours": 25,
            "buffer_hours": 3,
            "workdays": [1, 2, 3, 4, 5],
            "reminders_opt_in": 1,
        })
        expect(saved.json().get("ok"), saved.text)
        day4, hhmm4 = future_weekday(9, 12)
        booked = c.post("/api/p/jason-cheney/book", json={
            "date": day4.isoformat(),
            "time": hhmm4,
            "name": "Sam Optin",
            "email": "sam.optin.mail@example.com",
            "visitKind": "session",
        })
        expect(booked.json().get("ok"), booked.text)
        with connect() as conn:
            send_due(conn, now=datetime.now(TZ) + timedelta(days=40))
            conn.commit()
        later = [
            p["json"] for p in posts
            if "tomorrow" in (p["json"].get("subject") or "").lower()
            or (
                "today" in (p["json"].get("subject") or "").lower()
                and "booked" not in (p["json"].get("subject") or "").lower()
            )
        ]
        expect(later, f"opt-in reminders were not sent: {[p['json'].get('subject') for p in posts]}")
        expect(
            any("jasoncheney@scheduleavisit.example" in (p.get("to") or []) for p in later),
            "opt-in did not email the therapist a later reminder",
        )
        expect(
            any("sam.optin.mail@example.com" in (p.get("to") or []) for p in later),
            "opt-in did not email the client a later reminder",
        )
        blob = "\n".join(f"{p.get('subject','')}\n{p.get('text','')}" for p in later).lower()
        expect("sam" in blob, blob)
        expect("hipaa" not in blob and "clinical note" not in blob, blob)
        print("OK opted-in day-before and morning-of reminders go through the provider")
    finally:
        httpx.post = real_post
        os.environ.pop("RESEND_API_KEY", None)
        os.environ.pop("EMAIL_FROM", None)

    with connect() as conn:
        jason = conn.execute("SELECT * FROM users WHERE username='jasoncheney'").fetchone()
        expect(jason is not None, "jason missing")
        conn.execute(
            """UPDATE users
               SET page_hidden=1, photo_path='avatars/jason.jpg',
                   google_refresh_token='tok-keep', weekly_target_hours=22
               WHERE id=?""",
            (jason["id"],),
        )
        for slug in DEMO_SLUGS:
            peer = conn.execute("SELECT id FROM users WHERE slug=?", (slug,)).fetchone()
            expect(peer is not None, f"sample account missing before migration: {slug}")
            add_link(conn, jason["id"], peer["id"])
        before_appts = conn.execute(
            "SELECT COUNT(*) AS c FROM appointments WHERE provider_id=?",
            (jason["id"],),
        ).fetchone()["c"]
        password_hash = conn.execute(
            "SELECT password_hash FROM users WHERE id=?", (jason["id"],)
        ).fetchone()["password_hash"]
        conn.commit()
        init_db(conn)
        mixed = conn.execute(
            """SELECT n.id
               FROM network_links n
               JOIN users a ON a.id = n.user_id
               JOIN users b ON b.id = n.peer_id
               WHERE COALESCE(a.is_demo, 0) != COALESCE(b.is_demo, 0)"""
        ).fetchall()
        expect(not mixed, f"migration left sample peers on a real account: {len(mixed)}")
        for slug in DEMO_SLUGS:
            expect(
                conn.execute("SELECT id FROM users WHERE slug=?", (slug,)).fetchone() is not None,
                f"migration deleted sample account {slug}",
            )
        elena_james = conn.execute(
            """SELECT 1
               FROM network_links n
               JOIN users a ON a.id = n.user_id AND a.slug = 'elena-vasquez-lpc'
               JOIN users b ON b.id = n.peer_id AND b.slug = 'james-okonkwo-lcsw'"""
        ).fetchone()
        expect(elena_james is not None, "demo-to-demo referral link was removed")
        kept = conn.execute("SELECT * FROM users WHERE id=?", (jason["id"],)).fetchone()
        expect(kept["password_hash"] == password_hash, "migration changed the real password")
        expect(int(kept["page_hidden"] or 0) == 1, "migration cleared page_hidden")
        expect(kept["photo_path"] == "avatars/jason.jpg", "migration cleared the photo")
        expect(kept["google_refresh_token"] == "tok-keep", "migration cleared the calendar token")
        expect(kept["weekly_target_hours"] == 22, "migration changed weekly hours")
        after_appts = conn.execute(
            "SELECT COUNT(*) AS c FROM appointments WHERE provider_id=?",
            (jason["id"],),
        ).fetchone()["c"]
        expect(after_appts == before_appts, f"migration changed bookings {before_appts} -> {after_appts}")
        conn.commit()
        dash = c.get("/dashboard")
        expect("Elena Vasquez" not in dash.text, "dashboard still lists a sample colleague")
        expect("James Okonkwo" not in dash.text, "dashboard still lists James")
        expect("Maya Chen" not in dash.text, "dashboard still lists Maya")
        expect("0 of 5" in dash.text, "colleague count still includes sample profiles")

        james = conn.execute("SELECT * FROM users WHERE slug='james-okonkwo-lcsw'").fetchone()
        maya = conn.execute("SELECT * FROM users WHERE slug='maya-chen-lmft'").fetchone()
        elena = conn.execute("SELECT * FROM users WHERE slug='elena-vasquez-lpc'").fetchone()
        blocked = add_recommendation(conn, jason["id"], james["id"])
        expect(blocked and "Sample" in blocked, f"real account could recommend a sample profile: {blocked}")
        conn.execute(
            """INSERT INTO users (
                 email, password_hash, name, slug, created_at, setup_complete, is_demo,
                 weekly_target_hours, buffer_hours, workdays, slot_start, slot_end,
                 session_minutes, timezone
               ) VALUES (?,?,?,?,?,1,0,30,0,'[1,2,3,4,5]',9,17,50,'America/Denver')""",
            (
                "sam.open.mail@example.com",
                hash_password("longpass1"),
                "Sam Open",
                "sam-open-mail",
                now_iso(),
            ),
        )
        sam = conn.execute("SELECT * FROM users WHERE slug='sam-open-mail'").fetchone()
        add_link(conn, jason["id"], james["id"])
        add_link(conn, jason["id"], sam["id"])
        add_link(conn, sam["id"], maya["id"])
        conn.commit()
        os.environ["SHOW_DEMO_COUNSELORS"] = "1"
        try:
            jason = conn.execute("SELECT * FROM users WHERE id=?", (jason["id"],)).fetchone()
            offered = [p["slug"] for p in referral_candidates(conn, jason, today(), "11:00", 50)]
            expect("james-okonkwo-lcsw" not in offered, f"direct sample peer offered: {offered}")
            expect("maya-chen-lmft" not in offered, f"multi-hop sample peer offered: {offered}")
            expect("elena-vasquez-lpc" not in offered, f"sample peer offered: {offered}")
            expect("sam-open-mail" in offered, f"real colleague dropped: {offered}")
            demo_offered = [p["slug"] for p in referral_candidates(conn, elena, today(), "11:00", 50)]
            expect("james-okonkwo-lcsw" in demo_offered, f"demo network lost James: {demo_offered}")
        finally:
            os.environ.pop("SHOW_DEMO_COUNSELORS", None)
    print("OK migration drops sample peers from real accounts and keeps the demo network")
    print("ALL EMAIL AND DEMO PEER TESTS PASSED")


if __name__ == "__main__":
    main()
