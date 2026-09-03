"""Server-side capacity engine. Never trust the client."""
from __future__ import annotations

import json
from collections import deque
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote

from db import (
    TZ,
    at_local,
    category_label,
    date_on_weekday,
    normalize_category,
    parse_iso,
    start_of_week,
    today,
)

WEEKLY_HORIZON = 8
MILES = {
    frozenset({"elena-vasquez-lpc", "james-okonkwo-lcsw"}): 4,
    frozenset({"elena-vasquez-lpc", "maya-chen-lmft"}): 2,
    frozenset({"james-okonkwo-lcsw", "maya-chen-lmft"}): 5,
}


def first_name(name: str) -> str:
    return name.replace(",", " ").split()[0] if name else ""


def initials(name: str) -> str:
    parts = [p for p in name.replace(",", " ").split() if p and p.upper() not in {"LPC", "LCSW", "LMFT", "MD", "PHD"}]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def avatar_class(slug: str) -> str:
    slug = (slug or "").lower()
    if "jason" in slug:
        return "av-jason"
    if "elena" in slug:
        return "av-elena"
    if "james" in slug:
        return "av-james"
    if "maya" in slug:
        return "av-maya"
    if "priya" in slug:
        return "av-priya"
    return "av-elena"


def uget(user, key, default=None):
    try:
        val = user[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if val is None else val


def miles_between(a_slug: str, b_slug: str) -> int:
    return MILES.get(frozenset({a_slug, b_slug}), 6)


def user_workdays(user) -> list[int]:
    try:
        days = json.loads(user["workdays"] or "[1,2,3,4,5]")
        return [int(d) for d in days]
    except Exception:
        return [1, 2, 3, 4, 5]


def hide_setup_placeholder(value: str | None) -> str:
    """Blank copy that is clearly a setup hint, not a real public bio."""
    text = (value or "").strip()
    if not text:
        return ""
    low = text.lower()
    if low in {"my practice"}:
        return ""
    if "edit this in setup" in low or "rewrite in setup" in low:
        return ""
    return text


def public_address(user) -> str:
    """Blank seeded / misleading location until the provider saves real copy."""
    raw = (user["address"] or "").strip()
    if not raw:
        return ""
    slug = (user["slug"] or "").strip()
    # Jason's seed used Boulder; do not invent Grand Junction until he approves copy.
    if slug == "jason-cheney" and raw.lower() in {"boulder, co", "boulder"}:
        return ""
    return raw


def public_provider(user, from_slug: str | None = None) -> dict[str, Any]:
    slug = user["slug"]
    return {
        "id": user["id"],
        "name": user["name"],
        "first": first_name(user["name"]),
        "credentials": user["credentials"],
        "title": hide_setup_placeholder(user["title"]),
        "specialty": hide_setup_placeholder(user["specialty"]),
        "about": hide_setup_placeholder(user["about"]),
        "clinic": hide_setup_placeholder(user["clinic"]),
        "address": public_address(user),
        "slug": slug,
        "session_minutes": int(uget(user, "session_minutes", 50) or 50),
        "consult_minutes": int(uget(user, "consult_minutes", 15) or 15),
        "consult_enabled": int(uget(user, "consult_enabled", 1) or 0),
        "portal_url": uget(user, "portal_url", "") or "",
        "portal_kind": uget(user, "portal_kind", "none") or "none",
        "initials": initials(user["name"]),
        "avatar": avatar_class(slug),
        "miles": miles_between(from_slug, slug) if from_slug else 0,
    }


def infer_pattern(dates: list[date]) -> str:
    dates = sorted(set(dates))
    if len(dates) < 2:
        return "occasional"
    gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
    avg = sum(gaps) / len(gaps)
    if avg <= 9.5:
        return "weekly"
    if avg <= 18:
        return "biweekly"
    return "occasional"


def infer_label(pattern: str) -> str:
    return {"weekly": "Weekly", "biweekly": "Biweekly"}.get(pattern, "Occasional")


def status_for(used: float, target: float) -> str:
    if target <= 0:
        return "full"
    pct = used / target
    if pct >= 1:
        return "full"
    if pct >= 0.85:
        return "nearly"
    return "room"


def status_label(s: str) -> str:
    return {"full": "Full", "nearly": "Nearly full"}.get(s, "Room")


def hours_label(n: float) -> str:
    rounded = round(n * 10) / 10
    s = str(int(rounded)) if rounded % 1 == 0 else f"{rounded:.1f}"
    return f"{s} hr" if rounded == 1 else f"{s} hrs"


def client_visit_dates(conn, client_id: int) -> list[date]:
    rows = conn.execute(
        "SELECT start_iso FROM appointments WHERE client_id=? AND status='booked' ORDER BY start_iso",
        (client_id,),
    ).fetchall()
    return [parse_iso(r["start_iso"]).date() for r in rows]


def typical_minutes(conn, client_id: int, fallback: int = 50) -> int:
    row = conn.execute(
        """SELECT duration_minutes, COUNT(*) AS c FROM appointments
           WHERE client_id=? AND status='booked'
           GROUP BY duration_minutes ORDER BY c DESC LIMIT 1""",
        (client_id,),
    ).fetchone()
    return int(row["duration_minutes"]) if row else fallback


def bookings_for_week(conn, provider_id: int, week_start: date) -> list:
    start = at_local(week_start, "00:00").isoformat(timespec="seconds")
    end = at_local(week_start + timedelta(days=7), "00:00").isoformat(timespec="seconds")
    return conn.execute(
        """SELECT * FROM appointments
           WHERE provider_id=? AND status='booked' AND start_iso>=? AND start_iso<?
           ORDER BY start_iso""",
        (provider_id, start, end),
    ).fetchall()


def counts_toward_cap(row) -> bool:
    """Imported busy (visit_kind=external) occupies the slot but does not use the weekly cap."""
    return (uget(row, "visit_kind", "session") or "session") != "external"


def booked_hours(conn, provider_id: int, week_start: date) -> float:
    return sum(
        r["duration_minutes"] / 60.0
        for r in bookings_for_week(conn, provider_id, week_start)
        if counts_toward_cap(r)
    )


def inferred_hours_for_week(conn, client_id: int, week_start: date) -> float:
    dates = client_visit_dates(conn, client_id)
    pattern = infer_pattern(dates)
    if pattern == "occasional" or not dates:
        return 0.0
    minutes = typical_minutes(conn, client_id)
    by_week: dict[date, int] = {}
    for d in dates:
        ws = start_of_week(d)
        by_week[ws] = by_week.get(ws, 0) + 1
    counts = list(by_week.values())
    avg_count = sum(counts) / len(counts)
    if pattern == "weekly":
        sessions = max(1, round(avg_count))
    else:
        last = max(dates)
        weeks_since = round((week_start - start_of_week(last)).days / 7)
        sessions = 1 if weeks_since % 2 == 0 else 0
    return sessions * minutes / 60.0


def projected_hours(conn, user, week_start: date, extra_minutes: float = 0) -> dict[str, float]:
    provider_id = user["id"]
    booked = bookings_for_week(conn, provider_id, week_start)
    scheduled = sum(r["duration_minutes"] / 60.0 for r in booked if counts_toward_cap(r))
    covered = {r["client_id"] for r in booked if r["client_id"] and counts_toward_cap(r)}
    inferred = 0.0
    clients = conn.execute(
        "SELECT id FROM clients WHERE provider_id=? AND dismissed_at IS NULL",
        (provider_id,),
    ).fetchall()
    for c in clients:
        if c["id"] in covered:
            continue
        inferred += inferred_hours_for_week(conn, c["id"], week_start)
    buffer = float(user["buffer_hours"])
    extra = extra_minutes / 60.0
    total = scheduled + inferred + buffer + extra
    return {
        "scheduled": scheduled,
        "inferred": inferred,
        "buffer": buffer,
        "extra": extra,
        "projected": total,
        "target": float(user["weekly_target_hours"]),
    }


def can_accept_visit(conn, user, when: date, minutes: int) -> bool:
    info = projected_hours(conn, user, start_of_week(when), minutes)
    return info["projected"] <= info["target"] + 0.001


def can_accept_recurring(conn, user, minutes: int) -> tuple[bool, list[dict]]:
    weeks = []
    ok = True
    start = start_of_week(today())
    for i in range(WEEKLY_HORIZON):
        ws = start + timedelta(days=7 * i)
        base = projected_hours(conn, user, ws, 0)
        with_new = base["projected"] + minutes / 60.0
        over = with_new > base["target"] + 0.001
        if over:
            ok = False
        weeks.append({
            "start": ws.isoformat(),
            "label": "This week" if i == 0 else ws.strftime("%b %-d").replace(" 0", " "),
            "base": round(base["projected"] * 10) / 10,
            "with_new": round(with_new * 10) / 10,
            "over": over,
            "tight": (not over) and base["projected"] / base["target"] >= 0.85 if base["target"] else False,
        })
    return ok, weeks


def remaining_hours(conn, user, week_start: date | None = None) -> float:
    ws = week_start or start_of_week(today())
    info = projected_hours(conn, user, ws, 0)
    return max(0.0, info["target"] - info["projected"])


def slot_times(user) -> list[str]:
    times = []
    for h in range(int(user["slot_start"]), int(user["slot_end"])):
        if h == int(user["lunch"]):
            continue
        times.append(f"{h:02d}:00")
    return times


def intervals_overlap(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> bool:
    return a0 < b1 and a1 > b0


def is_taken(conn, provider_id: int, start: datetime, minutes: int, ignore_id: int | None = None) -> bool:
    end = start + timedelta(minutes=minutes)
    day = start.date()
    day_start = at_local(day, "00:00").isoformat(timespec="seconds")
    day_end = at_local(day + timedelta(days=1), "00:00").isoformat(timespec="seconds")
    rows = conn.execute(
        """SELECT id, start_iso, duration_minutes FROM appointments
           WHERE provider_id=? AND status='booked' AND start_iso>=? AND start_iso<?""",
        (provider_id, day_start, day_end),
    ).fetchall()
    for r in rows:
        if ignore_id and r["id"] == ignore_id:
            continue
        b0 = parse_iso(r["start_iso"])
        b1 = b0 + timedelta(minutes=r["duration_minutes"])
        if intervals_overlap(start, end, b0, b1):
            return True
    return False


def availability_for(conn, user, day: date, minutes: int | None = None) -> dict[str, Any]:
    minutes = int(minutes or user["session_minutes"] or 50)
    workdays = user_workdays(user)
    week_info = projected_hours(conn, user, start_of_week(day), 0)
    week_has_room = week_info["projected"] + minutes / 60.0 <= week_info["target"] + 0.001
    slots = []
    now = datetime.now(TZ)
    if day.isoweekday() in workdays:
        for t in slot_times(user):
            start = at_local(day, t)
            taken = is_taken(conn, user["id"], start, minutes)
            past = start <= now
            slots.append({
                "time": t,
                "booked": taken,
                "open": (not taken) and (not past),
                "past": past,
            })
    return {
        "date": day.isoformat(),
        "sessionMinutes": minutes,
        "minutes": minutes,
        "weekHasRoom": week_has_room,
        "weekProjected": round(week_info["projected"] * 10) / 10,
        "weekTarget": week_info["target"],
        "slots": slots,
    }


def next_open_slot(conn, user, from_date: date, prefer_time: str | None, minutes: int) -> dict | None:
    workdays = user_workdays(user)
    now = datetime.now(TZ)
    for i in range(21):
        d = from_date + timedelta(days=i)
        if d.isoweekday() not in workdays:
            continue
        if not can_accept_visit(conn, user, d, minutes):
            continue
        times = slot_times(user)
        order = times
        if prefer_time and prefer_time in times:
            order = [prefer_time] + [t for t in times if t != prefer_time]
        for t in order:
            start = at_local(d, t)
            if start <= now:
                continue
            if not is_taken(conn, user["id"], start, minutes):
                return {"date": d.isoformat(), "time": t, "start": start}
    return None


def peers_of(conn, user_id: int) -> list:
    return conn.execute(
        """SELECT u.*, COALESCE(n.category, 'general') AS referral_category
           FROM users u
           JOIN network_links n ON n.peer_id = u.id
           WHERE n.user_id=?
           ORDER BY u.name""",
        (user_id,),
    ).fetchall()


def link_category(conn, user_id: int, peer_id: int) -> str | None:
    row = conn.execute(
        "SELECT category FROM network_links WHERE user_id=? AND peer_id=?",
        (user_id, peer_id),
    ).fetchone()
    if not row:
        return None
    try:
        raw = row["category"]
    except (KeyError, IndexError, TypeError):
        raw = None
    return normalize_category(raw)


def network_reachable(conn, origin_id: int, target_id: int, max_hops: int = 8) -> bool:
    """True if target is reachable through trusted peer links (BFS)."""
    if origin_id == target_id:
        return False
    seen = {origin_id}
    q = deque([(origin_id, 0)])
    while q:
        uid, hops = q.popleft()
        if hops >= max_hops:
            continue
        for p in peers_of(conn, uid):
            pid = p["id"]
            if pid in seen:
                continue
            if pid == target_id:
                return True
            seen.add(pid)
            q.append((pid, hops + 1))
    return False


def referral_candidates(
    conn,
    from_user,
    when: date,
    prefer_time: str | None,
    minutes: int,
    max_hops: int = 8,
    limit: int = 8,
    category: str | None = None,
) -> list[dict]:
    """Walk the trust network until someone has room.

    Prefer a direct peer tagged with the client category. If none have room,
    fall back to that therapist's General slot, then multi-hop among remaining
    peers with room.
    """
    origin_id = from_user["id"]
    origin_first = first_name(from_user["name"])
    wanted = normalize_category(category)
    # Prefer demo individual counseling slightly among equal-hop ties.
    rank = {"james-okonkwo-lcsw": 3, "maya-chen-lmft": 1, "jason-cheney": 2}

    seen = {origin_id}
    # (provider_row, hops, via_first_name) — via is the immediate linker on the path
    q = deque()
    for p in peers_of(conn, origin_id):
        if p["id"] not in seen:
            q.append((p, 1, origin_first))

    out: list[dict] = []
    while q:
        p, hops, via_name = q.popleft()
        if p["id"] in seen:
            continue
        seen.add(p["id"])

        slot = next_open_slot(conn, p, when, prefer_time, minutes)
        if slot:
            rem = remaining_hours(conn, p, start_of_week(when))
            miles = miles_between(from_user["slug"], p["slug"])
            pub = public_provider(p, from_user["slug"])
            link_cat = link_category(conn, origin_id, p["id"]) if hops == 1 else None
            if hops == 1 and link_cat == wanted:
                phase = 0
            elif hops == 1 and link_cat == "general":
                phase = 0 if wanted == "general" else 1
            else:
                phase = 2
            shown_cat = link_cat or wanted
            out.append({
                **pub,
                "date": slot["date"],
                "time": slot["time"],
                "remaining": round(rem * 10) / 10,
                "miles": miles,
                "hops": hops,
                "viaName": via_name if hops > 1 else origin_first,
                "recommendedBy": origin_first,
                "rideUrl": f"/ride?address={quote(p['address'] or '')}",
                "category": shown_cat,
                "categoryLabel": category_label(shown_cat),
                "linkCategory": link_cat,
                "matchPhase": phase,
                "wantedCategory": wanted,
            })

        if hops < max_hops:
            peer_first = first_name(p["name"])
            for nxt in peers_of(conn, p["id"]):
                if nxt["id"] not in seen:
                    q.append((nxt, hops + 1, peer_first))

    out.sort(
        key=lambda x: (
            x.get("matchPhase", 2),
            x["hops"],
            -rank.get(x["slug"], 0),
            x["miles"],
            -x["remaining"],
        )
    )
    return out[:limit]


def format_time(hhmm: str) -> str:
    h, m = [int(x) for x in hhmm.split(":")]
    ampm = "pm" if h >= 12 else "am"
    hr = ((h + 11) % 12) + 1
    return f"{hr} {ampm}" if m == 0 else f"{hr}:{m:02d} {ampm}"


def format_long(d: date) -> str:
    return d.strftime("%A, %B ") + str(d.day)


def format_short(d: date) -> str:
    return d.strftime("%b ") + str(d.day)
