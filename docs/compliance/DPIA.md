# Data Protection Impact Assessment (DPIA) — MediaHub

**Status: DRAFT — requires controller sign-off and solicitor review before going live.**
**Date:** 2026-06-12 · **Version:** 1.0 · **Owner:** [DPIA_OWNER_NAME, ROLE]

A DPIA is effectively mandatory for MediaHub under UK GDPR Art. 35 and the ICO's
screening criteria: it processes **children's personal data at scale**, supports
**public dissemination** of that data (social media), and uses **innovative
technology** (cloud LLM generation) with **third-country processing**. This document
follows the ICO's DPIA structure. It describes the system as actually built (evidence:
`docs/COMPLIANCE_AUDIT.md`).

---

## Step 1 — Identify the need

MediaHub turns swimming competition results into branded social-media content for UK
clubs. The data subjects are predominantly **under-18 athletes**. The processing exists
to save volunteer time while keeping a human approval gate between data and public
publication. This DPIA covers the whole pipeline: ingestion → detection → PB
verification → rendering → AI captioning → approval → export/publication, plus
account/billing data.

## Step 2 — Describe the processing

**Nature.** Clubs upload results files (HY3/SDIF/PDF/CSV/XLSX) or links; MediaHub
parses them deterministically, detects achievements, verifies personal bests against
public web sources, renders graphics/video on its own servers, generates captions via
cloud LLMs, and holds everything for human review. Publication is by download or via
the club's Buffer account.

**Scope of data.** Athlete names, dates of birth/ages, gender, club, race results,
age groups, governing-body identifiers, photographs. Account data: club officer email +
bcrypt-hashed password. Billing: plan + Stripe customer reference. No special-category
data is intentionally processed; para-swimming classifications are **not** parsed
(re-run this DPIA before any para-swimming support — classification reveals
disability, Art. 9).

**Recipients / processors.**
| Recipient | Data | Region |
|---|---|---|
| Hosting provider ([HOSTING_PROVIDER_AND_REGION]) | All stored data | [HOSTING_REGION] |
| Google (Gemini API) | Caption prompts: name, event, time, placement, PB detail, age group, club, venue; page screenshots in link-reading | US |
| Anthropic | Same, as failover | US |
| Photoroom / Replicate (only if enabled) | Athlete photos for background removal | [PHOTOROOM_REGION] / US |
| DuckDuckGo (or self-hosted SearXNG) | Search queries: athlete name, club, birth year | US |
| Buffer (only if club connects) | Approved caption + graphic | US |
| Stripe | Email, plan (controller-side) | US |

**Retention.** Caches: PB warm cache 7 days, research cache 30 days, demo uploads
24 hours. Runs/uploads/packs: until deleted or per configured retention
(`MEDIAHUB_RETENTION_DAYS`). Caption memory: deleted with its run/account. Posting and
AI-usage logs: ring-buffer trimmed.

**Context.** Data subjects are children; the uploading club holds the direct
relationship and the consents. Results are typically already public (meet results,
rankings pages); MediaHub's added step is *amplification* into social media content.

## Step 3 — Consultation

[CONSULTATION_RECORD — the controller (each club) should confirm its athlete/parent
communications cover this processing; pilot-club feedback to be recorded here.]

## Step 4 — Necessity and proportionality

- **Lawful bases:** processor-on-instructions for club uploads (Art. 28 DPA + club
  attestation at workspace setup, recorded with timestamp); contract for accounts;
  legitimate interests for PB verification of already-public results (LIA below).
- **Data minimisation:** prompts carry only the fields needed for an accurate caption.
  A pseudonymisation flag (`MEDIAHUB_LLM_PSEUDONYMISE=1`) replaces athlete names with
  tokens in LLM prompts and restores them locally afterwards, trading some tone
  fidelity for minimisation; documented in ENV_INVENTORY.
- **Accuracy:** parsing/detection/ranking are deterministic; PB claims are verified
  against sources with confidence scores; uncertain rows are flagged, never guessed.
- **Human oversight:** nothing publishes without club approval except per-type
  autonomous opt-in behind a fail-closed gate — and **content about under-18s never
  auto-publishes** (`publishing/publish_gate.py`).
- **Rights support:** in-product erasure (run, athlete, account — cascading through
  caches, caption memory, rendered assets), export, rectification + post-publication
  correction/takedown workflow; Art 12A request log with stop-the-clock metadata
  (`/organisation/athlete-rights`); s.164A complaints intake with 30-day
  acknowledgement (`/complaints`).
- **Consent gating (two registries, one answer):** the W.2 per-athlete consent
  levels (photo/name/initials/do-not-feature) AND the compliance ledger
  (refusals/revocations, Art 18 restriction, opt-in mode with parental flags,
  erasure suppression) — a card is blocked at approval, pack build, the publish
  route, and the autonomous gate if EITHER blocks. Tenant-level Children's Code
  controls (surname initialisation, age suppression, photo exclusion) apply on
  top for under-18s, ON by default for new workspaces.

**Legitimate interests assessment (PB verification).** Purpose: prevent publishing a
false "personal best" claim about a named child — an accuracy duty. Necessity: the
check requires querying public results sources by name/club/birth-year; no less
intrusive means achieves verification. Balancing: the data is already public sports
data; lookups are cached (7 days) and rate-limited; the output stays inside the club's
review queue. Children's expectations: a competitive swimmer's results are routinely
published by governing bodies; verification reduces, not increases, the risk to them.
Conclusion: legitimate interests can be relied on, **subject to solicitor
confirmation**.

## Step 5 — Risks

| # | Risk | Likelihood | Severity | Overall |
|---|------|-----------|----------|---------|
| R1 | Children's data sent to US AI providers is retained/trained on beyond instruction | Possible | Significant | **High** |
| R2 | Wrong result/misidentified child published publicly (defamation/distress) | Possible | Significant | **High** |
| R3 | Club uploads data without parental consent; MediaHub amplifies it | Possible | Significant | **High** |
| R4 | Cross-tenant exposure of athlete data | Unlikely | Significant | Medium |
| R5 | Indefinite retention of children's data (caches, caption memory) | Was probable | Moderate | Medium |
| R6 | Breach of `DATA_DIR` (unencrypted SQLite at rest) | Unlikely | Significant | Medium |
| R7 | Public wall / demo exposes identifiable minors | Unlikely | Moderate | Low-Medium |
| R8 | Future para-swimming support leaks disability data | N/A today | Severe | Trigger |
| R9 | Prompt-injected results file manipulates captions about a child | Possible | Moderate | Medium |

## Step 6 — Mitigations

| Risk | Mitigation | Status |
|------|-----------|--------|
| R1 | Providers used via API terms with training disabled where offered; transfer mechanisms ([UK-US Data Bridge / IDTA]) executed per provider; pseudonymisation flag available; prompt content minimised; provider list disclosed in Privacy Notice/DPA | Code: done; vendor terms: **operational** |
| R2 | Deterministic engine + confidence scores + human approval + fail-closed gate; rectification + correction/takedown workflow; minors never auto-publish | Done |
| R3 | DPA + recorded lawful-basis/parental-consent attestation at workspace setup; children's section in Privacy Notice; media `permission_status` field | Done (attestation); per-photo consent enforcement: roadmap |
| R4 | ADR-0014 isolation + invariant test suite; IDOR checks on run/card routes | Done |
| R5 | Retention job (`MEDIAHUB_RETENTION_DAYS`) for runs/uploads/packs; erasure cascades to caches + caption memory + posting-log excerpts | Done |
| R6 | Hosting-level disk encryption; 0600 file modes; secrets in env | **Operational** (platform) |
| R7 | Wall is opt-in, token-scoped, approved-cards-only, initials-by-default; demo skips PB lookups and purges at 24h | Done |
| R8 | Standing rule: re-run DPIA + Art. 9 condition before para support ships | Recorded |
| R9 | Untrusted prose rides inside data delimiters with a hardened system prompt; instruction-shaped text is detected, logged (`prompt_injection_suspected`) and flagged — never silently rewritten; LLM output is inert text and the approval gate is server-side state a caption cannot reach | Done |

## Step 7 — Sign-off

| Item | Name | Date |
|------|------|------|
| Measures approved by | [CONTROLLER_SIGN_OFF] | |
| Residual risks accepted by | [CONTROLLER_SIGN_OFF] | |
| DPO advice (if appointed) | [DPO_NAME] | |
| Consult ICO first? | Only if the High residual risks above cannot be reduced — currently judged reducible via the mitigations; **solicitor to confirm** | |

**Review:** re-run on any of — new sub-processor, para-swimming support, autonomy
default changes, public-wall full-name default, EU expansion.
