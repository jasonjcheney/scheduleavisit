# ScheduleAVisit.com

Book a visit in seconds — even when your therapist is full.

Live demo: **https://scheduleavisit.onrender.com**

One public booking link for counselors and therapists. Providers set a weekly clinical hour cap (plus a paperwork buffer). Clients open the link, pick a time, and are never left at a dead end.

## Demo logins

| Who | Username | Password | Public page |
|---|---|---|---|
| Jason Cheney | `jasoncheney` | `123456` | `/p/jason-cheney` |
| Elena Vasquez, LPC | `Elena` | `demo1234` | `/p/elena-vasquez-lpc` |

Login also accepts email or first name (`jason` works for Jason). Elena’s peers James and Maya use `demo1234` too.

## Referral

When a provider hits their weekly cap, the booking page does not say “not taking new patients.” It offers a trusted colleague from their network — and if that peer is also full, it keeps walking peers of peers (multi-hop) until someone has room.

## Waitlist

If the whole reachable network is full, the client can leave a name and email on a calm waitlist. That request is stored and shown on the provider’s dashboard (notification + list). No email or SMS is sent yet.

## Run locally

```bash
cd /workspace/scheduleavisit
python3 -m pip install -r requirements.txt
python3 -m uvicorn app:app --host 0.0.0.0 --port 8080
```

Open `http://127.0.0.1:8080`. SQLite lives at `data/app.db` (or `$SAV_DB`).

## What this is / is not

**Is:** capacity math on the server, month calendar with click-to-add clients, optional iCal busy import, consult vs full session, referral invites, waitlist capture.

**Is not:** HIPAA / BAA, payments, insurance, real email/SMS, Uber API keys, or scheduleavisit.com DNS.

Stack: Python 3, FastAPI, SQLite, Jinja2, vanilla JS.
