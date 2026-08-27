"""SQLite schema, connection helpers, and first-boot seed."""
from __future__ import annotations

import json
import os
import hashlib
import secrets
import sqlite3
from datetime import datetime, date, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent


def db_path() -> Path:
    env = os.environ.get("SAV_DB")
    if env:
        return Path(env)
    return ROOT / "data" / "app.db"


DB_PATH = db_path()
TZ = ZoneInfo("America/Denver")

MAX_RECOMMENDATIONS = 5
CATEGORY_CHOICES = (
    ("general", "General"),
    ("anxiety", "Anxiety"),
    ("depression", "Depression"),
    ("couples", "Couples"),
    ("trauma", "Trauma"),
    ("addiction", "Addiction"),
    ("kids", "Kids / teens"),
    ("grief", "Grief"),
)
CATEGORY_KEYS = {key for key, _label in CATEGORY_CHOICES}
CATEGORY_LABELS = {key: label for key, label in CATEGORY_CHOICES}


def normalize_category(raw) -> str:
    if raw is None:
        return "general"
    s = str(raw).strip().lower()
    s = s.replace(" / ", "_").replace("/", "_").replace(" ", "_").replace("-", "_")
    aliases = {
        "kids_teens": "kids",
        "kids__teens": "kids",
        "kid": "kids",
        "teens": "kids",
        "teen": "kids",
        "couple": "couples",
        "relationship": "couples",
        "relationships": "couples",
        "substance": "addiction",
        "substances": "addiction",
        "alcohol": "addiction",
        "loss": "grief",
        "not_sure": "general",
        "unsure": "general",
        "none": "general",
        "": "general",
    }
    s = aliases.get(s, s)
    return s if s in CATEGORY_KEYS else "general"


def category_label(key: str) -> str:
    return CATEGORY_LABELS.get(normalize_category(key), "General")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  name TEXT NOT NULL,
  credentials TEXT DEFAULT '',
  title TEXT DEFAULT '',
  specialty TEXT DEFAULT '',
  about TEXT DEFAULT '',
  clinic TEXT DEFAULT '',
  address TEXT DEFAULT '',
  slug TEXT UNIQUE NOT NULL,
  weekly_target_hours REAL NOT NULL DEFAULT 25,
  buffer_hours REAL NOT NULL DEFAULT 3,
  workdays TEXT NOT NULL DEFAULT '[1,2,3,4,5]',
  slot_start INTEGER NOT NULL DEFAULT 9,
  slot_end INTEGER NOT NULL DEFAULT 17,
  lunch INTEGER NOT NULL DEFAULT 12,
  session_minutes INTEGER NOT NULL DEFAULT 50,
  timezone TEXT NOT NULL DEFAULT 'America/Denver',
  username TEXT,
  portal_kind TEXT DEFAULT 'none',
  portal_url TEXT DEFAULT '',
  consult_minutes INTEGER DEFAULT 15,
  consult_enabled INTEGER DEFAULT 1,
  setup_complete INTEGER DEFAULT 0,
  ical_url TEXT DEFAULT '',
  ical_synced_at TEXT,
  phone TEXT DEFAULT '',
  reminders_opt_in INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clients (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  email TEXT DEFAULT '',
  phone TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  dismissed_at TEXT
);

CREATE TABLE IF NOT EXISTS appointments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
  start_iso TEXT NOT NULL,
  duration_minutes INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'booked',
  booked_via TEXT NOT NULL DEFAULT 'direct',
  referred_from_provider_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  cancelled_at TEXT,
  visit_kind TEXT DEFAULT 'session',
  note TEXT DEFAULT '',
  public_token TEXT
);

CREATE TABLE IF NOT EXISTS network_invites (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  from_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  to_email TEXT NOT NULL,
  to_user_id INTEGER REFERENCES users(id),
  status TEXT NOT NULL DEFAULT 'pending',
  token TEXT UNIQUE NOT NULL,
  created_at TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'general'
);

CREATE TABLE IF NOT EXISTS network_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  peer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  category TEXT NOT NULL DEFAULT 'general',
  UNIQUE(user_id, peer_id)
);

CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL,
  read_at TEXT
);

CREATE TABLE IF NOT EXISTS waitlist_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  email TEXT NOT NULL,
  requested_minutes INTEGER NOT NULL DEFAULT 50,
  created_at TEXT NOT NULL,
  dismissed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_appt_provider ON appointments(provider_id, start_iso);
CREATE INDEX IF NOT EXISTS idx_waitlist_provider ON waitlist_requests(provider_id, created_at);
CREATE INDEX IF NOT EXISTS idx_appt_client ON appointments(client_id);
CREATE INDEX IF NOT EXISTS idx_clients_provider ON clients(provider_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS reminders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  appointment_id INTEGER NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  audience TEXT NOT NULL,
  send_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  sent_at TEXT,
  last_error TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, send_at);
CREATE INDEX IF NOT EXISTS idx_reminders_appt ON reminders(appointment_id);
"""


def now_dt() -> datetime:
    return datetime.now(TZ)


def now_iso() -> str:
    return now_dt().isoformat(timespec="seconds")


def today() -> date:
    return now_dt().date()


def start_of_week(d: date) -> date:
    return d - timedelta(days=d.isoweekday() - 1)


def parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def at_local(d: date, hhmm: str) -> datetime:
    h, m = [int(x) for x in hhmm.split(":")]
    return datetime.combine(d, time(h, m), tzinfo=TZ)


def date_on_weekday(week_start: date, iso_wd: int) -> date:
    return week_start + timedelta(days=iso_wd - 1)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), 200_000)
    return f"pbkdf2${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt, hexhash = stored.split("$", 2)
        if algo != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), 200_000)
        return secrets.compare_digest(dk.hex(), hexhash)
    except Exception:
        return False


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == col for r in rows)


def migrate(conn: sqlite3.Connection) -> None:
    """ALTER / CREATE IF NOT EXISTS so an existing Render SQLite DB picks this up."""
    user_cols = [
        ("username", "TEXT"),
        ("portal_kind", "TEXT DEFAULT 'none'"),
        ("portal_url", "TEXT DEFAULT ''"),
        ("consult_minutes", "INTEGER DEFAULT 15"),
        ("consult_enabled", "INTEGER DEFAULT 1"),
        ("setup_complete", "INTEGER DEFAULT 0"),
        ("ical_url", "TEXT DEFAULT ''"),
        ("ical_synced_at", "TEXT"),
        ("phone", "TEXT DEFAULT ''"),
        ("reminders_opt_in", "INTEGER NOT NULL DEFAULT 0"),
    ]
    for name, decl in user_cols:
        if not _has_column(conn, "users", name):
            conn.execute(f"ALTER TABLE users ADD COLUMN {name} {decl}")
    appt_cols = [
        ("visit_kind", "TEXT DEFAULT 'session'"),
        ("note", "TEXT DEFAULT ''"),
        ("public_token", "TEXT"),
    ]
    for name, decl in appt_cols:
        if not _has_column(conn, "appointments", name):
            conn.execute(f"ALTER TABLE appointments ADD COLUMN {name} {decl}")
    backfill_appointment_tokens(conn)
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_appt_public_token
           ON appointments(public_token)
           WHERE public_token IS NOT NULL AND public_token != ''"""
    )
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username
           ON users(username) WHERE username IS NOT NULL AND username != ''"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS waitlist_requests (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             provider_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
             name TEXT NOT NULL,
             email TEXT NOT NULL,
             requested_minutes INTEGER NOT NULL DEFAULT 50,
             created_at TEXT NOT NULL,
             dismissed_at TEXT
           )"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_waitlist_provider
           ON waitlist_requests(provider_id, created_at)"""
    )
    if not _has_column(conn, "waitlist_requests", "dismissed_at"):
        conn.execute("ALTER TABLE waitlist_requests ADD COLUMN dismissed_at TEXT")
    if not _has_column(conn, "network_links", "category"):
        conn.execute("ALTER TABLE network_links ADD COLUMN category TEXT NOT NULL DEFAULT 'general'")
    if not _has_column(conn, "network_invites", "category"):
        conn.execute("ALTER TABLE network_invites ADD COLUMN category TEXT NOT NULL DEFAULT 'general'")
    ensure_demo_usernames(conn)
    ensure_jason(conn)
    ensure_elena_referral_categories(conn)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS reminders (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             appointment_id INTEGER NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
             kind TEXT NOT NULL,
             audience TEXT NOT NULL,
             send_at TEXT NOT NULL,
             status TEXT NOT NULL DEFAULT 'pending',
             sent_at TEXT,
             last_error TEXT DEFAULT '',
             created_at TEXT NOT NULL
           )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, send_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_appt ON reminders(appointment_id)")
    conn.commit()


def ensure_demo_usernames(conn: sqlite3.Connection) -> None:
    for slug, uname in (
        ("elena-vasquez-lpc", "elena"),
        ("james-okonkwo-lcsw", "james"),
        ("maya-chen-lmft", "maya"),
    ):
        conn.execute(
            """UPDATE users SET
                 username = CASE WHEN username IS NULL OR username = '' THEN ? ELSE username END,
                 setup_complete = 1
               WHERE slug=?""",
            (uname, slug),
        )


def ensure_jason(conn: sqlite3.Connection) -> None:
    """Insert Jason Cheney once. If he exists, leave password and calendar alone."""
    existing = conn.execute(
        """SELECT * FROM users
           WHERE lower(COALESCE(username,'')) = 'jasoncheney'
              OR lower(email) = 'jasoncheney@scheduleavisit.example'
              OR slug = 'jason-cheney'"""
    ).fetchone()
    if existing:
        jason_id = existing["id"]
        if not (existing["username"] if "username" in existing.keys() else None):
            try:
                conn.execute("UPDATE users SET username='jasoncheney' WHERE id=?", (jason_id,))
            except sqlite3.IntegrityError:
                pass
    else:
        slug = "jason-cheney"
        n = 2
        while conn.execute("SELECT 1 FROM users WHERE slug=?", (slug,)).fetchone():
            slug = f"jason-cheney-{n}"
            n += 1
        cur = conn.execute(
            """INSERT INTO users (
                 email, password_hash, name, credentials, title, specialty, about, clinic, address,
                 slug, weekly_target_hours, buffer_hours, workdays, slot_start, slot_end, lunch,
                 session_minutes, timezone, created_at, username, setup_complete, consult_minutes,
                 consult_enabled, portal_kind, portal_url
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "jasoncheney@scheduleavisit.example",
                hash_password("123456"),
                "Jason Cheney",
                "Therapist",
                "Counselor",
                "Counseling — edit this in setup",
                "A short about you can rewrite in setup.",
                "My practice",
                "Boulder, CO",
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
                "jasoncheney",
                0,
                15,
                1,
                "none",
                "",
            ),
        )
        jason_id = int(cur.lastrowid)
        print("[seed] Jason Cheney ready. Username: jasoncheney  Password: 123456", flush=True)

    for slug in ("elena-vasquez-lpc", "james-okonkwo-lcsw", "maya-chen-lmft"):
        peer = conn.execute("SELECT id FROM users WHERE slug=?", (slug,)).fetchone()
        if peer:
            add_link(conn, jason_id, peer["id"])


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
    migrate(conn)
    elena = conn.execute("SELECT 1 FROM users WHERE slug='elena-vasquez-lpc'").fetchone()
    if elena is None:
        seed(conn)
        conn.commit()
    ensure_jason(conn)
    conn.commit()


def notify(conn: sqlite3.Connection, user_id: int, kind: str, title: str, body: str) -> None:
    conn.execute(
        "INSERT INTO notifications (user_id, kind, title, body, created_at) VALUES (?,?,?,?,?)",
        (user_id, kind, title, body, now_iso()),
    )
    print(f"[notify] user_id={user_id} kind={kind} | {title} — {body}", flush=True)


def add_link(conn: sqlite3.Connection, a: int, b: int, category: str = "general") -> None:
    cat = normalize_category(category)
    conn.execute(
        "INSERT OR IGNORE INTO network_links (user_id, peer_id, category) VALUES (?,?,?)",
        (a, b, cat),
    )
    conn.execute(
        "INSERT OR IGNORE INTO network_links (user_id, peer_id, category) VALUES (?,?,?)",
        (b, a, "general"),
    )


def outgoing_recommend_count(conn: sqlite3.Connection, user_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM network_links WHERE user_id=?",
        (user_id,),
    ).fetchone()
    return int(row["c"]) if row else 0


def set_link_category(conn: sqlite3.Connection, user_id: int, peer_id: int, category: str) -> None:
    conn.execute(
        "UPDATE network_links SET category=? WHERE user_id=? AND peer_id=?",
        (normalize_category(category), user_id, peer_id),
    )


def add_recommendation(conn: sqlite3.Connection, user_id: int, peer_id: int, category: str = "general") -> str | None:
    if user_id == peer_id:
        return "You cannot recommend yourself."
    existing = conn.execute(
        "SELECT id FROM network_links WHERE user_id=? AND peer_id=?",
        (user_id, peer_id),
    ).fetchone()
    if existing:
        set_link_category(conn, user_id, peer_id, category)
        return None
    if outgoing_recommend_count(conn, user_id) >= MAX_RECOMMENDATIONS:
        return f"You can recommend up to {MAX_RECOMMENDATIONS} colleagues."
    add_link(conn, user_id, peer_id, category=category)
    set_link_category(conn, user_id, peer_id, category)
    return None


def ensure_elena_referral_categories(conn: sqlite3.Connection) -> None:
    elena = conn.execute("SELECT id FROM users WHERE slug=?", ("elena-vasquez-lpc",)).fetchone()
    if not elena:
        return
    for slug, cat in (("james-okonkwo-lcsw", "general"), ("maya-chen-lmft", "couples")):
        peer = conn.execute("SELECT id FROM users WHERE slug=?", (slug,)).fetchone()
        if peer:
            add_link(conn, elena["id"], peer["id"], category=cat)
            set_link_category(conn, elena["id"], peer["id"], cat)



def add_client(conn, provider_id: int, name: str, email: str = "", dismissed_at: str | None = None, phone: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO clients (provider_id, name, email, phone, created_at, dismissed_at) VALUES (?,?,?,?,?,?)",
        (provider_id, name, email, phone or "", now_iso(), dismissed_at),
    )
    return int(cur.lastrowid)


def new_public_token() -> str:
    """Unguessable confirmation token. Never a raw integer, so /booked/1 stays dark."""
    while True:
        token = secrets.token_urlsafe(24)
        if token and not token.isdigit():
            return token


def backfill_appointment_tokens(conn: sqlite3.Connection) -> None:
    """Give existing rows a secret token. Small ALTER + UPDATE; does not wipe users."""
    if not _has_column(conn, "appointments", "public_token"):
        return
    rows = conn.execute(
        "SELECT id FROM appointments WHERE public_token IS NULL OR public_token = ''"
    ).fetchall()
    for r in rows:
        conn.execute(
            "UPDATE appointments SET public_token=? WHERE id=?",
            (new_public_token(), r["id"]),
        )


def add_appt(conn, provider_id: int, client_id: int | None, d: date, hhmm: str, minutes: int, via: str = "direct") -> int:
    start = at_local(d, hhmm)
    cur = conn.execute(
        """INSERT INTO appointments
           (provider_id, client_id, start_iso, duration_minutes, status, booked_via, created_at, public_token)
           VALUES (?,?,?,?, 'booked', ?, ?, ?)""",
        (provider_id, client_id, start.isoformat(timespec="seconds"), minutes, via, now_iso(), new_public_token()),
    )
    return int(cur.lastrowid)


def seed(conn: sqlite3.Connection) -> None:
    """Three demo providers. Elena is nearly full this week so a 50-min visit overflows."""
    pw = hash_password("demo1234")
    created = now_iso()
    week = start_of_week(today())

    providers = [
        {
            "email": "elena@sageandstone.example",
            "name": "Elena Vasquez, LPC",
            "credentials": "LPC",
            "title": "Licensed Professional Counselor",
            "specialty": "Adult therapy — anxiety, burnout, life transitions",
            "about": (
                "I work with adults who are carrying too much and still showing up. "
                "Sessions are 50 minutes. When my week is full, I will not leave you without a next step "
                "— I refer to people I would send my own family to."
            ),
            "clinic": "Sage & Stone Counseling",
            "address": "2145 Canyon Blvd, Boulder, CO",
            "slug": "elena-vasquez-lpc",
            "weekly_target_hours": 25,
            "buffer_hours": 3,
            "workdays": [1, 2, 3, 4, 5],
            "slot_start": 9,
            "slot_end": 17,
            "lunch": 12,
            "session_minutes": 50,
        },
        {
            "email": "james@northcreek.example",
            "name": "James Okonkwo, LCSW",
            "credentials": "LCSW",
            "title": "Licensed Clinical Social Worker",
            "specialty": "Counseling — stress, grief, and relationships",
            "about": "Straightforward, warm counseling for adults. I keep room in the week on purpose so new people can get in.",
            "clinic": "North Creek Therapy",
            "address": "500 Eldorado Blvd, Superior, CO",
            "slug": "james-okonkwo-lcsw",
            "weekly_target_hours": 28,
            "buffer_hours": 3,
            "workdays": [1, 2, 3, 4, 5],
            "slot_start": 9,
            "slot_end": 17,
            "lunch": 12,
            "session_minutes": 50,
        },
        {
            "email": "maya@riverview.example",
            "name": "Maya Chen, LMFT",
            "credentials": "LMFT",
            "title": "Licensed Marriage and Family Therapist",
            "specialty": "Couples and family therapy",
            "about": "I help couples and families slow down and actually hear each other. Sessions are 50 minutes; longer visits can be arranged.",
            "clinic": "Riverview Family Therapy",
            "address": "1011 Walnut St, Boulder, CO",
            "slug": "maya-chen-lmft",
            "weekly_target_hours": 24,
            "buffer_hours": 2,
            "workdays": [1, 2, 3, 4, 5],
            "slot_start": 10,
            "slot_end": 18,
            "lunch": 13,
            "session_minutes": 50,
        },
    ]

    ids = {}
    for p in providers:
        uname = {"elena-vasquez-lpc": "elena", "james-okonkwo-lcsw": "james", "maya-chen-lmft": "maya"}.get(p["slug"], "")
        cur = conn.execute(
            """INSERT INTO users (
                 email, password_hash, name, credentials, title, specialty, about, clinic, address,
                 slug, weekly_target_hours, buffer_hours, workdays, slot_start, slot_end, lunch,
                 session_minutes, timezone, created_at, username, setup_complete, consult_minutes,
                 consult_enabled, portal_kind, portal_url
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                p["email"], pw, p["name"], p["credentials"], p["title"], p["specialty"], p["about"],
                p["clinic"], p["address"], p["slug"], p["weekly_target_hours"], p["buffer_hours"],
                json.dumps(p["workdays"]), p["slot_start"], p["slot_end"], p["lunch"],
                p["session_minutes"], "America/Denver", created,
                uname, 1, 15, 1, "none", "",
            ),
        )
        ids[p["slug"]] = int(cur.lastrowid)

    elena, james, maya = ids["elena-vasquez-lpc"], ids["james-okonkwo-lcsw"], ids["maya-chen-lmft"]
    add_link(conn, elena, james, category="general")
    add_link(conn, elena, maya, category="couples")
    set_link_category(conn, elena, james, "general")
    set_link_category(conn, elena, maya, "couples")

    # Elena caseload: mix of weekly / biweekly / occasional + one dismissed client.
    # Slot map packs the week without collisions. History is real appointments so
    # labels are inferred, not tagged.
    caseload = [
        {"key": "marcus", "name": "Marcus Hale", "email": "marcus.hale@example.com",
         "pattern": "weekly", "minutes": 50, "slots": [(2, "09:00"), (5, "09:00")]},
        {"key": "sofia", "name": "Sofia Reyes", "email": "sofia.reyes@example.com",
         "pattern": "weekly", "minutes": 50, "slots": [(2, "10:00"), (5, "10:00")]},
        {"key": "david", "name": "David Kim", "email": "david.kim@example.com",
         "pattern": "weekly", "minutes": 50, "slots": [(3, "09:00"), (4, "09:00")]},
        {"key": "amara", "name": "Amara Johnson", "email": "amara.johnson@example.com",
         "pattern": "weekly", "minutes": 50, "slots": [(3, "10:00"), (4, "10:00")]},
        {"key": "luis", "name": "Luis Navarro", "email": "luis.navarro@example.com",
         "pattern": "weekly", "minutes": 50, "slots": [(1, "09:00"), (3, "13:00")]},
        {"key": "hannah", "name": "Hannah Brooks", "email": "hannah.brooks@example.com",
         "pattern": "weekly", "minutes": 80, "slots": [(1, "10:00")]},
        {"key": "owen", "name": "Owen Patel", "email": "owen.patel@example.com",
         "pattern": "biweekly", "minutes": 50, "slots": [(1, "14:00")]},
        {"key": "claire", "name": "Claire Nguyen", "email": "claire.nguyen@example.com",
         "pattern": "weekly", "minutes": 50, "slots": [(2, "13:00"), (4, "13:00")]},
        {"key": "jordan", "name": "Jordan Ellis", "email": "jordan.ellis@example.com",
         "pattern": "occasional", "minutes": 50, "slots": [(4, "14:00")]},
        {"key": "samira", "name": "Samira Haddad", "email": "samira.haddad@example.com",
         "pattern": "weekly", "minutes": 50, "slots": [(1, "13:00"), (2, "14:00")]},
        {"key": "ben", "name": "Ben Ortiz", "email": "ben.ortiz@example.com",
         "pattern": "weekly", "minutes": 80, "slots": [(3, "14:00")]},
        {"key": "riley", "name": "Riley Thompson", "email": "riley.thompson@example.com",
         "pattern": "occasional", "minutes": 50, "slots": [(5, "11:00")]},
    ]

    client_ids = {}
    for c in caseload:
        client_ids[c["key"]] = add_client(conn, elena, c["name"], c["email"])

    dismissed_week = week - timedelta(days=7)
    casey_id = add_client(
        conn, elena, "Casey Moon", "casey.moon@example.com",
        dismissed_at=at_local(dismissed_week + timedelta(days=2), "09:00").isoformat(timespec="seconds"),
    )

    def history_weeks(pattern: str):
        if pattern == "occasional":
            return [3, 7, 12]
        if pattern == "biweekly":
            return list(range(2, 17, 2))
        return list(range(1, 13))

    for c in caseload:
        cid = client_ids[c["key"]]
        for back in history_weeks(c["pattern"]):
            ws = week - timedelta(days=7 * back)
            for wd, hhmm in c["slots"]:
                add_appt(conn, elena, cid, date_on_weekday(ws, wd), hhmm, c["minutes"])

    # Casey was weekly on Monday 16:00 until last month — dismissed, no future load.
    for back in range(4, 16):
        ws = week - timedelta(days=7 * back)
        add_appt(conn, elena, casey_id, date_on_weekday(ws, 1), "16:00", 50)

    # Future + this week for recurring clients (8-week look-ahead + this week).
    for w in range(0, 9):
        ws = week + timedelta(days=7 * w)
        for c in caseload:
            if c["pattern"] == "occasional":
                if w == 0:
                    for wd, hhmm in c["slots"]:
                        add_appt(conn, elena, client_ids[c["key"]], date_on_weekday(ws, wd), hhmm, c["minutes"])
                continue
            if c["pattern"] == "biweekly" and w % 2 != 0:
                continue
            for wd, hhmm in c["slots"]:
                add_appt(conn, elena, client_ids[c["key"]], date_on_weekday(ws, wd), hhmm, c["minutes"])

        # Standing weekly clinical blocks (not a caseload person).
        group_id = None
        add_appt(conn, elena, group_id, date_on_weekday(ws, 5), "14:00", 50)
        add_appt(conn, elena, group_id, date_on_weekday(ws, 4), "16:00", 50)

    # One-off extras this week so projected hours land ~24.8 / 25.
    extras = [
        ("Avery Cole", "avery.cole@example.com", 1, "15:00", 50),
        ("Noah Grant", "noah.grant@example.com", 5, "13:00", 50),
        ("Priya Consult", "priya.note@example.com", 2, "15:00", 50),
    ]
    # Jordan already has Thu 14:00; crisis hold is a second 50 on Thu 15:00 (same person, one-off extra).
    crisis = add_client(conn, elena, "Jordan Ellis (crisis hold)", "jordan.ellis+crisis@example.com")
    add_appt(conn, elena, crisis, date_on_weekday(week, 4), "15:00", 50)
    for name, email, wd, hhmm, mins in extras:
        cid = add_client(conn, elena, name, email)
        add_appt(conn, elena, cid, date_on_weekday(week, wd), hhmm, mins)

    # Weeks 1 and 3 get extra admin so a new weekly client overflows those weeks too.
    for w in (1, 3):
        ws = week + timedelta(days=7 * w)
        for name, wd, hhmm, mins in [
            ("Group supervision block", 5, "13:00", 80),
            ("Court letter / paperwork clinic", 5, "15:00", 50),
            ("School consult — Ben Ortiz", 4, "15:00", 50),
            ("Intake overflow — Dana Ruiz", 1, "15:00", 50),
            ("Collateral calls", 1, "16:00", 50),
            ("Hospital follow-up note", 2, "15:00", 50),
        ]:
            add_appt(conn, elena, None, date_on_weekday(ws, wd), hhmm, mins)

    # James — light recurring caseload, plenty of room.
    james_people = [
        ("Tom Alvarez", "tom.alvarez@example.com", 2, "10:00", 50),
        ("Keisha Brown", "keisha.brown@example.com", 3, "11:00", 50),
        ("Peter Walsh", "peter.walsh@example.com", 4, "14:00", 50),
    ]
    for name, email, wd, hhmm, mins in james_people:
        cid = add_client(conn, james, name, email)
        for back in range(1, 13):
            ws = week - timedelta(days=7 * back)
            add_appt(conn, james, cid, date_on_weekday(ws, wd), hhmm, mins)
        for w in range(0, 9):
            ws = week + timedelta(days=7 * w)
            add_appt(conn, james, cid, date_on_weekday(ws, wd), hhmm, mins)

    # Maya — three standing couples, has room. 80-min visits.
    maya_people = [
        ("The Harpers", "harpers@example.com", 1, "10:00", 80),
        ("Lin & Park", "lin.park@example.com", 2, "14:00", 80),
        ("Diego & Ana R.", "diego.ana@example.com", 3, "10:00", 80),
    ]
    for name, email, wd, hhmm, mins in maya_people:
        cid = add_client(conn, maya, name, email)
        for back in range(1, 13):
            ws = week - timedelta(days=7 * back)
            add_appt(conn, maya, cid, date_on_weekday(ws, wd), hhmm, mins)
        for w in range(0, 9):
            ws = week + timedelta(days=7 * w)
            add_appt(conn, maya, cid, date_on_weekday(ws, wd), hhmm, mins)

    notify(
        conn, elena, "welcome",
        "Your week is nearly full",
        "Projected hours this week sit just under your 25-hour cap. A new 50-minute visit will overflow — the booking page will offer James or Maya.",
    )
    print("[seed] Demo providers ready: Elena, James, Maya. Password: demo1234", flush=True)
    ensure_jason(conn)
