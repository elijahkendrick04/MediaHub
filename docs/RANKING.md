# Ranking

MediaHub runs **two** rankers on every upload. Both live in the frozen
`legacy/` tree — not in `mediahub.recognition`, which is a thin re-export shell
(`legacy/` is placed on `sys.path` by `src/mediahub/__init__.py`, so its
packages import as top-level `swim_content` / `swim_content_v5`). Both rankers
are deliberately deterministic — the CLAUDE.md "which card outranks which?"
crown jewel — so identical input always produces identical output.

| Ranker | Module (import name) | Entry point | Ranks | Scale |
| --- | --- | --- | --- | --- |
| **V3 card ranker** | `legacy/swim_content/ranker_v3.py` (`swim_content.ranker_v3`) | `rank_cards(cards, *, queue_cap=20)` | `ContentCard`s (the V3 card system) | additive integer, 0–100 |
| **V5 achievement ranker** | `legacy/swim_content_v5/ranker.py` (`swim_content_v5.ranker`; re-exported as `mediahub.recognition.rank_achievements`) | `rank_achievements(achievements, ctx, history_map)` | `Achievement`s → `RankedAchievement`s | weighted, 0.0–1.0 |

`pipeline_v4` drives both: it groups claims into cards and calls `rank_cards`
on them, and separately triggers V5 ranking inside
`build_recognition_report_for_run` (`legacy/swim_content_v5/report.py`).

**V5 recognition is the canonical ranking authority** (ADR-0032). Both rankers
still run on every upload, but where their orderings disagree — the classic
PB-vs-gold question — V5 wins on every surfaced surface. `_reconcile_review_cards`
in `pipeline_v4.py` implements a **V5-first / V3-fallback** rule: when V5 produced
`ranked_achievements`, `run.cards` is derived from them in V5 priority order (via
`_v5_ranked_to_v3_stubs`) and `run.cards_order_source` is stamped `"v5"`; only
when V5 recognition is unavailable or empty does the pipeline keep the legacy V3
`rank_cards` output as the fallback (`"v3-legacy"`, or `"none"` if neither ranker
produced a card). The V3 detector chain still runs as an independent
deterministic cross-check (feeding `detector_summary` / `self_check`), but its
*ordering* is no longer surfaced when V5 has spoken. The per-achievement
`priority` scores and the "Why this card?" factor trace come from the V5 ranker.

## V5 achievement ranker — the weighted-factor score

`rank_achievements` gives each `Achievement` a `priority` in `[0.0, 1.0]`.
`_compute_priority` builds a weighted sum over six scoring factors, normalises it
by the maximum possible, then applies the club's per-type priority as an
**order-preserving** boost:

```
base     = Σ (factor_value_i × weight_i)  /  Σ weight_i      # six weighted factors

# profile_multiplier applied as an order-preserving boost (F04), NOT a plain multiply-and-clamp:
if multiplier >= 1.0:   priority = 1 - (1 - base) / multiplier   # compress headroom toward 1.0
else:                   priority = base × multiplier             # linear suppression
priority = clamp(priority, 0.0, 1.0)
```

For a boost (`multiplier >= 1`) the code compresses the *headroom* to 1.0 rather
than multiplying `base` directly: this is strictly monotonic in `base`, so two
distinct base scores can never collapse to the same `1.0` the way a plain
`min(1.0, base × multiplier)` would. For suppression (`0 <= multiplier < 1`, or a
nonsensical negative from a hand-edited profile) it scales down linearly, then
clamps to `[0, 1]`.

The six weighted factors and their weights (`_WEIGHTS`):

| Factor | Weight | What it measures |
| --- | --- | --- |
| `magnitude` | 0.30 | on-paper size of the result — per-type base from `_TYPE_MAGNITUDE`, plus a linear PB-drop boost `min(0.2, drop_pct / 20.0)` |
| `rarity` | 0.20 | how rare the result is at the meet's level |
| `meet_level` | 0.15 | national/international > university > regional > county > open > club (`_MEET_LEVEL_SCORE`) |
| `narrative` | 0.15 | story angles — multi-PB weekend, biggest drop, return to form (`_TYPE_NARRATIVE_BONUS`) |
| `barrier` | 0.10 | first-time sub-barrier crossing |
| `certainty` | 0.10 | confidence in the underlying data |

Both `rarity` and `meet_level` read the meet's level through `_MEET_LEVEL_SCORE`
(unknown levels fall back to `0.4`, matching `open`):

| Meet level | Score |
| --- | --- |
| `international` | 1.00 |
| `national` | 1.00 |
| `university` | 0.80 |
| `regional` | 0.75 |
| `county` | 0.60 |
| `open` | 0.40 |
| `club` | 0.20 |

(UK hierarchy: national > regional > county > open; `university`/BUCS sits
between national and regional.)

Two further factors carry weight `0.00`, so neither enters the `Σ weight_i`
denominator:

- `recency` — value in `[0, 1]` (`_recency_factor` / `_recency_value`): how
  recently the swimmer last competed in this event, read from `history_map`
  against the meet date (`1.0` = swum right before the meet, `0.0` = a year+ ago,
  `0.5` = unknown/undated). It is recorded in the factor list for explainability
  and used **only as a deterministic tie-break** (see the sort order below); it
  contributes nothing to the weighted sum.
- `profile_priority` — recorded in the factor list for transparency but applied
  **multiplicatively after** the weighted sum (see
  [Per-club tuning](#per-club-tuning)).

`magnitude` and `narrative` are keyed on the achievement's `type` string. The
real type strings are the keys of `_TYPE_MAGNITUDE` — e.g. `pb_confirmed`,
`medal_gold`, `first_sub_barrier`, `pb_magnitude_huge` / `_big` / `_notable`,
`club_record`, `race_milestone_*`, `qual_hit_*`, `top_of_field_*`,
`relay_medal_*`. There is **no** `pb_delta` sigmoid and **no** field-rank
normalisation — those were never implemented. (There is, since F34/P6, a
zero-weight `recency` factor — documented above — used purely as a tie-break.)

`rank_achievements` returns the achievements sorted by a deterministic key so the
published order never depends on detector emission order (F34):

```
score (priority) > PB confidence > recency > swim_id
```

i.e. it sorts by descending `priority`, then descending PB `confidence`, then
descending `recency` value, then ascending `swim_id` (unique per card, which
guarantees a total order). Each achievement is stamped with a 1-based `rank`.

## V3 card ranker — the additive card score

`score_card` gives each `ContentCard` a base score by card type (`_BASE_SCORE`:
spotlight 70, qual_alert 70, pb_roundup 65, podium_roundup 55,
weekend_in_numbers 45, standout 40, recap 25), then applies fixed integer
modifiers:

- **+10 / +6 / +4** — national / university (BUCS) / other qualifying-standard hit
- **+12 / +5** — confirmed / likely PB
- **+8 / +4 / +2** — best medal on the card (gold / silver / bronze; highest tier only)
- **+5 / +5** — spotlight covering ≥3 notable swims / same-stroke "clean sweep"
- **−10** — likely-PB-only card (no medal, no qualifier)

The score is clamped to `0…100`. `rank_cards` then buckets by the final score —
**queue** (≥65), **recap** (40–64), or **archive** (<40) — assigns a suggested
format, and sorts by `(bucket, -score, card_id)`.

## Per-club tuning

Ranker weights are **hardcoded module constants** (`_WEIGHTS`,
`_TYPE_MAGNITUDE`, `_BASE_SCORE`); they are **not** loaded from a config file.
(`data/ontology/levels.json` exists but is an empty `{}` that no code reads.)

The one per-club override is `ClubProfile.achievement_priorities`
(`src/mediahub/web/club_profile.py`) — a `{achievement_type: multiplier}` map,
resolved through `ClubProfile.get_achievement_priority()` (the club's AI
operating-profile priorities win over the legacy dict; default `1.0`).
`_profile_priority_factor` reads it and returns the multiplier, which
`_compute_priority` applies as the `profile_multiplier` (`> 1.0` boosts a type,
`< 1.0` suppresses it). The application is **order-preserving**, not a plain
multiply-and-clamp: a boost uses `priority = 1 - (1 - base) / multiplier`
(compressing the headroom toward `1.0`) so two distinct boosted cards keep their
relative order instead of both saturating at `1.0`; suppression uses
`priority = base × multiplier`; the result is clamped to `[0, 1]` (see the
formula block above). It scales the final V5 priority; it is not a weight
override, and there is no `ranker_overrides` brand-kit field.

## Volume control

The V3 ranker applies a `queue_cap=20`: once more than 20 cards land in the
**queue** bucket, the lowest-scoring overflow is demoted to **recap**. The other
V3 anti-spam lever is its spotlight demotion — a swimmer who has an
athlete-spotlight card has their individual-swim ("standout") cards demoted by 25
so the spotlight stays their canonical entry. Both apply inside V3 `rank_cards`,
so under ADR-0032 they shape `run.cards` **only on the V3-legacy fallback path**;
on the V5-authoritative path `run.cards` are V5-derived stubs
(`_v5_ranked_to_v3_stubs`), one per ranked achievement, all in the **queue**
bucket and **not** subject to the V3 cap. V5's own volume control is the
meet-recap slice below.

There is **no per-athlete cap** and **no `MAX_CARDS_PER_PACK`**. V5's
`recommend_post_type` (`legacy/swim_content_v5/recommender.py`) groups ranked
achievements by `swimmer_id` but keeps *all* of a swimmer's achievements; the
one bounded slice is the meet-recap recommendation, which keeps the top 10
notable achievements.

## Explainability — the factor trace

Each `RankedAchievement` carries a `factors` list — one `RankFactor(name,
value, weight, reason, plain_summary)` per component
(`legacy/swim_content_v5/schema.py`), built in `_compute_priority`. This is the
per-component audit trail. The `/review/<run_id>` "Why this card?" disclosure
renders it via `_render_factor_breakdown` in `src/mediahub/web/web.py`, which
reads each ranked achievement's `factors`.

Do not confuse this with `Achievement.evidence`: that is a separate list of
`AchievementEvidence` provenance records (`source_type`, `source_name`,
`statement`, `source_url`, `fetched_at`, `confidence`) describing *where a fact
came from* — it has no `trace` field and does not record ranker component
scores.
