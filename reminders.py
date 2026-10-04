"""Appointment reminders: schedule rows, email/SMS adapters, tick send.

Sending is best-effort. Missing mail/SMS env is a no-op — booking must still succeed.
Copy is scheduling-only: names, date/time, clinic/address. No clinical notes.
"""
from __future__ import annotations

import os
import smtplib
from datetime import datetime, time, timedelta
from email.message import EmailMessage
from typing import Any

from capacity import first_name, format_long, format_time
from db import TZ, now_dt, now_iso, parse_iso

KINDS = ("booked", "day_before", "morning_of")
AUDIENCES = ("client", "therapist")
FOOTER = "This is a scheduling reminder only."
TICK_HEADER = "X-Reminder-Secret"
TICK_ENV = "REMINDER_TICK_SECRET"


def reminder_times(start: datetime, now: datetime | None = None) -> dict[str, datetime]:
    """booked = now; day_before ≈ 24h before start; morning_of = 8:00am Denver that date."""
    start = start.astimezone(TZ)
    when = now.astimezone(TZ) if now is not None else now_dt()
    return {
        "booked": when,
        "day_before": start - timedelta(hours=24),
        "morning_of": datetime.combine(start.date(), time(8, 0), tzinfo=TZ),
    }


def normalize_phone(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return ""
    if s.startswith("+"):
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return "+" + digits


def from_address() -> str:
    """Verified sender. No placeholder — a missing address means we do not send."""
    return (
        os.environ.get("EMAIL_FROM")
        or os.environ.get("MAIL_FROM")
        or os.environ.get("RESEND_FROM")
        or os.environ.get("SMTP_FROM")
        or ""
    ).strip()


def _resend_ready() -> bool:
    return bool((os.environ.get("RESEND_API_KEY") or "").strip() and from_address())


def _mailgun_ready() -> bool:
    domain = (os.environ.get("MAILGUN_DOMAIN") or os.environ.get("MAILGUN_API_DOMAIN") or "").strip()
    return bool((os.environ.get("MAILGUN_API_KEY") or "").strip() and domain and from_address())


def _smtp_ready() -> bool:
    host = (
        os.environ.get("SMTP_HOST")
        or os.environ.get("SMTP_SERVER")
        or os.environ.get("SMTP_URL")
        or ""
    ).strip()
    return bool(host and from_address())


def email_provider() -> str:
    """Which HTTPS/SMTP sender is fully configured. Resend is the one we document."""
    if _resend_ready():
        return "resend"
    if _mailgun_ready():
        return "mailgun"
    if _smtp_ready():
        return "smtp"
    return ""


def email_unconfigured_reason() -> str:
    """Plain reason safe to log. Empty when a provider can send. Never includes secrets."""
    if email_provider():
        return ""
    if (os.environ.get("RESEND_API_KEY") or "").strip() and not from_address():
        return "EMAIL_FROM is not set"
    if (os.environ.get("MAILGUN_API_KEY") or "").strip():
        if not (os.environ.get("MAILGUN_DOMAIN") or os.environ.get("MAILGUN_API_DOMAIN") or "").strip():
            return "MAILGUN_DOMAIN is not set"
        if not from_address():
            return "EMAIL_FROM is not set"
    host = os.environ.get("SMTP_HOST") or os.environ.get("SMTP_SERVER") or os.environ.get("SMTP_URL")
    if (host or "").strip() and not from_address():
        return "EMAIL_FROM is not set"
    return "RESEND_API_KEY is not set"


def email_configured() -> bool:
    return email_unconfigured_reason() == ""


def public_base() -> str:
    raw = (os.environ.get("PUBLIC_BASE_URL") or "https://scheduleavisit.com").strip()
    if not raw:
        raw = "https://scheduleavisit.com"
    if "://" not in raw:
        raw = "https://" + raw
    return raw.rstrip("/")


def sms_configured() -> bool:
    return bool(
        os.environ.get("TWILIO_ACCOUNT_SID")
        and os.environ.get("TWILIO_AUTH_TOKEN")
        and os.environ.get("TWILIO_FROM")
    )


def mail_from() -> str:
    return from_address()


def place_line(clinic: str = "", address: str = "") -> str:
    parts = [p.strip() for p in (clinic or "", address or "") if p and str(p).strip()]
    return ", ".join(parts)


def build_copy(
    kind: str,
    audience: str,
    *,
    client_first: str,
    therapist_name: str,
    start: datetime,
    clinic: str = "",
    address: str = "",
    link: str = "",
    fee_note: str = "",
) -> tuple[str, str, str]:
    """Return (subject, email_body, sms_body). Scheduling facts only."""
    start = start.astimezone(TZ)
    when = f"{format_long(start.date())} at {format_time(start.strftime('%H:%M'))}"
    place = place_line(clinic, address)
    place_sentence = f" {place}." if place else ""
    who = (client_first or "there").strip() or "there"
    therapist = (therapist_name or "your therapist").strip()

    if kind == "booked":
        if audience == "therapist":
            subject = f"New booking — {format_long(start.date())}"
            lead = f"{who} booked a visit with you on {when}.{place_sentence}"
        else:
            subject = f"Visit booked — {format_long(start.date())}"
            lead = f"Hi {who} — you're on the calendar with {therapist} on {when}.{place_sentence}"
    elif kind == "day_before":
        if audience == "therapist":
            subject = f"Visit tomorrow — {format_long(start.date())}"
            lead = f"Reminder: {who} is on your calendar tomorrow, {when}.{place_sentence}"
        else:
            subject = f"Visit tomorrow — {format_long(start.date())}"
            lead = f"Hi {who} — a reminder: your visit with {therapist} is tomorrow, {when}.{place_sentence}"
    else:
        if audience == "therapist":
            subject = f"Visit today — {format_time(start.strftime('%H:%M'))}"
            lead = f"Reminder: {who} is on your calendar today at {format_time(start.strftime('%H:%M'))}.{place_sentence}"
        else:
            subject = f"Visit today — {format_time(start.strftime('%H:%M'))}"
            lead = f"Hi {who} — your visit with {therapist} is today at {format_time(start.strftime('%H:%M'))}.{place_sentence}"

    link = (link or "").strip()
    if link and kind == "booked" and audience == "client":
        link_block = f"\n\nYou can view or change this visit here:\n{link}"
    elif link and kind == "booked" and audience == "therapist":
        link_block = f"\n\nSee your schedule:\n{link}"
    elif link:
        link_block = f"\n\nDetails:\n{link}"
    else:
        link_block = ""
    fee_note = (fee_note or "").strip()
    fee_block = f"\n\n{fee_note}" if fee_note and kind == "booked" and audience == "client" else ""
    email_body = f"{lead}{fee_block}{link_block}\n\n{FOOTER}"
    sms_body = f"{lead} {FOOTER}".strip()
    return subject, email_body, sms_body


def _row_get(r, key, default=None):
    if r is None:
        return default
    try:
        if key in r.keys():
            val = r[key]
            return default if val is None else val
    except Exception:
        pass
    return default


def cancel_pending(conn, appointment_id: int) -> int:
    cur = conn.execute(
        "UPDATE reminders SET status='cancelled' WHERE appointment_id=? AND status='pending'",
        (appointment_id,),
    )
    return int(cur.rowcount or 0)


def cancel_pending_for_client(conn, client_id: int) -> int:
    cur = conn.execute(
        """UPDATE reminders SET status='cancelled'
           WHERE status='pending' AND appointment_id IN (
             SELECT id FROM appointments WHERE client_id=? AND status='cancelled'
           )""",
        (client_id,),
    )
    return int(cur.rowcount or 0)


def schedule_for_appointment(conn, appointment_id: int, now: datetime | None = None) -> list[int]:
    """Insert confirmation and reminder rows. Later therapist copies need opt-in."""
    appt = conn.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone()
    if not appt or _row_get(appt, "status") != "booked":
        return []
    start = parse_iso(appt["start_iso"])
    times = reminder_times(start, now=now)
    provider = conn.execute("SELECT * FROM users WHERE id=?", (appt["provider_id"],)).fetchone()
    opted = bool(provider and int(_row_get(provider, "reminders_opt_in", 0) or 0) == 1)
    # Client always gets the confirmation plus the two later reminders.
    # The therapist always gets the new-booking note. Day-before and morning-of
    # copies stay behind reminders_opt_in.
    plan = [
        ("client", "booked"),
        ("client", "day_before"),
        ("client", "morning_of"),
        ("therapist", "booked"),
    ]
    if opted:
        plan.extend([("therapist", "day_before"), ("therapist", "morning_of")])
    created = now_iso()
    ids: list[int] = []
    for audience, kind in plan:
        send_at = times[kind].isoformat(timespec="seconds")
        cur = conn.execute(
            """INSERT INTO reminders
               (appointment_id, kind, audience, send_at, status, created_at)
               VALUES (?,?,?,?, 'pending', ?)""",
            (appointment_id, kind, audience, send_at, created),
        )
        ids.append(int(cur.lastrowid))
    return ids


def _context_for(conn, reminder) -> dict[str, Any] | None:
    appt = conn.execute("SELECT * FROM appointments WHERE id=?", (reminder["appointment_id"],)).fetchone()
    if not appt:
        return None
    provider = conn.execute("SELECT * FROM users WHERE id=?", (appt["provider_id"],)).fetchone()
    client = None
    if appt["client_id"]:
        client = conn.execute("SELECT * FROM clients WHERE id=?", (appt["client_id"],)).fetchone()
    start = parse_iso(appt["start_iso"])
    client_name = _row_get(client, "name", "") if client else ""
    return {
        "appt": appt,
        "provider": provider,
        "client": client,
        "start": start,
        "client_first": first_name(client_name) or "there",
        "therapist_name": _row_get(provider, "name", "your therapist") if provider else "your therapist",
        "clinic": _row_get(provider, "clinic", "") if provider else "",
        "address": _row_get(provider, "address", "") if provider else "",
        "client_email": (_row_get(client, "email", "") or "").strip() if client else "",
        "client_phone": (_row_get(client, "phone", "") or "").strip() if client else "",
        "therapist_email": (_row_get(provider, "email", "") or "").strip() if provider else "",
        "therapist_phone": (_row_get(provider, "phone", "") or "").strip() if provider else "",
        "opt_in": int(_row_get(provider, "reminders_opt_in", 0) or 0) == 1 if provider else False,
    }


def _safe_mail_error(exc: BaseException) -> str:
    """A short reason for the log. Drops anything that could be a key or body."""
    msg = str(exc or "")
    low = msg.lower()
    if any(token in low for token in ("bearer", "api_key", "apikey", "re_", "secret", "password")):
        return type(exc).__name__
    if isinstance(exc, RuntimeError) and (
        msg.startswith("resend ") or msg.startswith("mailgun ") or msg.startswith("smtp ")
    ):
        return msg[:120]
    return type(exc).__name__


def send_email(to_addr: str, subject: str, body: str) -> str:
    """Send or no-op. Returns 'sent', 'skipped', or 'failed'. Never raises."""
    to_addr = (to_addr or "").strip()
    if not to_addr or "@" not in to_addr:
        print("[email] skipped — recipient address is missing", flush=True)
        return "skipped"
    reason = email_unconfigured_reason()
    if reason:
        print(f"[email] skipped — {reason}", flush=True)
        return "skipped"
    provider = email_provider()
    try:
        if provider == "resend":
            _send_resend(to_addr, subject, body)
        elif provider == "mailgun":
            _send_mailgun(to_addr, subject, body)
        elif provider == "smtp":
            _send_smtp(to_addr, subject, body)
        else:
            print("[email] skipped — RESEND_API_KEY is not set", flush=True)
            return "skipped"
    except Exception as exc:
        print(f"[email] {provider} failed ({_safe_mail_error(exc)})", flush=True)
        return "failed"
    print(f"[email] sent via {provider}", flush=True)
    return "sent"


def send_invite_email(
    to_email: str,
    inviter_name: str,
    invite_url: str,
    clinic: str = "",
    address: str = "",
) -> str:
    """Colleague invite. Returns send_email's status. Never raises."""
    who = first_name(inviter_name) or "A colleague"
    place = place_line(clinic, address)
    where = f" ({place})" if place else ""
    subject = f"{who} invited you to their referral network"
    body = (
        f"Hi — {who}{where} invited you to join their referral network on ScheduleAVisit.\n\n"
        "When one of you is full for the week, the booking page can offer the other person's next open time.\n\n"
        f"Accept the invite:\n{invite_url}\n\n"
        "You can also ignore this note. Nothing is booked until you accept.\n\n"
        "This note is only about scheduling."
    )
    try:
        return send_email(to_email, subject, body)
    except Exception as exc:
        print(f"[email] invite failed ({type(exc).__name__})", flush=True)
        return "failed"


def send_sms(to_phone: str, body: str) -> str:
    to_phone = normalize_phone(to_phone)
    if not to_phone:
        return "skipped"
    if not sms_configured():
        print("[reminders] sms skipped — twilio env not set", flush=True)
        return "skipped"
    _send_twilio(to_phone, body)
    return "sent"


def _send_resend(to_addr: str, subject: str, body: str) -> None:
    import httpx

    key = os.environ.get("RESEND_API_KEY") or ""
    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"from": mail_from(), "to": [to_addr], "subject": subject, "text": body},
            timeout=8.0,
        )
    except Exception as exc:
        # Do not chain the httpx error: its text can include request headers.
        raise RuntimeError(f"resend {type(exc).__name__}") from None
    if resp.status_code >= 400:
        raise RuntimeError(f"resend http {resp.status_code}")


def _send_mailgun(to_addr: str, subject: str, body: str) -> None:
    import httpx

    key = os.environ.get("MAILGUN_API_KEY") or ""
    domain = os.environ.get("MAILGUN_DOMAIN") or os.environ.get("MAILGUN_API_DOMAIN") or ""
    if not domain:
        raise RuntimeError("mailgun domain missing")
    resp = httpx.post(
        f"https://api.mailgun.net/v3/{domain}/messages",
        auth=("api", key),
        data={"from": mail_from(), "to": to_addr, "subject": subject, "text": body},
        timeout=8.0,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"mailgun http {resp.status_code}")


def _send_smtp(to_addr: str, subject: str, body: str) -> None:
    host = os.environ.get("SMTP_HOST") or os.environ.get("SMTP_SERVER") or ""
    url = os.environ.get("SMTP_URL") or ""
    port = int(os.environ.get("SMTP_PORT") or 587)
    user = os.environ.get("SMTP_USER") or os.environ.get("SMTP_USERNAME") or ""
    password = os.environ.get("SMTP_PASSWORD") or ""
    if url and not host:
        # smtp://user:pass@host:port — parse host only; never log the URL (may contain creds)
        rest = url.split("://", 1)[-1]
        if "@" in rest:
            rest = rest.rsplit("@", 1)[-1]
        if ":" in rest:
            host, port_s = rest.split(":", 1)
            host = host.split("/")[0]
            try:
                port = int(port_s.split("/")[0])
            except ValueError:
                port = 587
        else:
            host = rest.split("/")[0]
    if not host:
        raise RuntimeError("smtp host missing")
    msg = EmailMessage()
    msg["From"] = mail_from()
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(host, port, timeout=8) as smtp:
        try:
            smtp.starttls()
        except Exception:
            pass
        if user and password:
            smtp.login(user, password)
        smtp.send_message(msg)


def _send_twilio(to_phone: str, body: str) -> None:
    import httpx

    sid = os.environ.get("TWILIO_ACCOUNT_SID") or ""
    token = os.environ.get("TWILIO_AUTH_TOKEN") or ""
    frm = os.environ.get("TWILIO_FROM") or ""
    resp = httpx.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        auth=(sid, token),
        data={"From": frm, "To": to_phone, "Body": body},
        timeout=8.0,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"twilio http {resp.status_code}")


def send_one(conn, reminder) -> str:
    """Attempt email and/or SMS for one pending row. Returns new status."""
    ctx = _context_for(conn, reminder)
    if not ctx:
        _mark(conn, reminder["id"], "cancelled", "appointment missing")
        return "cancelled"
    if _row_get(ctx["appt"], "status") != "booked":
        _mark(conn, reminder["id"], "cancelled", "visit not booked")
        return "cancelled"

    audience = reminder["audience"]
    # The new-booking note goes out even when the therapist has not opted into
    # the later reminders. Day-before and morning-of stay behind that checkbox.
    if audience == "therapist" and reminder["kind"] != "booked" and not ctx["opt_in"]:
        _mark(conn, reminder["id"], "skipped", "therapist not opted in")
        return "skipped"

    dest_email = ctx["client_email"] if audience == "client" else ctx["therapist_email"]
    dest_phone = ctx["client_phone"] if audience == "client" else ctx["therapist_phone"]

    base = public_base()
    token = (_row_get(ctx["appt"], "public_token", "") or "").strip()
    if audience == "client" and token:
        link = f"{base}/booked/{token}"
    elif audience == "therapist":
        link = f"{base}/dashboard"
    else:
        link = ""

    fee_note = ""
    if reminder["kind"] == "booked" and audience == "client":
        cents = int(_row_get(ctx["appt"], "fee_cents", 0) or 0)
        state = (_row_get(ctx["appt"], "fee_state", "") or "").strip()
        window = int(_row_get(ctx["appt"], "fee_window_hours", 0) or 0)
        if cents > 0 and state == "card_saved" and window > 0:
            from fees import money_label

            fee_note = (
                f"A card is saved for the missed first-visit fee you agreed to "
                f"({money_label(cents)}). You were not charged. "
                f"If you miss this visit or cancel less than {window} hours before it starts, "
                f"{ctx['therapist_name']} may charge that card once. "
                "The money is paid to them. Stripe emails a receipt if that happens."
            )
    subject, email_body, sms_body = build_copy(
        reminder["kind"],
        audience,
        client_first=ctx["client_first"],
        therapist_name=ctx["therapist_name"],
        start=ctx["start"],
        clinic=ctx["clinic"],
        address=ctx["address"],
        link=link,
        fee_note=fee_note,
    )

    sent_any = False
    configured_fail = False
    errors: list[str] = []

    if dest_email:
        try:
            result = send_email(dest_email, subject, email_body)
            if result == "sent":
                sent_any = True
                print(f"[reminders] email {reminder['kind']} {audience} appt={reminder['appointment_id']}", flush=True)
            elif result == "failed":
                configured_fail = True
                errors.append("email")
        except Exception as exc:
            configured_fail = True
            errors.append("email")
            print(f"[reminders] email failed ({type(exc).__name__})", flush=True)

    if dest_phone:
        try:
            result = send_sms(dest_phone, sms_body)
            if result == "sent":
                sent_any = True
                print(f"[reminders] sms {reminder['kind']} {audience} appt={reminder['appointment_id']}", flush=True)
        except Exception as exc:
            configured_fail = True
            errors.append("sms")
            print(f"[reminders] sms failed ({type(exc).__name__})", flush=True)

    if sent_any:
        _mark(conn, reminder["id"], "sent", "")
        return "sent"
    if configured_fail:
        _mark(conn, reminder["id"], "failed", ",".join(errors))
        return "failed"
    _mark(conn, reminder["id"], "skipped", "no destination or sender")
    return "skipped"


def _mark(conn, reminder_id: int, status: str, error: str) -> None:
    sent_at = now_iso() if status in ("sent", "skipped", "failed") else None
    conn.execute(
        "UPDATE reminders SET status=?, sent_at=?, last_error=? WHERE id=?",
        (status, sent_at, error or "", reminder_id),
    )


def send_due(conn, now: datetime | None = None, appointment_id: int | None = None, limit: int = 50) -> dict:
    """Send pending reminders whose send_at is due. Never raises to the caller."""
    when = (now or now_dt()).astimezone(TZ).isoformat(timespec="seconds")
    args: list[Any] = [when]
    sql = "SELECT * FROM reminders WHERE status='pending' AND send_at<=?"
    if appointment_id is not None:
        sql += " AND appointment_id=?"
        args.append(appointment_id)
    sql += " ORDER BY send_at, id LIMIT ?"
    args.append(int(limit))
    rows = conn.execute(sql, args).fetchall()
    counts = {"sent": 0, "skipped": 0, "failed": 0, "cancelled": 0, "pending": 0}
    for r in rows:
        try:
            status = send_one(conn, r)
        except Exception as exc:
            print(f"[reminders] send_one crashed ({type(exc).__name__})", flush=True)
            try:
                _mark(conn, r["id"], "failed", type(exc).__name__)
            except Exception:
                pass
            status = "failed"
        counts[status] = counts.get(status, 0) + 1
    counts["processed"] = len(rows)
    return counts


def after_book(conn, appointment_id: int) -> dict:
    """Create the reminder set and try to send anything already due. Never raises."""
    try:
        ids = schedule_for_appointment(conn, appointment_id)
    except Exception as exc:
        print(f"[reminders] schedule failed ({type(exc).__name__})", flush=True)
        return {"scheduled": 0, "processed": 0}
    try:
        result = send_due(conn, appointment_id=appointment_id)
    except Exception as exc:
        print(f"[reminders] send after book failed ({type(exc).__name__})", flush=True)
        result = {"processed": 0}
    result["scheduled"] = len(ids)
    return result


def after_reschedule(conn, appointment_id: int) -> dict:
    try:
        cancel_pending(conn, appointment_id)
    except Exception as exc:
        print(f"[reminders] cancel on reschedule failed ({type(exc).__name__})", flush=True)
    return after_book(conn, appointment_id)
