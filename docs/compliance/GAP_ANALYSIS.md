# Gap Analysis — current state vs the legal framework

> Phase 1 deliverable. Current state evidenced by [`DATA_MAP.md`](DATA_MAP.md);
> target state per [`LEGAL_FRAMEWORK.md`](LEGAL_FRAMEWORK.md). Each gap is
> rated **Critical / High / Medium / Low** and names the capability that
> closes it. Severity = (regulatory exposure × likelihood × data-subject
> harm), with children's data weighting harm up.
>
> Closing capabilities (Phase 2 unless marked P3):
> C1 `compliance/lawful-basis-and-consent` · C2 `compliance/data-subject-rights` ·
> C3 `compliance/retention-and-minimisation` · C4 `compliance/transparency-artifacts` ·
> C5 `compliance/childrens-code` · C6 `compliance/complaints-and-breach` ·
> C7 `compliance/dpia` · S* `security/*` (Phase 3)

## UK GDPR, article by article

| Ref | Requirement | Current state | Gap | Severity | Closes |
|---|---|---|---|---|---|
| **Art 5(1)(a)** lawfulness, fairness, transparency | No lawful-basis records; no privacy notices anywhere; athletes/parents have no way to know MediaHub processes them | No documented basis for any processing; enrichment (E4) is invisible to data subjects | **Critical** | C1, C4 |
| **Art 5(1)(b)** purpose limitation | Purposes implicit in product flow; PB warm cache (S7) and search cache (S8) shared across tenants — data collected for club A's content reused beyond that purpose | Cross-tenant reuse undermines purpose limitation and the processor allocation | **High** | C1 (tenant-scope the caches), C3 |
| **Art 5(1)(c)** minimisation | LLM payloads carry full name, age, ASA ID, club (F1); image APIs get full photos (F3/F4); ntfy/webhooks unpoliced (F7) | More personal data leaves the platform than captioning needs | **High** | C3 |
| **Art 5(1)(d)** accuracy | Strong: deterministic parsers, confidence scores, ambiguity flagged, PB trust ledger | Rectification tooling missing (athlete-level) | Medium | C2 |
| **Art 5(1)(e)** storage limitation | **Indefinite retention everywhere** — no purge job exists (DATA_MAP §2); planned 90-day GC never shipped | No retention schedule at all | **Critical** | C3 |
| **Art 5(1)(f)** integrity & confidentiality | See security rows below | — | — | S* |
| **Art 5(2)** accountability | Autonomy audit ledger exists (S13) but no ROPA, no DPIA, no policies | Now partially closed by Phase 1 docs; remaining evidence lands with each capability | **High** | All |
| **Art 6** lawful basis | No per-tenant lawful-basis configuration; clubs cannot record what they rely on | Controllers (clubs) cannot demonstrate a basis; publication of children's content has no recorded consent | **Critical** | C1 |
| **Art 8** child consent (ISS) | n/a today (no child-facing service), but consent registry must model parental consent for under-18s regardless of basis chosen | No consent registry exists at all | **Critical** | C1 |
| **Arts 12–13** transparency (data from subject) | Nothing | No club-facing Art 13 template, no notice generator | **High** | C4 |
| **Art 14** (data NOT from subject — the swimmingresults.org enrichment) | Nothing; athletes/parents are never told their ranking history is being fetched and turned into content | **Mandatory notice missing for an active processing flow** | **Critical** | C4 (template) + C1 (per-tenant enrichment opt-in) |
| **Art 15** access (SAR) | No per-athlete export; data scattered over S1–S13 | SAR cannot be answered within Art 12A time limits without manual archaeology | **High** | C2 |
| **Art 16** rectification | Per-run re-edit only | No athlete-level rectification | Medium | C2 |
| **Art 17** erasure | Run-level delete + global cache clear + per-asset delete only | **No athlete-level erasure**; blind spots: memory.db (S12), per-run PB cache (S6), search cache HTML (S8), users ledger (S11), club-profile rosters (S10) — see DATA_MAP §7 | **Critical** | C2 |
| **Art 18** restriction | Nothing | No restriction flag; restricted athletes keep flowing into new packs | **High** | C2 |
| **Art 19** notification of rectification/erasure to recipients | Nothing | Erasure must record/propagate to recipients where feasible; content the club already exported and posted manually is honestly out of reach | Medium | C2 |
| **Art 20** portability | Nothing | SAR export in machine-readable JSON largely satisfies; applies only to consent/contract-based processing | Low | C2 |
| **Art 21** objection | Nothing | Opt-out registry needed (objection ≈ opt-out in this product) | **Critical** (same mechanism as consent gating) | C1 |
| **Arts 22 / 22A–22D** automated decisions | Human approval before any content is used; MediaHub does not publish to social — approved content is only exported for a human to post | Approval gate is UI-level; must be unbypassable in code; ADM analysis recorded (Q9) | **High** | S8 (`security/llm-pipeline`) + C7 |
| **Art 25** DP by design/default (+ children's higher protection matters, DUAA s 81) | `permission_status`/`safe_for_minors` fields exist (S9); MediaHub does not publish to social, so minors' content is only ever exported for a human to post | No child-policy controls (surname initialisation, age suppression, photo exclusion); defaults not privacy-high | **High** | C5 |
| **Art 28** processor contract | No DPA template; sub-processors engaged without flow-down terms visible to clubs | Clubs are processing without Art 28 terms | **Critical** | C4 |
| **Art 30** ROPA | None before this phase | Closed by [`ROPA.md`](ROPA.md) (DRAFT; needs operator identity + sign-off) | **High** → addressed | Phase 1 |
| **Art 32** security | Partial: bcrypt, signed cookies, tenant scoping on key routes, zip-bomb limits, audit ledger | No CSRF tokens, no login rate limiting, no idle timeout, no security headers/CSP, no MIME validation, no structured security log, no at-rest encryption, account deletion impossible | **Critical** | S1–S8 (Phase 3) |
| **Arts 33–34** breach notification | Nothing | No breach playbook, no incident log, no 72-hour workflow | **High** | C6 |
| **Art 35** DPIA | None | Children + AI + social publication ⇒ DPIA effectively mandatory | **High** | C7 |

## PECR

| Ref | Current state | Gap | Severity | Closes |
|---|---|---|---|---|
| Reg 6 (storage/access) | Only the signed Flask session cookie observed (strictly-necessary exemption); no analytics | Formal cookie audit + disclosure needed; consent mechanism only if non-exempt cookies appear; DUAA analytics exemption (notice + opt-out) documented for future use | Medium | C4 |
| Reg 22 (marketing) | No marketing emails sent by the platform | Document position; revisit if marketing added | Low | C4 |

## ICO Children's Code (treating standards as applicable — Q3)

| Standard | Current state | Gap | Severity | Closes |
|---|---|---|---|---|
| 1 Best interests · 5 Detrimental use | Human approval + export-only (no social publishing) only | No best-interests assessment; approval/export decisions lack child-specific controls | **High** | C5, C7 |
| 2 DPIA | None | See Art 35 | **High** | C7 |
| 4 Transparency | None | Athlete/parent-facing notice (Art 14) must be child-readable | **High** | C4 |
| 7 Default settings · 8 Minimisation | Defaults render full name + age + photo onto approved/exported content | Per-tenant under-18 rules needed: surname initialisation, age suppression, photo exclusion — **privacy-high by default** | **High** | C5 |
| 9 Data sharing | LLM/image/social flows un-minimised | See Art 5(1)(c) | **High** | C3, C5 |
| 12 Profiling | PB enrichment builds longitudinal performance profiles of children | Opt-in + transparency + purpose limits | **High** | C1, C4 |
| 15 Online tools | No way for an athlete/parent to exercise rights | Rights intake + complaints form | **High** | C2, C6 |

## DUAA additions

| Provision | Deadline | Current state | Severity | Closes |
|---|---|---|---|---|
| s 164A DPA 2018 complaints duty | **19 June 2026** (one week) | Nothing | **Critical** (date-driven) | C6 |
| Art 12A time-calculation | In force | No SAR workflow at all, so no clock metadata | **High** | C2 |
| Children's higher protection matters (Art 25(1)) | In force | As Art 25 row | **High** | C5 |
| PECR fines at UK GDPR level | In force | Raises stakes of the cookie audit only | Medium | C4 |
| "Not materially lower" transfer test | In force | Sub-processor TRAs not documented | Medium | C4 (+ SUBPROCESSORS annual review) |

## Repository-specific findings

| Finding | Severity | Disposition |
|---|---|---|
| **Real children's data in committed fixtures**: `samples/MISM-2024-Results.pdf` + `samples/learning_corpus/level1/*` (real named children, ages, clubs, times from published meets; ~10 test files depend on the MISM PDF) | **High** | Publicly published source documents, held in a private repo for parser testing — defensible but must be: documented as a deliberate decision with justification (testing necessity, public source), kept out of any public repo, and progressively replaced with synthetic fixtures. **Operator decision required before any deletion** (tests depend on them). |
| Git history secrets | — | Clean (gitleaks full-history scan; 9 false positives on a synthetic test value). |
| `DATA_DIR` defaults to `src/mediahub/` when unset (`web.py:808`) | Medium | Runtime personal data can land inside the package tree in dev; fail-fast env validation (S4, Phase 3) should require explicit `DATA_DIR` in production. |
| Cross-tenant PB caches (S7/S8) | **High** | Tenant-scope as part of C1/C3 (also preserves the processor allocation, Q4). |
| `users.jsonl` append-only with no account deletion | **High** | C2 adds account erasure (tombstone + rewrite). |
| `memory.db` captions survive run deletion | **High** | C2 wires memory purge into erasure + run delete. |

## Execution order (by severity, with the statutory date first)

1. **C6** complaints intake — s 164A is live **19 June 2026**.
2. **C1** lawful basis + consent/opt-out registry + hard publish gating — the
   single most important feature; closes Art 6/8/21 Criticals.
3. **C2** data subject rights (SAR export, rectify, erase-everywhere,
   restriction) — closes Art 15/17/18 + erasure blind spots.
4. **C3** retention + minimisation — closes Art 5(1)(c)/(e) Criticals.
5. **C4** transparency artifacts (Art 13/14 notices, Art 28 DPA template,
   sub-processor page, cookie audit) — closes Art 14/28 Criticals.
6. **C5** children's code controls; **C7** DPIA.
7. Phase 3 security capabilities close Art 32.
