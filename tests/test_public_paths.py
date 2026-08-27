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
        ("/", 200, [
            "Find a time — even when your clinician is full.",
            "No account needed",
            "I am a provider",
            "Clinician login",
            "Get your booking link",
            "Provider login",
            "Common questions",
            "What happens when I",
            "Do clients see my hour cap?",
            "How do peer referrals work?",
            "Is this HIPAA?",
            "How do I get my booking link?",
            "Trusted peers on your network",
            "No BAA",
            "in-dashboard for now",
            "faq-item",
            "Scheduling tool for independent counselors",
            "Not a substitute for clinical judgment",
            "Not HIPAA-compliant yet (no BAA)",
            'href="/privacy"',
            'href="/terms"',
        ]),
        ("/book", 200, ["Book a visit", "Elena Vasquez", "Choose a professional",
                         "Scheduling tool for independent counselors", "clinical judgment", "no BAA"]),
        ("/login", 200, ["Welcome back", "jasoncheney",
                         "Scheduling tool for independent counselors", "Not HIPAA-compliant yet",
                         'href="/privacy"', 'href="/terms"']),
        ("/signup", 200, ["Set your name", "Create account", 'data-next="/setup"',
                          "Not a substitute for clinical judgment"]),
        ("/p/jason-cheney", 200, ["Jason Cheney", "Pick a day", "Pick a time"]),
        ("/p/elena-vasquez-lpc", 200, ["Elena Vasquez", "Free consultation", "Full session"]),
        ("/privacy", 200, ["We only keep what we need", "jasonjcheney@gmail.com",
                           "clinical notes", "hosted on Render", "do not sell",
                           'href="/privacy"', 'href="/terms"']),
        ("/terms", 200, ["A scheduling tool", "jasonjcheney@gmail.com",
                         "do not take cards", "hosted on Render", 'href="/terms"']),
    ]
    for path, status, needles in cases:
        r = c.get(path)
        expect(r.status_code == status, f"{path} expected {status}, got {r.status_code}")
        for n in needles:
            expect(n in r.text, f"{path} missing {n!r}")
        print(f"OK {path} {r.status_code}")

    landing = c.get("/")
    expect("For counselors, therapists, and independent clinicians" not in landing.text,
           "landing still uses the old provider-first hero eyebrow")
    expect('class="provider-door"' in landing.text, "landing missing provider-door box")
    expect('href="/login"' in landing.text, "landing provider door missing /login")
    print("OK / client-first hero + provider door")

    # Friendly not-found for unknown provider slugs (200 HTML, not a hard 404)
    missing = c.get("/p/does-not-exist")
    expect(missing.status_code == 200, f"/p/does-not-exist expected 200, got {missing.status_code}")
    expect("text/html" in (missing.headers.get("content-type") or ""), "/p/does-not-exist should be HTML")
    expect("We could not find that calendar." in missing.text, "/p/does-not-exist missing friendly message")
    expect('href="/book"' in missing.text, "/p/does-not-exist missing Book a visit CTA")
    expect('href="/"' in missing.text, "/p/does-not-exist missing Home CTA")
    expect('href="/login"' in missing.text, "/p/does-not-exist missing Provider login CTA")
    expect("empty-hero" in missing.text, "/p/does-not-exist missing empty-hero layout")
    print("OK /p/does-not-exist 200 friendly notfound")

    missing2 = c.get("/p/missing-slug")
    expect(missing2.status_code == 200, f"/p/missing-slug expected 200, got {missing2.status_code}")
    expect("We could not find that calendar." in missing2.text, "/p/missing-slug missing friendly message")
    expect("Book a visit" in missing2.text and "Home" in missing2.text, "/p/missing-slug missing CTAs")
    expect("empty-hero" in missing2.text, "/p/missing-slug missing empty-hero layout")
    print("OK /p/missing-slug 200 friendly notfound")

    login = c.get("/login")
    expect("demo1234" not in login.text, "/login must not advertise demo1234")
    expect("123456" not in login.text, "/login must not advertise 123456")
    print("OK /login hides demo passwords")

    visit_miss = c.get("/booked/999999")
    expect(visit_miss.status_code == 404, f"/booked/999999 expected 404, got {visit_miss.status_code}")
    expect("We could not find that visit." in visit_miss.text, "/booked missing visit copy")
    expect("Book a visit" in visit_miss.text, "/booked missing Book a visit CTA")
    print("OK /booked missing 404 friendly")

    from datetime import date, timedelta
    when = date.today() + timedelta(days=10)
    while when.isoweekday() > 5:
        when += timedelta(days=1)
    booked = c.post(
        "/api/p/jason-cheney/book",
        json={
            "date": when.isoformat(),
            "time": "10:00",
            "name": "Token Client",
            "email": "token.client@example.com",
        },
    )
    expect(booked.status_code == 200, f"book failed: {booked.text}")
    payload = booked.json()
    expect(payload.get("ok"), f"book not ok: {payload}")
    redirect = payload.get("redirect") or ""
    expect(redirect.startswith("/booked/"), f"redirect shape {redirect}")
    token = redirect.split("/booked/", 1)[1]
    expect(token and not token.isdigit(), f"book should return token URL, got {redirect}")
    page = c.get(redirect)
    expect(page.status_code == 200, f"{redirect} got {page.status_code}")
    expect("Token Client" in page.text, "token confirmation missing client name")
    expect(f"/booked/{token}.ics" in page.text, "token confirmation missing token .ics href")
    leak = c.get("/booked/1")
    expect(leak.status_code == 404, f"/booked/1 should not show a visit, got {leak.status_code}")
    expect("Token Client" not in leak.text, "/booked/1 leaked Token Client")
    expect("Marcus Hale" not in leak.text, "/booked/1 leaked another client")
    expect("We could not find that visit." in leak.text, "/booked/1 missing generic not-found")
    ics_ok = c.get(f"/booked/{token}.ics")
    expect(ics_ok.status_code == 200, f"token .ics got {ics_ok.status_code}")
    expect("text/calendar" in (ics_ok.headers.get("content-type") or "").lower(), "token .ics content-type")
    expect("BEGIN:VEVENT" in ics_ok.text, "token .ics missing VEVENT")
    ics_leak = c.get("/booked/1.ics")
    expect(ics_leak.status_code == 404, f"/booked/1.ics should 404, got {ics_leak.status_code}")
    expect("Token Client" not in ics_leak.text, "/booked/1.ics leaked Token Client")
    expect("Marcus Hale" not in ics_leak.text, "/booked/1.ics leaked another client")
    print("OK booked token URL + integer ids stay dark")

    css = (ROOT / "static" / "styles.css").read_text()
    expect("@media (max-width: 480px)" in css, "missing 480px mobile breakpoint")
    expect("minmax(0, 1fr)" in css, "missing minmax slot/calendar overflow guard")
    expect(".week-grid { grid-template-columns: repeat(2" in css, "missing week-grid 2-col mobile rule")
    print("OK mobile 480px CSS guards")

    print("ALL PUBLIC PATH SMOKES PASSED")


if __name__ == "__main__":
    main()
