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
`build_recognition_report_for_run` (`legacy/swim_content_v5/report.py`). The
review queue, buckets and formats you see come from the V3 ranker; the
per-achievement `priority` scores and the "Why this card?" factor trace come
from the V5 ranker.

## V5 achievement ranker — the weighted-factor score

`rank_achievements` gives each `Achievement` a `priority` in `[0.0, 1.0]`.
`_compute_priority` builds a weighted sum over six factors, normalises it by the
maximum possible, then multiplies by the club's per-type priority:

```
base     = Σ (factor_value_i × weight_i)  /  Σ weight_i      # six weighted factors
priority  = clamp(base × profile_multiplier, 0.0, 1.0)
```

The six weighted factors and their weights (`_WEIGHTS`):

| Factor | Weight | What it measures |
| --- | --- | --- |
| `magnitude` | 0.30 | on-paper size of the result — per-type base from `_TYPE_MAGNITUDE`, plus a linear PB-drop boost `min(0.2, drop_pct / 20.0)` |
| `rarity` | 0.20 | how rare the result is at the meet's level |
| `meet_level` | 0.15 | national > university > county > open > club (`_MEET_LEVEL_SCORE`) |
| `narrative` | 0.15 | story angles — multi-PB weekend, biggest drop, return to form (`_TYPE_NARRATIVE_BONUS`) |
| `barrier` | 0.10 | first-time sub-barrier crossing |
| `certainty` | 0.10 | confidence in the underlying data |

A seventh factor, `profile_priority`, carries weight `0.00`: it is recorded in
the factor list for transparency but applied **multiplicatively after** the
weighted sum (see [Per-club tuning](#per-club-tuning)), so it never enters the
`Σ weight_i` denominator.

`magnitude` and `narrative` are keyed on the achievement's `type` string. The
real type strings are the keys of `_TYPE_MAGNITUDE` — e.g. `pb_confirmed`,
`medal_gold`, `first_sub_barrier`, `pb_magnitude_huge` / `_big` / `_notable`,
`club_record`, `race_milestone_*`, `qual_hit_*`, `top_of_field_*`,
`relay_medal_*`. There is **no** `pb_delta` sigmoid, **no** recency/decay term,
and **no** field-rank normalisation — those were never implemented.

`rank_achievements` returns the achievements sorted by descending `priority`,
each stamped with a 1-based `rank`.

## V3 card ranker — the additive card score

`score_card` gives each `ContentCard` a base score by card type (`_BASE_SCORE`:
spotlight 70, qual_alert 70, pb_roundup 65, podium_roundup 55,
weekend_in_numbers 45, standout 40, needs_confirmation 30, recap 25), then
applies fixed integer modifiers:

- **+10 / +6 / +4** — national / university (BUCS) / other qualifying-standard hit
- **+12 / +5** — confirmed / likely PB
- **+8 / +4 / +2** — best medal on the card (gold / silver / bronze; highest tier only)
- **+5 / +5** — spotlight covering ≥3 notable swims / same-stroke "clean sweep"
- **−10** — likely-PB-only card (no medal, no qualifier)
- **−15** — card flagged `needs_confirmation`

The score is clamped to `0…100`. `rank_cards` then buckets by the final score —
**queue** (≥65), **recap** (40–64), **archive** (<40), or
**needs_confirmation** — assigns a suggested format, and sorts by
`(bucket, -score, card_id)`.

## Per-club tuning

Ranker weights are **hardcoded module constants** (`_WEIGHTS`,
`_TYPE_MAGNITUDE`, `_BASE_SCORE`); they are **not** loaded from a config file.
(`data/ontology/levels.json` exists but is an empty `{}` that no code reads.)

The one per-club override is `ClubProfile.achievement_priorities`
(`src/mediahub/web/club_profile.py`) — a `{achievement_type: multiplier}` map,
resolved through `ClubProfile.get_achievement_priority()` (the club's AI
operating-profile priorities win over the legacy dict; default `1.0`).
`_profile_priority_factor` reads it and returns the multiplier, which
`_compute_priority` applies as the multiplicative `profile_multiplier`
(`> 1.0` boosts a type, `< 1.0` suppresses it). It scales the final V5
priority; it is not a weight override, and there is no `ranker_overrides`
brand-kit field.

## Volume control

The only card cap on the live path is the V3 ranker's `queue_cap=20`: once more
than 20 cards land in the **queue** bucket, the lowest-scoring overflow is
demoted to **recap**. The other anti-spam lever is V3's spotlight demotion — a
swimmer who has an athlete-spotlight card has their individual-swim ("standout")
cards demoted by 25 so the spotlight stays their canonical entry.

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
