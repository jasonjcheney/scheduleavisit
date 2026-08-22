# Competitive research: therapist booking & practice tools

**Date:** 2026-08-22 (PT)  
**Product:** ScheduleAVisit — public booking link + weekly hour caps + trusted peer referral when full + consult vs session + portal handoff  
**Sources:** SimplePractice, Jane App, TherapyNotes, Calendly (therapy/consult workflows), Headway, SonderMind, Alma, Psychology Today, Zocdoc; support docs and practitioner reviews.  
**Scope:** Features users praise, gaps ScheduleAVisit can own, shippable UX/copy tonight, messaging for solo LPC/LCSW/LMFT founders. No app code changed in this pass.

---

## Snapshot by competitor

| Tool | What booking is for | Praise / pattern | Weak vs ScheduleAVisit lens |
| --- | --- | --- | --- |
| **SimplePractice** | EHR + request/approve booking widget + portal | All-in-one, paperless intake, calendar sync, waitlist, Therapy Finder clinician referrals | Waitlist is mostly manual; referrals are directory-wide, not *your* trusted peers; no weekly *clinical hour* cap (calendar squares ≠ caseload load) |
| **Jane App** | Branded online booking + waitlist cues | Intuitive booking, reminders, waitlist exclusive-access when slots free | Optimized for filling *empty slots*, not protecting weekly hour budgets or peer handoff when full |
| **TherapyNotes** | TherapyPortal request/approve | Free branded portal, approve/deny on To-Do, assigned-clinician limits | Request friction; weaker “instant book” UX; no trusted-peer overflow story |
| **Calendly** | Free/cheap consult event types | Beautiful UX; 15-min “Free Phone Consultation”; buffers & booking windows | Not therapy-native on common plans (HIPAA/BAA enterprise); no caseload math; discreet titles / clinical intake weak |
| **Headway** | Network intake + direct booking after billed session | Insurance/admin offload; forms tasks; advanced booking window | Matching engine ≠ your peer network; light EHR; calendar ≠ hour-cap ethics |
| **SonderMind** | Direct scheduling post-match | Clear min notice (24h+) and horizon (1–8 weeks); modality pick | Platform match first; not “when I’m full, book my colleague on *my* link” |
| **Alma** | Membership directory + credentialing/billing | Autonomy messaging; insurance made easy; community referrals | Directory saturation; membership fee; not a capacity-aware public booking link |
| **Psychology Today** | Discovery + “accepting new patients” | Filter open caseloads; niche + insurance search | Dead-end when closed; email/phone tag; no live capacity or peer chain |
| **Zocdoc** | Instant book + insurance filters | Real-time slots, verified reviews, near-term availability | Medical booking UX; when empty, soft fail — not a warm peer referral |

### Waitlist / referral-when-full patterns (industry)

1. **Hold-the-client waitlist (Jane, SimplePractice):** Park prospects; Jane can notify eligible waitlisters when a cancellation opens (exclusive access window). Optimizes *your* next empty square.
2. **Directory / network referral (SimplePractice Clinician Referrals, Alma/Headway/SonderMind matching):** Send client elsewhere via platform directory or insurance match — not necessarily people *you* personally trust.
3. **Manual “email me / closed caseload” (Psychology Today era):** Client does the work; high drop-off.
4. **ScheduleAVisit pattern (ownable):** Capacity gate on **weekly hours + buffer + recurring load** → same-page **trusted peer** (invite graph, multi-hop) → optional ride → later **portal handoff** after consult/session. Client never hits a brick wall.

---

## Top 10 features users praise (and why)

1. **Client self-scheduling / appointment requests (SimplePractice, Jane, TherapyPortal)**  
   **Why:** Kills phone tag; clients book nights/weekends when distress hits; lifts conversion from directory → first session.

2. **Approve/decline or gated new-client requests (SimplePractice, TherapyNotes)**  
   **Why:** Clinicians keep clinical fit control; fear of “calendar takeover” drops once requests aren’t auto-confirmed.

3. **Embedded / branded booking widget or page**  
   **Why:** Feels like *their* practice, not a third-party marketplace; one link on website/IG bio.

4. **Automated reminders (email/SMS)**  
   **Why:** No-shows are expensive (often cited ~12–19%); reminders are table stakes practitioners refuse to lose.

5. **Paperless intake + portal forms before/after first book**  
   **Why:** Saves 15–20+ minutes per new client; sets professional tone; networks (Headway) add task lists + insurance nudges.

6. **Calendar sync / busy blocking (Google/Outlook/iCal)**  
   **Why:** Double-booking anxiety is the #1 objection to online booking; sync = peace of mind.

7. **Consult vs full session as separate bookable types (Calendly therapy workflows; SP initial consult availability)**  
   **Why:** Low-commitment “Free Phone Consultation” (15–30 min) converts seekers without locking a 50–60 min clinical hour on first contact.

8. **Booking windows & buffers (notice period, max advance, buffers between sessions)**  
   **Why:** Protects evenings, same-day chaos, and documentation time — language of “boundaries” resonates hard with solo founders.

9. **Waitlist / cancellation fill (Jane waitlist cues + exclusive access)**  
   **Why:** Turns last-minute openings into recovered revenue without public free-for-all.

10. **Referral path when not a fit or full (SP Clinician Referrals; Alma peer community; network matching)**  
    **Why:** Ethical duty + brand: “I won’t ghost you.” Solo clinicians still want *control over who* gets the warm handoff.

---

## Gaps ScheduleAVisit can own

Competitors optimize **empty calendar squares**, **insurance matching**, or **directory discovery**. Few (none cleanly) combine:

### 1. Weekly hour caps (clinical load, not UI slots)
- EHRs show open Tue 4pm even when 25 clinical hours + notes buffer would be violated.
- ScheduleAVisit: `booked + inferred recurring + buffer + new visit ≤ weekly target`, including 8-week projection for new weekly clients.
- **Own the story:** “Squares lie. Hours don’t.”

### 2. Trusted peer referral chains (invite graph, multi-hop)
- SP referrals search Therapy Finder; Headway/SonderMind/Alma own *their* funnel.
- Jane waitlist keeps the client on *your* list for later — doesn’t place them *today* with a peer.
- ScheduleAVisit: same booking page → one recommended colleague you invited → quiet “See more options” → multi-hop through the network.
- **Own the story:** “When you’re full, they still leave with a time — and a human you vouch for.”

### 3. Consult vs session on one public link
- Calendly does event types well but isn’t capacity-aware or therapy-networked.
- Networks often force match → then 60-min standard session.
- ScheduleAVisit: first-time consult vs full session; returning email → session; duration feeds the hour math.
- **Own the story:** “A 15-minute fit check that still respects your weekly cap.”

### 4. Portal handoff (Headway / SonderMind / custom) after booking
- Discovery and EHR portals are separate islands; clients get “email me for intake.”
- ScheduleAVisit: confirmation CTA **Get started on the online portal** using provider’s pasted Headway/SonderMind/custom URL — booking stays light; clinical intake stays where they already work.
- **Own the story:** “We schedule the visit. Your portal does the paperwork.”

### Adjacent white space (later)
- Auto-offer waitlist *or* peer when a cancel frees hours under the cap.
- Discreet calendar titles (Calendly gap therapists complain about).
- Referral-source thank-you loops (called out as missing in Jane/SP automation writeups).

---

## 8–12 concrete UX / copy / design tweaks to ship tonight

Priorities assume **copy/CSS/microcopy/template polish only** (no product/architecture changes). Ordered for solo LPC/LCSW/LMFT founders and the “full → peer” demo path.

### P0 — ship first (demo-critical)

1. **Full-state headline empathy (booking overflow)**  
   Current: “This week is full.”  
   Ship: **“{{first}}’s week is at capacity”** + sub: **“You still get a time — with a colleague they trust.”**  
   Why: Mirrors PT/Zocdoc dead-end anxiety; makes the differentiator obvious in 2 seconds.

2. **Consult choice copy clarity**  
   Current muted line is vague for returning vs new.  
   Ship cards: **“Free consultation ({{n}} min) — see if it’s a fit”** vs **“Full session ({{n}} min) — therapy hour”**; helper: **“New here? Start with a consult. Already working together? Book a session.”**

3. **Portal handoff specificity on confirmation**  
   Current generic “online portal.”  
   Ship by `portal_kind`: **“Continue on Headway”** / **“Continue on SonderMind”** / **“Start intake on {{first}}’s portal”**; notice: **“Your time is reserved. Finish paperwork where {{first}} already works.”**

4. **Landing hero: speak clinician, not “doctor” only**  
   Meta/H1 still say “doctor.”  
   Ship: **“Book a visit in seconds — even when your therapist is full.”** Sub: **“One link. A weekly hour cap. A trusted peer when you’re at capacity.”**

5. **Dashboard share strip: one-line “why this link”**  
   Under public link: **“Clients never see your hour cap — only a time with you, or someone you recommend.”** (tighten existing muted copy; add a copy-button success toast: **“Link copied — paste on your site or Psychology Today profile.”**)

### P1 — high leverage same night

6. **Referral card trust line**  
   Prefer **“{{first}} recommends {{peer}}”** over network jargon; keep multi-hop as secondary tiny text: **“In {{first}}’s wider network.”** Primary CTA: **“Book this time with {{peerFirst}}.”**

7. **Setup hour-cap helper**  
   Under weekly cap: **“Clinical hours this week (sessions + consults), not empty calendar squares.”** Under buffer: **“Notes, crises, and admin — counted before anyone can book.”**

8. **“See more options” → calmer secondary**  
   Ship: **“Show other trusted colleagues”** / when open **“Hide other colleagues.”** Avoid shopping-cart energy.

9. **Invite accept page payoff**  
   Lead with mutual benefit: **“When either of you hits your weekly cap, the other can catch the next client — on the same booking page.”**

### P2 — polish if time

10. **Booked page visit-kind badge**  
    Pill: **Consultation** vs **Session**; referred line already good — bold **“so you were not turned away.”**

11. **Directory demo caption**  
    **“Elena is near her weekly cap — book her to see the referral path. James and Maya have room.”**

12. **Login/setup micro-positioning**  
    Login sub: **“Hour cap, booking link, and the colleagues you trust.”** Setup portal section title: **“After they book → send them to intake.”**

---

## Competitor messaging angles that resonate with solo LPC / LCSW / LMFT founders

Use these tones on landing, setup, and outbound (not feature laundry lists).

| Angle | Who already uses it | How ScheduleAVisit can say it |
| --- | --- | --- |
| **Boundaries / burnout protection** | SonderMind booking windows; SP “control your availability” | “Protect 25 clinical hours — without turning people away.” |
| **Autonomy, not employment** | Alma membership | “Your link. Your peers. Your cap. Not a marketplace that owns the client.” |
| **Less admin, more care** | SimplePractice all-in-one; Headway billing offload | “We don’t replace your EHR — we stop the email tennis before intake.” |
| **Meet clients where they are** | SP night/weekend booking narrative | “They find you at 10pm. They shouldn’t wait until your lunch break to get a reply.” |
| **Fit before commitment** | Calendly free consult culture | “Offer a free consult that still counts against your real week.” |
| **Ethical handoff** | SP clinician referrals; Alma community | “Full isn’t failure — it’s a warm introduction to someone you’d send your sister to.” |
| **Insurance without identity loss** | Headway / SonderMind / Alma | “Keep Headway or SonderMind for claims — use ScheduleAVisit for the front door.” |
| **Discovery without dead ends** | Psychology Today “accepting”; Zocdoc instant book | “Put one link on your PT profile. If you’re full, the link still finishes the job.” |
| **Simple, not enterprise** | Jane ease-of-use; Calendly speed | “Live in an afternoon. No widget maze. No $125 membership to share a calendar.” |
| **Caseload honesty** | Rarely named explicitly | “Empty squares are a lie. Weekly hours are the truth.” ← category-defining line |

### Messaging to avoid (crowded or mismatched)
- “All-in-one EHR” (SP/Jane/TherapyNotes win).
- “We’ll fill your caseload with insured leads” (Headway/Alma/SonderMind win — and founders often resent lead quality/control tradeoffs).
- HIPAA/BAA claims ScheduleAVisit does not make (README: not a HIPAA product).

---

## Implications for product narrative (one paragraph)

Solo founders already believe in online booking, reminders, and portals. What still hurts is **being full with integrity**: Psychology Today says “not accepting,” Zocdoc shows no slots, Jane waitlists them for later, and network apps reassign them to strangers. ScheduleAVisit should own **capacity-honest booking** — weekly hour caps, consult vs session, portal handoff to tools they already use, and **trusted peer chains** so “full” becomes a successful handoff instead of a closed door.

---

## Source bookmarks (non-exhaustive)

- SimplePractice: online appointment requests; waitlist; Clinician Referrals; practitioner booking blog (Lindsay Bryan-Podvin LMSW, Mar 2025)
- Jane: Wait List Notifications / exclusive access
- TherapyNotes: TherapyPortal setup & assigned-clinician scheduling limits
- Calendly therapy consult guides (MyWellbeing et al.); HIPAA caveats on non-Enterprise plans
- Headway: Sigmund calendar / direct booking; intake forms & client tasks
- SonderMind: Direct Scheduling FAQ (notice + horizon controls)
- Alma: for-providers membership / insurance / directory autonomy messaging
- Psychology Today: “accepting new patients” discovery framing
- Zocdoc: instant book + insurance + near-term availability filters
