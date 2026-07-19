# 32. V3 content-ranker deterministic-engine bug-fixes (package P7)

- **Status:** Accepted. Scoped bug-fixes to the V3 content ranker
  (`legacy/swim_content/ranker_v3.py`) plus removal of the dead V1 ranker stack.
  Pressure-tested by the LLM Council per the deterministic-engine governance rule
  (changes that alter scoring/bucketing cross the engine boundary), because these
  edits touch a CLAUDE.md-designated deterministic crown-jewel ("which card
  outranks which?").
- **Date:** 2026-07-14
- **Deciders:** MediaHub maintainer (PB-ranker fix backlog, package **P7**:
  F06, F35, F55, F36, F37, F60, F53, F33, F58), grounded in
  [`../PB_RANKER_DIAGNOSIS.md`](../PB_RANKER_DIAGNOSIS.md) /
  [`../PB_RANKER_FIX_WORKLIST.md`](../PB_RANKER_FIX_WORKLIST.md), and the
  in-session `/llm-council` verdict (5 advisors → anonymised peer review →
  chairman).
- **Scope guardrails honoured:** LLM-free and deterministic throughout; each fix
  targets only its named defect; every *other* ranking input is preserved
  byte-for-byte (proven by a golden multi-card diff snapshotted **before** the
  first edit — see *Verification*). No existing test was weakened.

## Context

The diagnosis found nine latent defects in the V3 ranker path. Four change
scoring/bucketing (F06, F35, F55, F60) and so cross the deterministic-engine
boundary; the rest are docstring/dead-code/coverage (F36, F37, F33, F53, F58).
The scoring changes re-rank existing content and rewrite user-visible
`score_reasons`, and they **compose** through the 20-card queue cap — so they are
not independent local patches and were treated as one reviewable change.

## Decision (council verdict, adopted)

1. **F06 — out-of-window qualifier soft-weighting.** Read `Claim.extra['in_window']`
   (which `detector_v3` writes expressly for this). In-window national/international
   → +10, in-window university → +6; any out-of-window hit (or an "open"-level hit)
   → +4. **A missing flag defaults to in-window (True)** — absence of a negative
   signal is not evidence of expiry; defaulting False would silently re-score every
   pre-flag persisted run (a mass regression) and contradict "preserve every other
   input". The flag is coerced to a real bool so a persisted `"false"`/`0` string is
   read as out-of-window (serialization-stable). The "outside its window" reason is
   stamped **only** when a hit is *explicitly* out of window — never for a missing
   flag, which would fabricate an expiry the evidence never asserted.
2. **F35 — deterministic queue-cap.** The whole queue is ranked by the same
   `(-score, card_id)` total order the final sort uses, **then sliced** at the cap.
   This makes the keep/demote *partition* (not merely the demoted cards' order)
   deterministic, so which card is demoted at a tie no longer depends on input order.
   *(Determinism assumes `card_id` is a total order — it already backs the final sort.)*
3. **F55 — cap-demoted format.** A cap-demoted card recomputes `_suggested_format`
   for its new recap bucket instead of hardcoding `FMT_RECAP`, so a demoted spotlight
   keeps `athlete_spotlight`.
4. **F60 — sweep vocabulary + breadth key.** (a) The same-stroke gold bonus reason
   matches the grouper's vocabulary — 2 golds = "doubles up", 3+ = "clean sweep" (the
   +5 is unchanged; only the label differs, so it stops contradicting the headline).
   (b) The `>=3 notable` bonus keys on **distinct events** `(distance, stroke, course)`
   rather than per-round swims, so a prelim + final of one event is one event's
   breadth. This is the honest definition of breadth; a withheld +5 never un-spotlights
   a card (spotlights are base 70 ≥ 65, still queued). See the intentional
   ranker↔grouper divergence in *Cross-session hand-offs*.
5. **F37 / F33 — anti-spam demotion kept as a documented defensive safety-net.**
   The rule is dead in the live pipeline (the grouper emits spotlight XOR standouts),
   but **Remove** would require deleting a passing test *and* editing the grouper
   (another session's file) — both forbidden here — and **Wire-live** is a product
   change that adds cards. So the rule stays, its docstring is corrected to the truth
   ("demoted standouts land in recap **or archive** depending on residual score"), and
   a comment names it a deliberate safety-net so a future dead-code sweep keeps it.
6. **F36 — remove the phantom `-8` penalty from the docstring.** The
   "-8 open/host without finals/qualifier" modifier was never implemented and cannot
   be, here: `ContentCard` carries no meet-importance field, and adding one needs the
   detector/grouper (files this session cannot edit). The docstring is corrected to
   match the code. **Deferred, not deleted:** re-introducing the penalty requires a
   `meet_importance` input on the card and a follow-up ADR.
7. **F53 — coverage.** Added regression tests for the previously-unasserted spotlight
   multi-event bonus, the sweep/doubles-up bonus, the FMT_STORY assignment, and the
   `needs_confirmation` base score, plus a composite multi-card pipeline test and a
   repeated-run determinism check.
8. **F58 — remove the dead V1 ranker stack.** `legacy/swim_content/ranker.py` (V1
   `rank()`, a third, inconsistent queue threshold of 70 vs V3's 65) was reachable
   only via `pipeline.py` → `app_v2.py` → `run_with_demo.py.disabled` (a standalone
   legacy dev app with zero `src/`, test, or deploy references — grep-verified). On
   the maintainer's explicit instruction (which overrides the general
   "never delete `legacy/`" hygiene default for this cleanup), the full dead cluster
   — `ranker.py`, `pipeline.py`, `app_v2.py` — was removed so no dangling import
   remains. `run_with_demo.py.disabled` is inert and left untouched.

## Verification

- **Golden diff.** A diverse multi-card set (qualifier-window matrix, medal/PB
  hierarchy, spotlight bonuses, all card types, anti-spam, cap tie-breaks) was ranked
  and dumped (score, bucket, suggested_format, reasons) *before* any edit, then again
  *after*. The diff contains **only** the intended deltas — the F06 out-of-window
  re-scores, the F60 label/breadth changes, the F35 partition, the F55 format — and
  every other card is byte-identical. No card crossed the 65/40 thresholds or the cap
  boundary unintentionally.
- Existing `tests/test_ranker_v3_direct.py` (12) unchanged and green; new
  `tests/test_ranker_v3_pbfix.py` (17) green.

## Cross-session hand-offs

- **Grouper (package P8, `grouper.py`, finding F28).** F60(b) intentionally diverges
  the two "breadth" definitions: the grouper spawns a spotlight on **≥3 notable races**
  (rounds counted); the ranker awards the **+5 breadth bonus** only on **≥3 distinct
  events**. This is deliberate (a withheld bonus, not a withheld card) — do **not**
  "reconcile" it by re-adding round to the ranker key. P8 should also update the
  grouper's own docstring line "the standalone cards are demoted to RECAP" to match
  the corrected recap-or-archive reality (F37).
- **Captions (`captions_v3.py`, out of P7 scope).** It generates its own
  "clean sweep"/"notable swims" caption text from card data (not from `score_reasons`),
  so the reason-string changes here do not affect it — but it may warrant its own
  vocabulary/round-dedup review for the same reasons as F60.
- **Docs inventory (`docs/INVENTORY.md`, `docs/CHANGELOG.md`).** They list the now
  deleted `app_v2.py`/`pipeline.py`/`ranker.py` as "preserved verbatim"; those lines
  are now stale and should be trimmed by the docs owner.
