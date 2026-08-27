#!/usr/bin/env python3
"""Specialty referrals: exact match, General fallback, max 5, category on book."""
from __future__ import annotations

import os
import tempfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["SAV_DB"] = tmp.name

    import sys

    sys.path.insert(0, str(ROOT))
    for mod in list(sys.modules):
        if mod in {"db", "capacity", "app", "icalutil"} or mod.startswith("db.") or mod.startswith("capacity"):
            del sys.modules[mod]

    import db
    import capacity
    from fastapi.testclient import TestClient
    import app as appmod

    conn = db.connect()
    db.init_db(conn)
    conn.execute("DELETE FROM network_links")
    conn.execute("DELETE FROM appointments")
    conn.execute("DELETE FROM clients")
    conn.execute("DELETE FROM users")
    conn.commit()

    pw = db.hash_password("test1234")
    created = db.now_iso()

    def add_user(email, name, slug, target=25):
        cur = conn.execute(
            """INSERT INTO users (
                 email, password_hash, name, credentials, title, specialty, about, clinic, address,
                 slug, weekly_target_hours, buffer_hours, workdays, slot_start, slot_end, lunch,
                 session_minutes, timezone, created_at, username, setup_complete, consult_enabled
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                email, pw, name, "", "", "Counseling", "About", "Clinic", "Boulder, CO",
                slug, target, 0, "[1,2,3,4,5]", 9, 17, 12, 50, "America/Denver", created,
                slug.replace("-", "")[:32], 1, 0,
            ),
        )
        return int(cur.lastrowid)

    def pack_full(uid, when, weeks=5):
        for w in range(0, weeks):
            ws = db.start_of_week(when) + timedelta(days=7 * w)
            for i, (wd, hh) in enumerate([(1, "09:00"), (1, "10:00"), (2, "09:00"), (3, "09:00"), (4, "09:00")]):
                cid = db.add_client(conn, uid, f"Fill {uid}-w{w}-{i}")
                db.add_appt(conn, uid, cid, db.date_on_weekday(ws, wd), hh, 50)

    origin = add_user("origin@ex.com", "Origin Therapist", "origin-therapist", target=1)
    general_peer = add_user("gen@ex.com", "General Peer", "general-peer", target=25)
    anxiety_peer = add_user("anx@ex.com", "Anxiety Peer", "anxiety-peer", target=25)
    hop = add_user("hop@ex.com", "Hop Therapist", "hop-therapist", target=25)

    err = db.add_recommendation(conn, origin, general_peer, "general")
    assert err is None, err
    err = db.add_recommendation(conn, origin, anxiety_peer, "anxiety")
    assert err is None, err
    # Multi-hop only through the General peer, not a direct origin link.
    db.add_link(conn, general_peer, hop)
    conn.commit()

    when = db.today() + timedelta(days=1)
    while when.isoweekday() > 5:
        when += timedelta(days=1)
    pack_full(origin, when)
    conn.execute("UPDATE users SET weekly_target_hours=1, buffer_hours=0 WHERE id=?", (origin,))
    conn.commit()

    uo = conn.execute("SELECT * FROM users WHERE id=?", (origin,)).fetchone()

    exact = capacity.referral_candidates(conn, uo, when, "15:00", 50, category="anxiety")
    assert exact, "expected anxiety match"
    assert exact[0]["slug"] == "anxiety-peer", exact[0]
    assert exact[0]["matchPhase"] == 0, exact[0]

    fallback = capacity.referral_candidates(conn, uo, when, "15:00", 50, category="grief")
    assert fallback, "expected general fallback"
    assert fallback[0]["slug"] == "general-peer", fallback[0]
    assert fallback[0]["matchPhase"] == 1, fallback[0]

    # Pack direct peers so matching falls through to multi-hop.
    pack_full(general_peer, when)
    pack_full(anxiety_peer, when)
    conn.execute("UPDATE users SET weekly_target_hours=1, buffer_hours=0 WHERE id IN (?,?)", (general_peer, anxiety_peer))
    conn.commit()
    uo = conn.execute("SELECT * FROM users WHERE id=?", (origin,)).fetchone()
    hopped = capacity.referral_candidates(conn, uo, when, "15:00", 50, category="couples")
    assert hopped, hopped
    assert hopped[0]["slug"] == "hop-therapist", hopped[0]
    assert hopped[0]["hops"] == 2, hopped[0]
    assert hopped[0]["matchPhase"] == 2, hopped[0]
    print("ok exact / general fallback / multi-hop")

    extras = []
    for i in range(5):
        extras.append(add_user(f"e{i}@ex.com", f"Extra {i}", f"extra-{i}", target=25))
    cap_user = add_user("cap@ex.com", "Cap Therapist", "cap-therapist", target=25)
    for i, pid in enumerate(extras):
        msg = db.add_recommendation(conn, cap_user, pid, "general" if i else "anxiety")
        assert msg is None, msg
    sixth = add_user("sixth@ex.com", "Sixth Peer", "sixth-peer", target=25)
    msg = db.add_recommendation(conn, cap_user, sixth, "grief")
    assert msg and "up to 5" in msg.lower(), msg
    count = db.outgoing_recommend_count(conn, cap_user)
    assert count == 5, count
    conn.commit()
    print("ok max 5 enforced")

    client = TestClient(appmod.app)
    r = client.post(
        "/api/p/origin-therapist/book",
        json={
            "date": when.isoformat(),
            "time": "15:00",
            "name": "Sam Overflow",
            "email": "sam.overflow@example.com",
            "visitKind": "session",
            "category": "couples",
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("full") is True, data
    assert data.get("category") == "couples", data
    assert data["recommendation"]["peerSlug"] == "hop-therapist", data
    print("ok client category sent with book")

    login = client.post("/api/auth/login", json={"email": "cap@ex.com", "password": "test1234"})
    assert login.status_code == 200 and login.json().get("ok"), login.text
    r6 = client.post(
        "/api/me/network/recommend",
        json={"peerSlug": "sixth-peer", "category": "grief"},
    )
    assert r6.status_code == 400, r6.text
    assert "up to 5" in (r6.json().get("error") or "").lower(), r6.text
    print("ok max 5 API")

    conn.close()
    os.unlink(tmp.name)

    tmp2 = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp2.close()
    os.environ["SAV_DB"] = tmp2.name
    for mod in list(sys.modules):
        if mod in {"db", "capacity", "app", "icalutil"} or mod.startswith("db.") or mod.startswith("capacity"):
            del sys.modules[mod]
    import db as db2
    conn2 = db2.connect()
    db2.init_db(conn2)
    elena = conn2.execute("SELECT id FROM users WHERE slug=?", ("elena-vasquez-lpc",)).fetchone()
    james = conn2.execute("SELECT id FROM users WHERE slug=?", ("james-okonkwo-lcsw",)).fetchone()
    maya = conn2.execute("SELECT id FROM users WHERE slug=?", ("maya-chen-lmft",)).fetchone()
    assert elena and james and maya
    jcat = conn2.execute(
        "SELECT category FROM network_links WHERE user_id=? AND peer_id=?",
        (elena["id"], james["id"]),
    ).fetchone()
    mcat = conn2.execute(
        "SELECT category FROM network_links WHERE user_id=? AND peer_id=?",
        (elena["id"], maya["id"]),
    ).fetchone()
    assert jcat["category"] == "general", jcat
    assert mcat["category"] == "couples", mcat
    names = conn2.execute(
        "SELECT username FROM users WHERE username IN ('elena','james','maya','jasoncheney')"
    ).fetchall()
    assert len(names) == 4, names
    conn2.close()
    os.unlink(tmp2.name)
    print("ok Elena category seed + demo logins")


if __name__ == "__main__":
    main()
