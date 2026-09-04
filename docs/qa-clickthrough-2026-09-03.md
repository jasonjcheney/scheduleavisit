# ScheduleAVisit QA click-through — 2026-09-03

**Live:** https://scheduleavisit.onrender.com  
**Local:** `/workspace/scheduleavisit` @ `0a6e1d1` (ahead of `origin/main`; **not pushed**)  
**Tester window:** Thu Sep 3, 2026 evening MT  
**Method:** local `tests/*.py` + live HTTP/API (no browser automation; no counselor outreach)

Founder login verified via `POST /api/auth/login` (`jasoncheney` / `123456`) → cookie `sav_session` → `/dashboard` 200.  
QA booking emails used `singingpunter+qa-<unique>@gmail.com` only.

---

## Local tests

| Suite | Result |
| --- | --- |
| `python3 tests/test_live_paths.py` | **PASS** (incl. new `/ride` + Jason `rideUrl` checks) |
| `python3 tests/test_public_paths.py` | **PASS** |
| `python3 tests/test_book_search.py` | **PASS** |
| `python3 tests/test_specialty_referral.py` | **PASS** |
| `python3 tests/test_multihop_referral.py` | **PASS** |

---

## Live HTTP / API matrix

| Check | URL / call | Expected | Actual | Sev | Result |
| --- | --- | --- | --- | --- | --- |
| Home | `GET /` | 200, client-first hero + provider door | 200; “Find a time…”, Book a visit, I am a provider / Provider login | — | **PASS** |
| Directory | `GET /book` | 200, search | 200; Elena + Jason listed; Boulder appears for real Boulder demos | — | **PASS** |
| Boulder search | `GET /book?q=Boulder` | Elena/Maya; not Superior James; Jason not as a card | Elena + Maya cards; James absent; “Jason Cheney” only in search placeholder | — | **PASS** |
| Login page | `GET /login` | 200; no demo passwords | 200; Welcome back; `jasoncheney` placeholder; **no** `demo1234` / `123456` | — | **PASS** |
| Signup / legal | `GET /signup`, `/privacy`, `/terms` | 200 | 200 | — | **PASS** |
| Elena public | `GET /p/elena-vasquez-lpc` | 200; consult + session | 200; Free consultation / Full session; Boulder in her real address (OK) | — | **PASS** |
| Jason public | `GET /p/jason-cheney` | 200; **no** Boulder / setup placeholders; do not invent specialty/about | 200; no Boulder / “edit this in setup” / “rewrite in setup”; specialty/about blanked in public API | — | **PASS** |
| Founder auth | `POST /api/auth/login` | `{ok:true}` + session | `{ok:true,"redirect":"/dashboard","name":"Jason Cheney"}` + cookie | — | **PASS** |
| Dashboard | `GET /dashboard` (authed) | 200; Hello Jason; hours | 200; Hello, Jason; Room **3.0 / 25.0**; Waitlist / Scan to book present | — | **PASS** |
| Setup | `GET /setup` (authed) | 200 edit form | 200; form still shows raw seed specialty/about/address (expected for edit; public hides them) | P3 note | **PASS** (with note) |
| Elena availability | `GET /api/p/elena-vasquez-lpc/availability?date=2026-09-04` | week full; calendar holes possible | `weekHasRoom=false`, projected 24.5/25; open **11:00**, **16:00** | — | **PASS** |
| Peers availability | James / Maya / Jason same date | room + open slots | James 5.5/28, Maya 6/24, Jason 3/25; all open slots | — | **PASS** |
| Full → referral (general) | `POST /api/p/elena-vasquez-lpc/book` category=general time=11:00 | `full` + James first | `ok:false,full:true`; rec **james-okonkwo-lcsw**; alts Jason, Maya; `waitlist:false` | — | **PASS** |
| Specialty prefer | same book API category=couples time=16:00 | Maya first | rec **maya-chen-lmft** (couples) | — | **PASS** |
| Book referral | `POST .../book-referral` → James 11:00 | 200 booked token | `ok:true`, appt **531**, `/booked/VJLtgMqSwYAd5kUVqu5tejC4ObjBsRaG` | — | **PASS** |
| Booked + .ics | token HTML + `.ics`; integer id dark | confirm + VEVENT; `/booked/531` 404 | 200 “You’re on the calendar” / Referred by Elena; ICS `text/calendar` + VEVENT; integer 404 | — | **PASS** |
| Waitlist API | `POST /api/p/elena-vasquez-lpc/waitlist` | accept request | `ok:true,waitlistId:1` (network not exhausted; endpoint still accepts) | P3 note | **PASS** |
| Empty `/ride` on **live** | `GET /ride` (no address) | should not invent Boulder | **Still defaults to Boulder, CO** on live | **P2** | **FAIL** (live; fixed locally) |
| Jason alt `rideUrl` on **live** | referral alt for `jason-cheney` | blank / no Boulder | `address:""` but `rideUrl` = `/ride?address=Boulder%2C%20CO` | **P2** | **FAIL** (live; fixed locally) |

---

## Findings (severity)

### P2 — Live still invents Boulder on ride links (fixed in local commit `0a6e1d1`, needs deploy)

- **Expected:** Jason’s seeded `Boulder, CO` stays hidden everywhere public (same policy as `/p/jason-cheney`). Empty ride destinations must not invent a city.
- **Actual (live):** `public_provider` correctly blanks Jason’s address/specialty/about, but `referral_candidates` built `rideUrl` from the **raw** DB address, and `/ride` fell back to `"Boulder, CO"` when address was missing.
- **Local fix (committed, not pushed):**
  - `capacity.py` — `rideUrl` uses `pub["address"]`
  - `app.py` + `templates/ride.html` — no Boulder default; calm empty-address copy
  - `tests/test_live_paths.py` — regression coverage

### P3 — Setup form still shows seed placeholders for Jason

- `/api/me` / setup edit fields still contain specialty `Counseling — edit this in setup`, about `…rewrite in setup.`, address `Boulder, CO`.
- Public surfaces blank them (good). Not a client-facing bug; founder can clear in setup when ready. **Do not invent** replacement specialty/about.

### P3 — Waitlist reachable even when a peer recommendation exists

- Book response set `waitlist:false` when peers had room (correct UI signal).
- Direct `POST /waitlist` still succeeded (`waitlistId:1`). Harmless for demos; tighten later if product wants waitlist only when `recommendation` is null.

### Info — Deploy lag

- Local `main` is **19 commits** ahead of `origin/main` (hero/search/Google/reminders/calendar/cap badges/Boulder hide/`0a6e1d1` ride fix, etc.).
- Live already has Jason public blanking and core referral/booked/ics behavior; **ride Boulder leak remains until deploy**.

### Info — Uncommitted local WIP (not part of this QA commit)

- Dirty tree still has unstaged booking UX work (`open_days_ahead` / `prefer_open`, `static/app.js`, `styles.css`, `booking.html` reorder). Left untouched; not deployed.

### Info — Live QA artifacts created

- Referral visit: James Okonkwo, Fri Sep 4 2026 · 11 am (token above); client “QA Referral”.
- Elena waitlist row id `1` for `singingpunter+qa-wl-1788488100@gmail.com`.
- Safe to dismiss from Elena dashboard when convenient.

---

## Deploy needed?

**Yes — for the P2 ride/Boulder fix (`0a6e1d1`) and the other 18 local commits not on Render yet.**  
No push/deploy was performed in this session.

Until deploy: public Jason page is fine; avoid relying on Jason referral “Get a ride” on live (it still points at Boulder).
