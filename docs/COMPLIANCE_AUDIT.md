# MediaHub — UK Legal Compliance Audit

**Date:** 2026-06-12
**Auditor:** Engineering compliance pass (not legal advice; solicitor review required)
**Scope:** UK law as engaged by the code actually in this repository at commit `7db1b61`.
**Method:** Four parallel code-evidence sweeps (personal-data flows, third parties + legal
surfaces, security posture, IP/licensing + scraper behaviour), verified against the live
code, not the docs. Every claim below carries file:line evidence or is marked
CANNOT VERIFY.

---

## 1. Executive verdict

**No — MediaHub cannot lawfully be sold to UK consumers today.** The engineering
fundamentals (security, tenant isolation, human approval, consent gating, export-only
output with no social publishing, polite scraping) are unusually strong, but the legal
wrapper is almost entirely absent and one user-facing statement is materially false:

1. **The live privacy page states "No data is sent to third parties beyond fetching
   public PB-lookup pages"** (`src/mediahub/web/web.py` privacy_page, ~12468–12535) while
   the code sends children's names, ages, clubs and results to Google Gemini and
   Anthropic in caption prompts (`src/mediahub/ai_core/narrate.py:84–150`), athlete
   photos to Photoroom/Replicate (`src/mediahub/media_ai/providers/`), names + birth
   years to DuckDuckGo in plaintext query URLs
   (`src/mediahub/pb_discovery/discover.py:142–143`,
   `src/mediahub/web_research/search.py:11–12`), and emails to Stripe
   (`src/mediahub/web/billing.py`). A false privacy notice is worse than none —
   UK GDPR Art. 13/14 breach plus a CPUT/consumer-law misleading-statement exposure.
2. **There is no Terms of Service, no Article 28 DPA with clubs, no lawful-basis or
   parental-consent capture, no DPIA** — for a system whose data subjects are mostly
   under-18s and whose output is public social media.
3. **Live Stripe subscription billing** (`src/mediahub/web/billing.py`, routes
   `web.py:19518–19660`) **with none of the CCR 2013 pre-contract information, 14-day
   cooling-off/waiver handling, or DMCCA 2024 renewal-reminder duties.**
4. **No service-provider identity anywhere** (E-Commerce Regulations 2002 / Companies
   Act 2006).

The product becomes sellable once the Critical items in §4 are remediated in code +
documents, and the operational items (ICO registration, executed DPAs, solicitor review)
are completed outside the repo.

---

## 2. Findings table

| # | Area | Status | Severity | Evidence | Remediation |
|---|------|--------|----------|----------|-------------|
| 1.1 | Controller/processor analysis & Art. 28 DPA | NON-COMPLIANT | Critical | No DPA anywhere; clubs upload athlete data with no processing terms. PB discovery cache (`pb_discovery/cache.py:76–113`) is arguably independent-controller activity | Draft DPA, present at onboarding, record acceptance (build item B4) |
| 1.2 | Lawful basis per processing activity | NON-COMPLIANT | Critical | No lawful basis identified or recorded anywhere in code or docs | Lawful-basis register in Privacy Notice + club attestation at onboarding (B2, C8) |
| 1.3 | Children's data safeguards | PARTIAL | Critical | Strong: MediaHub does not publish to social — minors' content is only ever exported for a human to post; media assets carry `needs_parental_consent` (`media_library/models.py:32,63`). Missing: no parental-consent capture/attestation, field unenforced, no children's section in privacy notice | Consent attestation at onboarding (C8); children's section in Privacy Notice (B2) |
| 1.4 | Special category data (para classification) | NOT APPLICABLE (today) | Low | No S1–S14/SB/SM/para/disability handling anywhere in `recognition/`, `interpreter/`, `web/canonical.py` | Note in DPIA as a future-risk trigger before any para-swimming support ships |
| 1.5 | Privacy notice accuracy (Art. 13/14) | NON-COMPLIANT | Critical | `/privacy` page exists but materially misstates third-party flows (web.py privacy_page ~12468–12535) vs. actual egress in §3 of the data-flow map | Rewrite as full Art. 13/14 notice describing real flows (B2) |
| 1.6 | Right to erasure | PARTIAL | High | Per-run delete exists (`web.py:12537–12580` → `web.py:1831–1860`) but misses: `memory.db` caption store (`memory/store.py` — no delete API), PB warm cache (`pb_discovery/cache.py:76`), research cache, and there is no account deletion at all (`users.jsonl`, `auth.py:133–150`) | Cascading erasure + account deletion + athlete-level erasure (C1) |
| 1.7 | Right of access / portability | PARTIAL | High | Per-run JSON export exists (`web.py:12328–12450`); no per-account or per-athlete export | Account/athlete data export (C2) |
| 1.8 | Rectification + post-publication correction | NON-COMPLIANT | High | No rectification or takedown workflow; once a club has exported and posted content manually there is no correction path in code | Correction/takedown workflow (C3) |
| 1.9 | Retention limits & deletion jobs | PARTIAL | High | TTLs exist only for caches (7d warm PB `pb_discovery/cache.py:82`, 30d research `web_research/search.py:36`) and ring-buffer prunes (`observability/llm_usage.py:481`, demo runs `web/demo_try.py:20`). Runs, uploads (`input.bin`), packs, `memory.db`: indefinite | Configurable retention + scheduled deletion job (C4) |
| 1.10 | Security (Art. 32) | PARTIAL | Medium | Strong: bcrypt-12 (`auth.py:117`), constant-time verify + dummy hash (`auth.py:128,220`), HttpOnly/SameSite/Secure cookies (`web.py:7920–7934`), 0600 secret files (`web.py:7896`), parameterised SQL throughout, `_h()` escaping, ZIP-bomb guards (`interpreter/_zip_safety.py:24–26`), tenant isolation per ADR-0014 (`web.py:1643–1686`, invariant tests). Gaps: no rate limiting on `/login` `/signup` `/developer` (`web.py:18633,18694,18790`); no HSTS/forced HTTPS in app; SQLite unencrypted at rest | Auth rate limiting + security headers (C5); disk encryption = operational |
| 1.11 | International transfers | NON-COMPLIANT | High | Gemini/Anthropic/Photoroom/Replicate/Stripe/ntfy are US-based processors; `render.yaml` sets no region (Render default = US/Oregon); `fly.toml:6` = lhr (UK). No transfer mechanism (IDTA/Addendum) referenced anywhere | Document transfers + mechanisms in Privacy Notice/DPA (B2, B4); executing the mechanisms is operational (D) |
| 1.12 | Breach readiness (72h) | PARTIAL | Medium | Autonomy audit ledger is queryable (`workflow/autonomy.py` AuditLog); no breach-response procedure | Breach procedure section in DPA + ops checklist (B4, D) |
| 1.13 | DPIA | NON-COMPLIANT | Critical | Mandatory here (children's data at scale + public dissemination + third-country AI processing — ICO DPIA screening criteria squarely met); none exists | Draft DPIA (B5) |
| 2.1 | PECR — cookies | PARTIAL | Low | Only cookie set is the strictly-necessary Flask session cookie (`web.py:7908–7934`); no analytics/tracking anywhere (no Sentry/GA/PostHog — verified by sweep). Missing: any cookie disclosure | Cookie policy page + consent gate for future non-essential cookies (B3) |
| 2.2 | PECR — marketing email | NOT APPLICABLE | — | No marketing/newsletter email functionality exists (verified: email used only for auth + Stripe) | Note in BILLING/ops docs if ever added |
| 3 | Consumer Rights Act 2015 | NON-COMPLIANT | High | No ToS at all → no statement of digital-service quality duties, no contract terms whatsoever | ToS with CRA-aware terms (B1) |
| 4 | Consumer Contracts Regs 2013 | NON-COMPLIANT | Critical | Checkout (`web.py:19518–19551`) collects payment with no pre-contract information, no 14-day cancellation right, no digital-content waiver wording | Pre-contract info + cooling-off acknowledgement before checkout (C6) |
| 5 | DMCCA 2024 — subscriptions | NON-COMPLIANT | High | Auto-renewing Stripe subscriptions (`billing.py:172–198`, annual quote checkout `billing.py:201–265`) with no renewal reminders and no in-app statement of renewal terms. Good: no drip pricing, no fake reviews, price honesty is enforced (`/pricing` shows "Pricing TBC" until evidence gate, `web.py:19306–19448`); cancellation via Stripe portal (`web.py:19551+`) is roughly signup-parity but undocumented | Renewal terms at checkout + reminder requirement (C6); Stripe-side reminder config is operational (D) |
| 6 | E-Commerce Regs 2002 / Companies Act 2006 | NON-COMPLIANT | High | Footer has only status/privacy/roadmap links (`web.py:6963–6982`); no provider name, address, email, company number anywhere | Identity block in footer + legal pages with [PLACEHOLDERS] (C7) |
| 7.1 | Dependency licensing | COMPLIANT | Low | No in-process copyleft; SearXNG (AGPL) is a separate unmodified service (`tests/test_agpl_isolation.py:41–54`); PDF stack is pdfplumber/pypdf/pdfminer.six (no PyMuPDF) (`requirements.txt:6–8`); Remotion company-licence need is flagged and flag-gated (`MEDIAHUB_REEL_ENGINE=ffmpeg` fallback, `docs/DEPENDENCY_LICENSING.md`) | Remotion company licence = operational item (D) |
| 7.2 | Vendored code & attributions | PARTIAL | Medium | 5/7 `vendor/` dirs retain licences (Apache-2.0/MIT); `vendor/agent-skills-main/` and `vendor/bencium-marketplace-main/` have **no licence file** — redistribution rights unverifiable | THIRD_PARTY_NOTICES + resolve/flag the two unlicensed dirs (C9) |
| 7.3 | Fonts & visual assets | PARTIAL | Low | All bundled fonts are Google-Fonts OFL, self-hosted (`web/static/fonts/README.md`); attribution implicit, no consolidated notice | FONT/THIRD_PARTY notices file (C9) |
| 7.4 | Scraping behaviour | COMPLIANT (behaviour) / CANNOT VERIFY (target ToS) | Medium | robots.txt respected by default (`results_fetch/crawl.py:363–408,449`), 0.3 s politeness delay (`crawl.py:454`), identified UAs ("SwimPBDiscovery/7.5" `pb_discovery/fetch_profile.py:65–73`; "MediaHubResults/1.0" `results_fetch/fetch.py:312+`), 7-day warm cache (`pb_discovery/cache.py:82`), hard budgets (400 pages/50 MiB/180 s, `crawl.py:122–142`). swimmingresults.org ToS/database-right position cannot be assessed from code | Document scraper conduct (C9); ToS/database-right review = solicitor (D) |
| 7.5 | Club logos / athlete photo rights | NON-COMPLIANT | High | No warranty or consent basis captured anywhere for uploaded logos/photos; `permission_status` field exists but nothing requires it (`media_library/models.py:63`) | Club warranty in ToS/DPA (B1, B4) + onboarding attestation (C8) |
| 7.6 | Platform policies (IG/FB/TikTok) | NOT APPLICABLE | — | MediaHub does not publish to or automate any social platform: approved content is exported/downloaded and the club posts it manually. No platform API integration and no scraping of platforms exists in code | Documented here; revisit if any platform integration is ever added |
| 8 | Online Safety Act 2023 | NOT APPLICABLE | — | No user-to-user functionality: the public wall is one-way, club-curated, token-scoped, approved-cards-only output (`web/public_wall.py:14,133–146`); no comments, uploads, or interaction between service users | Documented here; revisit if any U2U feature ships |
| 9 | Accuracy / defamation / publication risk | PARTIAL | High | Strong: deterministic parsers/detectors, confidence scores, human approval before any content is used, consent gate at approval/pack build, immutable audit ledger; MediaHub does not publish to social — approved content is only exported for a human to post. Missing: post-publication correction/takedown workflow (1.8) | Correction/takedown workflow (C3) |
| 10.1 | Sponsored content / advertising (CAP code) | PARTIAL | Medium | Sponsor manager exists (`club_platform/sponsors.py`, PC.8) — sponsored output is advertising; no ad-disclosure (#ad) handling in captions | Disclosure note in ToS + sponsor docs (B1) |
| 10.2 | Accessibility (Equality Act good practice) | PARTIAL | Low | axe-core is a dependency (`package.json`) and used in tests; no formal accessibility statement | Good practice; note in handover |

---

## 3. Detailed findings

### 3.1 UK GDPR & DPA 2018

**Roles.** For athlete data uploaded by clubs, MediaHub (the operator) is a
**processor** and each club is controller — Art. 28 written terms are mandatory and
absent. Two activities exceed processor scope and make the operator an
**independent controller**: (a) PB discovery, which proactively searches the open web
for a named child's results and caches them for 7 days across tenants
(`pb_discovery/discover.py:133–143`, `cache.py:76–113`); (b) account data
(`users.jsonl`). The DPA and Privacy Notice must reflect this split.

**Lawful bases (none currently identified anywhere).** The defensible map, to be
recorded in the Privacy Notice and DPA:
- Club-uploaded results processing → club's purposes; operator processes under Art. 28
  contract. The club's own basis (typically legitimate interests + club–member
  agreements, with parental consent for photos of minors) must be attested by the club
  — the system currently never asks.
- PB discovery from public sources → legitimate interests (Art. 6(1)(f)) — needs an
  LIA in the DPIA; data is already public sports results, but subjects are children,
  which weighs heavily in the balancing test.
- Account/billing data → contract (Art. 6(1)(b)); legal obligation for tax records.

**Children.** Most competitive swimmers are minors. The ICO Children's Code applies to
online services *likely to be accessed by children*; MediaHub's users are adult club
volunteers, so the Code is engaged only weakly, but the *processing* of children's data
at scale plus public dissemination makes the DPIA mandatory and the
parental-consent attestation essential. The code's strongest safeguard — MediaHub does
not publish to social at all, so minors' content (like all approved content) is only
ever exported for a human to post — must never be weakened.

**Special category.** No para-swimming classification, disability, or health data is
parsed, stored, or rendered today (verified sweep of `recognition/`, `interpreter/`,
`web/canonical.py`). If para events are ever supported, classification codes (S1–S14)
reveal disability → Art. 9 condition needed *before* shipping. Recorded as a DPIA
trigger.

**Data subject rights — code reality.**
- Erasure: per-run delete cascades DB row + run JSON + run dir + turn-into packs +
  workflow file (`web.py:1831–1860`) but **not** `memory.db` captions (no delete API in
  `memory/store.py`), PB warm cache keyed by swimmer, or research cache. No account
  deletion exists.
- Access/export: per-run JSON export only (`web.py:12328–12450`).
- Rectification: nothing. A wrong result about a named child that a club has exported and
  posted has no in-product correction or takedown path.

**Transfers.** Gemini (Google, US), Anthropic (US), Photoroom (FR/US — CANNOT VERIFY
region from code), Replicate (US), Stripe (US), ntfy.sh (default server, EU/US —
operator-configurable), DuckDuckGo (US). Render deployment has **no region pinned**
(`render.yaml`) → default US; Fly config pins London (`fly.toml:6`). No IDTA/Addendum or
adequacy reliance is documented anywhere. The UK has adequacy for the
EU and an extension for the US (UK–US Data Bridge) **only** for certified organisations —
whether each processor is certified CANNOT be verified from code and is an operational
item.

**Security (Art. 32).** Genuinely strong baseline — see findings table 1.10. The gaps
to fix in code: rate limiting on auth endpoints, HSTS/security headers. Disk encryption
and TLS termination are platform-level (Render/Fly) and go on the operational checklist.

### 3.2 PECR
The only cookie is Flask's signed session cookie — strictly necessary, exempt from
consent. There is no analytics, tracking, or third-party embed (verified: no
Sentry/PostHog/GA/gtag/plausible anywhere). PECR therefore requires **disclosure**, not
a consent banner. Remediation: a Cookie Policy page, plus a consent gate that any future
non-essential cookie must pass through (so the protection is real, not theatre). No
marketing email exists → soft-opt-in rules not engaged.

### 3.3 CRA 2015 / CCR 2013 / DMCCA 2024
Buyers may be unincorporated volunteer clubs → treat as consumers. There is **live
subscription billing with no contract**: no ToS, no pre-contract information, no
cooling-off handling, no renewal reminders. The pricing page is honest (shows
"Pricing TBC" until the PC.4 evidence gate passes — `web.py:19306–19448`), there is no
drip pricing and no testimonial/review surface. Cancellation goes through the Stripe
customer portal — acceptable, but must be stated up front and reachable as easily as
signup. Required: B1 (ToS), C6 (checkout flow), D (Stripe renewal-reminder configuration
— Stripe can send these but it must be switched on, which code cannot prove).

### 3.4 E-Commerce Regs / Companies Act
Nothing identifies the service provider anywhere in the UI. Name, geographic address,
email, and (if incorporated) company number + registered office must be displayed —
remediation C7 with [PLACEHOLDERS].

### 3.5 IP & licensing
Clean overall (see 7.1–7.4). Action: THIRD_PARTY_NOTICES consolidation, font
attribution, resolve the two unlicensed `vendor/` directories, document scraper conduct.
Remotion company licensing and the swimmingresults.org terms/database-rights position
are operational/solicitor items.

### 3.6 Online Safety Act 2023
Out of scope: MediaHub has no user-to-user content sharing. Content flows one way —
club → MediaHub → club-approved output. The public wall (`web/public_wall.py`) is a
read-only, token-scoped showcase of club-approved cards (initials-only by default,
`public_wall.py:15–16,60–64`); viewers cannot post, comment, or interact. Re-assess if
any interactive feature ships.

### 3.7 Accuracy, defamation & publication risk
The deterministic engine + confidence scores + consent gate + human approval are a
strong control set before any content is used. MediaHub does not publish to social —
approved content is only exported/downloaded and the club posts it manually — so a
human decision always stands between the engine and any external use. The genuine
gap is **post-export**: no correction or takedown workflow once a club has downloaded
and posted content. Remediation C3.

---

## 4. Remediation roadmap (severity order)

### (a) Code changes — implemented in this branch
| ID | Item | Severity |
|----|------|----------|
| C0 | Fix the false third-party statement on `/privacy` (immediate, part of B2 wiring) | Critical |
| C7 | Provider-identity block ([PLACEHOLDERS]) in footer + legal pages (E-Commerce Regs) | High |
| C8 | Onboarding lawful-basis + parental-consent attestation, timestamped & versioned | Critical |
| —  | ToS/DPA acceptance recording at signup + re-acceptance on version change (with B1/B4) | Critical |
| C1 | Erasure that cascades: account deletion; athlete-level erasure across runs, PB caches, research cache, `memory.db`, rendered assets, packs | High |
| C2 | Data export per account (and per run, existing) | High |
| C3 | Rectification + post-publication correction/takedown workflow | High |
| C4 | Configurable retention periods + scheduled deletion job (runs, uploads, packs, memory) | High |
| C6 | CCR/DMCCA checkout flow: pre-contract information + cooling-off acknowledgement with digital-content waiver wording + renewal terms display | Critical |
| C5 | Auth rate limiting; HSTS + security headers; LLM prompt data-minimisation flag (pseudonymise athlete names, config-gated) | Medium |
| C9 | THIRD_PARTY_NOTICES + font attribution; flag unlicensed vendor dirs; scraper-conduct doc | Medium |
| B3w | Cookie policy page + consent gate for future non-essential cookies | Low |

### (b) Legal documents — drafted and integrated (all headed "DRAFT — requires solicitor review")
| ID | Document | Integration |
|----|----------|-------------|
| B1 | Terms of Service (CRA/CCR/DMCCA-aware, IP, club responsibilities, sponsor-content disclosure) | `/terms` page, footer, signup acceptance |
| B2 | Privacy Notice (Art. 13/14, real flows, children's section, transfers, retention table, ICO complaint info) | `/privacy` page, footer, signup |
| B3 | Cookie Policy | `/cookies` page, footer |
| B4 | Article 28 DPA template (sub-processors, security, breach, deletion on termination) | `/dpa` page, onboarding acceptance |
| B5 | DPIA | `docs/compliance/DPIA.md`, marked for controller sign-off |

### (c) Operational items (outside the repo)
1. Pay the ICO data protection fee / register as a controller.
2. Pin the Render deployment region (or move to Fly lhr) and enable disk encryption.
3. Accept/execute processor terms + transfer mechanisms with: Google (Gemini API),
   Anthropic, Photoroom, Replicate, Stripe, ntfy (or self-host), hosting
   provider. Verify UK–US Data Bridge certification or execute IDTA/Addendum per vendor.
4. Configure Stripe renewal-reminder emails + receipts; verify portal cancellation flow.
5. Obtain a Remotion company licence (or pin `MEDIAHUB_REEL_ENGINE=ffmpeg`).
6. Fill every [PLACEHOLDER] (company identity, addresses, contact email, ICO reg no.).
7. Execute the DPA with each onboarded club; keep signed copies.
8. Insurance (professional indemnity / cyber).
9. Breach-response runbook + 72h ICO reporting procedure assigned to a named person.

### (d) Requires a qualified solicitor
1. Review/finalise all drafted documents (ToS, Privacy Notice, Cookie Policy, DPA, DPIA).
2. swimmingresults.org terms of use + database-right position for PB discovery.
3. Confirm the lawful-basis map and the legitimate-interests assessment for PB discovery
   of children's public results.
4. DMCCA subscription-regime timing (provisions commence in stages) and the exact
   renewal-reminder cadence required.
5. Liability-cap and indemnity drafting in the ToS beyond the fair-terms baseline.

---

## 5. Cannot verify from code alone
1. Whether Google/Anthropic/Photoroom/Replicate/Stripe retain or train on
   submitted data — depends on their terms, not this repo.
2. Each vendor's UK transfer mechanism status (Data Bridge certification, IDTA).
3. The actual Render deployment region and disk-encryption state of production.
4. TLS termination / HSTS at the platform edge (code sets cookies correctly; headers
   added in C5).
5. swimmingresults.org terms of use and whether PB discovery's conduct breaches them.
6. Whether Stripe renewal-reminder emails are configured in the live Stripe account.
7. Upstream licences of `vendor/agent-skills-main/` and
   `vendor/bencium-marketplace-main/` (no licence files present).
8. Whether the production `.env` matches `.env.example` hygiene.
9. Whether any production logs (platform-level) capture personal data beyond what the
   app writes.
10. Photoroom's processing region.

---

*Phase 4 build work is recorded in the handover section appended at the end of this
file (or `docs/COMPLIANCE_HANDOVER.md`).*
