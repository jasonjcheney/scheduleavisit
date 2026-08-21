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

The SQLite file is created on first boot at `data/app.db` (or `$SAV_DB`). Existing databases pick up new columns via `migrate()` — you do not need to delete the file. Delete it and restart only if you want a clean seed.

## Demo logins

Elena, James, and Maya use the password `demo1234`. Jason uses `123456`.

| Name | Login | Slug | Notes |
|---|---|---|---|
| Jason Cheney | `jasoncheney` / `123456` | `/p/jason-cheney` | Real therapist account. First login opens `/setup`. Empty calendar. |
| Elena Vasquez, LPC | Elena / `demo1234` | `/p/elena-vasquez-lpc` | Target 25 hrs, buffer 3. Nearly full this week. |
| James Okonkwo, LCSW | James / `demo1234` | `/p/james-okonkwo-lcsw` | Has room. Superior, CO (~4 miles). |
| Maya Chen, LMFT | Maya / `demo1234` | `/p/maya-chen-lmft` | Has room. Boulder (~2 miles). |

Login accepts **username**, **email**, or **first name**. `jason` and `jasoncheney` both reach Jason.

First login as Jason (or any new signup) opens the setup page at `/setup` — name, hours, client portal link, optional iCal URL. Dashboard has **Edit my page** to reopen it.

Brand-new signup collects name, username, email, and password, then lands on setup.

### Booking: consult vs session

On `/p/{slug}`, a first-time client picks a free consultation or a full session. Returning clients (same email, already booked) are booked as a full session. After a first booking, if you pasted a portal URL in setup, the confirmation page shows **Get started on the online portal**.

### Month calendar

The dashboard month calendar lets you click a day, type a client name and time, and save. That creates a client and a manual block that counts toward weekly hours. Sage = booked on your public link, terracotta = you added, blue = imported from iCal.

### iCal busy import

Paste a secret ICS URL in setup. We fetch it at most every 15 minutes and treat events as busy time (they occupy slots and count toward the cap). There is no Google sign-in.

## What is real

- Capacity is computed on the server. A new visit of N minutes is allowed only if  
  `booked this week + inferred recurring load + buffer + N/60 <= weekly target`.
- Recurring vs occasional is inferred from visit history. Providers do not tag each client.
- A new weekly client is allowed only if every one of the next 8 weeks stays under the cap.
- Referral network: invite by email, accept at `/invite/{token}`. Both directions are stored. When the requested provider is full, the booking API returns one recommendation plus alternatives.
- Notifications are written to the dashboard and printed to the server log. There is no SMTP.
- Cancel on the dashboard marks the visit cancelled so the slot can be booked again.
- Click-to-add on the month calendar stores a named client (`booked_via=manual`) and counts the minutes.
- An iCal URL, if set, is imported as `booked_via=ical` busy blocks.

## Out of scope (not pretended)

- HIPAA BAA / production compliance
- Real Uber / Lyft API keys (the ride page is maps + public deep links)
- Android app
- scheduleavisit.com DNS
- Payments / insurance
- Transactional email

## Stack

Python 3, FastAPI, SQLite (`stdlib sqlite3`), Jinja2, vanilla JS. Passwords use `hashlib.pbkdf2_hmac` (no bcrypt dependency).
