# Overnight changelog

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
