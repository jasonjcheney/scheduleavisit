#!/usr/bin/env python3
"""Book-a-visit search: name, city, and empty state."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fd, DBFILE = tempfile.mkstemp(suffix="-book-search.db")
os.close(fd)
os.environ["SAV_DB"] = DBFILE
os.environ.setdefault("SAV_JASON_PASSWORD", "123456")
os.environ.setdefault("SAV_DEMO_PASSWORD", "demo1234")
os.environ.setdefault("SHOW_DEMO_COUNSELORS", "1")


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

    with connect() as conn:
        init_db(conn)

    c = TestClient(app)

    book = c.get("/book")
    expect(book.status_code == 200, f"/book got {book.status_code}")
    expect('name="q"' in book.text, "/book missing search name=q")
    expect('type="search"' in book.text, "/book missing search input")
    expect("Find someone to see" in book.text, "/book missing search headline")
    expect("Elena is near her weekly cap" not in book.text, "/book still has tester copy")
    print("OK /book shows a search input")

    # Seed Jason still has placeholder bio, so he stays off the directory until that is real.
    jason = c.get("/book?q=jason")
    expect(jason.status_code == 200, f"/book?q=jason got {jason.status_code}")
    expect(
        'class="person-card" href="/p/jason-cheney"' not in jason.text,
        "placeholder bio should keep Jason off /book",
    )
    expect(c.get("/p/jason-cheney").status_code == 200, "Jason's own /p link should still open")
    with connect() as conn:
        conn.execute(
            "UPDATE users SET specialty=? WHERE slug='jason-cheney'",
            ("Counseling — anxiety and life transitions",),
        )
        conn.commit()
    jason = c.get("/book?q=jason")
    expect("Jason Cheney" in jason.text, "/book?q=jason missing Jason Cheney after a real specialty")
    expect('href="/p/jason-cheney"' in jason.text, "/book?q=jason missing link to /p/jason-cheney")
    print("OK /book?q=jason includes Jason Cheney once his page is filled in")

    boulder = c.get("/book?q=Boulder")
    expect(boulder.status_code == 200, f"/book?q=Boulder got {boulder.status_code}")
    expect("Elena Vasquez" in boulder.text, "/book?q=Boulder missing Elena")
    expect("Maya Chen" in boulder.text, "/book?q=Boulder missing Maya")
    expect("James Okonkwo" not in boulder.text, "/book?q=Boulder included a Superior miss")
    print("OK /book?q=Boulder includes Boulder providers, not a random miss")

    miss = c.get("/book?q=zzzzzz")
    expect(miss.status_code == 200, f"/book?q=zzzzzz got {miss.status_code}")
    expect("No one matched that search" in miss.text, "/book?q=zzzzzz missing empty state")
    expect('href="/p/jason-cheney"' not in miss.text, "/book?q=zzzzzz listed Jason")
    expect("person-card" not in miss.text, "/book?q=zzzzzz still rendered result cards")
    expect('href="/p/elena-vasquez-lpc"' in miss.text and "demo" in miss.text.lower(),
           "/book?q=zzzzzz missing Elena demo CTA")
    print("OK /book?q=zzzzzz empty state, not a 500")

    # A random-letter name stays hidden even after setup is marked done and a bio is filled in.
    # A readable name with no bio (QA Empty Signup) stays hidden too. /p/ still opens.
    bot = TestClient(app)
    r = bot.post("/api/auth/signup", json={
        "name": "BtVpNzsZmOHPKWZp",
        "email": "singingpunter+dirbot@gmail.com",
        "password": "demo12345",
        "username": "dirbot_test",
    }, headers={"X-Forwarded-For": "203.0.113.21"})
    expect(r.json().get("ok"), f"signup failed: {r.text}")
    with connect() as conn:
        row = conn.execute("SELECT slug FROM users WHERE email=?", ("singingpunter+dirbot@gmail.com",)).fetchone()
    bot_slug = row["slug"]
    listing = c.get("/book")
    expect(f'href="/p/{bot_slug}"' not in listing.text, "random-letter sign-up should not be in /book")
    expect("BtVpNzsZmOHPKWZp" not in listing.text, "random-letter name visible in /book")
    expect(c.get(f"/p/{bot_slug}").status_code == 200, "hidden sign-up /p/ link should still open")
    with connect() as conn:
        conn.execute(
            """UPDATE users SET setup_complete=1, specialty=?, about=?
               WHERE slug=?""",
            ("Anxiety therapy", "I see adults.", bot_slug),
        )
        conn.commit()
    expect(f'href="/p/{bot_slug}"' not in c.get("/book").text, "random-letter name should stay hidden")

    empty = TestClient(app)
    r = empty.post("/api/auth/signup", json={
        "name": "QA Empty Signup",
        "email": "singingpunter+qaempty@gmail.com",
        "password": "demo12345",
        "username": "qa_empty_signup",
    }, headers={"X-Forwarded-For": "203.0.113.22"})
    expect(r.json().get("ok"), f"empty signup failed: {r.text}")
    with connect() as conn:
        empty_slug = conn.execute(
            "SELECT slug FROM users WHERE email=?", ("singingpunter+qaempty@gmail.com",)
        ).fetchone()["slug"]
        conn.execute("UPDATE users SET setup_complete=1 WHERE slug=?", (empty_slug,))
        conn.commit()
    book_empty = c.get("/book")
    expect("QA Empty Signup" not in book_empty.text, "QA Empty Signup should stay off /book")
    expect(f'href="/p/{empty_slug}"' not in book_empty.text, "QA Empty Signup link should stay off /book")
    expect(c.get(f"/p/{empty_slug}").status_code == 200, "QA Empty Signup /p/ should still open")
    with connect() as conn:
        conn.execute(
            "UPDATE users SET specialty=? WHERE slug=?",
            ("Adult therapy — anxiety and burnout", empty_slug),
        )
        conn.commit()
    expect(f'href="/p/{empty_slug}"' in c.get("/book").text, "name, bio, and hours should list the page")
    print("OK empty and random-letter sign-ups stay out of the public directory")

    print("ALL BOOK SEARCH TESTS PASSED")


if __name__ == "__main__":
    main()
