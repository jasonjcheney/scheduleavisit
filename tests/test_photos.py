#!/usr/bin/env python3
"""Therapist photos: upload, URL import, public serve, referral JSON."""
from __future__ import annotations

import os
import sys
import tempfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fd, DBFILE = tempfile.mkstemp(suffix="-photos.db")
os.close(fd)
os.environ["SAV_DB"] = DBFILE

TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x00\x03\x00\x01\x00\x05\xfe\xd4+\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)
TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00" + (b"\x08" * 64) +
    b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    b"\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\xff\xda\x00\x08\x01\x01\x00\x00?\x00\x7f\xff\xd9"
)


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

    import photos
    from app import app
    from db import connect, init_db
    from photos import extract_image_candidates, sniff_image

    expect(sniff_image(TINY_PNG) == ".png", "png sniff")
    expect(sniff_image(TINY_JPEG) == ".jpg", "jpeg sniff")
    expect(sniff_image(b"not-an-image") is None, "junk sniff")

    html = """
    <html><head>
      <meta property="og:image" content="/cdn/elena-headshot.jpg">
    </head><body>
      <img src="/icons/logo.png" width="20" height="20" alt="logo">
      <img class="profile-photo" src="https://cdn.example.com/elena.jpg" width="400" height="400">
    </body></html>
    """
    cands = extract_image_candidates(html, "https://www.psychologytoday.com/us/therapists/elena")
    expect(any("elena-headshot.jpg" in u for u in cands), f"og:image missing: {cands}")
    expect(any("elena.jpg" in u for u in cands), f"profile photo missing: {cands}")
    print("OK image sniff + HTML extraction")

    with connect() as conn:
        init_db(conn)

    client = TestClient(app)
    login = client.post("/api/auth/login", json={"email": "jasoncheney", "password": "123456"})
    expect(login.json().get("ok"), f"jason login failed: {login.text}")

    missing = client.get("/media/avatar/jason-cheney")
    expect(missing.status_code == 404, f"no photo should 404, got {missing.status_code}")

    traversal = client.get("/media/avatar/../photos.py")
    expect(traversal.status_code in (404, 422), f"traversal slug should not serve, got {traversal.status_code}")

    bad = client.post(
        "/api/me/photo",
        files={"photo": ("notes.txt", BytesIO(b"hello notes"), "text/plain")},
    )
    expect(not bad.json().get("ok"), f"plain text upload should fail: {bad.text}")
    expect("JPEG" in (bad.json().get("error") or "") or "picture" in (bad.json().get("error") or "").lower(),
           f"plain language upload error: {bad.text}")

    huge = client.post(
        "/api/me/photo",
        files={"photo": ("big.png", BytesIO(TINY_PNG + b"x" * (3 * 1024 * 1024 + 10)), "image/png")},
    )
    expect(not huge.json().get("ok"), f"oversized upload should fail: {huge.text}")
    print("OK upload validation")

    up = client.post(
        "/api/me/photo",
        files={"photo": ("headshot.png", BytesIO(TINY_PNG), "image/png")},
    )
    body = up.json()
    expect(up.status_code == 200 and body.get("ok"), f"upload failed: {up.text}")
    expect(body.get("photoUrl") == "/media/avatar/jason-cheney", f"photoUrl {body}")

    served = client.get("/media/avatar/jason-cheney")
    expect(served.status_code == 200, f"serve photo {served.status_code}")
    expect("image/png" in (served.headers.get("content-type") or ""), f"content-type {served.headers.get('content-type')}")
    expect(served.content.startswith(b"\x89PNG"), "served bytes are not png")

    page = client.get("/p/jason-cheney")
    expect(page.status_code == 200, f"booking {page.status_code}")
    expect("/media/avatar/jason-cheney" in page.text, "booking page missing photo url")
    expect("has-photo" in page.text, "booking page missing photo avatar")

    directory = client.get("/book?q=jason")
    expect("/media/avatar/jason-cheney" in directory.text, "directory card missing photo")

    setup = client.get("/setup")
    expect("Remove photo" in setup.text, "setup missing remove control after upload")
    print("OK upload shows on public page + directory")

    orig_get = photos.http_get

    def fake_get(url, **kwargs):
        if "psychologytoday.com" in url:
            page_html = (
                "<html><head><meta property='og:image' content='https://cdn.example.com/pt.jpg'></head>"
                "<body><img src='https://cdn.example.com/tiny.gif' width='10'></body></html>"
            )
            return page_html.encode("utf-8"), "text/html", url
        if url.endswith(".jpg"):
            return TINY_JPEG, "image/jpeg", url
        raise photos.PhotoError("We could not open that page. Check the address and try again.")

    photos.http_get = fake_get
    try:
        pulled = client.post(
            "/api/me/photo/import",
            json={"url": "https://www.psychologytoday.com/us/therapists/jason-cheney"},
        )
    finally:
        photos.http_get = orig_get
    pulled_body = pulled.json()
    expect(pulled.status_code == 200 and pulled_body.get("ok"), f"import failed: {pulled.text}")
    expect(pulled_body.get("photoUrl") == "/media/avatar/jason-cheney", f"import photoUrl {pulled_body}")

    served2 = client.get("/media/avatar/jason-cheney")
    expect(served2.content.startswith(b"\xff\xd8\xff"), "imported photo should be the jpeg")

    with connect() as conn:
        row = conn.execute("SELECT profile_page_url, photo_path FROM users WHERE slug='jason-cheney'").fetchone()
        expect(row is not None and "psychologytoday.com" in (row["profile_page_url"] or ""), "profile_page_url not saved")
        expect(row["photo_path"], "photo_path empty after import")
        expect(".." not in row["photo_path"] and "/" not in row["photo_path"], f"unsafe photo_path {row['photo_path']}")
    print("OK import from pasted profile URL")

    photos.http_get = lambda *a, **k: (_ for _ in ()).throw(photos.PhotoError("We could not open that page. Check the address and try again."))
    try:
        bad_import = client.post("/api/me/photo/import", json={"url": "https://example.com/no-photo"})
    finally:
        photos.http_get = orig_get
    expect(not bad_import.json().get("ok"), f"failed import should error: {bad_import.text}")
    expect("could not open" in (bad_import.json().get("error") or "").lower(), f"plain error: {bad_import.text}")

    blocked = client.post("/api/me/photo/import", json={"url": "http://127.0.0.1/secret"})
    expect(not blocked.json().get("ok"), f"localhost import should fail: {blocked.text}")

    empty = client.post("/api/me/photo/import", json={"url": ""})
    expect(not empty.json().get("ok"), f"empty url should fail: {empty.text}")
    print("OK import failures are plain language")

    with connect() as conn:
        conn.execute(
            "UPDATE users SET photo_path=? WHERE slug='james-okonkwo-lcsw'",
            ("james.png",),
        )
        dest = photos.avatar_dir() / "james.png"
        dest.write_bytes(TINY_PNG)
        conn.commit()

    from capacity import referral_candidates, today
    from db import connect as db_connect
    with db_connect() as conn:
        elena = conn.execute("SELECT * FROM users WHERE slug='elena-vasquez-lpc'").fetchone()
        recs = referral_candidates(conn, elena, today(), None, 50, limit=4, category="general")
    james = next((r for r in recs if r.get("slug") == "james-okonkwo-lcsw"), None)
    expect(james is not None, f"james not in referrals: {recs}")
    expect(james.get("photo_url") == "/media/avatar/james-okonkwo-lcsw", f"referral photo_url {james}")

    removed = client.post("/api/me/photo/remove")
    expect(removed.json().get("ok"), f"remove failed: {removed.text}")
    gone = client.get("/media/avatar/jason-cheney")
    expect(gone.status_code == 404, f"removed photo still served: {gone.status_code}")
    page2 = client.get("/p/jason-cheney")
    expect("/media/avatar/jason-cheney" not in page2.text, "booking still shows removed photo")
    print("OK remove photo + referral JSON photo URL")

    anon = TestClient(app)
    sneak = anon.post(
        "/api/me/photo",
        files={"photo": ("x.png", BytesIO(TINY_PNG), "image/png")},
    )
    expect(sneak.status_code == 401, f"anon upload should 401, got {sneak.status_code}")
    print("ALL PHOTO SMOKES PASSED")


if __name__ == "__main__":
    main()
