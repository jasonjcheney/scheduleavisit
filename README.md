# ScheduleAVisit.com

A working booking app for independent counselors, therapists, and doctors.

Clients get one public link. Providers set a weekly hour cap (plus a paperwork / emergency buffer). If they are full, the client is not sent away — they see one recommended peer, then a quiet “See more options.”

This is **not** a HIPAA product, not wired to real email or Uber APIs, and not on scheduleavisit.com DNS.

## How to run

From this folder, on the Linux box:

```bash
cd /workspace/scheduleavisit
python3 -m pip install -r requirements.txt
python3 -m uvicorn app:app --host 0.0.0.0 --port 8080
```


If `pip` refuses to install because the system Python is externally managed:

```bash
python3 -m pip install --break-system-packages -r requirements.txt
```

On this box a user pip config already allows the command without that flag.

Then open `http://127.0.0.1:8080` (or the machine’s address on port 8080).

The SQLite file is created on first boot at `data/app.db`. Delete that file and restart if you want a clean seed.

## Demo logins

All three seeded providers use the password `demo1234`.

| Name | Email | Slug | Notes |
|---|---|---|---|
| Elena Vasquez, LPC | elena@sageandstone.example | `/p/elena-vasquez-lpc` | Target 25 hrs, buffer 3. Nearly full this week. |
| James Okonkwo, LCSW | james@northcreek.example | `/p/james-okonkwo-lcsw` | Has room. Superior, CO (~4 miles). |
| Maya Chen, LMFT | maya@riverview.example | `/p/maya-chen-lmft` | Has room. Boulder (~2 miles). |

On the login page you can type **Elena** / **demo1234** (first name works for the three demo accounts).

Brand-new signup does not depend on the seed. Create an account, set a 10-hour cap on the dashboard, share `/p/{your-slug}`.

## What is real

- Capacity is computed on the server. A new visit of N minutes is allowed only if  
  `booked this week + inferred recurring load + buffer + N/60 <= weekly target`.
- Recurring vs occasional is inferred from visit history. Providers do not tag each client.
- A new weekly client is allowed only if every one of the next 8 weeks stays under the cap.
- Referral network: invite by email, accept at `/invite/{token}`. Both directions are stored. When the requested provider is full, the booking API returns one recommendation plus alternatives.
- Notifications are written to the dashboard and printed to the server log. There is no SMTP.
- Cancel on the dashboard marks the visit cancelled so the slot can be booked again.

## Out of scope (not pretended)

- HIPAA BAA / production compliance
- Real Uber / Lyft API keys (the ride page is maps + public deep links)
- Android app
- scheduleavisit.com DNS
- Payments / insurance
- Transactional email

## Stack

Python 3, FastAPI, SQLite (`stdlib sqlite3`), Jinja2, vanilla JS. Passwords use `hashlib.pbkdf2_hmac` (no bcrypt dependency).
