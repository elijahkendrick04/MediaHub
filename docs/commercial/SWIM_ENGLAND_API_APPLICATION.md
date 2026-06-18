# Swim England approved-systems API — application draft (PC.6a)

**Status:** draft — ready for the founder to adapt and submit.
**Tracking:** the live application state (not applied / applied / approved /
declined) is recorded on the operator console (`/operator/commercial`).
**Why this exists:** [ADR-0012](../adr/0012-ngb-distribution-channel-reality-check.md)
split the NGB channel in two: official **data-API access is real — apply**
(Swim England announced the approved-systems API on 1 Oct 2025 and explicitly
invites commercial organisations to apply); promotional endorsement is
down-weighted to speculative and is **not** what this application asks for.
The API grants **data + credibility, not promotion**. Sources in
[`research/SCALING_DILIGENCE_2026.md`](../research/SCALING_DILIGENCE_2026.md).

> Submission route: the Swim England approved-systems / API partnership
> contact published with the 1 Oct 2025 announcement (re-verify the current
> form/address before sending — it may have moved since).

---

## 1. Who is applying

- **Product:** MediaHub — a hosted web application that turns official swim
  meet results into branded, ready-to-approve social-media content for clubs
  (result cards, athlete spotlights, meet recaps, story graphics and reels).
- **Organisation:** sole-founder UK business (Swansea / South-East Wales),
  working hands-on with local clubs first; hosted-only SaaS — clubs access it
  in the browser, nothing is installed or self-hosted.
- **Stage:** working product, first hand-sold club cohort in progress;
  pricing being validated with real annual prepay.

## 2. What we are asking for

Read access to official swim times and PB data for the clubs that authorise
us, via the approved-systems API — the same class of access granted to the
initial club-administration partners (Swim Club Manager, Swim Manager), used
for a different, complementary job: **celebration content**, not club admin.

## 3. Why official data (what the API replaces)

Today MediaHub ingests the results files clubs already hold (HY3, SDIF,
SportSystems exports, PDFs) and verifies PBs against the club's own history.
Official API access would:

- replace file-shuffling with verified, current times straight from source;
- make "is this a PB?" checks authoritative rather than club-file-dependent;
- remove any temptation (industry-wide, not ours) to scrape rankings pages —
  we deliberately do not scrape Swim England rankings; ToS/CMA/GDPR analysis
  of why scraping minors' competition data is the wrong path is part of our
  internal diligence.

## 4. Safeguarding & data-protection posture (the substance of this application)

Most of this data concerns **minors**. MediaHub's handling is engineered, not
aspirational — each point below is enforced by tests that fail our build:

- **Hard tenant isolation.** Every run-scoped route is guarded
  (`_can_access_run`) and a sweep test auto-discovers all such routes and
  proves no club's data is reachable from another club's session
  ([ADR-0003](../adr/0003-pilot-safety-invariant-lock.md)). Workspace
  membership now binds sign-ins to clubs (org → workspace,
  [ADR-0014](../adr/0014-org-workspace-multitenancy-schema.md)), pinned by a
  second invariant suite.
- **Deterministic facts.** Times, PBs and rankings are computed by
  deterministic parsers and detectors — never by a language model — so a
  published time can always be traced to its source row (provenance is kept
  end-to-end).
- **Human approval before content is used**, always: MediaHub does not publish
  to social channels at all. Approved content — minors' included — is only ever
  exported/downloaded for a human to post manually, and consent gating blocks a
  refused athlete from approval and packing.
- **Immutable audit ledger** per organisation; export history and approval
  states are recorded.
- **EU/UK data-residency hygiene:** fonts and rendering are self-hosted
  (no Google-Fonts-style CDN leaks — the Munich ruling drove this); secrets
  live in environment config only; ledgers holding personal data are
  owner-read-only on disk.
- **Least privilege:** we request read access only, scoped to clubs that have
  authorised MediaHub, and we never connect a club's social account without
  the club doing so itself.

## 5. What Swim England gets

- Clubs (volunteer-run, time-poor) celebrating verified achievements with
  accurate, on-brand content within hours of a meet — increasing the visible
  value of official data.
- A commercial partner whose accuracy incentives align with the source of
  truth: our product is *wrong* if the time is wrong, so we want the official
  number, not a scraped one.
- A documented, auditable data path (this section + the ADRs above) rather
  than another scraper.

## 6. Technical integration notes

- Server-to-server REST consumption from our hosted deployment (Render);
  no client-side key exposure; keys held in environment configuration with
  rotation supported by design.
- Volume: low and bursty (post-meet); respectful of rate limits; caching with
  provenance retained.
- Contact: Elijah Kendrick — elijahkendrick04@gmail.com.

---

*Internal checklist before sending:* re-verify the submission route; attach
current club references from the pilot cohort; confirm the live deployment
URL; date the letter; record "applied" on `/operator/commercial` the same day.
