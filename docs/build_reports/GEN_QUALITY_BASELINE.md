# Generation Engine — Quality Baseline (High-Water Mark)

> The persisted **high-water mark** for the MediaHub generation engine: the best
> verified quality state the engine has ever reached. Every generation-engine
> change must verify as **no worse than this on every tracked metric** and
> strictly better on the metric it targets. When a change beats the mark live,
> this file is updated (new metrics + refreshed reference notes) so the bar only
> ever ratchets **up**. Owned by the autonomous generation-engine run; see
> [`GEN_ENGINE_LOG.md`](GEN_ENGINE_LOG.md) for the per-run history.

**Established:** 2026-06-09 13:30 UTC (first baseline) · **Updated:** 2026-06-09 20:25 UTC (quote_led_recap → 11 archetypes)
**Engine state:** Gen Engine v2 Tier A live (default-on; `MEDIAHUB_GEN_V2=0` kill-switch). Tier B (SEQ-2 director + pool/rank/compliance) not yet wired.

## Tracked metrics (the bar that only ratchets up)

| Metric | How measured | High-water mark |
|---|---|---|
| **Archetype library size** | distinct `layouts/v2/*.html` archetypes the deterministic picker spreads a pack across | **11** |
| **Pack archetype diversity** | `quality.variant_metrics.archetype_diversity` over a representative 10-card pack (distinct archetypes / cards); §8C floor is 0.60 | **1.00** |
| **Representative-pack perceptual spread** | `quality.variant_metrics.perceptual_spread` (mean pairwise dHash distance) over the same 10-card pack — *informational for library growth (not monotonic under insertion); the SEQ-2 candidate-pool path is where this is the gating metric* | **~0.435** |
| **Library distinctiveness floor** | smallest nearest-neighbour dHash distance across the library; a genuine new structure (not a reskin) lands in the existing **0.33–0.46** band, well clear of reskin territory (~0.10). A new archetype must not push this floor down. | **unchanged (set by a pre-existing archetype pair)** |
| **Brand-compliance pass-rate** | Tier A: deterministic `--mh-*` role resolution + APCA/ΔE2000 legibility guarantees every shipped card is legible/on-brand (compliance gate tests green). SEQ-2 per-candidate compliance scoring not yet wired. | **100% (deterministic, Tier A)** |
| **Caption non-repetition** | `quality.variant_metrics.caption_repetition` — unchanged this run (captions not touched) | n/a this run |

## Representative pack (methodology)

Deterministic 10-card pack, Swansea University Swimming brand kit (maroon #ground / gold #accent — resolved via `--mh-*` roles, never hardcoded), varied swimmer / event / result, seeds 0–9, 1080×1350, rendered offline via Playwright. Identical inputs are used before/after every change so the comparison is apples-to-apples. Reference renders for this mark add `magazine_cover` (the ten Tier-A archetypes); the new archetype's nearest-neighbour dHash distance is **0.38**, inside the existing library band (a genuinely new cover composition — masthead + headline-over-photo + marginal cover-line column + circular coverstar burst — not a reskin, which would read ~0.10). The library distinctiveness floor is set by a pre-existing archetype pair, so adding this archetype does not push it down (library floor unchanged — no distinctiveness regression). Verified live-palette stress renders: normal/no-photo, with-photo (scrim + headline-over-photo legible), long hyphenated surname (wraps, no clip, clears the coverstar), a 25-char single-token name (wraps, no off-canvas clip), and 1080×1920 (masthead top-anchored, foot bottom-anchored). The kicker badge and coverstar both use the resolver's APCA-gated primary-on-accent pair, so they stay legible whether the accent resolves to gold or white.

> **quote_led_recap (2026-06-09 20:25 UTC).** Added the 11th archetype — an editorial pull-quote recap (light `--mh-surface` ground + left accent quote-bar + oversized hanging quote glyph + ragged left column + inline accent-underlined result + em-dash attribution rule). Verified on the identical deterministic renderer: representative seeds-0..9 pack archetype-diversity stays saturated at **1.00**; library grows **10 → 11**. Distinctiveness measured by rendering one card per archetype with identical data and taking pairwise dHash — the new archetype's nearest-neighbour distance (**0.32**, to `stat_stack_sidebar`) is far above reskin territory (~0.10) and **above the pre-existing library distinctiveness floor (0.309, `split_diagonal_hero`↔`ticker_strip`)**, so it does not become the closest pair and the floor is **unchanged** (no distinctiveness regression). NOTE: this run measured on a newer sandbox Chromium than the earlier marks, so absolute dHash magnitudes sit ~0.02–0.03 lower across the board (the 0.33–0.46 band above was set on the older Chromium); the gating signals are scale-independent — library size ↑, pack diversity 1.00, and the new NN strictly above the contemporaneously-measured pre-existing floor. 245 gen-v2/archetype/metrics/compliance/autofit/saliency/director tests pass (8 in `test_archetype_quote_led_recap.py`); ruff clean; no hex literals; all placeholders allow-listed; `{{BASE_CSS}}` present; no `render.py`/route change (flag-OFF byte-identical). Render-stress (normal, long hyphenated name, 25-char single token, long event, 1080×1920, second navy/gold palette): legible, on-brand, no overflow.

## Library at this mark (11 archetypes)

`big_number_dominant`, `centered_medal_spotlight`, `editorial_numbers_grid`, `full_bleed_photo_lower_third`, `magazine_cover`, `minimal_type_poster`, `quote_led_recap`, `split_diagonal_hero`, `stat_stack_sidebar`, `ticker_strip`, `triptych_progression`.

Catalog target (GENERATION.md §6) is 12; remaining: `duo_athlete_split`.
