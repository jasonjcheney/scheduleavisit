"""ScheduleAVisit.com — FastAPI app. Run: uvicorn app:app --host 0.0.0.0 --port 8080"""
from __future__ import annotations

import json
import os
import re
import secrets
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from db import (
    TZ,
    CATEGORY_CHOICES,
    MAX_RECOMMENDATIONS,
    add_link,
    add_recommendation,
    at_local,
    category_label,
    connect,
    hash_password,
    init_db,
    normalize_category,
    now_iso,
    notify,
    new_public_token,
    outgoing_recommend_count,
    parse_iso,
    set_link_category,
    start_of_week,
    today,
    verify_password,
)
from icalutil import build_appointment_ics, maybe_sync_ical, note_summary
from reminders import (
    TICK_ENV,
    TICK_HEADER,
    after_book,
    after_reschedule,
    cancel_pending,
    cancel_pending_for_client,
    send_due,
)
from capacity import (
    WEEKLY_HORIZON,
    availability_for,
    avatar_class,
    booked_hours,
    uget,
    can_accept_recurring,
    can_accept_visit,
    client_visit_dates,
    first_name,
    format_long,
    format_short,
    format_time,
    hours_label,
    infer_label,
    infer_pattern,
    initials,
    is_taken,
    miles_between,
    network_reachable,
    peers_of,
    projected_hours,
    public_provider,
    referral_candidates,
    remaining_hours,
    status_for,
    status_label,
    typical_minutes,
    user_workdays,
)

ROOT = Path(__file__).resolve().parent
COOKIE = "sav_session"
SESSION_DAYS = 14
LOGIN_ALIASES = {
    "elena": "elena@sageandstone.example",
    "james": "james@northcreek.example",
    "maya": "maya@riverview.example",
    "jasoncheney": "jasoncheney@scheduleavisit.example",
    "jason": "jasoncheney@scheduleavisit.example",
}
USERNAME_RE = re.compile(r"^[a-z0-9_]{3,32}$")

app = FastAPI(title="ScheduleAVisit", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))
templates.env.filters["timefmt"] = format_time
templates.env.filters["longdate"] = lambda s: format_long(parse_iso(s).date() if isinstance(s, str) else s)
templates.env.filters["shortdate"] = lambda s: format_short(parse_iso(s).date() if isinstance(s, str) else s)


@app.on_event("startup")
def _startup():
    conn = connect()
    try:
        init_db(conn)
    finally:
        conn.close()


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row(r):
    return dict(r) if r is not None else None


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "provider"


def unique_slug(conn, name: str) -> str:
    base = slugify(name)
    slug = base
    n = 2
    while conn.execute("SELECT 1 FROM users WHERE slug=?", (slug,)).fetchone():
        slug = f"{base}-{n}"
        n += 1
    return slug


def user_by_id(conn, user_id: int):
    return conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def user_by_slug(conn, slug: str):
    return conn.execute("SELECT * FROM users WHERE slug=?", (slug,)).fetchone()


def user_by_email(conn, email: str):
    return conn.execute("SELECT * FROM users WHERE lower(email)=?", (email.lower().strip(),)).fetchone()


def current_user(request: Request):
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    with db() as conn:
        r = conn.execute(
            """SELECT u.* FROM users u
               JOIN sessions s ON s.user_id = u.id
               WHERE s.token=? AND s.expires_at > ?""",
            (token, now_iso()),
        ).fetchone()
        return row(r)


def set_session(conn, response, user_id: int):
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(TZ) + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
    conn.execute("INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)", (token, user_id, expires))
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=SESSION_DAYS * 86400, path="/")


def clear_session(request: Request, response):
    token = request.cookies.get(COOKIE)
    if token:
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    response.delete_cookie(COOKIE, path="/")


def json_err(msg: str, status: int = 400, **extra):
    return JSONResponse({"ok": False, "error": msg, **extra}, status_code=status)


def require_user(request: Request):
    user = current_user(request)
    if not user:
        return None
    return user


def tpl(request: Request, name: str, status_code: int = 200, **ctx):
    ctx.setdefault("user", current_user(request))
    ctx.setdefault("google_ready", google_configured())
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def find_login_user(conn, identifier: str):
    ident = (identifier or "").strip()
    if not ident:
        return None
    alias = LOGIN_ALIASES.get(ident.lower())
    if alias:
        ident = alias
    u = user_by_email(conn, ident)
    if u:
        return u
    u = conn.execute(
        "SELECT * FROM users WHERE lower(COALESCE(username,'')) = ?",
        (ident.lower(),),
    ).fetchone()
    if u:
        return u
    return conn.execute(
        """SELECT * FROM users
           WHERE lower(substr(name, 1, instr(name||' ', ' ') - 1)) = ?""",
        (ident.lower(),),
    ).fetchone()


def needs_setup(user) -> bool:
    return int(uget(user, "setup_complete", 0) or 0) != 1


def post_auth_redirect(user, nxt: str | None) -> str:
    nxt = (nxt or "/dashboard").strip() or "/dashboard"
    if not nxt.startswith("/"):
        nxt = "/dashboard"
    if needs_setup(user) and not nxt.startswith("/invite") and not nxt.startswith("/setup"):
        return "/setup"
    return nxt


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_STATE_COOKIE = "sav_google_oauth"
GOOGLE_SCOPES = "openid email profile"


def google_configured() -> bool:
    return bool(
        (os.environ.get("GOOGLE_CLIENT_ID") or "").strip()
        and (os.environ.get("GOOGLE_CLIENT_SECRET") or "").strip()
    )


def _google_client_id() -> str:
    return (os.environ.get("GOOGLE_CLIENT_ID") or "").strip()


def _google_client_secret() -> str:
    return (os.environ.get("GOOGLE_CLIENT_SECRET") or "").strip()


def request_origin(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    host = (
        (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
        or request.headers.get("host")
        or request.url.netloc
    )
    proto = forwarded or request.url.scheme
    return f"{proto}://{host}".rstrip("/")


def google_redirect_uri(request: Request) -> str:
    return f"{request_origin(request)}/auth/google/callback"


def _oauth_serializer():
    from itsdangerous import URLSafeTimedSerializer

    secret = _google_client_secret() or "sav-google-oauth-unconfigured"
    return URLSafeTimedSerializer(secret, salt="sav-google-oauth")


def dump_oauth_state(next_url: str) -> str:
    nxt = (next_url or "/dashboard").strip() or "/dashboard"
    if not nxt.startswith("/"):
        nxt = "/dashboard"
    return _oauth_serializer().dumps({"next": nxt, "nonce": secrets.token_urlsafe(16)})


def load_oauth_state(token: str) -> dict | None:
    from itsdangerous import BadSignature, SignatureExpired

    if not token:
        return None
    try:
        data = _oauth_serializer().loads(token, max_age=600)
    except (BadSignature, SignatureExpired, Exception):
        return None
    if not isinstance(data, dict):
        return None
    return data


def unique_username(conn, email: str, name: str) -> str:
    local = (email or "").split("@")[0]
    base = re.sub(r"[^a-z0-9_]", "", local.lower())
    if len(base) < 3:
        base = re.sub(r"[^a-z0-9_]", "", (slugify(name) or "provider").replace("-", "_"))
    if len(base) < 3:
        base = "provider"
    base = base[:32]
    if not USERNAME_RE.match(base):
        base = "provider"
    uname = base
    n = 2
    while conn.execute(
        "SELECT 1 FROM users WHERE lower(COALESCE(username,''))=?", (uname,)
    ).fetchone():
        suffix = f"_{n}"
        uname = (base[: 32 - len(suffix)] + suffix)
        n += 1
    return uname


def find_or_create_google_user(conn, email: str, name: str):
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return None, False
    existing = user_by_email(conn, email)
    if existing:
        return existing, False
    display = (name or "").strip() or email.split("@")[0]
    if len(display) < 2:
        display = email.split("@")[0]
    username = unique_username(conn, email, display)
    slug = unique_slug(conn, display)
    cur = conn.execute(
        """INSERT INTO users (
             email, password_hash, name, credentials, title, specialty, about, clinic, address,
             slug, weekly_target_hours, buffer_hours, workdays, slot_start, slot_end, lunch,
             session_minutes, timezone, created_at, username, setup_complete, consult_minutes,
             consult_enabled, portal_kind, portal_url
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            email,
            hash_password(secrets.token_urlsafe(32)),
            display,
            "",
            "",
            "",
            "",
            "",
            "",
            slug,
            25,
            3,
            json.dumps([1, 2, 3, 4, 5]),
            9,
            17,
            12,
            50,
            "America/Denver",
            now_iso(),
            username,
            0,
            15,
            1,
            "none",
            "",
        ),
    )
    uid = int(cur.lastrowid)
    notify(
        conn,
        uid,
        "welcome",
        "Welcome to ScheduleAVisit",
        "Finish setup so clients see the right hours and your portal link.",
    )
    return user_by_id(conn, uid), True


def oauth_notice(request: Request, message: str, status_code: int = 200, heading: str = "Not just yet."):
    return tpl(
        request,
        "oauth_notice.html",
        status_code=status_code,
        heading=heading,
        message=message,
    )


def build_google_authorize_url(request: Request, nxt: str) -> tuple[str, str]:
    from authlib.integrations.httpx_client import AsyncOAuth2Client

    redirect_uri = google_redirect_uri(request)
    client = AsyncOAuth2Client(
        _google_client_id(),
        scope=GOOGLE_SCOPES,
        redirect_uri=redirect_uri,
    )
    state = dump_oauth_state(nxt)
    url, _ = client.create_authorization_url(
        GOOGLE_AUTH_URL,
        state=state,
        access_type="online",
        include_granted_scopes="false",
    )
    return url, state


async def fetch_google_profile(code: str, redirect_uri: str) -> dict:
    """Exchange a one-time code for email/name. Never logs tokens."""
    from authlib.integrations.httpx_client import AsyncOAuth2Client

    client = AsyncOAuth2Client(_google_client_id(), _google_client_secret(), redirect_uri=redirect_uri)
    try:
        token = await client.fetch_token(
            GOOGLE_TOKEN_URL,
            code=code,
            grant_type="authorization_code",
        )
        if isinstance(token, dict):
            token.pop("refresh_token", None)
        resp = await client.get(GOOGLE_USERINFO_URL)
        resp.raise_for_status()
        data = resp.json()
    finally:
        await client.aclose()
    email = (data.get("email") or "").strip().lower()
    name = (data.get("name") or "").strip()
    if not name:
        given = (data.get("given_name") or "").strip()
        family = (data.get("family_name") or "").strip()
        name = f"{given} {family}".strip()
    return {
        "email": email,
        "name": name,
        "email_verified": data.get("email_verified"),
    }


def normalize_hhmm(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    parts = raw.split(":")
    try:
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
    except (TypeError, ValueError):
        return ""
    if h < 0 or h > 23 or m < 0 or m > 59:
        return ""
    return f"{h:02d}:{m:02d}"


def client_is_returning(conn, provider_id: int, email: str = "") -> bool:
    if not email or "@" not in email:
        return False
    r = conn.execute(
        """SELECT 1 FROM appointments a
           JOIN clients c ON c.id = a.client_id
           WHERE a.provider_id=? AND a.status='booked' AND lower(c.email)=?
           LIMIT 1""",
        (provider_id, email.lower().strip()),
    ).fetchone()
    return bool(r)


def resolve_visit(conn, u, requested_kind: str, email: str) -> tuple[str, int, bool]:
    session_min = int(uget(u, "session_minutes", 50) or 50)
    consult_min = int(uget(u, "consult_minutes", 15) or 15)
    consult_on = int(uget(u, "consult_enabled", 1) or 0) == 1
    returning = client_is_returning(conn, u["id"], email)
    kind = (requested_kind or "session").strip().lower()
    if returning or not consult_on or kind != "consult":
        return "session", session_min, returning
    return "consult", consult_min, returning


def block_label(a) -> str:
    name = a["client_name"] if "client_name" in a.keys() else None
    if name:
        return name
    note = a["note"] if "note" in a.keys() else ""
    return note_summary(note) or "Busy"


def get_or_create_client(conn, provider_id: int, name: str, email: str = "", phone: str = "") -> int:
    email = (email or "").strip()
    name = (name or "").strip()
    phone = (phone or "").strip()
    existing = None
    if email:
        existing = conn.execute(
            "SELECT id FROM clients WHERE provider_id=? AND lower(email)=? AND dismissed_at IS NULL",
            (provider_id, email.lower()),
        ).fetchone()
    else:
        existing = conn.execute(
            "SELECT id FROM clients WHERE provider_id=? AND lower(name)=? AND dismissed_at IS NULL",
            (provider_id, name.lower()),
        ).fetchone()
    if existing:
        if phone:
            conn.execute("UPDATE clients SET phone=? WHERE id=?", (phone, existing["id"]))
        return existing["id"]
    cur = conn.execute(
        "INSERT INTO clients (provider_id, name, email, phone, created_at) VALUES (?,?,?,?,?)",
        (provider_id, name, email, phone, now_iso()),
    )
    return int(cur.lastrowid)


def create_appointment(conn, provider_id, client_id, start, minutes, via="direct",
                       referred_from=None, visit_kind="session", note=""):
    token = new_public_token()
    cur = conn.execute(
        """INSERT INTO appointments
           (provider_id, client_id, start_iso, duration_minutes, status, booked_via,
            referred_from_provider_id, created_at, visit_kind, note, public_token)
           VALUES (?,?,?,?, 'booked', ?, ?, ?, ?, ?, ?)""",
        (provider_id, client_id, start.isoformat(timespec="seconds"), minutes, via,
         referred_from, now_iso(), visit_kind or "session", note or "", token),
    )
    return int(cur.lastrowid)


def confirm_url(conn, appt_id: int) -> str:
    row = conn.execute("SELECT public_token FROM appointments WHERE id=?", (appt_id,)).fetchone()
    token = (row["public_token"] if row else None) or ""
    if not token:
        token = new_public_token()
        conn.execute("UPDATE appointments SET public_token=? WHERE id=?", (token, appt_id))
    return f"/booked/{token}"


def appointment_by_public_token(conn, token: str):
    token = (token or "").strip()
    if not token or token.isdigit():
        return None
    return conn.execute("SELECT * FROM appointments WHERE public_token=?", (token,)).fetchone()


def rec_payload(item: dict, minutes: int) -> dict:
    d = date.fromisoformat(item["date"])
    return {
        "peerSlug": item["slug"],
        "name": item["name"],
        "first": item["first"],
        "clinic": item["clinic"],
        "address": item["address"],
        "miles": item["miles"],
        "date": item["date"],
        "time": item["time"],
        "displayWhen": f"{format_long(d)} · {format_time(item['time'])}",
        "minutes": minutes,
        "recommendedBy": item["recommendedBy"],
        "hops": item.get("hops", 1),
        "viaName": item.get("viaName") or item["recommendedBy"],
        "rideUrl": item["rideUrl"],
        "initials": item["initials"],
        "avatar": item["avatar"],
        "specialty": item["specialty"],
        "category": item.get("category") or item.get("wantedCategory") or "general",
        "categoryLabel": item.get("categoryLabel") or category_label(item.get("category") or "general"),
        "matchPhase": item.get("matchPhase", 2),
    }


DIRECTORY_SEARCH_FIELDS = ("name", "credentials", "slug", "clinic", "address", "title", "specialty")


def _norm_search(s) -> str:
    return (s or "").strip().lower()


def provider_matches_query(user, q: str) -> bool:
    """Case-insensitive substring match on public provider fields. No geocoding."""
    needle = _norm_search(q)
    if not needle:
        return True
    for field in DIRECTORY_SEARCH_FIELDS:
        try:
            val = user[field]
        except (KeyError, IndexError, TypeError):
            val = ""
        if needle in _norm_search(str(val) if val is not None else ""):
            return True
    return False


def place_line(clinic, address) -> str:
    clinic = (clinic or "").strip()
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    city = ", ".join(parts[-2:]) if len(parts) >= 2 else (address or "").strip()
    return " · ".join(b for b in (clinic, city) if b)


def directory_card(u) -> dict:
    p = public_provider(u)
    p["place"] = place_line(p.get("clinic"), p.get("address"))
    p["search_text"] = " ".join(
        str(p.get(k) or "")
        for k in ("name", "credentials", "slug", "clinic", "address", "title", "specialty", "place")
    )
    return p


# ───────── Public pages ─────────

@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return tpl(request, "landing.html")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    user = current_user(request)
    if user:
        return RedirectResponse(post_auth_redirect(user, request.query_params.get("next")), status_code=303)
    return tpl(request, "login.html", next=request.query_params.get("next") or "/dashboard")


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    user = current_user(request)
    if user:
        nxt = request.query_params.get("next")
        return RedirectResponse(post_auth_redirect(user, nxt), status_code=303)
    return tpl(
        request,
        "signup.html",
        prefill_email=request.query_params.get("email") or "",
        next=request.query_params.get("next") or "/setup",
    )


@app.get("/auth/google")
async def google_start(request: Request):
    nxt = request.query_params.get("next") or "/dashboard"
    if not google_configured():
        return oauth_notice(request, "Google sign-in is not connected yet")
    try:
        url, state = build_google_authorize_url(request, nxt)
    except Exception:
        return oauth_notice(request, "Google sign-in is not connected yet")
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(
        GOOGLE_STATE_COOKIE,
        state,
        httponly=True,
        samesite="lax",
        max_age=600,
        path="/",
    )
    return resp


@app.get("/auth/google/callback")
async def google_callback(request: Request):
    if not google_configured():
        return oauth_notice(request, "Google sign-in is not connected yet")
    err = request.query_params.get("error")
    if err == "access_denied":
        return oauth_notice(
            request,
            "Google sign-in was cancelled. You can still use email and a password.",
            heading="Cancelled.",
        )
    if err:
        return oauth_notice(request, "Google sign-in is not connected yet")
    code = (request.query_params.get("code") or "").strip()
    state = (request.query_params.get("state") or "").strip()
    cookie_state = request.cookies.get(GOOGLE_STATE_COOKIE) or ""
    payload = load_oauth_state(state)
    if not payload or (cookie_state and cookie_state != state):
        return oauth_notice(
            request,
            "Google sign-in did not finish. You can still use email and a password.",
            heading="Could not finish.",
        )
    if not code:
        return oauth_notice(
            request,
            "Google sign-in did not finish. You can still use email and a password.",
            heading="Could not finish.",
        )
    try:
        profile = await fetch_google_profile(code, google_redirect_uri(request))
    except Exception:
        return oauth_notice(
            request,
            "Google sign-in did not finish. You can still use email and a password.",
            heading="Could not finish.",
        )
    email = (profile.get("email") or "").strip().lower()
    if not email or profile.get("email_verified") is False:
        return oauth_notice(
            request,
            "Google did not share a verified email. You can still use email and a password.",
            heading="Could not finish.",
        )
    with db() as conn:
        user, _created = find_or_create_google_user(conn, email, profile.get("name") or "")
        if not user:
            return oauth_notice(
                request,
                "Google sign-in did not finish. You can still use email and a password.",
                heading="Could not finish.",
            )
        nxt = post_auth_redirect(user, payload.get("next"))
        resp = RedirectResponse(nxt, status_code=303)
        set_session(conn, resp, user["id"])
        resp.delete_cookie(GOOGLE_STATE_COOKIE, path="/")
        return resp


@app.get("/book", response_class=HTMLResponse)
def directory(request: Request, q: str = ""):
    q = (q or "").strip()
    with db() as conn:
        users = conn.execute("SELECT * FROM users ORDER BY name").fetchall()
        cards = [directory_card(u) for u in users if provider_matches_query(u, q)]
    return tpl(request, "directory.html", cards=cards, q=q, searched=bool(q))


@app.get("/p/{slug}", response_class=HTMLResponse)
def booking_page(request: Request, slug: str):
    with db() as conn:
        u = user_by_slug(conn, slug)
        if not u:
            return tpl(request, "notfound.html", message="We could not find that calendar.")
        provider = public_provider(u)
    resp = tpl(request, "booking.html", provider=provider, categories=CATEGORY_CHOICES)
    return resp


@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request):
    return tpl(request, "privacy.html")


@app.get("/terms", response_class=HTMLResponse)
def terms_page(request: Request):
    return tpl(request, "terms.html")


@app.get("/booked/{token}.ics")
@app.get("/api/booked/{token}/ics")
def booked_ics(token: str):
    """Download a minimal .ics so clients can add the visit to Apple/Google/Outlook."""
    with db() as conn:
        a = appointment_by_public_token(conn, token)
        if not a or a["status"] != "booked":
            return Response("Visit not found", status_code=404, media_type="text/plain")
        provider = user_by_id(conn, a["provider_id"])
        client = conn.execute("SELECT * FROM clients WHERE id=?", (a["client_id"],)).fetchone() if a["client_id"] else None
        start = parse_iso(a["start_iso"])
        visit_kind = uget(a, "visit_kind", "session") or "session"
        kind_label = "Consultation" if visit_kind == "consult" else "Visit"
        provider_name = provider["name"] if provider else "your provider"
        client_name = client["name"] if client else "Guest"
        minutes = int(a["duration_minutes"] or 50)
        location = (provider["address"] if provider else "") or ""
        clinic = (provider["clinic"] if provider else "") or ""
        summary = f"{kind_label} with {provider_name}"
        desc_parts = [
            f"{kind_label} for {client_name}",
            f"{minutes}-minute {visit_kind}",
        ]
        if clinic:
            desc_parts.append(clinic)
        if location:
            desc_parts.append(location)
        body = build_appointment_ics(
            appt_id=int(a["id"]),
            summary=summary,
            start=start,
            duration_minutes=minutes,
            description=" · ".join(desc_parts),
            location=location,
        )
    headers = {
        "Content-Disposition": f'attachment; filename="visit-{token}.ics"',
    }
    return Response(content=body, media_type="text/calendar; charset=utf-8", headers=headers)


@app.get("/booked/{token}", response_class=HTMLResponse)
def booked_page(request: Request, token: str):
    with db() as conn:
        a = appointment_by_public_token(conn, token)
        if not a or a["status"] != "booked":
            return tpl(request, "notfound.html", status_code=404, message="We could not find that visit.")
        provider = user_by_id(conn, a["provider_id"])
        client = conn.execute("SELECT * FROM clients WHERE id=?", (a["client_id"],)).fetchone() if a["client_id"] else None
        referred = user_by_id(conn, a["referred_from_provider_id"]) if a["referred_from_provider_id"] else None
        start = parse_iso(a["start_iso"])
        first_visit = False
        if a["client_id"]:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM appointments WHERE client_id=? AND status='booked'",
                (a["client_id"],),
            ).fetchone()["c"]
            first_visit = count == 1
        portal_url = (uget(provider, "portal_url", "") or "").strip()
        portal_kind = (uget(provider, "portal_kind", "none") or "none").strip().lower()
        visit_kind = uget(a, "visit_kind", "session") or "session"
        ctx = {
            "appointment": row(a),
            "confirm_token": a["public_token"],
            "provider": public_provider(provider),
            "client_name": client["name"] if client else "Guest",
            "client_email": client["email"] if client else "",
            "when_long": format_long(start.date()),
            "when_time": format_time(start.strftime("%H:%M")),
            "referred": public_provider(referred) if referred else None,
            "show_portal": bool(first_visit and portal_url),
            "portal_url": portal_url,
            "portal_kind": portal_kind,
            "visit_kind": visit_kind,
            "first_visit": first_visit,
        }
    return tpl(request, "booked.html", **ctx)


@app.get("/ride", response_class=HTMLResponse)
def ride_page(request: Request):
    address = request.query_params.get("address") or "Boulder, CO"
    maps = "https://www.google.com/maps/dir/?api=1&destination=" + quote(address)
    uber = "https://m.uber.com/ul/?action=setPickup&pickup=my_location&dropoff[formatted_address]=" + quote(address)
    lyft = "https://lyft.com/ride?destination[address]=" + quote(address)
    return tpl(request, "ride.html", address=address, maps=maps, uber=uber, lyft=lyft)


@app.get("/invite/{token}", response_class=HTMLResponse)
def invite_page(request: Request, token: str):
    with db() as conn:
        inv = conn.execute("SELECT * FROM network_invites WHERE token=?", (token,)).fetchone()
        if not inv:
            return tpl(request, "invite.html", state="missing", invite=None)
        if inv["status"] == "accepted":
            return tpl(request, "invite.html", state="already", invite=row(inv))
        from_user = user_by_id(conn, inv["from_user_id"])
        user = current_user(request)
        if not user:
            q = urlencode({"email": inv["to_email"], "next": f"/invite/{token}"})
            return RedirectResponse(f"/signup?{q}", status_code=303)
        if user["email"].lower() != inv["to_email"].lower():
            return tpl(
                request, "invite.html", state="wrong_email",
                invite=row(inv), from_name=from_user["name"], expected=inv["to_email"],
            )
        inv_cat = normalize_category(inv["category"] if "category" in inv.keys() else "general")
        add_link(conn, inv["from_user_id"], user["id"], category=inv_cat)
        set_link_category(conn, inv["from_user_id"], user["id"], inv_cat)
        conn.execute(
            "UPDATE network_invites SET status='accepted', to_user_id=? WHERE id=?",
            (user["id"], inv["id"]),
        )
        notify(
            conn, inv["from_user_id"], "network",
            f"{first_name(user['name'])} joined your network",
            f"{user['name']} accepted your invite. Their open hours will show when you are full.",
        )
        notify(
            conn, user["id"], "network",
            f"You joined {first_name(from_user['name'])}'s network",
            f"When {first_name(from_user['name'])} is at cap, clients can be offered a time with you.",
        )
        return tpl(request, "invite.html", state="accepted", invite=row(inv), from_name=from_user["name"])


@app.get("/setup", response_class=HTMLResponse)
@app.get("/dashboard/setup", response_class=HTMLResponse)
def setup_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login?next=/setup", status_code=303)
    with db() as conn:
        u = user_by_id(conn, user["id"])
    workdays = user_workdays(u)
    return tpl(
        request, "setup.html",
        me=row(u),
        first=first_name(u["name"]),
        workdays=workdays,
        editing=not needs_setup(u),
    )


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login?next=/dashboard", status_code=303)
    if needs_setup(user):
        return RedirectResponse("/setup", status_code=303)
    with db() as conn:
        u = user_by_id(conn, user["id"])
        maybe_sync_ical(conn, u, timeout=2.0)
        u = user_by_id(conn, user["id"])
        week = start_of_week(today())
        info = projected_hours(conn, u, week, 0)
        st = status_for(info["projected"], info["target"])
        minutes = int(u["session_minutes"] or 50)
        rec_ok, weeks = can_accept_recurring(conn, u, minutes)
        overflow = sum(1 for w in weeks if w["over"])
        clients = conn.execute(
            "SELECT * FROM clients WHERE provider_id=? ORDER BY dismissed_at IS NOT NULL, name",
            (u["id"],),
        ).fetchall()
        client_rows = []
        dismissed = []
        for c in clients:
            dates = client_visit_dates(conn, c["id"])
            pattern = infer_pattern(dates)
            last = max(dates) if dates else None
            nxt = None
            upcoming = conn.execute(
                """SELECT start_iso FROM appointments
                   WHERE client_id=? AND status='booked' AND start_iso>=?
                   ORDER BY start_iso LIMIT 1""",
                (c["id"], now_iso()),
            ).fetchone()
            if upcoming:
                nxt = parse_iso(upcoming["start_iso"]).date()
            rec = {
                "id": c["id"],
                "name": c["name"],
                "email": c["email"],
                "dismissed": bool(c["dismissed_at"]),
                "pattern": pattern,
                "label": infer_label(pattern),
                "minutes": typical_minutes(conn, c["id"], minutes),
                "last": format_short(last) if last else None,
                "next": format_short(nxt) if nxt else None,
            }
            if c["dismissed_at"]:
                dismissed.append(rec)
            else:
                client_rows.append(rec)

        appts = conn.execute(
            """SELECT a.*, c.name AS client_name
               FROM appointments a
               LEFT JOIN clients c ON c.id = a.client_id
               WHERE a.provider_id=? AND a.status='booked' AND a.start_iso>=?
               ORDER BY a.start_iso LIMIT 40""",
            (u["id"], now_iso()),
        ).fetchall()
        upcoming = []
        for a in appts:
            start = parse_iso(a["start_iso"])
            upcoming.append({
                "id": a["id"],
                "client_name": a["client_name"] or note_summary(uget(a, "note", "")) or "Reserved",
                "when": f"{format_long(start.date())} · {format_time(start.strftime('%H:%M'))}",
                "date": start.date().isoformat(),
                "time": start.strftime("%H:%M"),
                "minutes": a["duration_minutes"],
                "via": a["booked_via"],
                "visit_kind": uget(a, "visit_kind", "session") or "session",
                "referred": bool(a["referred_from_provider_id"]),
            })

        peer_rows = []
        for p in peers_of(conn, u["id"]):
            rem = remaining_hours(conn, p, week)
            pinfo = projected_hours(conn, p, week, 0)
            pst = status_for(pinfo["projected"], pinfo["target"])
            fill = min(100, max(0, (pinfo["projected"] / pinfo["target"]) * 100 if pinfo["target"] else 100))
            pcat = normalize_category(uget(p, "referral_category", "general"))
            peer_rows.append({
                **public_provider(p, u["slug"]),
                "remaining_label": hours_label(rem) + " left",
                "status": pst,
                "fill": round(fill, 1),
                "category": pcat,
                "category_label": category_label(pcat),
            })

        notes = conn.execute(
            "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
            (u["id"],),
        ).fetchall()
        waitlist = conn.execute(
            """SELECT id, name, email, requested_minutes, created_at FROM waitlist_requests
               WHERE provider_id=? AND dismissed_at IS NULL
               ORDER BY created_at DESC LIMIT 30""",
            (u["id"],),
        ).fetchall()
        waitlist_rows = []
        for w in waitlist:
            wr = row(w)
            try:
                asked = parse_iso(w["created_at"])
                wr["asked_label"] = "asked " + format_short(asked.date())
            except Exception:
                wr["asked_label"] = ""
            waitlist_rows.append(wr)
        note_rows = [row(n) | {"unread": not n["read_at"]} for n in notes]
        unread_count = sum(1 for n in note_rows if n["unread"])

        host = request.base_url
        booking_url = f"{host}p/{u['slug']}"
        base = str(host).rstrip("/")
        pending = conn.execute(
            """SELECT id, to_email, token, created_at FROM network_invites
               WHERE from_user_id=? AND status='pending' ORDER BY id DESC""",
            (u["id"],),
        ).fetchall()
        pending_invites = []
        for inv in pending:
            ir = row(inv)
            try:
                sent = parse_iso(inv["created_at"])
                ir["sent_label"] = "sent " + format_short(sent.date())
            except Exception:
                ir["sent_label"] = ""
            ir["url"] = f"{base}/invite/{inv['token']}"
            pending_invites.append(ir)

        ctx = {
            "me": row(u),
            "first": first_name(u["name"]),
            "initials": initials(u["name"]),
            "avatar": avatar_class(u["slug"]),
            "cap": {
                "projected": round(info["projected"] * 10) / 10,
                "target": info["target"],
                "scheduled": round(info["scheduled"] * 10) / 10,
                "buffer": info["buffer"],
                "status": st,
                "status_label": status_label(st),
                "pct": min(100, max(0, (info["projected"] / info["target"]) * 100 if info["target"] else 100)),
                "fits": can_accept_visit(conn, u, today(), minutes),
                "scheduled_label": hours_label(info["scheduled"]),
                "buffer_label": hours_label(info["buffer"]),
                "projected_label": hours_label(info["projected"]),
            },
            "weeks": weeks,
            "overflow": overflow,
            "rec_ok": rec_ok,
            "session_minutes": minutes,
            "clients": client_rows,
            "dismissed": dismissed,
            "upcoming": upcoming,
            "peers": peer_rows,
            "notes": note_rows,
            "unread_count": unread_count,
            "waitlist_rows": waitlist_rows,
            "pending_invites": pending_invites,
            "booking_url": booking_url,
            "booking_display": f"scheduleavisit.com/p/{u['slug']}",
            "workdays_json": u["workdays"],
            "cal_year": today().year,
            "cal_month": today().month,
            "consult_minutes": int(uget(u, "consult_minutes", 15) or 15),
            "consult_enabled": int(uget(u, "consult_enabled", 1) or 0),
            "categories": CATEGORY_CHOICES,
            "recommend_max": MAX_RECOMMENDATIONS,
            "recommend_count": outgoing_recommend_count(conn, u["id"]),
        }
    return tpl(request, "dashboard.html", **ctx)


# ───────── Auth API ─────────

async def _body(request: Request) -> dict:
    ct = request.headers.get("content-type", "")
    if "json" in ct:
        return await request.json()
    form = await request.form()
    return {k: (v if isinstance(v, str) else str(v)) for k, v in form.items()}


@app.post("/api/auth/login")
async def api_login(request: Request):
    data = await _body(request)
    ident = (data.get("email") or data.get("identifier") or "").strip()
    password = data.get("password") or ""
    with db() as conn:
        u = find_login_user(conn, ident)
        if not u or not verify_password(password, u["password_hash"]):
            return json_err("That email or password did not match.", 401)
        nxt = post_auth_redirect(u, data.get("next"))
        resp = JSONResponse({"ok": True, "redirect": nxt, "name": u["name"]})
        set_session(conn, resp, u["id"])
        return resp


@app.post("/api/auth/signup")
async def api_signup(request: Request):
    data = await _body(request)
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    name = (data.get("name") or "").strip()
    username = (data.get("username") or "").strip().lower()
    credentials = (data.get("credentials") or "").strip()
    if not email or "@" not in email:
        return json_err("Please enter a real email.")
    if len(password) < 8:
        return json_err("Password needs at least 8 characters.")
    if len(name) < 2:
        return json_err("Please enter the name clients will see.")
    if not USERNAME_RE.match(username):
        return json_err("Pick a username: 3–32 letters, numbers, or underscores.")
    if credentials and credentials not in name:
        display = f"{name}, {credentials}"
    else:
        display = name
    with db() as conn:
        if user_by_email(conn, email):
            return json_err("That email already has an account. Try logging in.")
        taken = conn.execute(
            "SELECT 1 FROM users WHERE lower(COALESCE(username,''))=?", (username,)
        ).fetchone()
        if taken:
            return json_err("That username is taken. Try another.")
        slug = unique_slug(conn, display)
        cur = conn.execute(
            """INSERT INTO users (
                 email, password_hash, name, credentials, title, specialty, about, clinic, address,
                 slug, weekly_target_hours, buffer_hours, workdays, slot_start, slot_end, lunch,
                 session_minutes, timezone, created_at, username, setup_complete, consult_minutes,
                 consult_enabled, portal_kind, portal_url
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                email, hash_password(password), display, credentials,
                data.get("title") or "",
                data.get("specialty") or "",
                data.get("about") or "",
                data.get("clinic") or "",
                data.get("address") or "",
                slug, 25, 3, json.dumps([1, 2, 3, 4, 5]), 9, 17, 12, 50,
                "America/Denver", now_iso(),
                username, 0, 15, 1, "none", "",
            ),
        )
        uid = int(cur.lastrowid)
        notify(conn, uid, "welcome", "Welcome to ScheduleAVisit",
               "Finish setup so clients see the right hours and your portal link.")
        nxt = data.get("next") or "/setup"
        if not str(nxt).startswith("/invite"):
            nxt = "/setup"
        resp = JSONResponse({"ok": True, "redirect": nxt, "slug": slug})
        set_session(conn, resp, uid)
        return resp


@app.post("/api/auth/logout")
async def api_logout(request: Request):
    resp = JSONResponse({"ok": True, "redirect": "/"})
    clear_session(request, resp)
    return resp


# ───────── Public booking API ─────────

@app.get("/api/p/{slug}/availability")
def api_availability(slug: str, date: str, minutes: Optional[int] = None, visit_kind: Optional[str] = None):
    try:
        day = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        return json_err("Use date=YYYY-MM-DD")
    with db() as conn:
        u = user_by_slug(conn, slug)
        if not u:
            return json_err("Calendar not found", 404)
        maybe_sync_ical(conn, u, timeout=2.0)
        kind = (visit_kind or "session").lower()
        if minutes is None:
            if kind == "consult" and int(uget(u, "consult_enabled", 1) or 0):
                minutes = int(uget(u, "consult_minutes", 15) or 15)
            else:
                minutes = int(uget(u, "session_minutes", 50) or 50)
        data = availability_for(conn, u, day, minutes=int(minutes))
        data["ok"] = True
        data["visitKind"] = kind
        data["provider"] = public_provider(u)
        return data


@app.post("/api/p/{slug}/book")
async def api_book(slug: str, request: Request):
    data = await _body(request)
    try:
        day = datetime.strptime(data.get("date") or "", "%Y-%m-%d").date()
    except ValueError:
        return json_err("Pick a day.")
    hhmm = (data.get("time") or "").strip()
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()
    if not re.match(r"^\d{2}:\d{2}$", hhmm):
        return json_err("Pick a time.")
    if len(name) < 2:
        return json_err("Please tell us your name.")
    if "@" not in email:
        return json_err("Please leave an email so the office can reach you.")
    with db() as conn:
        u = user_by_slug(conn, slug)
        if not u:
            return json_err("Calendar not found", 404)
        requested = (data.get("visitKind") or data.get("visit_kind") or "session")
        visit_kind, minutes, returning = resolve_visit(conn, u, requested, email)
        start = at_local(day, hhmm)
        if start <= datetime.now(TZ):
            return json_err("That time has already passed.")
        if day.isoweekday() not in user_workdays(u):
            return json_err("The office is closed that day.")
        if is_taken(conn, u["id"], start, minutes):
            return json_err("That time was just taken. Please pick another.")
        if not can_accept_visit(conn, u, day, minutes):
            wanted = normalize_category(data.get("category") or data.get("need") or "general")
            recs = referral_candidates(conn, u, day, hhmm, minutes, category=wanted)
            recommendation = rec_payload(recs[0], minutes) if recs else None
            alternatives = [rec_payload(r, minutes) for r in recs[1:]]
            return JSONResponse({
                "ok": False,
                "full": True,
                "recommendation": recommendation,
                "alternatives": alternatives,
                "waitlist": recommendation is None,
                "minutes": minutes,
                "category": wanted,
                "categoryLabel": category_label(wanted),
                "message": f"{first_name(u['name'])} does not have room for another {minutes}-minute visit this week.",
            })
        cid = get_or_create_client(conn, u["id"], name, email, phone)
        appt_id = create_appointment(conn, u["id"], cid, start, minutes, "direct", visit_kind=visit_kind)
        notify(
            conn, u["id"], "booking",
            f"New visit — {name}",
            f"{name} booked {format_long(day)} at {format_time(hhmm)} ({minutes} min, {visit_kind}) on your public link.",
        )
        after_book(conn, appt_id)
        print(f"[book] {name} <{email}> with {u['slug']} on {day} {hhmm} {visit_kind}", flush=True)
        portal = "" if returning else (uget(u, "portal_url", "") or "").strip()
        return {
            "ok": True,
            "appointmentId": appt_id,
            "redirect": confirm_url(conn, appt_id),
            "portalUrl": portal or None,
            "visitKind": visit_kind,
            "firstVisit": not returning,
            "minutes": minutes,
        }


@app.post("/api/p/{slug}/book-referral")
async def api_book_referral(slug: str, request: Request):
    data = await _body(request)
    peer_slug = (data.get("peerSlug") or "").strip()
    try:
        day = datetime.strptime(data.get("date") or "", "%Y-%m-%d").date()
    except ValueError:
        return json_err("Pick a day.")
    hhmm = (data.get("time") or "").strip()
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    if not peer_slug or not re.match(r"^\d{2}:\d{2}$", hhmm) or len(name) < 2 or "@" not in email:
        return json_err("Name, email, peer, date, and time are required.")
    with db() as conn:
        origin = user_by_slug(conn, slug)
        peer = user_by_slug(conn, peer_slug)
        if not origin or not peer:
            return json_err("Calendar not found", 404)
        if not network_reachable(conn, origin["id"], peer["id"]):
            return json_err("That professional is not in this referral network.")
        minutes = int(peer["session_minutes"] or 50)
        start = at_local(day, hhmm)
        if is_taken(conn, peer["id"], start, minutes):
            return json_err("That time was just taken.")
        if not can_accept_visit(conn, peer, day, minutes):
            return json_err("That professional just reached their weekly cap.")
        cid = get_or_create_client(conn, peer["id"], name, email, data.get("phone") or "")
        appt_id = create_appointment(conn, peer["id"], cid, start, minutes, "referral", origin["id"], visit_kind="session")
        notify(
            conn, peer["id"], "referral",
            f"Referral visit — {name}",
            f"{first_name(origin['name'])} referred {name} for {format_long(day)} at {format_time(hhmm)}.",
        )
        notify(
            conn, origin["id"], "referral",
            f"You referred {name} to {first_name(peer['name'])}",
            f"{name} is on {first_name(peer['name'])}'s calendar {format_long(day)} at {format_time(hhmm)}.",
        )
        after_book(conn, appt_id)
        print(f"[book-referral] {name} {origin['slug']} → {peer['slug']} {day} {hhmm}", flush=True)
        return {"ok": True, "appointmentId": appt_id, "redirect": confirm_url(conn, appt_id)}


@app.post("/api/p/{slug}/waitlist")
async def api_waitlist(slug: str, request: Request):
    """Client joins origin provider waitlist when the whole network is full.
    Dashboard notification + DB only — no SMS/email send."""
    data = await _body(request)
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    try:
        minutes = int(data.get("requested_minutes") or data.get("minutes") or 50)
    except (TypeError, ValueError):
        minutes = 50
    minutes = max(5, min(180, minutes))
    if len(name) < 2:
        return json_err("Please tell us your name.")
    if "@" not in email:
        return json_err("Please leave an email so the office can reach you.")
    with db() as conn:
        u = user_by_slug(conn, slug)
        if not u:
            return json_err("Calendar not found", 404)
        cur = conn.execute(
            """INSERT INTO waitlist_requests
               (provider_id, name, email, requested_minutes, created_at)
               VALUES (?,?,?,?,?)""",
            (u["id"], name, email, minutes, now_iso()),
        )
        wid = int(cur.lastrowid)
        notify(
            conn, u["id"], "waitlist",
            f"Waitlist — {name}",
            f"{name} ({email}) asked to be notified when you or your network have room for a {minutes}-minute visit.",
        )
        print(f"[waitlist] {name} <{email}> → {u['slug']} {minutes}min id={wid}", flush=True)
        return {
            "ok": True,
            "waitlistId": wid,
            "message": f"You're on {first_name(u['name'])}'s waitlist. The office will see your request on their dashboard.",
        }


# ───────── Provider API ─────────

def _auth(request: Request):
    user = current_user(request)
    if not user:
        return None, json_err("Please log in.", 401)
    return user, None


@app.get("/api/me")
def api_me(request: Request):
    user, err = _auth(request)
    if err:
        return err
    with db() as conn:
        u = user_by_id(conn, user["id"])
        week = start_of_week(today())
        info = projected_hours(conn, u, week, 0)
        return {
            "ok": True,
            "user": {
                **row(u),
                "password_hash": None,
                "workdays": user_workdays(u),
                "first": first_name(u["name"]),
            },
            "capacity": {**info, "status": status_for(info["projected"], info["target"])},
        }


@app.patch("/api/me")
async def api_me_patch(request: Request):
    user, err = _auth(request)
    if err:
        return err
    data = await _body(request)
    fields = {
        "name": str,
        "credentials": str,
        "title": str,
        "specialty": str,
        "about": str,
        "clinic": str,
        "address": str,
        "weekly_target_hours": float,
        "buffer_hours": float,
        "slot_start": int,
        "slot_end": int,
        "lunch": int,
        "session_minutes": int,
        "consult_minutes": int,
        "consult_enabled": int,
        "portal_kind": str,
        "portal_url": str,
        "ical_url": str,
        "phone": str,
        "reminders_opt_in": int,
    }
    allow_empty = {"about", "specialty", "clinic", "address", "credentials", "title",
                   "portal_url", "ical_url", "portal_kind", "phone"}
    sets, args = [], []
    for key, cast in fields.items():
        if key not in data:
            continue
        if data[key] in (None, "") and key not in allow_empty:
            continue
        try:
            val = cast(data[key]) if data[key] not in (None, "") else ("" if cast is str else 0)
        except (TypeError, ValueError):
            return json_err(f"Invalid {key}")
        if key == "portal_kind" and val not in ("none", "headway", "sondermind", "custom"):
            return json_err("Pick a portal type.")
        if key in ("portal_url", "ical_url") and val and not str(val).lower().startswith(("http://", "https://")):
            return json_err(f"{key.replace('_', ' ')} should start with https://")
        if key == "consult_enabled":
            val = 1 if val else 0
        if key == "reminders_opt_in":
            val = 1 if val else 0
        sets.append(f"{key}=?")
        args.append(val)
    if "workdays" in data:
        days = data["workdays"]
        if isinstance(days, str):
            days = json.loads(days)
        days = [int(d) for d in days if int(d) in (1, 2, 3, 4, 5, 6, 7)]
        if not days:
            return json_err("Pick at least one workday.")
        sets.append("workdays=?")
        args.append(json.dumps(days))
    if not sets:
        return {"ok": True}
    args.append(user["id"])
    with db() as conn:
        conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", args)
    return {"ok": True}


@app.post("/api/me/password")
async def api_me_password(request: Request):
    user, err = _auth(request)
    if err:
        return err
    data = await _body(request)
    current = data.get("current_password") or data.get("current") or ""
    new = data.get("new_password") or data.get("new") or ""
    confirm = data.get("confirm_password") or data.get("confirm") or ""
    if len(new) < 6:
        return json_err("Please use at least 6 characters for the new password.")
    if new != confirm:
        return json_err("Those two new passwords don’t match yet. Try typing them again.")
    with db() as conn:
        u = user_by_id(conn, user["id"])
        if not u or not verify_password(current, u["password_hash"]):
            return json_err("That doesn’t match your current password.", 401)
        conn.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (hash_password(new), user["id"]),
        )
    return {"ok": True, "message": "Your password is updated."}


@app.get("/api/me/clients")
def api_clients(request: Request):
    user, err = _auth(request)
    if err:
        return err
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM clients WHERE provider_id=? ORDER BY name", (user["id"],)
        ).fetchall()
        out = []
        for c in rows:
            dates = client_visit_dates(conn, c["id"])
            out.append({
                **row(c),
                "pattern": infer_pattern(dates),
                "label": infer_label(infer_pattern(dates)),
            })
        return {"ok": True, "clients": out}


@app.post("/api/me/clients/{client_id}/dismiss")
def api_dismiss(request: Request, client_id: int):
    user, err = _auth(request)
    if err:
        return err
    with db() as conn:
        c = conn.execute(
            "SELECT * FROM clients WHERE id=? AND provider_id=?", (client_id, user["id"])
        ).fetchone()
        if not c:
            return json_err("Client not found", 404)
        conn.execute("UPDATE clients SET dismissed_at=? WHERE id=?", (now_iso(), client_id))
        # Cancel future visits so the slots actually open.
        conn.execute(
            """UPDATE appointments SET status='cancelled', cancelled_at=?
               WHERE client_id=? AND status='booked' AND start_iso>=?""",
            (now_iso(), client_id, now_iso()),
        )
        cancel_pending_for_client(conn, client_id)
        notify(conn, user["id"], "client", f"{c['name']} dismissed",
               "Their future visits were cancelled. Inferred weekly load no longer includes them.")
        return {"ok": True}


@app.post("/api/me/clients/{client_id}/restore")
def api_restore(request: Request, client_id: int):
    user, err = _auth(request)
    if err:
        return err
    with db() as conn:
        c = conn.execute(
            "SELECT * FROM clients WHERE id=? AND provider_id=?", (client_id, user["id"])
        ).fetchone()
        if not c:
            return json_err("Client not found", 404)
        if not c["dismissed_at"]:
            return {"ok": True}
        conn.execute("UPDATE clients SET dismissed_at=NULL WHERE id=?", (client_id,))
        notify(conn, user["id"], "client", f"{c['name']} restored",
               "They’re back on your caseload. Future visits are not recreated automatically.")
        return {"ok": True}


@app.post("/api/me/waitlist/{waitlist_id}/dismiss")
def api_waitlist_dismiss(request: Request, waitlist_id: int):
    user, err = _auth(request)
    if err:
        return err
    with db() as conn:
        w = conn.execute(
            "SELECT * FROM waitlist_requests WHERE id=? AND provider_id=?",
            (waitlist_id, user["id"]),
        ).fetchone()
        if not w:
            return json_err("Waitlist request not found", 404)
        if w["dismissed_at"]:
            return {"ok": True}
        conn.execute(
            "UPDATE waitlist_requests SET dismissed_at=? WHERE id=?",
            (now_iso(), waitlist_id),
        )
        return {"ok": True}


@app.get("/api/me/appointments")
def api_appts(request: Request):
    user, err = _auth(request)
    if err:
        return err
    with db() as conn:
        rows = conn.execute(
            """SELECT a.*, c.name AS client_name FROM appointments a
               LEFT JOIN clients c ON c.id=a.client_id
               WHERE a.provider_id=? ORDER BY a.start_iso DESC LIMIT 80""",
            (user["id"],),
        ).fetchall()
        return {"ok": True, "appointments": [row(r) for r in rows]}


@app.post("/api/me/appointments/{appt_id}/cancel")
def api_cancel(request: Request, appt_id: int):
    user, err = _auth(request)
    if err:
        return err
    with db() as conn:
        a = conn.execute(
            "SELECT * FROM appointments WHERE id=? AND provider_id=?", (appt_id, user["id"])
        ).fetchone()
        if not a:
            return json_err("Visit not found", 404)
        if a["status"] == "cancelled":
            return {"ok": True, "already": True}
        conn.execute(
            "UPDATE appointments SET status='cancelled', cancelled_at=? WHERE id=?",
            (now_iso(), appt_id),
        )
        cancel_pending(conn, appt_id)
        start = parse_iso(a["start_iso"])
        notify(conn, user["id"], "cancel", "Visit cancelled",
               f"The {format_time(start.strftime('%H:%M'))} time on {format_long(start.date())} "
               "is open again. This week's hours updated immediately.")
        return {"ok": True}


@app.post("/api/me/appointments/{appt_id}/reschedule")
async def api_reschedule(request: Request, appt_id: int):
    user, err = _auth(request)
    if err:
        return err
    data = await _body(request)
    try:
        day = datetime.strptime(data.get("date") or "", "%Y-%m-%d").date()
    except ValueError:
        return json_err("Pick a day.")
    hhmm = (data.get("time") or "").strip()
    if not re.match(r"^\d{2}:\d{2}$", hhmm):
        return json_err("Pick a time.")
    with db() as conn:
        u = user_by_id(conn, user["id"])
        a = conn.execute(
            "SELECT * FROM appointments WHERE id=? AND provider_id=?", (appt_id, user["id"])
        ).fetchone()
        if not a:
            return json_err("Visit not found", 404)
        if a["status"] != "booked":
            return json_err("That visit is not on the calendar.")
        minutes = a["duration_minutes"]
        start = at_local(day, hhmm)
        if is_taken(conn, u["id"], start, minutes, ignore_id=appt_id):
            return json_err("That time is already booked.")
        old = parse_iso(a["start_iso"])
        if not can_accept_visit(conn, u, day, minutes):
            # Allow moving within the same week without double-counting this visit.
            if start_of_week(old.date()) != start_of_week(day):
                return json_err("That week does not have hour-cap room.")
        new_iso = start.isoformat(timespec="seconds")
        conn.execute(
            "UPDATE appointments SET start_iso=? WHERE id=?",
            (new_iso, appt_id),
        )
        after_reschedule(conn, appt_id)
        notify(conn, user["id"], "reschedule", "Visit moved",
               f"{format_long(old.date())} {format_time(old.strftime('%H:%M'))} → "
               f"{format_long(day)} {format_time(hhmm)}. Hours stay with this visit.")
        return {"ok": True, "startIso": new_iso, "date": day.isoformat(), "time": hhmm}


@app.post("/api/me/network/invite")
async def api_invite(request: Request):
    user, err = _auth(request)
    if err:
        return err
    data = await _body(request)
    email = (data.get("email") or "").strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        return json_err("Enter a colleague’s email address.")
    if email == user["email"].lower():
        return json_err("That’s your own email — invite a colleague instead.")
    category = normalize_category(data.get("category") or "general")
    with db() as conn:
        existing = conn.execute(
            "SELECT * FROM network_invites WHERE from_user_id=? AND lower(to_email)=? AND status='pending'",
            (user["id"], email),
        ).fetchone()
        already = bool(existing)
        if existing:
            token = existing["token"]
            if "category" in existing.keys():
                conn.execute(
                    "UPDATE network_invites SET category=? WHERE id=?",
                    (category, existing["id"]),
                )
        else:
            target = user_by_email(conn, email)
            already_linked = False
            if target:
                already_linked = bool(conn.execute(
                    "SELECT 1 FROM network_links WHERE user_id=? AND peer_id=?",
                    (user["id"], target["id"]),
                ).fetchone())
            if (not already_linked) and outgoing_recommend_count(conn, user["id"]) >= MAX_RECOMMENDATIONS:
                return json_err(f"You can recommend up to {MAX_RECOMMENDATIONS} colleagues.")
            token = secrets.token_urlsafe(24)
            conn.execute(
                """INSERT INTO network_invites (from_user_id, to_email, status, token, created_at, category)
                   VALUES (?,?, 'pending', ?, ?, ?)""",
                (user["id"], email, token, now_iso(), category),
            )
        invite_url = str(request.base_url).rstrip("/") + f"/invite/{token}"
        print(f"[invite] {user['email']} → {email}  {invite_url}", flush=True)
        if not already:
            notify(conn, user["id"], "invite", f"Invite sent to {email}",
                   f"They can accept at {invite_url}. No email was sent — share the link.")
            target = user_by_email(conn, email)
            if target:
                notify(conn, target["id"], "invite", f"{first_name(user['name'])} invited you",
                       f"Open {invite_url} while logged in as {email} to join their referral network.")
        message = (
            f"You already have a pending invite for {email}. Share the link again — we do not send email."
            if already
            else f"Invite ready for {email}. Share the link — we do not send email."
        )
        return {"ok": True, "token": token, "url": invite_url, "email": email, "already": already, "message": message}


@app.get("/api/me/network")
def api_network(request: Request):
    user, err = _auth(request)
    if err:
        return err
    with db() as conn:
        week = start_of_week(today())
        peers = []
        for p in peers_of(conn, user["id"]):
            rem = remaining_hours(conn, p, week)
            pcat = normalize_category(uget(p, "referral_category", "general"))
            peers.append({
                **public_provider(p, user["slug"]),
                "remainingHours": rem,
                "category": pcat,
                "categoryLabel": category_label(pcat),
            })
        invites = conn.execute(
            "SELECT id, to_email, status, token, created_at FROM network_invites WHERE from_user_id=? ORDER BY id DESC",
            (user["id"],),
        ).fetchall()
        return {"ok": True, "peers": peers, "invites": [row(i) for i in invites]}


@app.post("/api/me/network/recommend")
async def api_recommend(request: Request):
    user, err = _auth(request)
    if err:
        return err
    data = await _body(request)
    category = normalize_category(data.get("category") or "general")
    peer = None
    with db() as conn:
        peer_id = data.get("peerId") or data.get("peer_id")
        slug = (data.get("peerSlug") or data.get("slug") or "").strip()
        email = (data.get("email") or "").strip().lower()
        if peer_id:
            try:
                peer = user_by_id(conn, int(peer_id))
            except (TypeError, ValueError):
                peer = None
        if peer is None and slug:
            peer = user_by_slug(conn, slug)
        if peer is None and email and "@" in email:
            peer = user_by_email(conn, email)
        if not peer:
            return json_err("Choose a colleague already on ScheduleAVisit, or send an invite.")
        msg = add_recommendation(conn, user["id"], peer["id"], category)
        if msg:
            return json_err(msg)
        count = outgoing_recommend_count(conn, user["id"])
        return {
            "ok": True,
            "peerId": peer["id"],
            "peerSlug": peer["slug"],
            "name": peer["name"],
            "category": category,
            "categoryLabel": category_label(category),
            "count": count,
            "max": MAX_RECOMMENDATIONS,
        }


@app.get("/api/me/notifications")
def api_notes(request: Request):
    user, err = _auth(request)
    if err:
        return err
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 40",
            (user["id"],),
        ).fetchall()
        notes = [row(r) | {"unread": not r["read_at"]} for r in rows]
        return {
            "ok": True,
            "notifications": notes,
            "unread": sum(1 for n in notes if n["unread"]),
        }


@app.post("/api/me/notifications/read-all")
def api_notes_read_all(request: Request):
    user, err = _auth(request)
    if err:
        return err
    with db() as conn:
        cur = conn.execute(
            "UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL",
            (now_iso(), user["id"]),
        )
        return {"ok": True, "marked": cur.rowcount}


@app.post("/api/me/notifications/{note_id}/read")
def api_note_read(request: Request, note_id: int):
    user, err = _auth(request)
    if err:
        return err
    with db() as conn:
        n = conn.execute(
            "SELECT * FROM notifications WHERE id=? AND user_id=?",
            (note_id, user["id"]),
        ).fetchone()
        if not n:
            return json_err("Notification not found", 404)
        if not n["read_at"]:
            conn.execute(
                "UPDATE notifications SET read_at=? WHERE id=?",
                (now_iso(), note_id),
            )
        return {"ok": True}


def _parse_workdays(raw) -> list[int] | None:
    days = raw
    if isinstance(days, str):
        try:
            days = json.loads(days)
        except Exception:
            days = [int(x) for x in days.split(",") if x.strip().isdigit()]
    try:
        days = [int(d) for d in days if int(d) in (1, 2, 3, 4, 5, 6, 7)]
    except (TypeError, ValueError):
        return None
    return days or None


@app.post("/api/setup")
async def api_setup(request: Request):
    user, err = _auth(request)
    if err:
        return err
    data = await _body(request)
    portal_kind = (data.get("portal_kind") or "none").strip().lower()
    if portal_kind not in ("none", "headway", "sondermind", "custom"):
        return json_err("Pick how clients start intake.")
    portal_url = (data.get("portal_url") or "").strip()
    ical_url = (data.get("ical_url") or "").strip()
    if portal_url and not portal_url.lower().startswith(("http://", "https://")):
        return json_err("Portal link should start with https://")
    if ical_url and not ical_url.lower().startswith(("http://", "https://")):
        return json_err("Calendar link should start with https://")
    days = _parse_workdays(data.get("workdays") or [1, 2, 3, 4, 5])
    if not days:
        return json_err("Pick at least one workday.")
    try:
        weekly = float(data.get("weekly_target_hours") or 25)
        buffer = float(data.get("buffer_hours") or 3)
        slot_start = int(data.get("slot_start") or 9)
        slot_end = int(data.get("slot_end") or 17)
        lunch = int(data.get("lunch") or 12)
        session_minutes = int(data.get("session_minutes") or 50)
        consult_minutes = int(data.get("consult_minutes") or 15)
        consult_enabled = 1 if str(data.get("consult_enabled", 1)) not in ("0", "false", "off", "") else 0
        reminders_opt_in = 1 if str(data.get("reminders_opt_in", 0)) in ("1", "true", "on", "yes") else 0
    except (TypeError, ValueError):
        return json_err("Check the hour and minute numbers.")
    name = (data.get("name") or "").strip()
    if len(name) < 2:
        return json_err("Please enter the name clients will see.")
    ical_changed = False
    with db() as conn:
        u = user_by_id(conn, user["id"])
        old_ical = (uget(u, "ical_url", "") or "").strip()
        ical_changed = ical_url != old_ical
        phone = (data.get("phone") or "").strip()
        conn.execute(
            """UPDATE users SET
                 name=?, credentials=?, title=?, specialty=?, about=?, clinic=?, address=?,
                 weekly_target_hours=?, buffer_hours=?, workdays=?, slot_start=?, slot_end=?,
                 lunch=?, session_minutes=?, consult_minutes=?, consult_enabled=?,
                 portal_kind=?, portal_url=?, ical_url=?, phone=?, reminders_opt_in=?,
                 ical_synced_at=CASE WHEN ? THEN NULL ELSE ical_synced_at END,
                 setup_complete=1
               WHERE id=?""",
            (
                name,
                (data.get("credentials") or "").strip(),
                (data.get("title") or "").strip(),
                (data.get("specialty") or "").strip(),
                (data.get("about") or "").strip(),
                (data.get("clinic") or "").strip(),
                (data.get("address") or "").strip(),
                weekly, buffer, json.dumps(days), slot_start, slot_end, lunch,
                session_minutes, consult_minutes, consult_enabled,
                portal_kind, portal_url, ical_url, phone, reminders_opt_in,
                1 if ical_changed else 0,
                user["id"],
            ),
        )
        if ical_url:
            u2 = user_by_id(conn, user["id"])
            maybe_sync_ical(conn, u2, timeout=2.0)
    return {"ok": True, "redirect": "/dashboard"}


def _month_span(year: int, month: int):
    first = date(year, month, 1)
    grid_start = first - timedelta(days=first.isoweekday() % 7)
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    last = nxt - timedelta(days=1)
    grid_end = last + timedelta(days=(6 - last.isoweekday() % 7))
    return grid_start, grid_end


def _is_ical_sourced(a) -> bool:
    via = a["booked_via"] or ""
    kind = uget(a, "visit_kind", "") or ""
    return via == "ical" or kind == "external"


def _calendar_block(a) -> dict:
    start = parse_iso(a["start_iso"])
    via = a["booked_via"] or "direct"
    kind = uget(a, "visit_kind", "session") or "session"
    if via == "ical" or kind == "external":
        source = "ical"
    elif via == "manual" or kind == "manual":
        source = "manual"
    else:
        source = "booked"
    client_name = uget(a, "client_name", "") or ""
    calendar_title = note_summary(uget(a, "note", "") or "") if source == "ical" else ""
    return {
        "id": a["id"],
        "date": start.date().isoformat(),
        "time": start.strftime("%H:%M"),
        "minutes": a["duration_minutes"],
        "name": block_label(a),
        "clientName": client_name,
        "calendarTitle": calendar_title or "",
        "visit_kind": kind,
        "booked_via": via,
        "source": source,
        "editable": source == "manual",
        "markable": source == "ical",
        "countsTowardCap": kind != "external",
    }


@app.get("/api/calendar")
def api_calendar(request: Request, year: Optional[int] = None, month: Optional[int] = None):
    user, err = _auth(request)
    if err:
        return err
    today_d = today()
    year = int(year or today_d.year)
    month = int(month or today_d.month)
    if month < 1 or month > 12 or year < 2000 or year > 2100:
        return json_err("Use a real year and month.")
    with db() as conn:
        u = user_by_id(conn, user["id"])
        maybe_sync_ical(conn, u, timeout=2.0)
        grid_start, grid_end = _month_span(year, month)
        rows = conn.execute(
            """SELECT a.*, c.name AS client_name
               FROM appointments a
               LEFT JOIN clients c ON c.id = a.client_id
               WHERE a.provider_id=? AND a.status='booked'
                 AND a.start_iso>=? AND a.start_iso<?
               ORDER BY a.start_iso""",
            (
                u["id"],
                at_local(grid_start, "00:00").isoformat(timespec="seconds"),
                at_local(grid_end + timedelta(days=1), "00:00").isoformat(timespec="seconds"),
            ),
        ).fetchall()
        days = {}
        for a in rows:
            blk = _calendar_block(a)
            days.setdefault(blk["date"], []).append(blk)
        return {
            "ok": True,
            "year": year,
            "month": month,
            "gridStart": grid_start.isoformat(),
            "gridEnd": grid_end.isoformat(),
            "days": days,
            "sessionMinutes": int(uget(u, "session_minutes", 50) or 50),
            "slotStart": int(u["slot_start"] or 9),
            "slotEnd": int(u["slot_end"] or 17),
            "icalSyncedAt": uget(u, "ical_synced_at", None),
        }


@app.post("/api/calendar/block")
async def api_calendar_block(request: Request):
    user, err = _auth(request)
    if err:
        return err
    data = await _body(request)
    try:
        day = datetime.strptime(data.get("date") or "", "%Y-%m-%d").date()
    except ValueError:
        return json_err("Pick a day.")
    hhmm = normalize_hhmm(data.get("time") or "")
    name = (data.get("name") or "").strip()
    if not hhmm:
        return json_err("Pick a time.")
    if len(name) < 2:
        return json_err("Enter the client’s name.")
    with db() as conn:
        u = user_by_id(conn, user["id"])
        try:
            minutes = int(data.get("minutes") or u["session_minutes"] or 50)
        except (TypeError, ValueError):
            return json_err("Minutes should be a number.")
        minutes = max(10, min(180, minutes))
        start = at_local(day, hhmm)
        if is_taken(conn, u["id"], start, minutes):
            return json_err("That time overlaps another block.")
        cid = get_or_create_client(conn, u["id"], name)
        appt_id = create_appointment(
            conn, u["id"], cid, start, minutes, "manual", visit_kind="manual", note=name,
        )
        return {"ok": True, "id": appt_id, "clientId": cid}


@app.post("/api/calendar/block/{appt_id}/update")
async def api_calendar_update(request: Request, appt_id: int):
    user, err = _auth(request)
    if err:
        return err
    data = await _body(request)
    with db() as conn:
        a = conn.execute(
            "SELECT * FROM appointments WHERE id=? AND provider_id=?",
            (appt_id, user["id"]),
        ).fetchone()
        if not a:
            return json_err("Block not found", 404)
        via = a["booked_via"] or ""
        kind = uget(a, "visit_kind", "") or ""
        if via != "manual" and kind != "manual":
            return json_err("Only blocks you added can be edited here.")
        name = (data.get("name") or "").strip()
        hhmm = normalize_hhmm(data.get("time") or parse_iso(a["start_iso"]).strftime("%H:%M"))
        try:
            day = datetime.strptime(data.get("date") or parse_iso(a["start_iso"]).date().isoformat(), "%Y-%m-%d").date()
        except ValueError:
            return json_err("Pick a day.")
        if not hhmm:
            return json_err("Pick a time.")
        try:
            minutes = int(data.get("minutes") or a["duration_minutes"])
        except (TypeError, ValueError):
            return json_err("Minutes should be a number.")
        minutes = max(10, min(180, minutes))
        start = at_local(day, hhmm)
        if is_taken(conn, user["id"], start, minutes, ignore_id=appt_id):
            return json_err("That time overlaps another block.")
        cid = a["client_id"]
        if name:
            cid = get_or_create_client(conn, user["id"], name)
        conn.execute(
            """UPDATE appointments
               SET start_iso=?, duration_minutes=?, client_id=?, note=?, visit_kind='manual', booked_via='manual'
               WHERE id=?""",
            (start.isoformat(timespec="seconds"), minutes, cid, name or uget(a, "note", ""), appt_id),
        )
        return {"ok": True}


@app.post("/api/calendar/block/{appt_id}/delete")
def api_calendar_delete(request: Request, appt_id: int):
    user, err = _auth(request)
    if err:
        return err
    with db() as conn:
        a = conn.execute(
            "SELECT * FROM appointments WHERE id=? AND provider_id=?",
            (appt_id, user["id"]),
        ).fetchone()
        if not a:
            return json_err("Block not found", 404)
        via = a["booked_via"] or ""
        kind = uget(a, "visit_kind", "") or ""
        if via != "manual" and kind != "manual":
            return json_err("Use Cancel for visits a client booked.")
        conn.execute(
            "UPDATE appointments SET status='cancelled', cancelled_at=? WHERE id=?",
            (now_iso(), appt_id),
        )
        cancel_pending(conn, appt_id)
        return {"ok": True}


@app.post("/api/calendar/block/{appt_id}/mark")
async def api_calendar_mark(request: Request, appt_id: int):
    user, err = _auth(request)
    if err:
        return err
    data = await _body(request)
    raw = data.get("counts")
    if isinstance(raw, str):
        counts = raw.strip().lower() in ("1", "true", "yes", "on")
    else:
        counts = bool(raw)
    name = (data.get("name") or "").strip()
    with db() as conn:
        a = conn.execute(
            "SELECT * FROM appointments WHERE id=? AND provider_id=?",
            (appt_id, user["id"]),
        ).fetchone()
        if not a:
            return json_err("Block not found", 404)
        if (a["status"] or "") != "booked":
            return json_err("That appointment is not on the calendar.")
        if not _is_ical_sourced(a):
            return json_err("Only imported calendar appointments can be marked here.")
        if counts:
            kind = "session"
            cid = a["client_id"]
            if len(name) >= 2:
                cid = get_or_create_client(conn, user["id"], name)
        else:
            kind = "external"
            cid = None
        conn.execute(
            "UPDATE appointments SET visit_kind=?, client_id=? WHERE id=?",
            (kind, cid, appt_id),
        )
        row = conn.execute(
            """SELECT a.*, c.name AS client_name
               FROM appointments a
               LEFT JOIN clients c ON c.id = a.client_id
               WHERE a.id=?""",
            (appt_id,),
        ).fetchone()
        return {"ok": True, **_calendar_block(row)}


def _tick_secret_ok(request: Request) -> bool:
    expected = os.environ.get(TICK_ENV) or ""
    got = request.headers.get(TICK_HEADER) or ""
    if not expected or not got or len(got) != len(expected):
        return False
    return secrets.compare_digest(got, expected)


@app.post("/internal/reminders/tick")
@app.get("/internal/reminders/tick")
def api_reminders_tick(request: Request):
    """Wake-friendly send: process due reminder rows. Requires X-Reminder-Secret."""
    if not _tick_secret_ok(request):
        return json_err("Forbidden", 403)
    with db() as conn:
        result = send_due(conn)
    return {"ok": True, **result}


@app.get("/health")
def health():
    return {"ok": True}
