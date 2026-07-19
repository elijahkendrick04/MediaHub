# ADR 0032 — V5 recognition is the canonical ranking authority (P12 / F16)

- **Status:** accepted (2026-07-14). Resolves diagnosed defect **F16** from
  [`PB_RANKER_DIAGNOSIS.md`](../PB_RANKER_DIAGNOSIS.md) (package **P12** in
  [`PB_RANKER_FIX_WORKLIST.md`](../PB_RANKER_FIX_WORKLIST.md)). Pressure-tested
  with the LLM Council (`/llm-council` methodology — five advisors, anonymous
  peer review, chairman verdict) before implementation, per CLAUDE.md's
  deterministic-engine-boundary / high-stakes rule. Verdict: **Option A
  refined**, unanimous (5 advisors + 5 peer reviews + chairman), high
  confidence.
- **Context:** `src/mediahub/pipeline/pipeline_v4.py` runs **two rankers on
  every run**, and their orderings disagree on the single most common
  swim-content question — is a personal best worth more than a gold medal?
  - **V3 `rank_cards`** (`legacy/swim_content/ranker_v3.py`) scores a confirmed
    PB `+12` above a gold `+8`, and produces `run.cards` — the review-queue
    list. It only emits cards when swimmers carry an `asa_id`, which the
    interpreter sets from a Hy-Tek/SDIF `member_id`.
  - **V5 `rank_achievements`** (`legacy/swim_content_v5/ranker.py`) scores
    `medal_gold` (magnitude 1.0) far above `pb_confirmed` (0.5) and bands any
    gold ELITE → MAIN_FEED, while `pb_confirmed` floors at NICE. It produces
    `recognition_report["ranked_achievements"]`.

  So for the same meet, the review queue could put the PB swimmer first while
  the run's own recognition report ranks the gold medallist first and marks the
  PB "nice/recap" — the engine contradicting itself. **Which ordering surfaces
  depended on the parse path:** on member-id HY3/SDIF uploads the V3 detector
  produces cards (contradiction live); on every interpreter path (PDF, CSV,
  free-text, LENEX — the dominant customer input) the V3 detector produces
  nothing, `run.cards` is empty, and the cards are synthesised from the V5
  `ranked_achievements` in V5 order via `_v5_ranked_to_v3_stubs`
  (no contradiction).

  A four-agent code investigation established two decisive facts:
  1. **V5 is already the de-facto authority on every acted-upon surface.** The
     primary review/approve list (`web.py`), the content pack and export
     (`workflow/pack.py`, `content_pack/builder.py`), the reel top-N, and the
     approve/reject keying all read `ranked_achievements` in V5 order. V3's
     `run.cards` order leaks only into a collapsed `<details>` "Legacy content
     cards" table with no rank/priority columns — so the PB-vs-gold flip was a
     **data-level** contradiction, essentially invisible to the operator, but a
     genuine violation of MediaHub's "every step explainable and auditable"
     promise (one swim carrying two audit truths).
  2. **V5 is the modern engine.** `swim_content_v5` is the active detector
     suite; `ranker_v3` is explicitly scheduled for migrate-then-delete
     ([`TECHNICAL_DEBT.md`](../TECHNICAL_DEBT.md) row `swim_content`); `v3_shim`
     frames the V3 path as pilot-era scaffolding.

  This session owns only `pipeline_v4.py` and this ADR. It may **not** edit
  either ranker file (P6 owns the V5 ranker, P7 owns the V3 ranker), so the fix
  had to live entirely in the pipeline glue — no ranker-semantics change.

## Decision

**V5 recognition is the single canonical ranking authority for the review-queue
cards. The pipeline derives `run.cards` from `ranked_achievements` whenever V5
recognition produced them, on every parse path — V5-first, with the legacy V3
`rank_cards` output kept only as a fallback.**

The derived invariant the council named: **single-valued provenance per surfaced
event** — for any real swim, exactly one ranking/bucket/trust verdict, agreed
across every readable surface.

Implementation (all in `pipeline_v4.py`):

1. **`_reconcile_review_cards(v3_cards, ranked_achievements, meet_results)`** —
   a pure, unit-testable helper encoding the authority rule:
   - if V5 produced ranked achievements → cards come from
     `_v5_ranked_to_v3_stubs(ranked, …)` (V5 priority order), source `"v5"`;
   - else if the V3 chain produced cards → keep them, source `"v3-legacy"`;
   - else → `([], "none")`.
   This replaces the old `if not run.cards` gate (which was **V3-first,
   V5-fallback**) with **V5-first, V3-fallback**.

2. **V5-first / V3-fallback, not "always V5".** The V3 detector chain
   (`detect_v3 → grouper → rank_cards`) still runs and still feeds
   `detector_summary` and `self_check` as an independent deterministic
   cross-check; only its *ordering* stops being surfaced. Keeping the rich V3
   cards as the fallback means a V5 recognition failure (the report build does
   online meet-identity research that can throw) or an empty result never
   regresses a run to the old "upload succeeded but produced 0 content cards"
   bug on the member-id path.

3. **Trust is rebuilt from the V5-derived cards, never the rich V3 cards.**
   `run.cards` and `run.trust` must describe the same card set for the
   `card_id`-keyed review-page join, and the rich V3 cards bypass the Children's
   Code identity transform (`apply_to_ranked`, applied to `ranked_achievements`
   only) — feeding them to the trust surface would leak untransformed under-18
   identity. The medium/review flattening of the collapsed legacy table is
   accepted as honest; the acted-upon safety signal is the V5 achievement's own
   `safe_to_post`, not this trust table.

4. **A `run.cards_order_source` provenance marker** (`"v5"` / `"v3-legacy"` /
   `"none"`) records which authority produced the surfaced cards — auditability
   (the rejected Option D's one real merit) folded into the accepted option, and
   a guard against a future re-introduction of a competing ordering.

5. **`self_check` is deliberately left computed from the V3 local cards** (not
   recomputed against the V5-derived `run.cards`): recomputing over claim-less
   stubs flips self-check codes on the dominant interpreter path and would break
   byte-identity. Recorded as a deferred follow-up below.

The change is **byte-identical on every interpreter (customer-dominant) path** —
`run.cards`, `run.trust` and `run.self_check` were already V5-derived / empty
there. The only behavioural change is on the fixtureless member-id/HY3 path,
where the review queue now agrees with the recognition report.

## Consequences

- The two ranking paths no longer contradict on PB-vs-gold: one authority (V5),
  one surfaced order, on every parse path.
- **F16 severs the last surfacing/persisted consumer of `rank_cards`'
  ordering.** After this change `run.cards` carries V5 order everywhere, which
  is the precondition for the already-scheduled retirement of `ranker_v3`
  (`TECHNICAL_DEBT.md`). The V3 **detector** stays.
- **Honest cost (recorded, not hidden):** on the highest-fidelity input MediaHub
  can receive — official member-id HY3/SDIF — the member-id path now surfaces
  claim-less V5 stubs (trust defaulting to medium/review) instead of the
  claim-bearing, evidence-grounded V3 cards. Accepted because no acted-upon
  surface reads that richness today and there is no customer signal the path is
  live; if that richness is ever wanted, its correct home is V5 (enrich
  `ranked_achievements`), not a pipeline join or a revived V3.
- Deterministic-engine boundary respected: no ranker file edited, no ranker
  logic duplicated, no LLM introduced. The reconciliation is pure selection +
  provenance.

### Deferred follow-ups (filed, not blocking F16)

1. **`self_check` set-fork.** Recompute `run.self_check` against the V5-derived
   `run.cards` so cards/trust/self-check describe one set. Deferred because it
   changes self-check output on the dominant path and needs its own review.
2. **Stub-claims enrichment.** Populate the V5 stubs' `claims` from each
   achievement's own grounding (the PB/medal/magnitude facts already on the
   `RankedAchievement`) so trust is honest without a fork. Deferred because it
   would change dominant-path trust output.

### Cross-session hand-offs

- **To P7 (`ranker_v3.py` owner):** F16 removes the last surfacing/persisted
  consumer of `rank_cards`' ordering — `run.cards` is V5-ordered on every path
  now. This unblocks the scheduled migrate-then-delete of `ranker_v3`. **No
  ranker-file edit was needed for F16.** When deleting the ranker, keep the V3
  **detector** (`detect_v3`) — it still feeds `detector_summary` and
  `self_check` as an independent deterministic cross-check; do not delete the
  detector by accident.
- **To P6 (`swim_content_v5/ranker.py` owner) — live coupling:** F16 hardens
  `pipeline_v4`'s dependence on the `ranked_achievements` contract (a list of
  dicts: `achievement.{swim_id, headline, event, type, swimmer_name}` plus
  `voice_captions` and `rank`) exactly while P6 edits the V5 ranker in parallel.
  Coordinate merge order; do not change that shape without a heads-up to the
  pipeline session.
- **To P6 — deferred editorial question (the dissent, below):** whether every
  confirmed PB should rank below every minor gold for age-group club content is
  a V5-ranker decision, not a pipeline one.

## Dissent (recorded verbatim per the chairman)

> The ADR must honestly record that F16 enshrines V5's gold-over-PB ordering as
> canonical purely on authority-of-incumbency ("it is the modern engine; it is
> already on every acted-upon surface"), without anyone adjudicating whether
> demoting every confirmed personal best below every gold — including a gold in
> a two-swimmer heat — is editorially correct for age-group swim-club content,
> where a PB is often the emotional headline. This sits squarely on CLAUDE.md's
> deterministic-engine principle that "which card outranks which" is
> accuracy-critical. If V5's ordering is editorially wrong, F16 entrenches the
> wrong ranking on every surface and forecloses the debate — so the ADR flags it
> as a deferred content-quality question owned by P6, not a settled one.
> Secondary surviving objection: on the highest-fidelity input MediaHub can
> receive (official member-id HY3/SDIF), Option A replaces claim-bearing,
> evidence-grounded V3 cards with claim-less stubs whose trust defaults to
> medium/review — a genuine (if operator-buried and fixtureless) fidelity loss
> on precisely the upload that most deserves confidence. It is accepted only
> because no acted-upon surface reads that richness today and there is no
> customer signal the path is live.

## Alternatives considered

- **Option B — reorder rich V3 cards into V5 order via a swimmer+event join.**
  Rejected as structurally unbuildable inside `pipeline_v4.py` alone: the V3
  grouper emits aggregate card types (`spotlight`, `pb_roundup::all`,
  `podium_roundup::all`, `weekend_in_numbers`) with no per-achievement V5
  counterpart, V3 keys on `asa_id` while V5 keys on canonical name, and one swim
  can yield PB+gold as two V5 rows — a many-to-one, cross-namespace join that is
  neither total nor stable (non-deterministic). It also entrenches the ranker
  slated for deletion, and the card-identity semantics live in the grouper
  (another session).
- **Option C — Option B plus overwriting each V3 card's bucket/priority from its
  matched V5 achievement.** Rejected: same infeasible join, and it duplicates
  V5's band→bucket logic inside `pipeline_v4.py` — the closest option to the
  deterministic-engine boundary and a real cross-session coupling.
- **Option D — document V5 as canonical + a provenance marker, but do NOT
  reorder `run.cards`.** Rejected as masking rather than fixing: the data-level
  contradiction persists on the member-id path and relies on the view layer
  never promoting V3 order. Its one merit — the provenance marker — was folded
  into the accepted option.
- **Naive Option A — "stop assigning `run.cards` at the V3 site; always build
  V5 stubs".** Rejected: it deletes the existence-fallback and re-opens the
  "0 content cards" bug whenever V5 recognition throws or returns nothing. The
  accepted version is V5-first / V3-**fallback**.
- **Feed the trust report from the rich V3 cards to preserve claim grounding**
  (an initially popular refinement). Rejected as verified broken (disjoint
  `card_id` namespaces orphan the rich rows, which fall back to medium/review
  anyway) and a safeguarding regression (untransformed under-18 identity).
- **Editing a ranker to reconcile the two scoring rubrics.** Out of scope —
  another session's file and a deterministic-engine change; captured as the P6
  editorial hand-off instead.
