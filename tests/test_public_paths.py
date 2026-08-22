#!/usr/bin/env python3
"""Public route smoke tests via FastAPI TestClient + temp SAV_DB."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fd, DBFILE = tempfile.mkstemp(suffix="-public-paths.db")
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

    cases = [
        ("/", 200, ["Book a visit in seconds", "Get your booking link", "Provider login"]),
        ("/book", 200, ["Book a visit", "Elena Vasquez", "Choose a professional"]),
        ("/login", 200, ["Welcome back", "jasoncheney", "demo1234"]),
        ("/signup", 200, ["Set your name", "Create account", 'data-next="/setup"']),
        ("/p/jason-cheney", 200, ["Jason Cheney", "Pick a day", "Pick a time"]),
        ("/p/elena-vasquez-lpc", 200, ["Elena Vasquez", "Free consultation", "Full session"]),
    ]
    for path, status, needles in cases:
        r = c.get(path)
        expect(r.status_code == status, f"{path} expected {status}, got {r.status_code}")
        for n in needles:
            expect(n in r.text, f"{path} missing {n!r}")
        print(f"OK {path} {r.status_code}")

    css = (ROOT / "static" / "styles.css").read_text()
    expect("@media (max-width: 480px)" in css, "missing 480px mobile breakpoint")
    expect("minmax(0, 1fr)" in css, "missing minmax slot/calendar overflow guard")
    expect(".week-grid { grid-template-columns: repeat(2" in css, "missing week-grid 2-col mobile rule")
    print("OK mobile 480px CSS guards")

    print("ALL PUBLIC PATH SMOKES PASSED")


if __name__ == "__main__":
    main()
