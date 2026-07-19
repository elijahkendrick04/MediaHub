# PB Ranker — Fix Worklist & Parallel-Session Dispatch Plan

Companion to [`PB_RANKER_DIAGNOSIS.md`](PB_RANKER_DIAGNOSIS.md). That document is *what is wrong* (62 verified flaws);
this one is *how the fixes are sliced for parallel work*.

The 62 issues are grouped into **14 file-owned packages**. The slicing rule is strict: **each source file is owned by
exactly one package**, so the packages can be worked in fully parallel sessions with no merge conflicts and no session
overwriting another's fix. Where a correct fix implies a change to a file another package owns, that is called out as a
**cross-session hand-off** rather than edited directly.

> **Deterministic-engine note.** Packages marked *engine* touch parsers / detectors / rankers, which `CLAUDE.md` keeps
> deliberately deterministic. These are **bug fixes, not Gemini-ification** — allowed, but they must preserve engine
> accuracy except for the specific defect, keep the code LLM-free, and follow the 15-step breakage + 15-step verification
> checklists for any route/data-structure change. Packages marked *high-stakes* change ranking/architecture semantics and
> should be pressure-tested (`/llm-council`) with an ADR before merging.

## Package overview

| Pkg | Area | Owns (files) | Issues | Flags |
| --- | --- | --- | --- | --- |
| P1 | Discovery baseline parser | `src/mediahub/pb_discovery/parse_pbs.py` | F01, F09, F20 | engine |
| P2 | PB bridge time-format handling | `src/mediahub/pipeline/pb_bridge.py` | F50 | engine |
| P3 | PB baseline cache freshness | `src/mediahub/pb_discovery/cache.py` | F25 | engine |
| P4 | PB detectors — same-meet & zero-time | `legacy/swim_content_v5/achievements/pb.py` | F02, F56 | engine |
| P5 | Official-PB detector fireability | `src/mediahub/recognition_swim/achievements/official_pb.py` | F18 | engine |
| P6 | V5 ranker — tables, maths, crash, contract | `legacy/swim_content_v5/ranker.py` | F13, F03, F07, F08, F19, F12, F05, F14, F15, F21, F24, F27, F34, F49, F54, F04, F62, F22, F23, F52, F59 | engine, high-stakes |
| P7 | V3 ranker + dead V1 ranker | `legacy/swim_content/ranker_v3.py` · `legacy/swim_content/ranker.py` | F06, F35, F55, F36, F37, F60, F53, F33, F58 | engine, high-stakes |
| P8 | Grouper — anti-spam & stroke lookup | `legacy/swim_content/grouper.py` | F28, F61 | engine |
| P9 | Report assembly — double registration & ghost type | `legacy/swim_content_v5/report.py` | F10, F57 | — |
| P10 | Recommender — dead output & unreachable paths | `legacy/swim_content_v5/recommender.py` | F29, F26, F32 | — |
| P11 | Web workflow-state keying & safety default | `src/mediahub/web/web.py` | F11, F51 | high-stakes |
| P12 | Pipeline dual-ranker reconciliation (architectural) | `src/mediahub/pipeline/pipeline_v4.py` | F16 | engine, high-stakes, architectural |
| P13 | Governance engine-boundary guard | `autotest/gitops.py` | F17 | — |
| P14 | Docs alignment + empty stub modules | `docs/RANKING.md` · `docs/DETECTOR_BUS.md` · `docs/SYSTEM_MAP.md` · `src/mediahub/recognition/ranker.py` · `src/mediahub/recognition/recommender.py` · `src/mediahub/recognition/report.py` | F38, F39, F40, F42, F43, F48, F41, F31, F44, F45, F46, F47, F30 | — |

---

## P1 · Discovery baseline parser

**Owns:** `src/mediahub/pb_discovery/parse_pbs.py`
  ·  **Flags:** engine  ·  **Suggested branch:** `claude/pbfix-discovery-parser`

| Issue | Sev | Location | Fix intent |
| --- | --- | --- | --- |
| **F01** | 🔴 | `src/mediahub/pb_discovery/parse_pbs.py`:139 | Reject relay rows (`N x DIST` / 'relay') before building an event baseline; the same guard must cover the interpreter path, not just the heuristic fallback, since both mis-parse relay legs into individual-event PB baselines. |
| **F09** | 🟠 | `src/mediahub/pb_discovery/parse_pbs.py`:95 | Detect course per-row, not per-page; stop flattening mixed LC/SC profile pages into one course, and stop defaulting unknown pages to LC (mark course unknown and let the bridge keep LC/SC keys separate). |
| **F20** | 🟠 | `src/mediahub/pb_discovery/parse_pbs.py`:145 | Disambiguate dotted dates from swim times: `12.03.2024` must not become a 12.03s baseline. Require a plausible time shape / reject 3-part dotted date tokens before treating a match as a time. |

**Acceptance:** A relay-listing page and a date-bearing page produce zero individual-event PB baselines from those rows; a mixed LC/SC page keeps both courses distinct; existing parse tests still pass and add regression tests for each case.

## P2 · PB bridge time-format handling

**Owns:** `src/mediahub/pipeline/pb_bridge.py`
  ·  **Flags:** engine  ·  **Suggested branch:** `claude/pbfix-pb-bridge`

| Issue | Sev | Location | Fix intent |
| --- | --- | --- | --- |
| **F50** | 🟡 | `src/mediahub/pipeline/pb_bridge.py`:42 | Stop silently dropping valid PB rows: accept the `HH:MM:SS.ss` and 3-digit-fraction times that `parse_pbs` actually emits, and stop treating `:` as a decimal separator. Round-trip every format parse_pbs can produce. |

**Acceptance:** Every time string parse_pbs can emit round-trips through the bridge to a correct centisecond value; add a table-driven test over all supported formats.

## P3 · PB baseline cache freshness

**Owns:** `src/mediahub/pb_discovery/cache.py`
  ·  **Flags:** engine  ·  **Suggested branch:** `claude/pbfix-pb-cache`

| Issue | Sev | Location | Fix intent |
| --- | --- | --- | --- |
| **F25** | 🟡 | `src/mediahub/pb_discovery/cache.py`:90 | Compare the cached baseline's age against the meet date, not just wall-clock TTL, so a warm (≤7-day) cached baseline can't mark a slower swim as a 'new PB' when the meet predates or straddles the cache entry. |

**Acceptance:** A cached baseline older/newer than the meet no longer yields a false PB; add a test fixing 'now', the cache timestamp, and the meet date (note: the code must take these as inputs — do not call Date.now() implicitly in a way tests can't pin).

## P4 · PB detectors — same-meet & zero-time

**Owns:** `legacy/swim_content_v5/achievements/pb.py`
  ·  **Flags:** engine  ·  **Suggested branch:** `claude/pbfix-pb-detectors`

| Issue | Sev | Location | Fix intent |
| --- | --- | --- | --- |
| **F02** | 🔴 | `legacy/swim_content_v5/achievements/pb.py`:71 | Fold earlier same-meet swims into the baseline (use the accepted-but-unused `all_results`) so a final slower than the swimmer's own heat is NOT announced as a new PB, and the prior-time shown is the fastest same-meet swim. Apply the same fix to PBImprovementMagnitudeDetector. |
| **F56** | ⚪ | `legacy/swim_content_v5/achievements/pb.py`:67 | Treat `finals_time_cs == 0` (and other non-positive times) as 'no swim', never a valid PB of 0.00. |

**Acceptance:** Heats-then-slower-final produces exactly one PB card (the heat); a zero/None time produces no PB card; add tests for both.

## P5 · Official-PB detector fireability

**Owns:** `src/mediahub/recognition_swim/achievements/official_pb.py`
  ·  **Flags:** engine  ·  **Suggested branch:** `claude/pbfix-official-pb`

| Issue | Sev | Location | Fix intent |
| --- | --- | --- | --- |
| **F18** | 🟠 | `src/mediahub/recognition_swim/achievements/official_pb.py`:198 | The ISO-date gate makes `official_pb_confirmed` effectively unfireable (interpreter PBs have date=None; heuristic dates are non-ISO). Loosen/normalise the date acceptance so a genuinely confirmed official PB can fire, or make the gate independent of an ISO date. |

**Acceptance:** A realistic confirmed-official-PB input fires `official_pb_confirmed`; add a test proving it fires (it currently cannot).

## P6 · V5 ranker — tables, maths, crash, contract

**Owns:** `legacy/swim_content_v5/ranker.py`
  ·  **Flags:** engine, high-stakes  ·  **Suggested branch:** `claude/pbfix-v5-ranker`

| Issue | Sev | Location | Fix intent |
| --- | --- | --- | --- |
| **F13** | 🟠 | `legacy/swim_content_v5/ranker.py`:141 | Guard `_narrative_factor` against `raw_facts['drop_pct'] is None` — it currently raises TypeError and crashes the entire ranking run. |
| **F03** | 🔴 | `legacy/swim_content_v5/ranker.py`:352 | Add the Phase-W types (club_record, club_debut, race_milestone_*, first_event_swim) to the inline `_POST_ANGLE_MAP` so they don't ship as `recap_mention`; align with `content_pack/builder.py:_TYPE_TO_ANGLE`. |
| **F07** | 🟠 | `legacy/swim_content_v5/ranker.py`:70 | Add `official_pb_confirmed` (and any other live-but-missing types) to `_TYPE_MAGNITUDE` so the strongest PB confirmation doesn't rank below `pb_likely`/`pb_confirmed` at the default 0.3. |
| **F08** | 🟠 | `legacy/swim_content_v5/ranker.py`:63 | Key the ranker tables on `biggest_drop_of_meet` (the relabelled type) not just `biggest_drop_candidate`, so the meet's headline drop keeps its magnitude/narrative bonus. |
| **F19** | 🟠 | `legacy/swim_content_v5/ranker.py`:378 | Handle `relay_strong_performance` (detector's actual type) not just `relay_strong`. |
| **F12** | 🟠 | `legacy/swim_content_v5/ranker.py`:45 | Add meet levels `regional` and `international` to `_MEET_LEVEL_SCORE`/post-type logic so a regional champs doesn't score like an open gala. |
| **F05** | 🟠 | `legacy/swim_content_v5/ranker.py`:296 | Add `club_record` to the quality-band type overrides so the club's biggest moment doesn't band below a routine gold at club/county meets. |
| **F14** | 🟠 | `legacy/swim_content_v5/ranker.py`:105 | Fix the club_record magnitude inversion: the 1.1 base is clamped to 1.0 only when drop_pct is present, so improvement evidence LOWERS the score. Decide a single consistent treatment (cap at 1.0 OR let the boost apply) that keeps club_record top. |
| **F15** | 🟠 | `legacy/swim_content_v5/ranker.py`:298 | Gate the quality-band type overrides on a minimum priority/confidence and on `safe_to_post`, so a 0.1-confidence or do_not_post medal_gold is not banded ELITE/MAIN_FEED. |
| **F21** | 🟠 | `legacy/swim_content_v5/ranker.py`:188 | Stop silently swallowing profile-priority errors: don't `except Exception: pass` and then report 'no profile priority override' — surface/record the real reason. |
| **F24** | 🟡 | `legacy/swim_content_v5/ranker.py`:383 | Stop mutating input Achievement objects (post_angle) in a way that can serialise two contradictory post_angle values; don't override a detector-preset angle silently. |
| **F27** | 🟡 | `legacy/swim_content_v5/ranker.py`:327 | Either read `history_map` (add the documented recency/history dimension) or drop the unused parameter and the report.py plumbing that fills it. |
| **F34** | 🟡 | `legacy/swim_content_v5/ranker.py`:404 | Add deterministic tie-breakers to the final sort (documented order: PB confidence > score > recency > diversity) so equal-priority order isn't detector-emission-order arbitrary. |
| **F49** | 🟡 | `legacy/swim_content_v5/ranker.py`:13 | Reconcile the factor contract: magnitude 1.1 and the raw-multiplier profile factor violate the '(value 0-1, weight, reason)' docstring, and the docstring calls profile priority ADDITIVE while code is multiplicative. Fix code or docstring so they agree. |
| **F54** | ⚪ | `legacy/swim_content_v5/ranker.py`:157 | Rework the certainty penalty so perfect confidence with a few uncertainty notes isn't indistinguishable from zero confidence (flat 0.05/note floor-clamp). |
| **F04** | 🟠 | `legacy/swim_content_v5/ranker.py`:292 | Fix profile-priority saturation: the `min(1.0,...)` clamp collapses order among a club's boosted cards even at the sanctioned ×2.0; preserve relative order after boosting. |
| **F62** | ⚪ | `legacy/swim_content_v5/ranker.py`:396 | Remove the pointless bare-except `object.__setattr__` pattern on non-frozen dataclasses (or make the intent explicit) so a future `slots=True` can't silently drop safe_to_post/post_angle. |
| **F22** | 🟠 | `legacy/swim_content_v5/ranker.py`:324 | Add direct behavioural tests for the V5 ranker (weights, magnitude tables, priority maths) — currently only one assertion exists in the whole suite. |
| **F23** | 🟠 | `legacy/swim_content_v5/ranker.py`:296 | Add assertions for quality-band thresholds, type overrides, and band→post-type mapping, including the NOT_WORTHY/INTERNAL_NOTE branches (currently never executed in any test). |
| **F52** | 🟡 | `legacy/swim_content_v5/ranker.py`:149 | Add tests that rank a first_sub_barrier and a big-drop achievement so the barrier/rarity/drop-pct branches are exercised. |
| **F59** | ⚪ | `legacy/swim_content_v5/ranker.py`:1 | Fix the coverage command's glob patterns (single `*` doesn't cross `/`) so v5 ranker coverage is actually measured, not silently zero. |

**Acceptance:** No ranking run can crash on realistic input; every live achievement type resolves to a real magnitude/angle/band; club_record, official_pb_confirmed, biggest_drop_of_meet and regional/international meets rank sensibly; ranking is deterministic for equal-priority ties; the ranker has real behavioural test coverage. Full suite stays green with no weakened tests.

## P7 · V3 ranker + dead V1 ranker

**Owns:** `legacy/swim_content/ranker_v3.py`, `legacy/swim_content/ranker.py`
  ·  **Flags:** engine, high-stakes  ·  **Suggested branch:** `claude/pbfix-v3-ranker`

| Issue | Sev | Location | Fix intent |
| --- | --- | --- | --- |
| **F06** | 🟠 | `legacy/swim_content/ranker_v3.py`:123 | Read `Claim.extra['in_window']` and soft-weight out-of-window qualifier hits below in-window ones (the detector writes the flag expressly for this; the ranker ignores it). |
| **F35** | 🟡 | `legacy/swim_content/ranker_v3.py`:226 | Make queue-cap demotion tie-break deterministic (use the same `(bucket, -score, card_id)` order the ranker already uses elsewhere) instead of input order. |
| **F55** | ⚪ | `legacy/swim_content/ranker_v3.py`:230 | Recompute `_suggested_format` for cap-demoted cards instead of hardcoding FMT_RECAP, so a demoted weekend_in_numbers/spotlight gets a consistent format. |
| **F36** | 🟡 | `legacy/swim_content/ranker_v3.py`:33 | Resolve the documented but unimplemented '-8 open/host without finals/qualifier' penalty: either implement it (needs a meet-importance input) or correct the docstring. |
| **F37** | 🟡 | `legacy/swim_content/ranker_v3.py`:38 | Fix the anti-spam docstring/behaviour mismatch: demoted standouts often land in ARCHIVE, not 'recap' as documented — make behaviour and docstring agree. |
| **F60** | ⚪ | `legacy/swim_content/ranker_v3.py`:162 | Align the 'clean sweep' bonus with the grouper's vocabulary (2 = 'doubles up', 3+ = 'clean sweep') and stop double-counting one event across rounds in the ≥3-notable-swims bonus. |
| **F53** | 🟡 | `legacy/swim_content/ranker_v3.py`:158 | Add tests for the spotlight multi-swim bonus, clean-sweep bonus, and FMT_STORY assignment (three documented rules currently unasserted). |
| **F33** | 🟡 | `legacy/swim_content/ranker_v3.py`:177 | The entire `needs_confirmation` card path (−15 penalty, `needs_confirmation` bucket, `FMT_HOLD`, base-30 `TYPE_NEEDS_CONFIRMATION`) is unreachable — no producer ever creates a `needs_confirmation` card (detector routes unverifiable swims into `out.needs_confirmation_swims` plain dicts that are never carded; grouper imports `TYPE_NEEDS_CONFIRMATION` but never uses it), so `output_pack.py`'s 'Needs confirmation' section is permanently empty. Either wire it to a reachable state or remove the dead path and its docstring. Follow-up fully removed it (penalty, bucket, `FMT_HOLD`, `TYPE_NEEDS_CONFIRMATION`, and the unused grouper import). |
| **F58** | ⚪ | `legacy/swim_content/ranker.py`:62 | Remove the dead V1 ranker/pipeline (`legacy/swim_content/ranker.py`, and `pipeline.py` if unreferenced) — unreachable and carrying a third inconsistent queue threshold. Confirm zero live references first (15-step breakage check). |

**Acceptance:** Out-of-window quals rank below in-window; cap demotion and suggested-format are deterministic and consistent; docstrings match behaviour; the newly-tested bonuses pass; dead V1 ranker removed with no broken imports. Full suite green.

## P8 · Grouper — anti-spam & stroke lookup

**Owns:** `legacy/swim_content/grouper.py`
  ·  **Flags:** engine  ·  **Suggested branch:** `claude/pbfix-grouper`

| Issue | Sev | Location | Fix intent |
| --- | --- | --- | --- |
| **F28** | 🟡 | `legacy/swim_content/grouper.py`:137 | Resolve the dead spotlight-demotion coupling from the grouper side (it emits spotlight XOR standouts, so the ranker's demotion can never fire) — coordinate the intended behaviour with the V3-ranker session via your PR notes, since that session owns ranker_v3.py. |
| **F61** | ⚪ | `legacy/swim_content/grouper.py`:110 | Guard the `_STROKE_FAMILY_TITLE[stroke]` lookup (use `.get` with a fallback like the guarded sites elsewhere) so an unknown stroke code can't KeyError-crash spotlight headline building. |

**Acceptance:** An unknown stroke code no longer crashes headline building; the spotlight/standout emission contract is documented; full suite green.

## P9 · Report assembly — double registration & ghost type

**Owns:** `legacy/swim_content_v5/report.py`
  ·  **Flags:** none  ·  **Suggested branch:** `claude/pbfix-report-assembly`

| Issue | Sev | Location | Fix intent |
| --- | --- | --- | --- |
| **F10** | 🟠 | `legacy/swim_content_v5/report.py`:386 | Register MilestoneDetector and ClubRecordDetector once, not twice, so milestones/club-records aren't detected, ranked, counted and exported in duplicate. |
| **F57** | ⚪ | `legacy/swim_content_v5/report.py`:177 | Remove or wire up the ghost `pb_likely` type in the V5 path (counted and ranked but emitted by no detector). |

**Acceptance:** No duplicate milestone/club-record achievements in a run; no counted-but-unproduced pb_likely; add a test asserting single registration. Full suite green.

## P10 · Recommender — dead output & unreachable paths

**Owns:** `legacy/swim_content_v5/recommender.py`
  ·  **Flags:** none  ·  **Suggested branch:** `claude/pbfix-recommender`

| Issue | Sev | Location | Fix intent |
| --- | --- | --- | --- |
| **F29** | 🟡 | `legacy/swim_content_v5/recommender.py`:143 | Remove the dead `recommend_post_type` 'recommendations' output (computed every run, persisted as a full duplicate of every ranked achievement, read by nothing) — after a 15-step breakage check confirms no consumer. |
| **F26** | 🟡 | `legacy/swim_content_v5/recommender.py`:17 | Fix the `from recognition.schema import ...` that can never succeed at canonical import time (always falls through to shadow classes, so isinstance vs the canonical types is always False) — import the real path or drop the shadow classes. |
| **F32** | 🟡 | `legacy/swim_content_v5/recommender.py`:45 | Remove or make reachable `derive_safe_to_post`'s dead identity-suppression path (its only caller never passes `pb_decision`). |

**Acceptance:** No dead persisted 'recommendations' blob; schema classes resolve to the canonical types; no unreachable suppression branch. Full suite green, no broken importers.

## P11 · Web workflow-state keying & safety default

**Owns:** `src/mediahub/web/web.py`
  ·  **Flags:** high-stakes  ·  **Suggested branch:** `claude/pbfix-web-state`

| Issue | Sev | Location | Fix intent |
| --- | --- | --- | --- |
| **F11** | 🟠 | `src/mediahub/web/web.py`:25969 | Key interactive workflow state on a unique per-card id, not bare `achievement.swim_id`: duplicate swim_ids currently collide (approve/reject/caption on one card applies to its twin) and the deduped '~n' stub cards are unresolvable by card-id routes. Preserve back-compat for existing persisted runs. |
| **F51** | 🟡 | `src/mediahub/web/web.py`:56060 | Stop failing open: `safe_to_post` defaulting to `{'level':'safe'}` when the field is missing means a missing safety verdict silently becomes 'safe'. Default to the cautious verdict and surface the gap. |

**Acceptance:** Two cards with the same swim_id are independently approvable/captionable; a missing safe_to_post never renders as 'safe'; existing persisted runs still load; full suite green. NOTE: web.py is a ~69k-line monolith — follow the 15-step breakage check, keep the change surgical, and use `url_for()`/`_h()` conventions.

## P12 · Pipeline dual-ranker reconciliation (architectural)

**Owns:** `src/mediahub/pipeline/pipeline_v4.py`
  ·  **Flags:** engine, high-stakes, architectural  ·  **Suggested branch:** `claude/pbfix-dual-ranker`

| Issue | Sev | Location | Fix intent |
| --- | --- | --- | --- |
| **F16** | 🟠 | `src/mediahub/pipeline/pipeline_v4.py`:549 | Two rankers (V3 `rank_cards` and V5 `rank_achievements`) both run in the live pipeline and give OPPOSITE PB-vs-gold orderings, so the review queue can contradict the recognition report. This is architectural: decide the canonical ranking authority and make the other consistent or clearly subordinate. Do NOT silently pick one — this crosses the deterministic-engine boundary, so pressure-test it with `/llm-council` and record an ADR under `docs/adr/` before implementing. |

**Acceptance:** A single documented ranking authority; the two paths no longer contradict on PB-vs-gold; an ADR captures the decision. If the fix would require changing V5 or V3 ranking semantics, coordinate with those sessions via PR notes (you own only pipeline_v4.py).

## P13 · Governance engine-boundary guard

**Owns:** `autotest/gitops.py`
  ·  **Flags:** none  ·  **Suggested branch:** `claude/pbfix-engine-guard`

| Issue | Sev | Location | Fix intent |
| --- | --- | --- | --- |
| **F17** | 🟠 | `autotest/gitops.py`:42 | The autonomous-merge guard protects a nonexistent path (`legacy/swim_content_v5/ranker_v3.py`), so both live rankers are editable by the self-merging CI bot and uncovered by the deterministic-engine boundary. Point the guard at the real ranker paths (`legacy/swim_content_v5/ranker.py`, `legacy/swim_content/ranker_v3.py`). If the fix also needs a CLAUDE.md/governance-doc wording correction, note it for the docs session — you own only gitops.py. |

**Acceptance:** The guard matches the real ranker files; add/adjust a test proving a change to the real ranker paths is caught. Full suite green.

## P14 · Docs alignment + empty stub modules

**Owns:** `docs/RANKING.md`, `docs/DETECTOR_BUS.md`, `docs/SYSTEM_MAP.md`, `src/mediahub/recognition/ranker.py`, `src/mediahub/recognition/recommender.py`, `src/mediahub/recognition/report.py`
  ·  **Flags:** none  ·  **Suggested branch:** `claude/pbfix-docs-align`

| Issue | Sev | Location | Fix intent |
| --- | --- | --- | --- |
| **F38** | 🟡 | `docs/RANKING.md`:10 | Rewrite RANKING.md's fabricated formula (w_strength/w_rarity/w_pb_delta/w_recency/w_visibility) to describe the two rankers that actually exist. |
| **F39** | 🟡 | `docs/RANKING.md`:18 | Correct the claim that weights live in `data/ontology/levels.json` (it is an empty `{}` loaded by nothing). |
| **F40** | 🟡 | `docs/RANKING.md`:19 | Replace the nonexistent brand-kit `ranker_overrides` field with the real `ClubProfile.achievement_priorities`. |
| **F42** | 🟡 | `docs/RANKING.md`:40 | Remove/replace the 'Diversity penalty | recognition.ranker | 0.1' knob (points at a 0-byte file / nonexistent mechanism). |
| **F43** | 🟡 | `docs/RANKING.md`:42 | Remove/replace the '_pb_delta_score sigmoid mid=2.0s' knob (function does not exist). |
| **F48** | 🟡 | `docs/RANKING.md`:46 | Replace the fabricated `evidence.trace` audit field with the real `RankedAchievement.factors`. |
| **F41** | 🟡 | `legacy/swim_content_v5/recommender.py`:71 | Correct the fabricated per-athlete cap (k=2 in recommend_post_type) and MAX_CARDS_PER_PACK=12 claims (no such capping exists; the only cap is ranker_v3's queue_cap=20). |
| **F31** | 🟡 | `docs/DETECTOR_BUS.md`:67 | Fix DETECTOR_BUS.md's sport-registry framing: the live pipeline never reads it, so `register_sport` for a new sport does nothing — document reality. |
| **F44** | 🟡 | `docs/DETECTOR_BUS.md`:12 | Fix the wrong `register_sport` example (signature, sport name, and SportConfig fields ranker_weights/copy_text_builder don't exist). |
| **F45** | 🟡 | `docs/DETECTOR_BUS.md`:32 | Fix the fabricated detector contract `detect(swim, context: DetectorContext)` and the DetectorContext field list. |
| **F46** | 🟡 | `docs/DETECTOR_BUS.md`:46 | Fix the documented Achievement fields `kind`/`claim_text` (real fields: `type`/`headline`). |
| **F47** | 🟡 | `docs/SYSTEM_MAP.md`:27 | Correct SYSTEM_MAP.md's 'recognition.ranker (sport-agnostic)' convergence node to the real ranking topology. |
| **F30** | 🟡 | `src/mediahub/recognition/ranker.py`:1 | Resolve the three 0-byte modules (`recognition/ranker.py`, `recommender.py`, `report.py`) that are silent import traps at exactly the paths the docs advertise: either implement them as thin re-export shims to the real code or delete them and fix the docs to point at the real modules. Grep for importers first. |

**Acceptance:** Every factual claim in RANKING.md / DETECTOR_BUS.md / SYSTEM_MAP.md matches code (verify each with grep/read); the 0-byte stub modules are either real shims or gone with no dangling importers; nothing in the docs references a symbol/path that doesn't exist.
