#!/usr/bin/env python3
"""Google sign-in: button copy, calm missing-env callback, password login still works."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fd, DBFILE = tempfile.mkstemp(suffix="-google-auth.db")
os.close(fd)
os.environ["SAV_DB"] = DBFILE
os.environ.pop("GOOGLE_CLIENT_ID", None)
os.environ.pop("GOOGLE_CLIENT_SECRET", None)


def fail(msg: str) -> None:
    print("FAIL:", msg)
    sys.exit(1)


def expect(cond: bool, msg: str) -> None:
    if not cond:
        fail(msg)


def calm_html(resp, path: str) -> None:
    text = resp.text or ""
    expect(resp.status_code != 500, f"{path} should not 500, got {resp.status_code}")
    expect("Traceback" not in text, f"{path} leaked a stack trace")
    expect("Internal Server Error" not in text, f"{path} leaked Internal Server Error")
    expect("Google sign-in is not connected yet" in text, f"{path} missing calm message")
    expect("text/html" in (resp.headers.get("content-type") or ""), f"{path} should be HTML")


def main() -> None:
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        os.system(f"{sys.executable} -m pip install -q httpx")
        from fastapi.testclient import TestClient

    import app as appmod
    from db import init_db, connect

    with connect() as conn:
        init_db(conn)

    c = TestClient(appmod.app)

    login = c.get("/login")
    expect(login.status_code == 200, f"/login expected 200, got {login.status_code}")
    expect("Continue with Google" in login.text, "/login missing Continue with Google")
    expect('href="/auth/google' in login.text, "/login missing Google start href")
    print("OK /login contains Continue with Google")

    signup = c.get("/signup")
    expect(signup.status_code == 200, f"/signup expected 200, got {signup.status_code}")
    expect("Continue with Google" in signup.text, "/signup missing Continue with Google")
    print("OK /signup contains Continue with Google")

    start = c.get("/auth/google", follow_redirects=False)
    calm_html(start, "/auth/google")
    print("OK /auth/google without env is calm")

    cb = c.get("/auth/google/callback", follow_redirects=False)
    calm_html(cb, "/auth/google/callback")
    print("OK /auth/google/callback without env is calm")

    for ident, password, allowed in (
        ("Elena", "demo1234", ("/dashboard",)),
        ("James", "demo1234", ("/dashboard",)),
        ("Maya", "demo1234", ("/dashboard",)),
        ("jasoncheney", "123456", ("/setup", "/dashboard")),
    ):
        r = c.post("/api/auth/login", json={"email": ident, "password": password})
        expect(r.status_code == 200 and r.json().get("ok"), f"{ident} password login failed: {r.text}")
        nxt = r.json().get("redirect")
        expect(nxt in allowed, f"{ident} unexpected redirect {nxt}")
        print(f"OK password login {ident} → {nxt}")

    os.environ["GOOGLE_CLIENT_ID"] = "test-client-id.apps.googleusercontent.com"
    os.environ["GOOGLE_CLIENT_SECRET"] = "test-not-a-real-secret"
    try:
        start = c.get("/auth/google?next=/dashboard", follow_redirects=False)
        expect(start.status_code in (302, 303), f"configured start should redirect, got {start.status_code}")
        loc = start.headers.get("location") or ""
        expect("accounts.google.com" in loc, f"start should go to Google, got {loc}")
        q = parse_qs(urlparse(loc).query)
        expect(q.get("client_id") == ["test-client-id.apps.googleusercontent.com"], "start missing client_id")
        redir = (q.get("redirect_uri") or [""])[0]
        expect(redir.endswith("/auth/google/callback"), f"redirect_uri path wrong: {redir}")
        expect("test-not-a-real-secret" not in loc, "client secret leaked into authorize URL")
        expect("test-not-a-real-secret" not in (start.text or ""), "client secret leaked into start body")
        state = (q.get("state") or [""])[0]
        expect(state, "start missing state")

        async def fake_new(_code, _redirect_uri):
            return {"email": "ada.google@example.com", "name": "Ada Google", "email_verified": True}

        orig = appmod.fetch_google_profile
        appmod.fetch_google_profile = fake_new
        try:
            cb = c.get(
                f"/auth/google/callback?code=fake-code&state={state}",
                follow_redirects=False,
            )
        finally:
            appmod.fetch_google_profile = orig
        expect(cb.status_code in (302, 303), f"new Google user should redirect, got {cb.status_code} {cb.text[:200]}")
        expect((cb.headers.get("location") or "") == "/setup", f"new user should go to /setup, got {cb.headers.get('location')}")
        expect("sav_session" in cb.cookies, "new Google user missing session cookie")
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE lower(email)=?",
                ("ada.google@example.com",),
            ).fetchone()
            expect(row is not None, "new Google user was not created")
            expect(int(row["setup_complete"] or 0) != 1, "new Google user should need setup")
        print("OK mocked Google signup → /setup")

        start2 = c.get("/auth/google", follow_redirects=False)
        state2 = parse_qs(urlparse(start2.headers.get("location") or "").query).get("state", [""])[0]

        async def fake_elena(_code, _redirect_uri):
            return {
                "email": "elena@sageandstone.example",
                "name": "Elena Vasquez, LPC",
                "email_verified": True,
            }

        appmod.fetch_google_profile = fake_elena
        try:
            cb2 = c.get(
                f"/auth/google/callback?code=fake-code&state={state2}",
                follow_redirects=False,
            )
        finally:
            appmod.fetch_google_profile = orig
        expect(cb2.status_code in (302, 303), f"existing Google user should redirect, got {cb2.status_code}")
        expect((cb2.headers.get("location") or "") == "/dashboard", f"Elena should go to /dashboard, got {cb2.headers.get('location')}")
        print("OK mocked Google login for existing setup_complete user → /dashboard")
    finally:
        os.environ.pop("GOOGLE_CLIENT_ID", None)
        os.environ.pop("GOOGLE_CLIENT_SECRET", None)

    r = c.post("/api/auth/login", json={"email": "Elena", "password": "demo1234"})
    expect(r.status_code == 200 and r.json().get("ok"), f"Elena password login after Google tests failed: {r.text}")
    print("OK password login still works after Google flow")

    print("ALL GOOGLE AUTH SMOKES PASSED")


if __name__ == "__main__":
    main()
