# UK Legal Compliance — Handover

**Date:** 2026-06-12 · **Branch:** `claude/uk-legal-compliance-audit-pp3oti`
**Work order:** [`docs/COMPLIANCE_AUDIT.md`](COMPLIANCE_AUDIT.md) (read that first —
it grades every framework with file:line evidence and explains the remediation IDs
referenced below).

---

## 1. What was implemented, mapped to commits

| Commit | Capability | Audit refs |
|---|---|---|
| `9f1ac6f` | The audit itself — verdict, findings table, roadmap | all |
| `555d1f2` | `web/legal.py`: Terms of Service, rewritten Privacy Notice (Art. 13/14, accurate to real flows — replaces the false "no third parties" claim), Cookie Policy, Art. 28 DPA; `/terms` `/cookies` `/dpa` routes; footer legal links + provider-identity block; legal pages public before signup; `AcceptanceStore` ledger (`DATA_DIR/legal_acceptances.jsonl`, 0600) | 1.5, 6, B1–B4 |
| `7ffd963` | Versioned acceptance: signup requires + records ToS acceptance; `/legal/accept` re-acceptance interstitial + before_request gate on TERMS_VERSION change; workspace setup (both forms) requires + records DPA acceptance and the lawful-basis / parental-consent attestation per workspace | 1.1–1.3, 7.5, C8 |
| `375dd34` | `docs/compliance/DPIA.md` — ICO-structure draft incl. PB-discovery LIA, risk register R1–R8, mitigations mapped to this branch | 1.13, B5 |
| `7abbd25` | `mediahub.privacy` package: run-deletion cascade (per-run PB cache, caption memory, posting-log excerpts, motion cache); athlete erasure across runs/assets/caches/memory/log with prose redaction; account deletion (`UserStore.delete`, `MembershipStore.erase_email` — physical, tombstone-free) + password-verified route; account export | 1.6, 1.7, C1, C2 |
| `6ca25ec` | Correction/takedown workflow: tenant-scoped correction log in `data.db`, `/privacy/correction` records + pulls the card from the public wall + honest platform-takedown checklist; resolve flow; Privacy-page panel | 1.8, 9, C3 |
| `76c3351` | Retention: `MEDIAHUB_RETENTION_DAYS` daily scheduler sweep deleting expired runs **through the cascade** + stale uploads; Privacy page states the live setting | 1.9, C4 |
| `3fd1f87` | CCR/DMCCA checkout: `/billing/confirm` pre-contract page (price honesty, auto-renewal disclosure, cancellation parity, cooling-off); checkout blocked without the recorded immediate-supply acknowledgement | 4, 5, C6 |
| `72e59bd` | Security: per-IP rate limiting on `/login` `/signup` `/developer`; nosniff / Referrer-Policy / X-Frame-Options (embed-exempt) / conditional HSTS headers; `MEDIAHUB_LLM_PSEUDONYMISE` data-minimisation flag for caption prompts | 1.10, C5 |
| `b3dd4b1` | Licensing: OFL font attribution table, vendor/ licence flags (2 unresolved dirs), scraper-conduct record; ROUTE/API/file inventories regenerated | 7.2–7.4, C9 |

Billing code exists, so `docs/compliance/BILLING_REQUIREMENTS.md` was **not**
written — the lawful flows were implemented instead (audit roadmap C6).

## 2. Legal documents drafted — and their placeholders

All four live in `src/mediahub/web/legal.py`, render at `/terms`, `/privacy`,
`/cookies`, `/dpa`, and are headed **"DRAFT — requires solicitor review before going
live"**. The DPIA is at `docs/compliance/DPIA.md`. Placeholders to fill (grep for
them; the canonical list is `legal.PLACEHOLDERS` plus the DPIA's):

- `[COMPANY_NAME]`, `[COMPANY_NUMBER]`, `[REGISTERED_ADDRESS]`, `[CONTACT_EMAIL]`,
  `[ICO_REGISTRATION_NUMBER]` — `web/legal.py` constants (one edit fixes every page
  and the footer).
- `[PHOTOROOM_REGION]`, `[HOSTING_PROVIDER_AND_REGION]`, `[HOSTING_REGION]` —
  Privacy Notice §7 / DPA §6 / DPIA step 2.
- DPIA: `[DPIA_OWNER_NAME, ROLE]`, `[CONSULTATION_RECORD]`, `[CONTROLLER_SIGN_OFF]`,
  `[DPO_NAME]`, transfer-mechanism brackets.

Document versions are date-stamped constants (`TERMS_VERSION` etc.). **Bumping
`TERMS_VERSION` automatically routes every signed-in account through re-acceptance**
— that's the mechanism, not a promise.

## 3. Operational checklist (things code cannot do)

1. **ICO**: pay the data protection fee / register as controller; put the number in
   `legal.ICO_REGISTRATION_NUMBER`.
2. **Solicitor review** of ToS, Privacy Notice, Cookie Policy, DPA, DPIA — plus the
   specific questions in audit §4(d): swimmingresults.org terms/database right, the
   PB-discovery LIA, DMCCA commencement timing, liability drafting.
3. **Vendor data-processing terms + transfer mechanisms** — accept/execute and record
   for: Google (Gemini API), Anthropic, Photoroom, Replicate, Stripe, Buffer, ntfy
   (or self-host), hosting provider. Verify UK–US Data Bridge certification per
   vendor or execute IDTA/Addendum; disable provider training on submitted data
   where the toggle exists.
4. **Hosting**: pin the Render region (or use Fly `lhr`), confirm disk encryption,
   confirm TLS/HSTS at the edge.
5. **Stripe**: enable renewal-reminder emails for annual subscriptions (the ToS and
   `/billing/confirm` say "we send a reminder before renewal" — make it true), and
   verify the customer-portal cancellation flow stays as easy as signup.
6. **Remotion company licence** (or pin `MEDIAHUB_REEL_ENGINE=ffmpeg`).
7. **Execute the DPA with each club** — the in-product acceptance records it; keep
   countersigned copies where clubs want paper.
8. **Set `MEDIAHUB_RETENTION_DAYS`** for production and make sure the Privacy
   Notice's retention table stays true.
9. **Breach runbook**: name the person who notifies clubs without undue delay and
   the ICO within 72h; the posting log + autonomy audit ledger are the evidence
   sources.
10. **Insurance**: professional indemnity / cyber.
11. **vendor/**: resolve or remove `agent-skills-main/` and
    `bencium-marketplace-main/` (no licence files).
12. **Demo data**: confirm the public try-demo sample files contain no real
    children's data (could not be verified from code).

## 4. Closing verdict

**Before this branch:** not lawfully sellable — no ToS, a materially false privacy
notice, no DPA/consent capture, no DPIA, live subscriptions without CCR/DMCCA
flows, no provider identity, and erasure that left children's data in five stores.

**After this branch:** the product-side blockers are remediated in code and
integrated drafts. The engineering posture (already strong: tenant isolation,
minors-never-auto-publish, deterministic accuracy engine) is now matched by a legal
wrapper that describes reality and is enforced by tests (~75 new tests; full suite
green).

**Remaining between this commit and lawfully selling to UK consumers:** the
operational checklist above — principally (a) filling the identity placeholders,
(b) ICO registration, (c) executing vendor DPAs/transfer mechanisms, (d) Stripe
renewal reminders, and (e) solicitor sign-off of the five drafted documents. None
of these requires further engineering; all are recorded here so a follow-up session
or a human can pick them off the list.

**Standing engineering rules going forward** (also in the DPIA review triggers):
re-run the DPIA before any para-swimming support (special category data), before
weakening the minors' safeguarding gate (don't), before adding any non-essential
cookie (must go through a consent gate), and update `legal.py` + bump the document
version whenever a described flow changes.
