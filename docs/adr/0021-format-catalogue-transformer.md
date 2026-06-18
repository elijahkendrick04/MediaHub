# ADR 0021 — Smart format catalogue + format transformer (P6.1)

- **Status:** accepted (2026-06-18). Implements roadmap item **P6.1** — the
  first Phase-2 (creative-suite) work package. See
  [`CREATIVE_SUITE_PARITY.md`](../CREATIVE_SUITE_PARITY.md) §P6.1 for the
  feature-by-feature coverage map this builds against.
- **Context:** MediaHub already renders feed/story/reel cards from run data +
  a `BrandKit`, and `turn_into` already turns one meet into eight artefacts.
  Canva/Adobe-class parity needs two more things: (a) a *catalogue* of the
  off-feed and per-channel design formats a club actually needs — certificates,
  posters, coach cards, season calendars, wallpapers, and a per-platform size
  preset for every social channel; and (b) a *transformer* that re-targets an
  approved design to any of those formats ("Magic Switch" / "resize for any
  channel") by re-laying-out the content for the new canvas rather than
  stretching pixels.

## Decision

**Two new modules + a thin web surface; the renderer and the engine are
untouched.**

1. **`club_platform/format_catalog.py` — the catalogue is pure data.** Each
   format is a typed, frozen `FormatSpec` (canvas size, safe zones, the
   archetypes that suit its aspect, the run data it needs, optional print
   bleed/dpi). No AI and no I/O build the registry. `custom_format()` adds an
   any-size canvas (px/mm/cm/in, bounds-checked). `aspect_class()` mirrors the
   renderer's private `_format_aspect` and is parity-tested so the two cannot
   drift. This keeps the catalogue squarely on the deterministic side of the
   engine boundary — sizes and geometry are facts, not judgements.

2. **Per-sport availability is sourced from the sport profile.** A format that
   needs particular run data declares `requires_post_types` (canonical taxonomy
   slugs); `formats_for_sport()` keeps it only when the sport profile enables at
   least one of those post types. A certificate appears for a sport that
   produces results; a season calendar for one with fixtures. Universal formats
   (every social size, posters, wallpapers) declare nothing and are always
   available. No sport-profile **schema** change was needed — the existing
   `enabled_post_types()` is the source of truth.

3. **`turn_into/transform.py` — the transformer re-lays-out, it does not
   scale.** `transform_design(source_brief, target_format)` returns a *new*
   `CreativeBrief` (the source is never mutated) that **preserves** every
   approved creative decision — palette, colour-role assignment, headline,
   stats, photo, tone — and **re-decides only the archetype** (composition) for
   the new aspect. That single judgement goes through the design-spec director
   (Gemini→Anthropic via `ai_core`), constrained to the format's
   aspect-appropriate archetypes; when no provider is configured the
   deterministic per-aspect picker is the honest floor — never a fabricated
   layout. This is the same Tier-B pattern `creative_brief` already uses, reused
   rather than reinvented. `blank_brief_for_format()` is the blank-start escape
   hatch (a minimal on-brand brief seeded from brand tokens).

4. **The renderer is reused, not extended.** `graphic_renderer.render_brief`
   already accepts an explicit `size=(w, h)` and adapts the composition to the
   aspect, so the transformer just threads the format's size into the existing
   render path. No new rendering engine, no per-format template, no change to
   `FORMAT_SIZES` defaults.

5. **Web surface mirrors the motion routes.** `GET /api/formats` returns the
   catalogue JSON (optionally filtered by sport). `POST
   /api/runs/<run_id>/card/<card_id>/reformat?format=<slug>` (or `w/h/unit`, or
   `blank=1`, or `ai=1`) loads the card's approved brief, transforms it, renders
   at the format's size, and serves the PNG directly — exactly as
   `api_card_motion` serves an MP4. A per-card **Reformat…** control on the
   content builder drives it. Tenant-gated (`_can_access_run` /
   `_session_can_access_profile`); JSON POST so CSRF-exempt by content-type.

## Consequences

- Adding a new format is a one-line `FormatSpec` (or `custom_format()` at
  runtime) — formats are data, the renderer already knows how to paint any size.
- The deterministic-engine boundary holds: catalogue geometry is deterministic;
  the one judgement (which layout for which shape) goes through the AI director
  with a deterministic floor, never hardcoded heuristics and never a fake.
- **Out of scope, deferred to their owning packages:** multi-page composition
  (programmes, yearbooks) → P6.12; print-ready CMYK/bleed export → P6.19;
  free-form manual element editing → P6.24; save-as-org-format presets and
  bulk autofill → P6.11 / P6.15. Tumblr/Lemon8 sizes are one `FormatSpec` row
  each when a club asks (pull-driven, per the phase's ordering rule).
- Hosted-only stands (ADR-0011): this is a server-side render surface; there is
  no customer self-host path.

## Alternatives considered

- **Register catalogue sizes into `graphic_renderer.FORMAT_SIZES`.** Rejected:
  it inverts the layering (the low-level renderer would import the higher-level
  catalogue) and risks changing the existing default-export trio. `render_brief`
  takes an explicit size, so the transformer passes the size directly instead.
- **Re-run `create_visual_for_item` with a format hint.** That regenerates the
  brief from the achievement rather than transforming the *approved* design, so
  it would discard the human's approved copy/palette. The transformer starts
  from the persisted brief precisely to preserve those decisions.
- **A sport-profile YAML `formats:` block for availability.** Heavier than
  needed; deriving availability from `enabled_post_types()` reuses the existing
  contract with no schema change or migration.
