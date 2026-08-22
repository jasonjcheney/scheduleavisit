#!/usr/bin/env python3
"""Multi-hop referral: A full → B full → C has room."""
from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["SAV_DB"] = tmp.name

    import importlib
    import sys

    sys.path.insert(0, str(ROOT))
    # Force reimport against temp db
    for mod in list(sys.modules):
        if mod in {"db", "capacity", "app", "icalutil"} or mod.startswith("db.") or mod.startswith("capacity"):
            del sys.modules[mod]

    import db
    import capacity
    from fastapi.testclient import TestClient
    import app as appmod

    conn = db.connect()
    db.init_db(conn)
    # Wipe seeded users for a clean A-B-C graph (keep schema)
    conn.execute("DELETE FROM network_links")
    conn.execute("DELETE FROM appointments")
    conn.execute("DELETE FROM clients")
    conn.execute("DELETE FROM users")
    conn.commit()

    pw = db.hash_password("test1234")
    created = db.now_iso()

    def add_user(email, name, slug, target=10):
        cur = conn.execute(
            """INSERT INTO users (
                 email, password_hash, name, credentials, title, specialty, about, clinic, address,
                 slug, weekly_target_hours, buffer_hours, workdays, slot_start, slot_end, lunch,
                 session_minutes, timezone, created_at, username, setup_complete, consult_enabled
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                email, pw, name, "", "", "Counseling", "About", "Clinic", "Boulder, CO",
                slug, target, 0, "[1,2,3,4,5]", 9, 17, 12, 50, "America/Denver", created,
                slug.split("-")[0], 1, 0,
            ),
        )
        return int(cur.lastrowid)

    a = add_user("a@ex.com", "Alpha Therapist", "alpha-therapist", target=1)
    b = add_user("b@ex.com", "Beta Therapist", "beta-therapist", target=1)
    c = add_user("c@ex.com", "Gamma Therapist", "gamma-therapist", target=25)
    db.add_link(conn, a, b)
    db.add_link(conn, b, c)
    # Pick a future weekday, then pack Alpha + Beta that same week so they are full.
    when = db.today() + timedelta(days=1)
    while when.isoweekday() > 5:
        when += timedelta(days=1)
    # Pack Alpha + Beta for several weeks so next_open_slot (21-day look-ahead) finds nothing.
    for uid in (a, b):
        for w in range(0, 5):
            ws = db.start_of_week(when) + timedelta(days=7 * w)
            for i, (wd, hh) in enumerate([(1, "09:00"), (1, "10:00"), (2, "09:00"), (3, "09:00"), (4, "09:00")]):
                cid = db.add_client(conn, uid, f"Fill {uid}-w{w}-{i}")
                db.add_appt(conn, uid, cid, db.date_on_weekday(ws, wd), hh, 50)
    conn.commit()

    ua = conn.execute("SELECT * FROM users WHERE id=?", (a,)).fetchone()

    recs = capacity.referral_candidates(conn, ua, when, "15:00", 50)
    assert recs, "expected at least one referral"
    assert recs[0]["slug"] == "gamma-therapist", recs[0]
    assert recs[0]["hops"] == 2, recs[0]
    assert capacity.network_reachable(conn, a, c)
    assert not capacity.network_reachable(conn, a, a)

    # HTTP path: booking Alpha when full should recommend Gamma
    client = TestClient(appmod.app)
    r = client.post(
        "/api/p/alpha-therapist/book",
        json={
            "date": when.isoformat(),
            "time": "15:00",
            "name": "Sam Overflow",
            "email": "sam.overflow@example.com",
            "visitKind": "session",
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("full") is True, data
    assert data["recommendation"]["peerSlug"] == "gamma-therapist", data
    assert data["recommendation"]["hops"] == 2, data

    # Book the multi-hop referral
    rec = data["recommendation"]
    r2 = client.post(
        "/api/p/alpha-therapist/book-referral",
        json={
            "peerSlug": rec["peerSlug"],
            "date": rec["date"],
            "time": rec["time"],
            "name": "Sam Overflow",
            "email": "sam.overflow@example.com",
        },
    )
    assert r2.status_code == 200, r2.text
    assert r2.json().get("ok") is True, r2.text
    print("ok multihop referral")
    conn.close()
    os.unlink(tmp.name)


if __name__ == "__main__":
    main()
