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
