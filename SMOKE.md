# Smoke path (verified 20 Aug 2026, America/Denver)

Server: `python3 -m uvicorn app:app --host 127.0.0.1 --port 8080` from `/workspace/scheduleavisit`.
Updated 21 Aug 2026. Today is Friday 21 Aug 2026. Elena’s week is Mon 17 – Sun 23 Aug. Friday 21 Aug still has calendar holes at 3 pm and 4 pm; the hour cap does not.

## 1. Fresh provider can take a booking

```
POST /api/auth/signup
  {name:"Alex Rivera", credentials:"LPC", email:"alex.rivera@newclinic.example", password:"demo1234"}
  → 200 {ok:true, slug:"alex-rivera-lpc"}

PATCH /api/me
  {weekly_target_hours:10, buffer_hours:1}
  → 200 {ok:true}

GET  /api/p/alex-rivera-lpc/availability?date=2026-08-21
  → weekHasRoom true, 09:00 open

POST /api/p/alex-rivera-lpc/book
  {date:"2026-08-21", time:"09:00", name:"Pat Client", email:"pat.client@example.com"}
  → 200 {ok:true, appointmentId:…, redirect:"/booked/…"}

GET  /booked/{id}
  → 200 “You’re on the calendar.” (no fake “email sent”)
```

Also works in the browser: `/signup` → dashboard → set the cap → open `/p/{slug}` → pick a time → confirm.

## 2. Elena is full this week → James, then Maya

Login page hint: **Elena** / **demo1234** (or `elena@sageandstone.example`).

```
POST /api/auth/login {email:"Elena", password:"demo1234"} → cookie + /dashboard
GET  /dashboard → “Hello, Elena.” · badge “Nearly full” · 24.8 / 25 · Casey Moon freed-slot note
GET  /p/elena-vasquez-lpc
GET  /api/p/elena-vasquez-lpc/availability?date=2026-08-21
  → weekHasRoom false
  → 15:00 and 16:00 open (calendar holes)

POST /api/p/elena-vasquez-lpc/book
  {date:"2026-08-21", time:"15:00", name:"Sam Overflow", email:"sam.overflow@example.com"}
  → 200 {
      ok:false, full:true,
      recommendation: {peerSlug:"james-okonkwo-lcsw", name:"James Okonkwo, LCSW",
                       recommendedBy:"Elena", miles:4, date:"2026-08-21", time:"15:00",
                       rideUrl:"/ride?address=…"},
      alternatives: [{peerSlug:"maya-chen-lmft", miles:2, …}]
    }
```

UI: one referral card (James, time, “Recommended by Elena”, 4 miles, Get a ride). “See more options” reveals Maya.

```
POST /api/p/elena-vasquez-lpc/book-referral
  {peerSlug:"james-okonkwo-lcsw", date:"2026-08-21", time:"15:00",
   name:"Sam Overflow", email:"sam.overflow@example.com"}
  → 200 {ok:true, redirect:"/booked/…"}
```

## 3. Both dashboards see it

```
GET /api/me/notifications  (Elena cookie)
  → “You referred Sam Overflow to James”

GET /dashboard             (James / demo1234)
  → upcoming visit “Sam Overflow”
GET /api/me/appointments   (James)
  → Sam Overflow, booked_via=referral
```

Server log also prints `[book-referral]` and `[notify]` lines. No SMTP.

## 4. Cancel frees the slot

```
POST /api/me/appointments/{id}/cancel   (James cookie)
  → 200 {ok:true}

GET  /api/p/james-okonkwo-lcsw/availability?date=2026-08-21
  → 15:00 booked:false, open:true
```

## 5. Invite a colleague

From Elena’s dashboard invite form, or:

```
POST /api/me/network/invite {email:"priya.shah@newpeer.example"}
  → {ok:true, url:"http://127.0.0.1:8080/invite/{token}"}

POST /api/auth/signup
  {name:"Priya Shah", credentials:"MD", email:"priya.shah@newpeer.example",
   password:"demo1234", next:"/invite/{token}"}

GET  /invite/{token}   (Priya cookie)
  → “You’re in Elena’s network.”

GET  /api/me/network   (Elena cookie)
  → peers include James, Maya, and Priya Shah, MD
```

## 6. Ride page

```
GET /ride?address=500+Eldorado+Blvd,+Superior,+CO
  → Google Maps directions + Uber deep link + Lyft deep link. No paid keys.
```

## Notes

- Capacity is server-side. Friday 3 pm is open on Elena’s grid and still rejected by the cap (24.8 + 0.83 > 25).
- Later weeks on Elena can have room — that is the engine, not a bug.
- Recurring labels (Weekly / Biweekly / Occasional) are inferred from visit history.
- Delete `data/app.db` and restart to re-seed the three demo providers.


## 7. Jason Cheney — setup, consult, calendar

```
POST /api/auth/login {email:"jasoncheney", password:"123456"}
  → cookie + redirect "/setup"

GET  /setup
  → who you are, hours, portal radios, iCal how-tos

POST /api/setup {name, hours, portal_kind:"headway", portal_url:"https://headway.co/…", …}
  → {ok:true, redirect:"/dashboard"}
  setup_complete becomes 1

GET  /p/jason-cheney
  → Free consultation (15 min) and Full session (50 min)

POST /api/p/jason-cheney/book
  {date, time:"10:00", name:"Pat First", email:"pat.first@example.com", visitKind:"consult"}
  → {ok:true, visitKind:"consult", minutes:15, firstVisit:true, portalUrl:"https://…"}

GET  /booked/{id}
  → “Get started on the online portal” (new tab) when portal_url is set

POST /api/p/jason-cheney/book  (same email, later time, visitKind consult)
  → visitKind "session", 50 min, no portalUrl

POST /api/calendar/block {date, time:"16:00", name:"Casey Manual", minutes:50}
  → client Casey Manual + appointment booked_via=manual
  → GET /api/me capacity.scheduled includes those 50 minutes
```

Dashboard: month calendar, prev/next month, click a day to add a client. Edit my page reopens `/setup`.

Existing Elena / James / Maya first-name login (`demo1234`) is unchanged and skips setup.
