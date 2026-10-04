# ScheduleAVisit.com

Book a visit in seconds — even when your therapist is full.

Live demo: **https://scheduleavisit.onrender.com**

One public booking link for counselors and therapists. Providers set a weekly clinical hour cap (plus a paperwork buffer). Clients open the link, pick a time, and are never left at a dead end.

## Demo logins

Seeded accounts are created on first boot. Passwords are not written in this repo. Set `SAV_JASON_PASSWORD` for the founder account and `SAV_DEMO_PASSWORD` for the sample counselors before starting the app. If either variable is unset, that account gets a random password that is not printed. An account that already exists keeps its password.

| Who | Username | Public page |
|---|---|---|
| Jason Cheney | `jasoncheney` | `/p/jason-cheney` |
| Elena Vasquez, LPC | `Elena` | `/p/elena-vasquez-lpc` |

Login also accepts email or first name (`jason` works for Jason). James and Maya use `SAV_DEMO_PASSWORD` as well. Sample counselors stay off the public directory unless `SHOW_DEMO_COUNSELORS` is set.

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

**Is:** capacity math on the server, month calendar with click-to-add clients, optional Google Calendar (two-way) plus iCal busy import, consult vs full session, referral invites, waitlist capture.

**Is not:** HIPAA / BAA, payments, insurance, real email/SMS, Uber API keys, or scheduleavisit.com DNS.

Therapists can upload a JPEG/PNG/WebP photo (or pull one from a Psychology Today / personal page they paste) on setup. Photos live on the Render disk under `data/uploads/avatars/` and show on the public booking page, directory, and referral cards. Initials stay as the fallback.

Google Calendar needs three environment variables (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`). Setup steps: [docs/google-calendar.md](docs/google-calendar.md). The Google OAuth client must list **both** `scheduleavisit.com` and `scheduleavisit.onrender.com` origins plus redirect URIs. Connect on `.com` stays on `.com` so login cookies are not dropped. Without the env vars, therapists still see an honest “not set up yet” note and can paste an iCal link.

Stack: Python 3, FastAPI, SQLite, Jinja2, vanilla JS.
