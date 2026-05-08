# Ranking

Cards are produced by ranking the detector output. The ranker lives in
`mediahub.recognition.ranker` (sport-agnostic) and the legacy V5 ranker
`legacy/swim_content_v5/ranker.py` (still active for swim).

## Formula

```
score(achievement) =
      w_strength    * detector_confidence
    + w_rarity      * (1 - normalised_field_rank)
    + w_pb_delta    * scaled(pb_delta_seconds)
    + w_recency     * decay(days_since_last_pb)
    + w_visibility  * (1 if medal_final else 0)
```

Weights live in `data/ontology/levels.json` and can be overridden per club via
the brand kit's `ranker_overrides` field.

## Meet-level scoring

After per-achievement ranking, cards are grouped by athlete (so we don't post
five cards for the same swimmer in the same weekend) and the top `k` per
athlete are kept (default `k=2`).

Then the cards are sorted globally by:

1. PB confidence (`NEW_PB` > `LIKELY_PB` > `NOT_PB`)
2. Score
3. Recency (newer events first)
4. Diversity penalty for repeating an event/age band

## Tunable knobs

| Knob | Where | Default |
| --- | --- | --- |
| Detector weights | `data/ontology/levels.json` | per-detector |
| Per-athlete cap | `swim_content_v5.recommender.recommend_post_type` | 2 |
| Diversity penalty | `recognition.ranker` | 0.1 |
| Card limit per pack | `mediahub.web.web.MAX_CARDS_PER_PACK` | 12 |
| PB-delta scaling | `swim_content_v5.ranker._pb_delta_score` | sigmoid, mid=2.0s |

## Trace

Each card's `evidence.trace` field records the per-component score so you can
audit the ranker decision in `/review/<run_id>` (click the card → "Why this
card?").
