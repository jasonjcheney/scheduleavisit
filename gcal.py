"""Two-way Google Calendar for therapists. Never logs tokens. Fail softly."""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from capacity import uget
from db import TZ, at_local, now_iso, new_public_token, parse_iso, today

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

CALENDAR_SCOPES = (
    "https://www.googleapis.com/auth/calendar.readonly "
    "https://www.googleapis.com/auth/calendar.events"
)
STATE_COOKIE = "sav_google_cal"
SYNC_EVERY = timedelta(minutes=15)
WINDOW_PAST_DAYS = 7
WINDOW_FUTURE_DAYS = 90
HTTP_TIMEOUT = 8.0


class GoogleAPIError(Exception):
    def __init__(self, status: int, hint: str = ""):
        self.status = status
        super().__init__(hint or f"google-api-{status}")


def client_id() -> str:
    return (os.environ.get("GOOGLE_CLIENT_ID") or "").strip()


def client_secret() -> str:
    return (os.environ.get("GOOGLE_CLIENT_SECRET") or "").strip()


def configured() -> bool:
    return bool(client_id() and client_secret())


def request_origin(request) -> str:
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    host = (
        (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
        or request.headers.get("host")
        or request.url.netloc
    )
    proto = forwarded or request.url.scheme
    return f"{proto}://{host}".rstrip("/")


CUSTOM_CALENDAR_HOSTS = {"scheduleavisit.com", "www.scheduleavisit.com"}
CUSTOM_CALENDAR_REDIRECT = "https://scheduleavisit.com/auth/google/calendar/callback"


def request_host(request) -> str:
    host = (
        (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
        or request.headers.get("host")
        or getattr(getattr(request, "url", None), "netloc", "")
        or ""
    )
    return host.split(":")[0].strip().lower()


def calendar_redirect_uri(request) -> str:
    """Match the live hostname so Connect does not bounce .com logins to onrender.

    scheduleavisit.com (and www) always use the custom-domain callback. Other
    hosts keep GOOGLE_REDIRECT_URI / the current request origin (usually onrender).
    """
    if request_host(request) in CUSTOM_CALENDAR_HOSTS:
        return CUSTOM_CALENDAR_REDIRECT
    explicit = (os.environ.get("GOOGLE_REDIRECT_URI") or "").strip()
    if explicit:
        trimmed = explicit.rstrip("/")
        if trimmed.endswith("/auth/google/callback") and "/auth/google/calendar/" not in trimmed:
            return trimmed[: -len("/auth/google/callback")] + "/auth/google/calendar/callback"
        return explicit
    return f"{request_origin(request)}/auth/google/calendar/callback"


def _oauth_serializer():
    from itsdangerous import URLSafeTimedSerializer

    secret = client_secret() or "sav-google-cal-unconfigured"
    return URLSafeTimedSerializer(secret, salt="sav-google-calendar-oauth")


def _token_serializer():
    from itsdangerous import URLSafeTimedSerializer

    secret = (client_secret() or "sav-google-cal-unconfigured") + "|sav-gcal-refresh"
    return URLSafeTimedSerializer(secret, salt="sav-google-calendar-refresh")


def encrypt_refresh_token(token: str) -> str:
    return _token_serializer().dumps(token)


def decrypt_refresh_token(blob: str) -> str | None:
    from itsdangerous import BadSignature

    if not blob:
        return None
    try:
        data = _token_serializer().loads(blob)
    except (BadSignature, Exception):
        return None
    return data if isinstance(data, str) and data else None


def dump_connect_state(user_id: int, next_url: str) -> str:
    nxt = (next_url or "/setup#calendar-ical").strip() or "/setup#calendar-ical"
    if not nxt.startswith("/"):
        nxt = "/setup#calendar-ical"
    return _oauth_serializer().dumps(
        {"uid": int(user_id), "next": nxt, "nonce": secrets.token_urlsafe(16)}
    )


def load_connect_state(token: str) -> dict | None:
    from itsdangerous import BadSignature, SignatureExpired

    if not token:
        return None
    try:
        data = _oauth_serializer().loads(token, max_age=600)
    except (BadSignature, SignatureExpired, Exception):
        return None
    if not isinstance(data, dict) or not data.get("uid"):
        return None
    return data


def is_connected(user) -> bool:
    return bool(uget(user, "google_refresh_token", "") or "")


def connected_email(user) -> str:
    return (uget(user, "google_connected_email", "") or "").strip()


def write_calendar_id(user) -> str:
    return (uget(user, "google_write_calendar_id", "") or "primary").strip() or "primary"


def busy_calendar_ids(user) -> list[str]:
    raw = uget(user, "google_busy_calendar_ids", None)
    if raw in (None, ""):
        return ["primary"]
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    try:
        data = json.loads(raw)
    except Exception:
        return ["primary"]
    if not isinstance(data, list):
        return ["primary"]
    return [str(x).strip() for x in data if str(x).strip()]


def note_for_google(calendar_id: str, event_id: str, summary: str) -> str:
    summary = (summary or "Busy").strip() or "Busy"
    cal = (calendar_id or "").strip() or "primary"
    eid = (event_id or "").strip()
    return f"__gcal__:{cal}:{eid}__|{summary}"


def note_gcal_ids(note: str | None) -> tuple[str, str]:
    note = note or ""
    if note.startswith("__gcal__:") and "|" in note:
        core = note[9:].split("__|", 1)[0]
        if ":" in core:
            cal, eid = core.split(":", 1)
            return cal, eid
    return "", ""


def http_request(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    json_body: Any = None,
    data: dict | None = None,
    params: dict | None = None,
    timeout: float = HTTP_TIMEOUT,
) -> dict:
    """Single HTTP seam so tests can mock Google without a live network."""
    with httpx.Client(timeout=timeout) as client:
        resp = client.request(
            method,
            url,
            headers=headers,
            json=json_body,
            data=data,
            params=params,
        )
        if resp.status_code == 204:
            return {}
        if resp.status_code >= 400:
            raise GoogleAPIError(resp.status_code, "google-http-error")
        if not resp.content:
            return {}
        try:
            parsed = resp.json()
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}


def exchange_code(code: str, redirect_uri: str) -> dict:
    token = http_request(
        "POST",
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id(),
            "client_secret": client_secret(),
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )
    return token if isinstance(token, dict) else {}


def refresh_access_token(refresh_token: str) -> dict:
    token = http_request(
        "POST",
        GOOGLE_TOKEN_URL,
        data={
            "refresh_token": refresh_token,
            "client_id": client_id(),
            "client_secret": client_secret(),
            "grant_type": "refresh_token",
        },
    )
    return token if isinstance(token, dict) else {}


def fetch_userinfo(access_token: str) -> dict:
    data = http_request(
        "GET",
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    return data if isinstance(data, dict) else {}


def calendar_api(
    method: str,
    path: str,
    access_token: str,
    *,
    json_body: Any = None,
    params: dict | None = None,
    timeout: float = HTTP_TIMEOUT,
) -> dict:
    url = path if path.startswith("http") else f"{GOOGLE_CALENDAR_API}{path}"
    return http_request(
        method,
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        json_body=json_body,
        params=params,
        timeout=timeout,
    )


def build_connect_url(request, user_id: int, next_url: str) -> tuple[str, str]:
    redirect_uri = calendar_redirect_uri(request)
    state = dump_connect_state(user_id, next_url)
    params = {
        "client_id": client_id(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": CALENDAR_SCOPES.strip(),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "false",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}", state


def access_token_for(user) -> str | None:
    blob = uget(user, "google_refresh_token", "") or ""
    refresh = decrypt_refresh_token(blob)
    if not refresh:
        return None
    try:
        token = refresh_access_token(refresh)
    except GoogleAPIError:
        return None
    except Exception:
        return None
    access = (token.get("access_token") or "").strip()
    return access or None


def _cal_can_write(item: dict) -> bool:
    role = (item.get("accessRole") or "").lower()
    return role in ("owner", "writer")


def normalize_calendar_list(items: list) -> list[dict]:
    out = []
    for item in items or []:
        cid = (item.get("id") or "").strip()
        if not cid:
            continue
        out.append({
            "id": cid,
            "summary": (item.get("summary") or cid).strip() or cid,
            "primary": bool(item.get("primary")),
            "selected": bool(item.get("selected")),
            "canWrite": _cal_can_write(item),
        })
    return out


def fetch_calendar_list(access_token: str) -> list[dict]:
    data = calendar_api("GET", "/users/me/calendarList", access_token, params={"minAccessRole": "reader"})
    return normalize_calendar_list(data.get("items") or [])


def store_connection(conn, user_id: int, refresh_token: str, email: str, calendars: list[dict]) -> None:
    busy = [c["id"] for c in calendars if c.get("selected") or c.get("primary")]
    if not busy:
        busy = [c["id"] for c in calendars[:1]] if calendars else ["primary"]
    write = "primary"
    for c in calendars:
        if c.get("primary") and c.get("canWrite"):
            write = c["id"]
            break
    else:
        for c in calendars:
            if c.get("canWrite"):
                write = c["id"]
                break
    conn.execute(
        """UPDATE users SET
             google_refresh_token=?,
             google_connected_email=?,
             google_write_calendar_id=?,
             google_busy_calendar_ids=?,
             google_synced_at=NULL
           WHERE id=?""",
        (
            encrypt_refresh_token(refresh_token),
            (email or "").strip().lower(),
            write,
            json.dumps(busy),
            user_id,
        ),
    )


def clear_connection(conn, user_id: int) -> None:
    """Forget the Google login. Imported busy that was never marked as a session goes away."""
    conn.execute(
        """UPDATE appointments SET status='cancelled', cancelled_at=?
           WHERE provider_id=? AND booked_via='google' AND status='booked'
             AND COALESCE(visit_kind,'') IN ('external','')""",
        (now_iso(), user_id),
    )
    conn.execute(
        """UPDATE users SET
             google_refresh_token='',
             google_connected_email='',
             google_synced_at=NULL
           WHERE id=?""",
        (user_id,),
    )


def save_calendar_prefs(conn, user_id: int, busy_ids: list[str], write_id: str) -> None:
    busy = [str(x).strip() for x in (busy_ids or []) if str(x).strip()]
    write = (write_id or "primary").strip() or "primary"
    conn.execute(
        """UPDATE users SET
             google_busy_calendar_ids=?,
             google_write_calendar_id=?,
             google_synced_at=NULL
           WHERE id=?""",
        (json.dumps(busy), write, user_id),
    )


def finish_connect(conn, user_id: int, code: str, redirect_uri: str) -> str | None:
    """Exchange the one-time code and store the refresh token. Returns an error string or None."""
    try:
        token = exchange_code(code, redirect_uri)
    except Exception:
        return "Google Calendar did not finish connecting. Please try again."
    refresh = (token.get("refresh_token") or "").strip()
    access = (token.get("access_token") or "").strip()
    if not refresh:
        return (
            "Google did not give us a lasting connection. "
            "Please try Connect Google Calendar again and accept the calendar permission."
        )
    email = ""
    calendars: list[dict] = []
    if access:
        try:
            info = fetch_userinfo(access)
            email = (info.get("email") or "").strip().lower()
        except Exception:
            email = ""
        try:
            calendars = fetch_calendar_list(access)
        except Exception:
            calendars = []
    store_connection(conn, user_id, refresh, email, calendars)
    return None


def _parse_google_dt(part: dict | None, fallback_tz=TZ):
    if not part:
        return None
    if part.get("date") and not part.get("dateTime"):
        try:
            from datetime import date as date_cls

            raw = part["date"]
            return date_cls.fromisoformat(raw[:10])
        except Exception:
            return None
    raw = part.get("dateTime") or ""
    if not raw:
        return None
    try:
        return parse_iso(raw)
    except Exception:
        return None


def _event_minutes(start, end, slot_start: int, workday_minutes: int) -> int:
    from datetime import date as date_cls

    if isinstance(start, date_cls) and not isinstance(start, datetime):
        if isinstance(end, date_cls) and not isinstance(end, datetime):
            days = max(1, (end - start).days)
            return days * workday_minutes
        return workday_minutes
    if isinstance(start, datetime) and isinstance(end, datetime):
        return max(1, int((end - start).total_seconds() // 60))
    return 60


def list_busy_events(access_token: str, calendar_id: str, time_min: datetime, time_max: datetime) -> list[dict]:
    events: list[dict] = []
    page = None
    for _ in range(6):
        params = {
            "timeMin": time_min.astimezone(TZ).isoformat(),
            "timeMax": time_max.astimezone(TZ).isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": "250",
            "fields": (
                "nextPageToken,items(id,summary,status,transparency,"
                "start,end,extendedProperties)"
            ),
        }
        if page:
            params["pageToken"] = page
        cal = quote(calendar_id, safe="")
        data = calendar_api("GET", f"/calendars/{cal}/events", access_token, params=params)
        for ev in data.get("items") or []:
            events.append(ev)
        page = data.get("nextPageToken")
        if not page:
            break
    return events


def _should_import_event(ev: dict, known_event_ids: set[str]) -> bool:
    if (ev.get("status") or "").lower() == "cancelled":
        return False
    if (ev.get("transparency") or "").lower() == "transparent":
        return False
    priv = ((ev.get("extendedProperties") or {}).get("private") or {})
    if priv.get("savAppointmentId"):
        return False
    eid = (ev.get("id") or "").strip()
    if eid and eid in known_event_ids:
        return False
    return True


def maybe_sync_google(conn, user, timeout: float = 2.0, force: bool = False) -> None:
    """Pull busy events into appointments. Same idea as iCal. Never raise into the page."""
    try:
        if not is_connected(user) or not configured():
            return
        synced = uget(user, "google_synced_at", None)
        if synced and not force:
            try:
                last = parse_iso(synced)
                if datetime.now(TZ) - last < SYNC_EVERY:
                    return
            except Exception:
                pass
        _sync_google(conn, user, timeout=timeout)
    except Exception:
        try:
            conn.execute("UPDATE users SET google_synced_at=? WHERE id=?", (now_iso(), user["id"]))
            conn.commit()
        except Exception:
            pass


def _sync_google(conn, user, timeout: float = 2.0) -> None:
    provider_id = user["id"]
    access = access_token_for(user)
    try:
        conn.execute("UPDATE users SET google_synced_at=? WHERE id=?", (now_iso(), provider_id))
        conn.commit()
    except Exception:
        pass
    if not access:
        return

    cals = busy_calendar_ids(user)
    if not cals:
        return

    slot_start = int(user["slot_start"] or 9)
    slot_end = int(user["slot_end"] or 17)
    workday_minutes = max(30, (slot_end - slot_start) * 60)
    window_start = today() - timedelta(days=WINDOW_PAST_DAYS)
    window_end = today() + timedelta(days=WINDOW_FUTURE_DAYS)
    time_min = at_local(window_start, "00:00")
    time_max = at_local(window_end, "00:00")
    win0 = time_min.isoformat(timespec="seconds")
    win1 = time_max.isoformat(timespec="seconds")

    known = {
        (r["google_event_id"] or "")
        for r in conn.execute(
            """SELECT google_event_id FROM appointments
               WHERE provider_id=? AND google_event_id IS NOT NULL AND google_event_id != ''
                 AND booked_via != 'google'""",
            (provider_id,),
        ).fetchall()
        if r["google_event_id"]
    }

    events: list[dict] = []
    got = False
    for cal_id in cals:
        try:
            raw = list_busy_events(access, cal_id, time_min, time_max)
        except Exception:
            continue
        got = True
        for ev in raw:
            if not _should_import_event(ev, known):
                continue
            start = _parse_google_dt(ev.get("start"))
            end = _parse_google_dt(ev.get("end"))
            if start is None:
                continue
            events.append({
                "calendar_id": cal_id,
                "event_id": (ev.get("id") or "").strip(),
                "summary": (ev.get("summary") or "Busy").strip() or "Busy",
                "start": start,
                "end": end,
            })
    if not got:
        return

    existing = conn.execute(
        """SELECT * FROM appointments
           WHERE provider_id=? AND booked_via='google' AND status='booked'
             AND start_iso>=? AND start_iso<?""",
        (provider_id, win0, win1),
    ).fetchall()
    by_uid: dict[str, Any] = {}
    by_start: dict[str, Any] = {}
    for row in existing:
        _cal, eid = note_gcal_ids(row["note"] if "note" in row.keys() else "")
        if eid:
            by_uid[f"{_cal}:{eid}"] = row
            by_uid[eid] = row
        by_start[row["start_iso"]] = row

    keep_ids = set()
    seen = set()
    for ev in events:
        key = ev["event_id"] or (str(ev["start"]), ev["summary"])
        if key in seen:
            continue
        seen.add(key)
        start = ev["start"]
        minutes = _event_minutes(start, ev.get("end"), slot_start, workday_minutes)
        if isinstance(start, datetime):
            start_dt = start.astimezone(TZ)
        else:
            start_dt = at_local(start, f"{slot_start:02d}:00")
            minutes = workday_minutes
        day = start_dt.date()
        if day < window_start or day >= window_end:
            continue
        start_iso = start_dt.isoformat(timespec="seconds")
        note = note_for_google(ev["calendar_id"], ev["event_id"], ev["summary"])
        row = None
        if ev["event_id"]:
            row = by_uid.get(f"{ev['calendar_id']}:{ev['event_id']}") or by_uid.get(ev["event_id"])
        if row is None:
            row = by_start.get(start_iso)
        if row is not None:
            conn.execute(
                """UPDATE appointments
                   SET start_iso=?, duration_minutes=?, note=?
                   WHERE id=?""",
                (start_iso, int(minutes), note, row["id"]),
            )
            keep_ids.add(row["id"])
        else:
            cur = conn.execute(
                """INSERT INTO appointments
                   (provider_id, client_id, start_iso, duration_minutes, status, booked_via,
                    created_at, visit_kind, note, public_token)
                   VALUES (?,?,?,?, 'booked', 'google', ?, 'external', ?, ?)""",
                (provider_id, None, start_iso, int(minutes), now_iso(), note, new_public_token()),
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


def slot_busy_on_google(user, start: datetime, minutes: int, timeout: float = 2.0) -> bool:
    """Live FreeBusy check for the exact slot. False if we cannot ask Google."""
    if not is_connected(user) or not configured():
        return False
    cals = busy_calendar_ids(user)
    if not cals:
        return False
    access = access_token_for(user)
    if not access:
        return False
    end = start + timedelta(minutes=int(minutes or 0))
    try:
        data = calendar_api(
            "POST",
            "/freeBusy",
            access,
            json_body={
                "timeMin": start.astimezone(TZ).isoformat(),
                "timeMax": end.astimezone(TZ).isoformat(),
                "timeZone": "America/Denver",
                "items": [{"id": cid} for cid in cals],
            },
            timeout=timeout,
        )
    except Exception:
        return False
    calendars = data.get("calendars") or {}
    for info in calendars.values():
        if not isinstance(info, dict):
            continue
        for block in info.get("busy") or []:
            if not isinstance(block, dict):
                continue
            try:
                b0 = parse_iso(block.get("start") or "")
                b1 = parse_iso(block.get("end") or "")
            except Exception:
                continue
            if b0 < end and start < b1:
                return True
    return False


def visit_title(client_name: str, visit_kind: str) -> str:
    name = (client_name or "Client").strip() or "Client"
    kind = (visit_kind or "session").strip().lower()
    if kind == "consult":
        label = "Consultation"
    elif kind == "manual":
        label = "Visit"
    else:
        label = "Session"
    return f"{name} · {label}"


def visit_description(client_name: str, visit_kind: str, minutes: int, when_label: str) -> str:
    kind = (visit_kind or "session").strip().lower()
    if kind == "consult":
        kind_words = "consultation"
    elif kind == "manual":
        kind_words = "visit"
    else:
        kind_words = "session"
    name = (client_name or "Client").strip() or "Client"
    parts = [
        "ScheduleAVisit booking",
        f"{name}",
        when_label,
        f"{int(minutes)}-minute {kind_words}",
        "Scheduling only — no clinical notes.",
    ]
    return "\n".join(p for p in parts if p)


def _should_push(appt) -> bool:
    via = (appt["booked_via"] if "booked_via" in appt.keys() else "") or ""
    return via in ("direct", "referral", "manual")


def _encode_cal(calendar_id: str) -> str:
    return quote(calendar_id or "primary", safe="")


def push_appointment(conn, appt_id: int) -> None:
    """Create or update the Google event for a SAV booking. Never raise."""
    try:
        _push_appointment(conn, appt_id)
    except Exception:
        print(f"[gcal] could not write visit {appt_id} to Google Calendar", flush=True)


def _push_appointment(conn, appt_id: int) -> None:
    appt = conn.execute(
        """SELECT a.*, c.name AS client_name
           FROM appointments a
           LEFT JOIN clients c ON c.id = a.client_id
           WHERE a.id=?""",
        (appt_id,),
    ).fetchone()
    if not appt or not _should_push(appt):
        return
    if (appt["status"] or "") != "booked":
        return
    user = conn.execute("SELECT * FROM users WHERE id=?", (appt["provider_id"],)).fetchone()
    if not user or not is_connected(user) or not configured():
        return
    access = access_token_for(user)
    if not access:
        print(f"[gcal] no access token while writing visit {appt_id}", flush=True)
        return
    start = parse_iso(appt["start_iso"])
    minutes = int(appt["duration_minutes"] or 50)
    end = start + timedelta(minutes=minutes)
    client_name = uget(appt, "client_name", "") or uget(appt, "note", "") or "Client"
    visit_kind = uget(appt, "visit_kind", "session") or "session"
    when_label = start.strftime("%A, %B %-d · %-I:%M %p") if hasattr(start, "strftime") else ""
    try:
        when_label = f"{start.strftime('%A, %B ')}{start.day} · {start.strftime('%I:%M %p').lstrip('0')}"
    except Exception:
        when_label = start.isoformat(timespec="minutes")
    location = (user["address"] if "address" in user.keys() else "") or ""
    body = {
        "summary": visit_title(client_name, visit_kind),
        "description": visit_description(client_name, visit_kind, minutes, when_label),
        "start": {"dateTime": start.isoformat(timespec="seconds"), "timeZone": "America/Denver"},
        "end": {"dateTime": end.isoformat(timespec="seconds"), "timeZone": "America/Denver"},
        "extendedProperties": {"private": {"savAppointmentId": str(appt_id)}},
    }
    if location:
        body["location"] = location
    cal_id = write_calendar_id(user)
    event_id = (uget(appt, "google_event_id", "") or "").strip()
    cal = _encode_cal(cal_id)
    if event_id:
        try:
            calendar_api("PATCH", f"/calendars/{cal}/events/{quote(event_id, safe='')}", access, json_body=body)
            return
        except GoogleAPIError as exc:
            if exc.status not in (404, 410):
                raise
            event_id = ""
    created = calendar_api("POST", f"/calendars/{cal}/events", access, json_body=body)
    new_id = (created.get("id") or "").strip()
    if new_id:
        conn.execute("UPDATE appointments SET google_event_id=? WHERE id=?", (new_id, appt_id))
        try:
            conn.commit()
        except Exception:
            pass


def delete_appointment_event(conn, appt) -> None:
    """Remove the Google event for a cancelled visit. Never raise."""
    try:
        _delete_appointment_event(conn, appt)
    except Exception:
        print("[gcal] could not remove a cancelled visit from Google Calendar", flush=True)


def _delete_appointment_event(conn, appt) -> None:
    event_id = ""
    provider_id = None
    appt_id = None
    try:
        event_id = (uget(appt, "google_event_id", "") or "").strip()
        provider_id = appt["provider_id"]
        appt_id = appt["id"]
    except Exception:
        return
    if not event_id or not provider_id:
        return
    user = conn.execute("SELECT * FROM users WHERE id=?", (provider_id,)).fetchone()
    if not user or not is_connected(user) or not configured():
        return
    access = access_token_for(user)
    if not access:
        return
    cal = _encode_cal(write_calendar_id(user))
    try:
        calendar_api("DELETE", f"/calendars/{cal}/events/{quote(event_id, safe='')}", access)
    except GoogleAPIError as exc:
        if exc.status not in (404, 410):
            raise
    if appt_id:
        conn.execute("UPDATE appointments SET google_event_id='' WHERE id=?", (appt_id,))


def public_status(user) -> dict:
    return {
        "configured": configured(),
        "connected": is_connected(user),
        "email": connected_email(user),
        "writeCalendarId": write_calendar_id(user),
        "busyCalendarIds": busy_calendar_ids(user),
    }
