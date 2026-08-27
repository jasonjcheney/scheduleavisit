# Smoke path (verified 22 Aug 2026, America/Denver)

Server: `python3 -m uvicorn app:app --host 127.0.0.1 --port 8080` from `/workspace/scheduleavisit`.

Today is Saturday 22 Aug 2026. Elena’s week is Mon 17 – Sun 23 Aug. Friday 21 Aug still has calendar holes at 3 pm and 4 pm; the hour cap does not.

## What the product does now

- **Weekly hour cap** — clinical hours + buffer; capacity is server-side
- **Specialty referral** — client picks one plain-language category; overflow prefers that tagged colleague, then General, then multi-hop
- **Multi-hop referral** — when full, walk trusted peers (and peers of peers) until someone has room
- **Waitlist** — if the whole reachable network is full, client leaves name + email; provider sees it and can dismiss
- **Consult vs session** — free first consult (default 15 min) or full session (default 50 min)
- **Month calendar** — click a day to add a client; optional iCal busy import
- **.ics download** — booked page “Add to calendar”
- **Scan to book QR** — beside the dashboard booking link
- **Change password** — on `/setup`
- **Cancel / reschedule** — from the dashboard upcoming list
- **Client name filter** — search the Clients list
- **Notifications mark-read** — per note or mark all; GET no longer auto-reads

No SMTP, no paid ride keys, no HIPAA claims.

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
  → 200 “You’re on the calendar.” + “Add to calendar” (.ics)
GET  /booked/{id}.ics
  → 200 text/calendar with BEGIN:VEVENT
```

Also works in the browser: `/signup` → `/setup` → dashboard → open `/p/{slug}` → pick a time → confirm.

## 2. Elena is full this week → James, then Maya (multi-hop)

Login hint: **Elena** / **demo1234** (or `elena@sageandstone.example`).

```
POST /api/auth/login {email:"Elena", password:"demo1234"} → cookie + /dashboard
GET  /dashboard → “Hello, Elena.” · badge “Nearly full” · 24.8 / 25
GET  /api/p/elena-vasquez-lpc/availability?date=2026-08-21
  → weekHasRoom false
  → 15:00 and 16:00 open (calendar holes)

POST /api/p/elena-vasquez-lpc/book
  {date:"2026-08-21", time:"15:00", name:"Sam Overflow", email:"sam.overflow@example.com",
   category:"general"}
  → 200 {
      ok:false, full:true, category:"general",
      recommendation: {peerSlug:"james-okonkwo-lcsw", name:"James Okonkwo, LCSW",
                       recommendedBy:"Elena", miles:4, date:"2026-08-21", time:"15:00",
                       rideUrl:"/ride?address=…"},
      alternatives: [{peerSlug:"maya-chen-lmft", miles:2, …}]
    }
```

Booking page asks one category question (General, Anxiety, Depression, Couples, Trauma, Addiction, Kids / teens, Grief). Elena’s list seeds James as General and Maya as Couples, so a General (or omitted) category still offers James first. Couples prefers Maya when she has room.

UI: one referral card (James, time, “Elena recommends …”, Get a ride). “Show other trusted colleagues” reveals Maya.

If James and Maya were also full, the server keeps walking *their* trusted peers (multi-hop) until someone has room. The card then says “In Elena’s wider network.” Booking that referral is allowed even when the peer is not a direct link.

```
POST /api/p/elena-vasquez-lpc/book-referral
  {peerSlug:"james-okonkwo-lcsw", date:"2026-08-21", time:"15:00",
   name:"Sam Overflow", email:"sam.overflow@example.com"}
  → 200 {ok:true, redirect:"/booked/…"}
```

## 3. Whole network full → waitlist

When booking returns `full` and there is no recommendation, the booking page shows a calm waitlist form.

```
POST /api/p/{slug}/waitlist
  {name:"Pat Waitlist", email:"pat.waitlist@example.com", minutes:50}
  → 200 {ok:true, waitlistId:…}

GET  /dashboard  (origin provider)
  → Waitlist card lists the request + notification “Waitlist — Pat Waitlist”

POST /api/me/waitlist/{id}/dismiss  (owner cookie)
  → 200 {ok:true}; row leaves the list (soft dismiss)
```

No email or SMS is sent — dashboard only.

## 4. Both dashboards see a referral

```
GET /api/me/notifications  (Elena cookie)
  → “You referred Sam Overflow to James” · unread count
POST /api/me/notifications/{id}/read
  → marks one read
POST /api/me/notifications/read-all
  → marks all read
  (GET no longer auto-marks; dashboard has Mark read / Mark all as read)

GET /dashboard             (James / demo1234)
  → upcoming visit “Sam Overflow”
GET /api/me/appointments   (James)
  → Sam Overflow, booked_via=referral
```

Server log also prints `[book-referral]` and `[notify]` lines. No SMTP.

## 5. Cancel frees the slot; reschedule moves it

```
POST /api/me/appointments/{id}/cancel   (James cookie)
  → 200 {ok:true}
GET  /api/p/james-okonkwo-lcsw/availability?date=2026-08-21
  → 15:00 booked:false, open:true

POST /api/me/appointments/{id}/reschedule
  {date:"2026-08-21", time:"14:00"}
  → 200 {ok:true, startIso:…}; old slot opens, new slot books
```

Dashboard upcoming list: Reschedule opens a 16-day chip picker + availability slots. Cancel toast: “Cancelled — that hour is free now.”

## 6. Invite a colleague

From Elena’s dashboard invite form, or:

```
POST /api/me/network/invite {email:"priya.shah@newpeer.example"}
  → {ok:true, url:"http://127.0.0.1:8080/invite/{token}", message:…}

POST /api/auth/signup
  {name:"Priya Shah", credentials:"MD", email:"priya.shah@newpeer.example",
   password:"demo1234", next:"/invite/{token}"}

GET  /invite/{token}   (Priya cookie)
  → “You’re in Elena’s network.”

GET  /api/me/network   (Elena cookie)
  → peers include James, Maya, and Priya Shah, MD (each with a category tag)

Dashboard network: assign up to 5 peers and a category on each link (General is always in the list).
```

Pending invites show on the dashboard with Copy link.

## 7. Ride page

```
GET /ride?address=500+Eldorado+Blvd,+Superior,+CO
  → Google Maps directions + Uber deep link + Lyft deep link. No paid keys.
```

## 8. Jason Cheney — setup, consult, calendar, password, QR

```
POST /api/auth/login {email:"jasoncheney", password:"123456"}
  → cookie + redirect "/setup" (until setup_complete)

GET  /setup
  → who you are, hours, consult/session, portal radios, iCal how-tos, Change password

POST /api/setup {name, hours, portal_kind:"headway", portal_url:"https://headway.co/…", …}
  → {ok:true, redirect:"/dashboard"}

GET  /dashboard
  → booking link + “Scan to book” QR · month calendar · Clients filter · notifications

GET  /p/jason-cheney
  → Free consultation (15 min) and Full session (50 min)

POST /api/p/jason-cheney/book
  {date, time:"10:00", name:"Pat First", email:"pat.first@example.com", visitKind:"consult"}
  → {ok:true, visitKind:"consult", minutes:15, firstVisit:true, portalUrl:"https://…"}

GET  /booked/{id}
  → Consultation badge · portal CTA when set · “Add to calendar”

POST /api/p/jason-cheney/book  (same email, later time, visitKind consult)
  → visitKind "session", 50 min, no portalUrl

POST /api/calendar/block {date, time:"16:00", name:"Casey Manual", minutes:50}
  → client Casey Manual + appointment booked_via=manual
  → capacity.scheduled includes those 50 minutes

POST /api/me/password
  {current_password, new_password, confirm_password}
  → 200 {ok:true} when current matches, new ≥ 6 chars, confirm matches
```

Dashboard: month calendar, prev/next month, click a day to add a client. Clients list has a name filter (`#client-filter`). Edit my page reopens `/setup`.

Existing Elena / James / Maya first-name login (`demo1234`) is unchanged and skips setup.

## Notes

- Capacity is server-side. Friday 3 pm is open on Elena’s grid and still rejected by the cap (24.8 + 0.83 > 25).
- Later weeks on Elena can have room — that is the engine, not a bug.
- Recurring labels (Weekly / Biweekly / Occasional) are inferred from visit history.
- Delete `data/app.db` and restart to re-seed the three demo providers (+ Jason).
- Automated suites: `tests/test_public_paths.py`, `test_live_paths.py`, `test_setup_calendar.py`, `test_multihop_referral.py`, `test_specialty_referral.py`.
