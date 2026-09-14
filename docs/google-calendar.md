# Connect Google Calendar (plain language)

ScheduleAVisit can read a therapist’s Google calendars so busy time is not offered to clients, and it can write new visits onto the calendar they pick. This is scheduling only — client name, time, consult vs session. No clinical notes. This is not a HIPAA product.

You need a Google Cloud project. Jason does this once on Render. Each therapist then taps **Connect Google Calendar** on Edit my page.

## 1. Turn on the Calendar API

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or pick the one already used for “Continue with Google” sign-in).
3. APIs & Services → Library → enable **Google Calendar API**.

## 2. OAuth consent screen

1. APIs & Services → OAuth consent screen.
2. User type: **External**.
3. App name: `ScheduleAVisit`. Support email: Jason’s Gmail.
4. App home / privacy: `https://scheduleavisit.com` (or `https://scheduleavisit.onrender.com`) and `/privacy`.
5. Scopes to add:
   - `https://www.googleapis.com/auth/calendar.readonly` (see when they are busy)
   - `https://www.googleapis.com/auth/calendar.events` (add / move / remove the visits booked here)
6. While the app is in **Testing**, add every therapist Gmail under **Test users**. Only those people can connect.
7. Publishing for any Google account needs Google’s review because calendar access is a sensitive scope. Stay in Testing until that is done. Do not claim HIPAA in the Google listing.

## 3. Create the web client

1. APIs & Services → Credentials → Create credentials → OAuth client ID → **Web application**.
2. Authorized JavaScript origins — list **both** live hosts (and local only if you test on your computer):
   - `https://scheduleavisit.com`
   - `https://www.scheduleavisit.com`
   - `https://scheduleavisit.onrender.com`
   - `http://127.0.0.1:8080` (only if you test on your own computer)
3. Authorized redirect URIs — list **both** the custom domain and onrender, for sign-in and for calendar:
   - `https://scheduleavisit.com/auth/google/callback` (sign-in)
   - `https://scheduleavisit.com/auth/google/calendar/callback` (calendar connect)
   - `https://scheduleavisit.onrender.com/auth/google/callback` (sign-in)
   - `https://scheduleavisit.onrender.com/auth/google/calendar/callback` (calendar connect)
   - Local extras if you need them: `http://127.0.0.1:8080/auth/google/callback` and `http://127.0.0.1:8080/auth/google/calendar/callback`
4. Copy the client ID and client secret. Do not commit them to git.

If a therapist opens **Connect Google Calendar** on scheduleavisit.com (or www), the app sends Google back to `https://scheduleavisit.com/auth/google/calendar/callback`. That keeps the login cookie on the same host. If they open Connect on the onrender URL, the app uses `GOOGLE_REDIRECT_URI` (usually the onrender callback). Google must allow both, or Connect on one host will fail.

## 4. Put the secrets on Render

Dashboard → the `scheduleavisit` web service → **Environment**. Add:

| Name | Value |
|---|---|
| `GOOGLE_CLIENT_ID` | the client ID from step 3 |
| `GOOGLE_CLIENT_SECRET` | the client secret from step 3 |
| `GOOGLE_REDIRECT_URI` | `https://scheduleavisit.onrender.com/auth/google/calendar/callback` |

Keep `GOOGLE_REDIRECT_URI` on the onrender callback. The app overrides it only when the browser is on scheduleavisit.com / www. Do not put client secrets in git.

Save and deploy. The Blueprint (`render.yaml`) lists these keys as `sync: false` so Render asks for them instead of storing secrets in git.

If `GOOGLE_REDIRECT_URI` is left as the sign-in callback (`…/auth/google/callback`), the app maps it to the calendar callback automatically. Register the onrender and `.com` URIs in Google either way.

## 5. What a therapist sees

- **Edit my page** and the dashboard: **Connect Google Calendar**.
- After they accept: pick which calendars count as busy, and which calendar receives new ScheduleAVisit bookings (default: main / primary).
- **Disconnect** forgets the Google login. iCal paste still works for Outlook, Apple, or a portal calendar.
- If the three env vars are missing, the page says so in plain language. Nothing crashes.

## 6. What we store

- An encrypted refresh token on the provider row (same SQLite file on the Render disk).
- `google_event_id` on each visit we wrote to Google, so reschedule and cancel can update that event.
- Imported busy blocks use `booked_via='google'` (same idea as iCal).

If you rotate `GOOGLE_CLIENT_SECRET`, therapists need to Connect again.

## Local test without a real Google account

The automated suite in `tests/test_google_calendar.py` mocks Google. You do not need live credentials for that.
