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

    jason = c.get("/book?q=jason")
    expect(jason.status_code == 200, f"/book?q=jason got {jason.status_code}")
    expect("Jason Cheney" in jason.text, "/book?q=jason missing Jason Cheney")
    expect('href="/p/jason-cheney"' in jason.text, "/book?q=jason missing link to /p/jason-cheney")
    print("OK /book?q=jason includes Jason Cheney")

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
    expect('href="/p/elena-vasquez-lpc"' not in miss.text, "/book?q=zzzzzz listed Elena")
    expect("person-card" not in miss.text, "/book?q=zzzzzz still rendered result cards")
    print("OK /book?q=zzzzzz empty state, not a 500")

    print("ALL BOOK SEARCH TESTS PASSED")


if __name__ == "__main__":
    main()
