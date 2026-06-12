# Compliance Summary — gap → capability → evidence

> Phase 4 deliverable: every Critical/High gap from
> [`GAP_ANALYSIS.md`](GAP_ANALYSIS.md), the capability that closed it, and
> the evidence a regulator or club would ask for. Open legal-judgment items
> remain in [`OPEN_LEGAL_QUESTIONS.md`](OPEN_LEGAL_QUESTIONS.md) (Q1–Q12 —
> none silently decided). All legal-shaped documents are **DRAFT — FOR
> LEGAL REVIEW**.

## Criticals — all closed in code/docs (legal sign-off pending where noted)

| Gap (severity) | Closed by | Evidence |
|---|---|---|
| Art 5(1)(a)+6+21 — no lawful basis records, no consent/opt-out, objections unenforceable (**Critical**) | `compliance/lawful-basis-and-consent` | Per-tenant basis config + append-only consent registry (`mediahub/compliance/consent.py`); ONE gate function enforced at **approval (403), pack build (filtered), publish route (403), autonomous publish gate (check)** — `tests/test_consent_gating.py` (14), `test_llm_pipeline_security.py` consent-revocation test. Which basis a club should pick: **Q2 (open, by design)** |
| Art 8 — no parental-consent modelling (**Critical**) | same | Opt-in mode requires parental grants for under-18/unknown-age athletes — tested |
| Art 5(1)(e) — indefinite retention (**Critical**) | `compliance/retention-and-minimisation` | Per-class windows + tenant tightening + daily exactly-once purge job; accountability ledgers exempt — `tests/test_retention_minimisation.py` (13). Default values: **Q8** |
| Art 14 — enrichment invisible to athletes/parents (**Critical**) | `compliance/transparency-artifacts` + per-tenant enrichment opt-out | Child-readable Art 14 notice template naming swimmingresults.org; `pb_enrichment_enabled` wired into the pipeline with an honest skip message. Lawfulness of the scraping itself: **Q4** |
| Art 17 — no athlete-level erasure; memory.db/PB-cache/users blind spots (**Critical**) | `compliance/data-subject-rights` | `erase_athlete` walks every DATA_MAP store (runs, visuals, workflow, packs, caches incl. raw HTML, media, caption memory, profile text), writes a suppression record, reports residuals honestly; `erase_user_account` for the users ledger — `tests/test_dsr_rights.py` (11) incl. the **definition-of-done propagation test** and erased-athlete-excluded-from-new-packs |
| Art 28 — no DPA (**Critical**) | `compliance/transparency-artifacts` | Art 28(3)-complete DPA template (UK IDTA/Addendum + EU SCC modules) — `tests/test_transparency_artifacts.py` pins the 28(3) elements + DRAFT marker |
| Art 32 — security gaps (**Critical**) | Phase 3 S1–S8 | [`../security/SECURITY_REPORT.md`](../security/SECURITY_REPORT.md): ASVS L2 mapping, scans (pip-audit/bandit/semgrep/gitleaks/ZAP), residual register |
| DUAA s 164A — complaints duty, statutory 19 June 2026 (**Critical**) | `compliance/complaints-and-breach` | Public electronic form (`/complaints`), 30-day acknowledgement workflow with overdue detection, operator desk — `tests/test_compliance_complaints.py` (10). **Live ahead of the deadline** |

## Highs — closed

| Gap | Closed by | Evidence |
|---|---|---|
| Art 5(1)(b) — cross-tenant PB caches | Partially: per-run cache tenant-scoped, warm cache retention-bounded (30d) + reached by erasure; full scoping roadmapped | DATA_MAP S7; residual R7 in SECURITY_REPORT |
| Art 5(1)(c) — over-broad LLM/image payloads | `compliance/retention-and-minimisation` | IDs/DOB stripped at the prompt boundary; notify carries no athlete data — tested |
| Arts 12/13 — no notices | `compliance/transparency-artifacts` | Art 13 club-user notice + Art 14 athlete/parent notice templates (DRAFT) |
| Art 15 — no SAR | `compliance/data-subject-rights` | `export_athlete` machine-readable export across all stores; Art 12A clock metadata (stop/resume extends due date) — tested |
| Art 18 — no restriction | same | Registry `restricted` flag blocks in **every** mode — tested |
| Arts 22/22A–D — approval gate UI-only | `security/llm-pipeline` | Publish route now enforces approval/consent/tenant **server-side**; ADM analysis recorded (**Q9**) |
| Art 25 + DUAA children's duty | `compliance/childrens-code` | Surname-initialisation / age-suppression / photo-exclusion controls; high-privacy defaults for new orgs; [`CHILDRENS_CODE.md`](CHILDRENS_CODE.md) maps all 15 standards — `tests/test_childrens_code_controls.py` (13) |
| Art 30 — no ROPA | Phase 1 | [`ROPA.md`](ROPA.md) (operator identity to complete) |
| Arts 33–34 — no breach process | `compliance/complaints-and-breach` | [`BREACH_PLAYBOOK.md`](BREACH_PLAYBOOK.md) + incident register with 72h-clock evidence — tested |
| Art 35 — no DPIA | `compliance/dpia` | [`DPIA.md`](DPIA.md) on the ICO structure — **requires human sign-off (Q11)** |
| Children's Code standards 1/4/5/7/8/9/12/15 | C4+C5+C1+C2 | CHILDRENS_CODE.md table, per-standard |
| Real children's data in committed fixtures | **Flagged, not deleted** | DATA_MAP §6 / GAP_ANALYSIS: public competition documents used as parser fixtures; ~10 test files depend on them. **Operator decision required** (replace with synthetic fixtures over time; keep repo private meanwhile) |
| users.jsonl undeletable; memory.db survives run delete | `compliance/data-subject-rights` | `erase_user_account`; erasure reaches memory.db — tested |

## Mediums (status)

PECR cookie audit → [`COOKIE_AUDIT.md`](COOKIE_AUDIT.md) (clean: one
strictly-necessary cookie; **no banner required**; DUAA analytics-exemption
conditions recorded). Art 16 rectification → shipped. Art 19 → erasure
reports recipients honestly. Transfer TRAs under the "not materially
lower" test → per-provider mechanisms recorded in
[`SUBPROCESSORS.md`](SUBPROCESSORS.md); formal TRAs queued with **Q7**.
`DATA_DIR` unset in production → fail-fast boot validation.

## Verification

- **Full pytest suite green** (~4,150 passed incl. ~120 new
  compliance/security tests; exact count in CHANGELOG).
- Definition-of-done checks: opted-out athlete provably absent from new
  packs (`test_erasure_then_new_pack_excludes_athlete`,
  `test_pack_filter_removes_blocked_athletes`); erasure provably reaches
  every mapped store (`test_erasure_propagates_to_every_store`);
  cross-tenant isolation suites green; CI security gates active;
  threat model + residual register exist.

## What still needs a human

1. **Solicitor review** of Q1–Q12 and every DRAFT-marked document.
2. **DPIA sign-off** by a named operator reviewer (Q11).
3. **Operator identity fields** in ROPA/notices/DPA templates.
4. **Sample-fixture decision** (real children's data in `samples/`).
5. **Legacy-tenant child-policy defaults** (new orgs are high-privacy by
   default; existing profiles need a deliberate migration).
