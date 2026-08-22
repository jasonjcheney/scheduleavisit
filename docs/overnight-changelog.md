# Overnight changelog

## Current product summary (22 Aug 2026 ~1:46 AM MT)

Plain-language snapshot of what ScheduleAVisit does **now**. Detail entries below stay as the overnight history.

### For clients
- Open a provider’s booking link, pick **consult** (short free intro) or **full session**
- If that provider’s week is at the hour cap, get a **trusted colleague** — and if they’re full too, the app keeps walking the network (**multi-hop**) until someone has room
- If the whole reachable network is full, leave a **waitlist** name + email (no “not taking patients” dead end)
- On the booked page: portal CTA when set, **Add to calendar** (`.ics`), Consultation / Session badge

### For therapists
- **Setup**: who you are, weekly hour cap + buffer, consult on/off, portal (Headway / SonderMind / custom), optional iCal busy import, **Change password**
- **Dashboard**: share strip with booking URL + **Scan to book QR**, month calendar (**click a day** to add a client), upcoming visits with **cancel / reschedule**, Clients list with **name filter**, waitlist (dismiss), network invite, **notifications** with mark-one / mark-all read
- Capacity math stays on the server; clients never see the hour-cap number
- Landing **FAQ** accordion (full / hour cap / referrals / HIPAA / booking link)

### Demo logins
- Jason: `jasoncheney` / `123456` → `/setup` then `/p/jason-cheney`
- Elena: `Elena` / `demo1234` → near-cap demo with James / Maya peers

### Ship note
Local overnight commits after waitlist/OG deploy are **not pushed** until Jason is awake. Smoke path: `SMOKE.md`. Suites: `tests/test_public_paths.py`, `test_live_paths.py`, `test_setup_calendar.py`, `test_multihop_referral.py`.


## 2026-08-22 ~1:46 AM MT — Landing FAQ accordion (local-only)

Jason asleep. **Local only — not pushed; pending morning deploy.** No GitHub / Render API calls. No secrets printed.

### Landing FAQ
- Added accessible FAQ accordion (`details` / `summary`) on `/` with five questions:
  - What happens when I'm full?
  - Do clients see my hour cap?
  - How do peer referrals work?
  - Is this HIPAA?
  - How do I get my booking link?
- Honest copy: not a HIPAA product; waitlist / booking alerts are dashboard notifications (not email yet)
- Brand CSS (cream cards, sage chevron, focus-visible); footer link to `#faq`

### Tests
- `tests/test_public_paths.py` asserts FAQ question/answer strings + `faq-item` on `GET /`
- Full `tests/` suite re-run

### Ship status
- **Local commit only.** Morning: push `main` + Render deploy when Jason is awake.


## 2026-08-22 ~1:45 AM MT — Branded friendly not-found (local-only)

Jason asleep. **Local only — not pushed; pending morning deploy.** No GitHub / Render API calls. No secrets printed.

### Not-found page
- Rewrote `templates/notfound.html` as a cream card with forest title + terracotta top accent (`.empty-hero` / `.empty-hero-card`)
- Title uses `{{ message }}`; CTAs: **Book a visit** (`/book`), **Home** (`/`), **Provider login** (`/login`)
- Tiny help line for providers setting up a public booking link
- Minimal CSS in `static/styles.css`

### Behavior
- `GET /p/{slug}` for unknown slugs returns **200** HTML with friendly calendar-missing copy (not a hard 404)
- Missing booked visits still 404 via the same template

### Tests
- `tests/test_public_paths.py` asserts `/p/does-not-exist` → 200 HTML + message + CTAs + `empty-hero`
- `python3 tests/test_public_paths.py` — green
- `python3 tests/test_live_paths.py` — green
- `python3 tests/test_setup_calendar.py` — green
- `python3 tests/test_multihop_referral.py` — green

### Deploy
- Local commit only (Jason asleep)

## 2026-08-22 ~1:41 AM MT — Docs refresh: SMOKE + product summary (local-only)

Jason asleep. **Local only — not pushed; pending morning deploy.** No GitHub / Render API calls. No secrets printed.

### Docs
- `SMOKE.md` rewritten for the current product (waitlist, multi-hop, consult/session, calendar click, `.ics`, QR, password change, reschedule, client filter, notifications mark-read)
- This file: **Current product summary** added at the top; plain language kept

### Tests
- Docs-only change; full `tests/` suite re-run to confirm green

### Ship status
- **Local commit only.** Morning: push `main` + Render deploy when Jason is awake.


## 2026-08-22 ~1:38 AM MT — Dashboard notifications polish (local-only)

Jason asleep. **Local only — not pushed; pending morning deploy.** No GitHub / Render API calls. No secrets printed.

### Notifications
- GET `/api/me/notifications` lists only (no longer auto-marks read on fetch); returns `unread` count
- POST `/api/me/notifications/{id}/read` marks one as read
- POST `/api/me/notifications/read-all` marks all as read
- Dashboard: **Mark all as read** button + per-note **Mark read**; unread badge (“N new”)
- Clearer unread styling: amber side bar + amber dot beside title

### Tests
- `tests/test_live_paths.py`: Elena notifications GET / individual mark-read / mark-all

### Ship status
- **Local commit only.** Morning: push `main` + Render deploy when Jason is awake.


## 2026-08-22 ~1:34 AM MT — Dashboard booking-link QR (local-only)

Jason asleep. **Local only — not pushed; pending morning deploy.** No GitHub / Render API calls. No secrets printed.

### Feature
- Share strip: **Scan to book** QR next to the booking link / Copy button
- MVP image via public QR API (`api.qrserver.com`) using existing `booking_url` (urlencode) — no new deps
- Light flex CSS; stacks on mobile (≤719px)

### Tests
- `tests/test_live_paths.py`: asserts Scan to book + qrserver src on `/dashboard`

### Ship status
- **Local commit only.** Morning: push `main` + Render deploy when Jason is awake.



## 2026-08-22 ~1:36 AM MT — Dashboard client name filter (local-only)

Jason asleep. **Local only — not pushed; pending morning deploy.** No GitHub / Render API calls. No secrets printed.

### Feature
- Clients card: `#client-filter` search input filters rows by name client-side
- Each client row marked `data-name` (lowercase) for matching
- No-match empty state when the filter has zero hits
- Sage-focus CSS aligned with existing field inputs

### Tests
- `tests/test_live_paths.py`: Elena login → logged-in `/dashboard` HTML contains `client-filter`

### Ship status
- **Local commit only.** Morning: push `main` + Render deploy when Jason is awake.



## 2026-08-22 ~1:31 AM MT — Design pass #4 (local-only)

Jason asleep. **Local only — not pushed; pending morning deploy.** No GitHub / Render API calls. No secrets printed.

### Landing
- Hero type scale: slightly larger clamp, tighter letter-spacing, calmer lede measure
- CTA buttons: taller primary actions (50–52px) with a bit more horizontal padding
- Footer: more vertical padding and clearer brand / link / note gaps

### Booking
- Date-strip: roomier chips, stronger selected shadow, scroll-padding
- Slot-grid: 50px slots, sage-wash hover, selected elevation
- Waitlist panel: consistent inner form gap and padding with referral chrome

### Dashboard
- Cards denser (16–18px padding) but readable; tighter list/peer/waitlist row rhythm
- Section gaps via `.dash-grid` and slightly reduced card margins

### Setup
- Field spacing consistency: 14px field gaps, aligned help/day/choice margins
- Section padding aligned with dashboard density

### Palette
- Unchanged cream / forest / terracotta — CSS-only polish, no layout rewrites

### Tests
- All suites under `tests/` run after this pass

### Ship status
- **Local commit only.** Morning: push `main` + Render deploy when Jason is awake.


## 2026-08-22 ~1:35 AM MT — Therapist network invite polish (local-only)

Jason asleep. **Local only — not pushed; pending morning deploy.** No GitHub / Render API calls. No secrets printed.

### Dashboard invite peer
- Clearer empty state when no peers: **“No trusted peers yet”** + mutual-cap catch copy
- Pending invites list (email, sent label, Copy link) when status is pending
- Success/error copy after invite: ready vs already-pending; self-invite / bad email messages
- Invite form result is live (`aria-live`); Copy link on success and on each pending row

### Invite accept page
- Kept mutual-benefit payoff copy
- Polished CTA → **Open your referral network** + hint to invite their own colleague
- Calmer missing / already / wrong-email states

### API
- `POST /api/me/network/invite` returns `email`, `already`, `message`; skips duplicate notify on re-share

### Tests
- `tests/test_setup_calendar.py`: invite create TestClient case (validation, create, idempotent re-invite, pending on `/api/me/network` + dashboard)

### Ship status
- **Local commit only.** Morning: push `main` + Render deploy when Jason is awake.


## 2026-08-22 ~1:30 AM MT — Change password on /setup (local-only)

Jason asleep. **Local only — not pushed; pending morning deploy.** No GitHub / Render API calls. No secrets printed.

### Feature
- `/setup` Account card: current / new / confirm password fields
- `POST /api/me/password`: auth required; current must match; new min 6 chars; new must match confirm
- Success message on the form; light `.ok-msg` CSS aligned with existing `.err`
- `jasoncheney` / `123456` left untouched until he changes it (`ensure_jason` already does not reset)

### Tests
- `tests/test_setup_calendar.py`: wrong current → 401; short/mismatch fail; correct update; login with new password; Jason default still works (disposable user)

### Ship status
- **Local commit only.** Morning: push `main` + Render deploy when Jason is awake.



## 2026-08-22 ~1:28 AM MT — Dashboard cancel / reschedule polish (local-only)

Jason asleep. **Local only — not pushed; pending morning deploy.** No GitHub / Render API calls. No secrets printed.

### Cancel
- Confirmation copy is calmer: the time opens immediately and this week’s hours drop as soon as you confirm
- Toast: “Cancelled — that hour is free now”
- Repeat cancel is idempotent (`already: true`); notify body mentions hours update immediately

### Reschedule
- Upcoming list (non-imported visits) has Reschedule → modal with 16-day chips + availability slots
- Reuses `GET /api/p/{slug}/availability` (current slot shown as open until save)
- Existing `POST /api/me/appointments/{id}/reschedule` polished: reject non-booked, notify “Visit moved”, return `startIso`
- Client booked page: no cancellation token; left as-is (office cancels from the dashboard)

### Tests
- `tests/test_setup_calendar.py`: cancel frees the slot; reschedule moves 11:00 → 14:00 and old slot opens

### Ship status
- **Local commit only.** Morning: push `main` + Render deploy when Jason is awake.


## 2026-08-22 ~1:16 AM MT — Add to calendar (.ics) on booked page (local-only)

Jason asleep. **Local only — not pushed; pending morning deploy.** No GitHub / Render API calls. No secrets printed.

### Feature
- `GET /booked/{id}.ics` and `GET /api/booked/{id}/ics` return `text/calendar` with a minimal VEVENT
- Fields: SUMMARY, DTSTART/DTEND (`TZID=America/Denver`), DESCRIPTION, LOCATION (provider address)
- Stdlib-only builder in `icalutil.build_appointment_ics` (no new deps)
- Booked confirmation page: “Add to calendar” download link

### Tests
- `tests/test_live_paths.py`: .ics returns 200 and contains `BEGIN:VEVENT`

### Ship status
- **Local commit only.** Morning: push `main` + Render deploy when Jason is awake.

## 2026-08-22 ~1:15 AM MT — Waitlist dismiss (local-only)

Jason asleep. **Local only — not pushed; pending morning deploy.** No GitHub / Render API calls. No secrets printed.

### Schema
- `waitlist_requests.dismissed_at` added in SCHEMA + migrate `CREATE IF NOT EXISTS`
- `migrate()` `ALTER TABLE … ADD COLUMN dismissed_at` when missing (existing Render SQLite)

### Dashboard + API
- Waitlist list hides rows with `dismissed_at` set
- Per-row Dismiss → `POST /api/me/waitlist/{id}/dismiss` (auth required, owns row)
- Soft-dismiss only (no delete); idempotent if already dismissed

### A11y
- `aria-live="polite"` on booking `visit-err` and waitlist `waitlist-err`
- Dismiss buttons: `type="button"` + `aria-label` (clients + waitlist)

### Tests
- `tests/test_multihop_referral.py`: 401 unauth, 404 wrong owner, owner dismiss + dashboard hides row
- All suites green: public / live / setup_calendar / multihop_referral

### Ship status
- **Local commit only.** Morning: push `main` + Render deploy when Jason is awake.

## 2026-08-22 ~1:05 AM MT — Design pass #3 (local-only)

Jason asleep. **Local only — not pushed; pending morning deploy.** No GitHub / Render API calls. No secrets printed.

### Landing
- Spacing rhythm tightened across hero → trust → audience → how → band → who
- Subtle `section-rule` dividers between major blocks
- Stronger sage CTA band (on-sage / ghost-on-sage buttons) plus a final cream CTA band before the footer

### Booking waitlist
- Waitlist panel chrome aligned with referral cards (warm gradient, terracotta border, inner form card)
- Focus ring matches referral (`:focus-visible` via global focus token)

### Dashboard
- Waitlist rows: clearer name / email / asked-date + minutes pill
- Calendar legend: padded strip with more gap between keys

### Global CSS
- Consistent radius / shadow / hover on cards and landing tiles
- Visible skip-link (slides in on focus) and broader `:focus-visible` coverage

### Docs
- README shortened into plain language for Jason: live URL, jasoncheney/123456 + Elena demo1234, one paragraph each for referral and waitlist

### Tests
- `python3 tests/test_public_paths.py` — green
- `python3 tests/test_live_paths.py` — green
- `python3 tests/test_setup_calendar.py` — green
- `python3 tests/test_multihop_referral.py` — green (incl. waitlist)

### Ship status
- **Local commit only.** Morning: push `main` + Render deploy when Jason is awake.

## 2026-08-22 ~12:50 AM MT — Waitlist when whole network is full + Open Graph meta

Jason asleep — overnight ship to live. No SMS/email send (dashboard notification + DB only).

### Feature: calm waitlist
- When booking returns `full` **and** referral candidates are empty, booking UI shows a waitlist panel (name + email).
- Table `waitlist_requests` (`provider_id`, `name`, `email`, `requested_minutes`, `created_at`) via SCHEMA + `migrate()` CREATE IF NOT EXISTS.
- `POST /api/p/{slug}/waitlist` stores the row and notifies the origin provider (`kind=waitlist`) on the dashboard.
- `static/app.js` `showReferral` when `!rec` offers the waitlist form.

### Sharing
- Open Graph / Twitter meta on `base.html` with landing + booking overrides (`og:title`, `og:description`, `og:url`, canonical).

### Also includes prior local commit
- 480px mobile overflow guards + `tests/test_public_paths.py` (was local-only; now shipping).

### Tests
- Extended `tests/test_multihop_referral.py`: pack A→B→C → book `full` + `waitlist: true` → waitlist API **200** + DB + notification.
- Live-path smokes assert OG tags. All suites green. Elena + jasoncheney intact.

### Deploy
- Commits `accba28` + `0b468f4` pushed to `main`
- Render deploy `dep-da4kah5d9g6s738ovn10` on `srv-da463sou01pc73erg9l0` → **live** (~12:45 AM MT / 06:45 UTC)
- Live smoke: `/` and `/p/jason-cheney` HTTP 200 with `og:title` present


## 2026-08-22 ~12:45 AM MT — Local-only: 480px mobile overflow + public-path tests

Jason asleep. **Local only — not pushed; pending morning ship if needed.** No Render / GitHub API calls.

### CSS
- Added `@media (max-width: 480px)` covering booking slots (`minmax(0,1fr)`), referral card CTA stack, dashboard month calendar + week-grid (2-col), landing hero/actions/footer padding, setup progress steps, share-strip link wrap.
- Kept tighter `@media (max-width: 390px)` cascade; `provider-hero` min-width/wrap guards.

### JS (small)
- Referral “see more” null-guards `#more-list`.
- Referred-visit confirm scrolls into view on mobile.
- Copy-link uses textarea `execCommand` fallback when Clipboard API is missing/fails (no false “Copied”).

### Tests
- Added `tests/test_public_paths.py` — TestClient + temp `SAV_DB` for `GET /`, `/book`, `/login`, `/signup`, `/p/jason-cheney`, `/p/elena-vasquez-lpc` (200 + key strings) and 480px CSS guards.
- `tests/test_live_paths.py` also asserts 480px present.

### Ship status
- **Local commit only.** Do not treat as live until morning push + Render deploy.

## 2026-08-22 ~12:31 AM MT — Visual QA: referral minutes, mobile 390px, live-path smokes

Overnight QA pass (WebFetch + TestClient; no browser MCP). Jason asleep — no contact.

### Bugs / polish fixed
1. **Referral confirm showed wrong duration** — If the client picked a consult, “Confirm this referred visit” echoed 15 minutes even though `book-referral` always books the peer’s session length. Buttons now carry `data-ref-minutes`; confirm uses the peer’s minutes. Direct confirm uses `currentMinutes()`.
2. **Signup `data-next` pointed at `/dashboard`** — Page defaulted to dashboard while copy + API send new providers to `/setup`. Signup route now defaults `next=/setup`.
3. **Directory caption omitted Jason** — Now: “James, Maya, and Jason have room.”
4. **Mobile overflow at ~390px** — Added `@media (max-width: 390px)` for booking slots, referral card CTA stack, month calendar cells/legend, share-strip code; `overflow-x: hidden` on `body`; `.person > div { min-width: 0 }` so long names wrap.

### Tests
- Added `tests/test_live_paths.py` — TestClient smokes for `/`, `/book`, `/p/jason-cheney`, `/p/elena-vasquez-lpc`, `/login`, `/signup`, auth gates, jasoncheney/123456 → setup/dashboard, mobile CSS guards.
- `python3 tests/test_live_paths.py` — green
- `python3 tests/test_setup_calendar.py` — green
- `python3 tests/test_multihop_referral.py` — green

### Deploy
- Commit `c0db2e4` + push to `main`
- Render deploy `dep-da4k4ibl550s7385psk0` on `srv-da463sou01pc73erg9l0` (build started)

## 2026-08-22 (America/Denver) — design + completeness + reliability polish

Shipped while Jason slept. No HIPAA claims, payments, or SMTP.

### Landing
- Clearer dual value props: **For therapists** and **For clients**
- Stronger CTAs: Book a visit / Provider login / Get your booking link
- Trust strip (weekly caps, trusted referrals, first-visit consult, no portal maze)
- How-it-works plus Elena → James → Maya multi-hop referral story
- Mobile polish for header, hero actions, and slot grids
- Kept cream / forest green / terracotta with Fraunces + Outfit

### Booking
- Clearer consult vs full-session copy and choice hints
- Emptier/fuller slot states (no hours, day full, week at cap banner)
- Referral panel explains multi-hop walking of the trusted network
- Accessibility: aria-pressed on visit kind, aria-expanded on more options, focus on referral panel, live regions, contrast tweaks

### Dashboard / setup
- Getting-started checklist (calendar, peers, optional iCal)
- Month calendar discoverability (“click any empty day”) + help tip
- Richer empty states for visits, clients, peers, notifications
- Setup progress stepper (4 sections) + microcopy for consult/portal/calendar

### Verification
- `python3 tests/test_setup_calendar.py` — green
- `python3 tests/test_multihop_referral.py` — green
- Local template smoke: `/`, `/p/jason-cheney`, `/login`, `/dashboard`

### Go-to-market pack
- `docs/competitive-research.md` — competitive landscape notes informing UX polish
- `docs/marketing-plan.md` — therapist acquisition / positioning plan
- `docs/ScheduleAVisit-Marketing-Plan.pdf` — shareable marketing PDF

### Live deploy
- Pushed `15d2722` to `main`
- Render deploy `dep-da4jv8c9v7es738dvs1g` → **live** (finished ~00:21 MT / 06:21 UTC)
- Curl smoke (all HTTP 200):
  - `/` — CTAs, trust strip, dual audience copy present
  - `/p/jason-cheney` — consult vs session choice present
  - `/login` — demo hints present


## 2026-08-22 ~12:25 AM PT — Competitive-research P0 polish wave

Ensured P0s from `docs/competitive-research.md` are truly in the UI (prior waves were close; gaps closed):

1. **Full-state empathy headline** — Referral panel: **“{{first}}’s week is at capacity”** + **“You still get a time — with a colleague they trust.”** Eyebrow: Weekly capacity.
2. **Consult vs session** — Cards: **“Free consultation (N min) — see if it’s a fit”** / **“Full session (N min) — therapy hour”**; helper: **“New here? Start with a consult. Already working together? Book a session.”**
3. **Portal CTAs by Headway/SonderMind/custom** — `portal_kind` into `booked.html`; CTAs **Continue on Headway** / **Continue on SonderMind** / **Start intake on {{first}}’s portal**; notice about reserved time + paperwork. Setup retitled **After they book → send them to intake.**
4. **Landing therapist + hour cap + trusted peer** — H1 **“Book a visit in seconds — even when your therapist is full.”** Lede/meta: one link, weekly hour cap, trusted peer at capacity.
5. **Dashboard share strip + copy-link feedback** — “Clients never see your hour cap — only a time with you, or someone you recommend.” Toast/inline: **“Link copied — paste on your site or Psychology Today profile.”** Sage-wash share strip; mobile link-box stack.

Also: referral CTA **Book this time with {{peerFirst}}**, **Show other trusted colleagues**, directory demo caption, design pass #2 (share-strip contrast/spacing). Palette unchanged (cream/forest/terracotta).

### Tests
- `python3 tests/test_setup_calendar.py` — green (assertion updated for new setup portal heading)
- `python3 tests/test_multihop_referral.py` — green

### Deploy
- Commit + push + Render `srv-da463sou01pc73erg9l0`; smoke `/`, `/p/jason-cheney`, `/login`.

## 2026-08-22 ~12:35 AM PT — Design pass #2 (hierarchy, states, calendar)

Second overnight UX pass (distinct from the first polish / P0 wave). Palette unchanged (cream / forest / terracotta; Fraunces + Outfit).

### Landing
- Stronger hero spacing and section rhythm (audience → how → band → who)
- Footer rebuilt with brand, nav links, and clearer disclaimer block

### Booking
- Slot loading skeleton + retry empty state on failure
- Clearer empty titles (no hours / day full)
- Visit-kind choice cards as chip-style with inset active edge
- Mobile slot grid: taller touch targets, 2-column skeleton

### Dashboard / setup
- Month calendar: today highlight, empty-day “+” affordance, color legend, loading skeleton, block titles
- Setup wizard: progress bar fill + done/active steps while scrolling; section “current” highlight
- P1 field helpers under weekly cap and buffer (clinical hours vs notes/admin)

### Also
- Invite accept payoff copy (mutual weekly-cap catch)
- Booked page Consultation / Session badge
- CSS type scale, button/focus-ring/card polish

### Tests
- `python3 tests/test_setup_calendar.py` — green
- `python3 tests/test_multihop_referral.py` — green

### Deploy
- Commit + push + Render `srv-da463sou01pc73erg9l0`

## 2026-08-22 ~12:40 AM PT — Competitive-research P1 / easy P2 (wave 3)

Third overnight wave. Closed remaining items **6–12** from `docs/competitive-research.md` (P0s already live).

### Booking referral card (6, 8)
- Primary trust line: **“{{first}} recommends {{peer}}”** (full peer name)
- Multi-hop as tiny secondary only: **“In {{first}}’s wider network.”**
- CTA unchanged: **“Book this time with {{peerFirst}}”**
- Toggle: **Show other trusted colleagues** / **Hide other colleagues**

### Setup + login (7, 12)
- Hour-cap helpers under weekly cap and buffer fields
- Login sub: **“Hour cap, booking link, and the colleagues you trust.”**
- Setup portal section: **“After they book → send them to intake.”**

### Invite / booked / directory (9–11)
- Invite accept mutual-benefit payoff copy
- Booked page Consultation vs Session badge; bold **“so you were not turned away”** when referred
- Directory demo caption: Elena near cap; James and Maya have room

### Visual
- Light CSS for featured rec-card trust line / hop secondary

### Tests
- `python3 tests/test_setup_calendar.py` — green
- `python3 tests/test_multihop_referral.py` — green

### Deploy
- Commit `bd03e49` + push + Render deploy `dep-da4k29mk1f9s73ejdbu0` → **live** on `srv-da463sou01pc73erg9l0`

Live note: Render deploy `dep-da4k1mmk1f9s73ejbsi0` → **live** (finished ~12:26 AM MT / 06:26 UTC) for commit `161ee6b`. Curl smoke `/`, `/p/elena-vasquez-lpc`, `/login` HTTP 200 with footer-inner / visit-chips / slot-loading present.

## 2026-08-22 ~1:45 AM PT — Friendly not-found / empty error states

Local-only polish (no push / no Render).

### Not found
- `templates/notfound.html` rebuilt as branded **empty-hero** card (cream card → sage wash, terracotta top edge, clay eyebrow)
- Clear CTAs: **Book a visit** (primary), **Home** (sage), **Provider login** (ghost)
- Helper line for mistyped / retired / not-yet-public links
- `/p/{slug}` unknown calendars keep a **friendly 200 HTML** page (not a bare 404)
- Missing booked visits still return **404** with the same branded template

### Other empty states
- Directory empty: eyebrow + empty-title + Home / Get your booking link CTAs
- Invite invalid: Home + Book a visit button row (`.notfound-actions`)
- Light CSS for `.empty-hero*` and shared `.notfound-actions`

### Tests
- `tests/test_public_paths.py`: `/p/does-not-exist`, `/p/missing-slug` friendly HTML; `/booked/999999` 404
- `python3 tests/test_public_paths.py` — green
- `python3 tests/test_setup_calendar.py` — green
- `python3 tests/test_multihop_referral.py` — green
- `python3 tests/test_live_paths.py` — green

### Deploy
- Commit locally only (no push, no Render)

## 2026-08-22 ~1:50 AM PT — Landing FAQ plain-language answers

Local-only (no push / no Render).

### Landing
- FAQ accordion before final CTA uses `<details>` / `<summary>`
- Five plain answers: full → peers/waitlist; hour cap hidden; peer invites + hops; not yet HIPAA / no BAA; signup → setup → dashboard link + QR
- In-dashboard notifications called out (no email yet)

### Tests
- `tests/test_public_paths.py` asserts key FAQ strings on `GET /`

### Deploy
- Commit locally only (no push, no Render)
