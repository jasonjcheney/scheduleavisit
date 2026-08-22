# Overnight changelog

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

