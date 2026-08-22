"""Fetch and parse an iCalendar feed into busy blocks. Stdlib only."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from db import TZ, at_local, now_iso, parse_iso, today

SYNC_EVERY = timedelta(minutes=15)
MAX_BYTES = 1_500_000


def _unfold(text: str) -> list[str]:
    raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines: list[str] = []
    for line in raw:
        if line.startswith(" ") or line.startswith("\t"):
            if lines:
                lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def _unescape(val: str) -> str:
    return (
        val.replace("\\\\", "\\")
        .replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
    )


def _parse_dt(prop: str, value: str) -> datetime | date | None:
    params = {}
    if ";" in prop:
        for part in prop.split(";")[1:]:
            if "=" in part:
                k, v = part.split("=", 1)
                params[k.upper()] = v
    value = value.strip()
    tz = TZ
    tzid = params.get("TZID")
    if tzid:
        try:
            tz = ZoneInfo(tzid.strip('"'))
        except Exception:
            tz = TZ
    if params.get("VALUE", "").upper() == "DATE" or (len(value) == 8 and "T" not in value):
        try:
            return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
        except Exception:
            return None
    zulu = value.endswith("Z")
    core = value[:-1] if zulu else value
    core = core.replace("-", "")
    try:
        if len(core) >= 15:
            dt = datetime.strptime(core[:15], "%Y%m%dT%H%M%S")
        else:
            dt = datetime.strptime(core[:13], "%Y%m%dT%H%M")
    except Exception:
        return None
    if zulu:
        dt = dt.replace(tzinfo=timezone.utc).astimezone(TZ)
    else:
        dt = dt.replace(tzinfo=tz).astimezone(TZ)
    return dt


def _parse_duration(val: str) -> int | None:
    """Return minutes from an ICS DURATION like PT1H30M or P1D."""
    if not val:
        return None
    val = val.strip().upper()
    sign = -1 if val.startswith("-") else 1
    if val[0] in "+-":
        val = val[1:]
    if not val.startswith("P"):
        return None
    val = val[1:]
    days = hours = minutes = seconds = 0
    num = ""
    in_time = False
    try:
        for ch in val:
            if ch.isdigit():
                num += ch
            elif ch == "T":
                in_time = True
                num = ""
            elif ch == "W" and num:
                days += int(num) * 7
                num = ""
            elif ch == "D" and num:
                days += int(num)
                num = ""
            elif ch == "H" and num:
                hours += int(num)
                num = ""
            elif ch == "M" and num:
                minutes += int(num)
                num = ""
            elif ch == "S" and num:
                seconds += int(num)
                num = ""
        total = days * 24 * 60 + hours * 60 + minutes + (seconds + 59) // 60
        return sign * total if total else None
    except Exception:
        return None


def parse_ics(text: str) -> list[dict]:
    events: list[dict] = []
    current: dict | None = None
    for line in _unfold(text):
        if not line:
            continue
        upper = line.upper()
        if upper == "BEGIN:VEVENT":
            current = {}
            continue
        if upper == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        prop, val = line.split(":", 1)
        name = prop.split(";", 1)[0].upper()
        current[name] = val
        current[f"{name}_PROP"] = prop
    out = []
    for ev in events:
        start_raw = ev.get("DTSTART")
        if not start_raw:
            continue
        start = _parse_dt(ev.get("DTSTART_PROP", "DTSTART"), start_raw)
        if start is None:
            continue
        end = None
        if ev.get("DTEND"):
            end = _parse_dt(ev.get("DTEND_PROP", "DTEND"), ev["DTEND"])
        minutes = None
        if end is not None:
            if isinstance(start, date) and not isinstance(start, datetime):
                if isinstance(end, date) and not isinstance(end, datetime):
                    minutes = max(1, (end - start).days) * 24 * 60
                else:
                    minutes = 24 * 60
            elif isinstance(end, datetime) and isinstance(start, datetime):
                minutes = max(1, int((end - start).total_seconds() // 60))
        if minutes is None:
            dur = _parse_duration(ev.get("DURATION") or "")
            minutes = dur if dur and dur > 0 else 60
        uid = _unescape(ev.get("UID") or "").strip()
        summary = _unescape(ev.get("SUMMARY") or "Busy").strip() or "Busy"
        out.append({"uid": uid, "summary": summary, "start": start, "minutes": int(minutes)})
    return out


def fetch_ics(url: str, timeout: float = 2.0) -> str | None:
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    try:
        req = Request(url, headers={"User-Agent": "ScheduleAVisit/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raw = raw[:MAX_BYTES]
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return None


def note_for(uid: str, summary: str) -> str:
    summary = (summary or "Busy").strip() or "Busy"
    uid = (uid or "").strip()
    if uid:
        return f"__uid__:{uid}__|{summary}"
    return summary


def note_summary(note: str | None) -> str:
    note = note or ""
    if note.startswith("__uid__:") and "|" in note:
        return note.split("|", 1)[1] or "Busy"
    return note or "Busy"


def note_uid(note: str | None) -> str:
    note = note or ""
    if note.startswith("__uid__:") and "|" in note:
        return note[8:].split("__|", 1)[0]
    return ""


def maybe_sync_ical(conn, user, timeout: float = 2.0) -> None:
    """Re-fetch at most every 15 minutes. Fail softly. Never raise into the page."""
    try:
        keys = set(user.keys())
    except Exception:
        keys = set()
    if "ical_url" not in keys:
        return
    url = (user["ical_url"] or "").strip()
    if not url:
        return
    synced = user["ical_synced_at"] if "ical_synced_at" in keys else None
    if synced:
        try:
            last = parse_iso(synced)
            if datetime.now(TZ) - last < SYNC_EVERY:
                return
        except Exception:
            pass
    _sync_ical(conn, user, url, timeout)


def _sync_ical(conn, user, url: str, timeout: float) -> None:
    provider_id = user["id"]
    text = fetch_ics(url, timeout=timeout)
    # Stamp the attempt so a bad URL does not stall every page load.
    try:
        conn.execute("UPDATE users SET ical_synced_at=? WHERE id=?", (now_iso(), provider_id))
        conn.commit()
    except Exception:
        pass
    if not text:
        return
    try:
        events = parse_ics(text)
    except Exception:
        return

    slot_start = int(user["slot_start"] or 9)
    slot_end = int(user["slot_end"] or 17)
    workday_minutes = max(30, (slot_end - slot_start) * 60)

    window_start = today() - timedelta(days=7)
    window_end = today() + timedelta(days=90)
    win0 = at_local(window_start, "00:00").isoformat(timespec="seconds")
    win1 = at_local(window_end, "00:00").isoformat(timespec="seconds")

    existing = conn.execute(
        """SELECT * FROM appointments
           WHERE provider_id=? AND booked_via='ical' AND status='booked'
             AND start_iso>=? AND start_iso<?""",
        (provider_id, win0, win1),
    ).fetchall()
    by_uid = {}
    by_start = {}
    for row in existing:
        uid = note_uid(row["note"] if "note" in row.keys() else "")
        if uid:
            by_uid[uid] = row
        by_start[row["start_iso"]] = row

    keep_ids = set()
    for ev in events:
        start = ev["start"]
        minutes = ev["minutes"]
        if isinstance(start, datetime):
            start_dt = start.astimezone(TZ)
        else:
            # All-day: occupy the clinic workday so it blocks slots and counts hours.
            start_dt = at_local(start, f"{slot_start:02d}:00")
            minutes = workday_minutes
        day = start_dt.date()
        if day < window_start or day >= window_end:
            continue
        start_iso = start_dt.isoformat(timespec="seconds")
        note = note_for(ev["uid"], ev["summary"])
        row = by_uid.get(ev["uid"]) if ev["uid"] else None
        if row is None:
            row = by_start.get(start_iso)
        if row is not None:
            conn.execute(
                """UPDATE appointments
                   SET start_iso=?, duration_minutes=?, note=?, visit_kind='external'
                   WHERE id=?""",
                (start_iso, int(minutes), note, row["id"]),
            )
            keep_ids.add(row["id"])
        else:
            cur = conn.execute(
                """INSERT INTO appointments
                   (provider_id, client_id, start_iso, duration_minutes, status, booked_via,
                    created_at, visit_kind, note)
                   VALUES (?,?,?,?, 'booked', 'ical', ?, 'external', ?)""",
                (provider_id, None, start_iso, int(minutes), now_iso(), note),
            )
            keep_ids.add(int(cur.lastrowid))
    for row in existing:
        if row["id"] not in keep_ids:
            conn.execute(
                "UPDATE appointments SET status='cancelled', cancelled_at=? WHERE id=?",
                (now_iso(), row["id"]),
            )
    try:
        conn.commit()
    except Exception:
        pass


def _ics_escape(val: str) -> str:
    return (
        (val or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _ics_dt_local(dt: datetime) -> str:
    """Format as floating local / TZID America/Denver wall time (YYYYMMDDTHHMMSS)."""
    local = dt.astimezone(TZ) if dt.tzinfo else dt.replace(tzinfo=TZ)
    return local.strftime("%Y%m%dT%H%M%S")


def build_appointment_ics(
    *,
    appt_id: int,
    summary: str,
    start: datetime,
    duration_minutes: int,
    description: str = "",
    location: str = "",
) -> str:
    """Minimal VCALENDAR/VEVENT for a booked visit. Stdlib only."""
    start_local = start.astimezone(TZ) if start.tzinfo else start.replace(tzinfo=TZ)
    end_local = start_local + timedelta(minutes=int(duration_minutes or 0))
    stamp = datetime.now(TZ).strftime("%Y%m%dT%H%M%S")
    uid = f"sav-{appt_id}@scheduleavisit.com"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ScheduleAVisit//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"DTSTART;TZID=America/Denver:{_ics_dt_local(start_local)}",
        f"DTEND;TZID=America/Denver:{_ics_dt_local(end_local)}",
        f"SUMMARY:{_ics_escape(summary)}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{_ics_escape(description)}")
    if location:
        lines.append(f"LOCATION:{_ics_escape(location)}")
    lines.extend(["END:VEVENT", "END:VCALENDAR", ""])
    return "\r\n".join(lines)
