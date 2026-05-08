# V8 — Image / Media Generation Engine

## Mission (verbatim from user)
"Turn swimming results, achievement recognition, club/team branding, approved real images, and current sports social media creative patterns into ready-to-post branded visual content packs." Output must be **100x better than Canva**, never "fake AI swimmers", and fully integrated with the existing app.

The full spec is at `/home/user/workspace/paste.txt` (2436 lines). Read it in full — every requirement matters.

## Existing app to integrate with (READ FIRST)

Don't duplicate. Hook into:

- `swim_content_v4/pipeline_v4.py` — meet ingest → recognition → content_pack
- `recognition/` — achievement detection (RecognitionItem types in `recognition/schema.py`)
- `recognition_swim/achievements/*` — 16 detectors that produce achievements
- `content_pack/builder.py` — ContentPackItem grouping
- `brand/` — BrandKit, Tone, templates, apply
- `voice/learned/` — voice profiles (use these for caption tone)
- `swim_content_v4/web.py` — Flask routes + UI templates
- `workflow/` — CardStatus + sidecar persistence

Brand profile data is at `data/club_profiles/` (currently `coma.json`, `swansea-uni.json`).
Sample data at `samples/learning_corpus/` (44 real meet docs).

## Required modules (new)

```
media_ai/
  __init__.py
  llm.py                     — Claude Sonnet wrapper (live captions, alt text, brief generation)
  providers/
    __init__.py
    rembg_local.py           — local rembg cutouts (free, default)
    replicate_provider.py    — paid Replicate API for higher quality
    base.py                  — provider interface; switch via env var

media_library/
  __init__.py
  models.py                  — MediaAsset dataclass with full metadata
  store.py                   — SQLite-backed CRUD; file blobs in uploads/
  describe.py                — parse user free-text descriptions → structured tags via Claude
  tagger.py                  — extract subjects/swimmers/venue/event from description
  selector.py                — pick best media asset for a content item

media_requirements/
  __init__.py
  rules.py                   — MediaRequirement per content item type
  evaluator.py               — given a content item + library, produce status

venue_search/
  __init__.py
  search.py                  — search public-domain images by venue/meet name; show source + permission

inspiration/
  __init__.py
  pattern_library.py         — curated layout patterns (data, JSON; user-extendable)
  exemplar_analyser.py       — given user-uploaded reference images, extract style features via Claude vision

creative_brief/
  __init__.py
  generator.py               — given achievement + brand + media + inspiration → CreativeBrief

graphic_renderer/
  __init__.py
  layouts/                   — HTML/CSS templates per layout pattern
    individual_hero.html
    medal_card.html
    weekend_numbers.html
    athlete_spotlight.html
    meet_preview.html
    sponsor_branded.html
    text_led_recap.html
    story_card.html
    reel_cover.html
  render.py                  — Playwright HTML→PNG renderer
  variants.py                — produce 1080x1080, 1080x1350, 1080x1920, carousel slides, reel cover from one brief

content_pack_visual/
  __init__.py
  integration.py             — extend existing content_pack/builder.py output with visual assets
```

## Data model

`MediaAsset`:
```python
@dataclass
class MediaAsset:
    id: str
    filename: str
    path: str
    type: Literal["athlete_headshot","athlete_action","team_photo","venue_photo","logo","sponsor_logo","brand_pattern","exemplar_post"]
    description_raw: str            # what the user typed
    description_parsed: dict        # AI-parsed: {athletes: [...], venue: ..., meet: ..., tags: [...]}
    linked_athlete_ids: list[str]
    linked_meet_ids: list[str]
    linked_venue: str | None
    permission_status: Literal["user_owned","approved_public","needs_approval","internal_only","do_not_use","unknown"]
    approval_status: Literal["approved","draft","rejected","pending"]
    width: int
    height: int
    orientation: Literal["portrait","landscape","square"]
    dominant_colours: list[str]     # hex
    has_face: bool
    safe_for_minors: bool
    cutout_path: str | None         # if rembg ran
    source_url: str | None          # for venue/web-sourced
    uploaded_at: datetime
    used_in: list[str]              # generated_visual ids that consumed it
```

`CreativeBrief`:
```python
@dataclass
class CreativeBrief:
    id: str
    content_item_id: str
    achievement_summary: str
    objective: str
    primary_hook: str
    tone: str
    layout_template: str            # e.g. "individual_hero"
    image_treatment: str
    text_hierarchy: list[str]       # ordered list of fields by prominence
    brand_instructions: str
    sponsor_instructions: str | None
    sourced_asset_ids: list[str]
    inspiration_pattern_id: str
    safety_notes: list[str]         # e.g. "likeness_preserved", "minor_consent_pending"
    why_this_design: str            # explainability
```

`GeneratedVisual`:
```python
@dataclass
class GeneratedVisual:
    id: str
    content_item_id: str
    creative_brief_id: str
    format: Literal["feed_square","feed_portrait","story","reel_cover","carousel_slide"]
    width: int
    height: int
    image_path: str
    preview_path: str
    text_layers: list[dict]         # editable layers with {field, text, x, y, font, size}
    source_asset_ids: list[str]
    caption: str
    alt_text: str
    voice_id: str
    status: Literal["draft","approved","exported","posted","rejected"]
    version: int
    created_at: datetime
```

## Hard requirements (from spec, paraphrased — read paste.txt for nuance)

1. **Never generate fake people.** Real photos for human posts. AI placeholder only if explicitly labelled.
2. **Match real photos to achievements** via `media_library.selector` — score on: athlete match (description tags), orientation, has face, brand colours, freshness, quality.
3. **Ask for missing photos** — when no real photo exists, surface a "Upload athlete photo" panel inline on the card with a clear request message naming the swimmer.
4. **Online venue photo search** — `venue_search.search()` returns public-domain results with source URL, dimensions, permission status, "approve for use" button. Default source: Wikimedia Commons (CC). Show user the source.
5. **Inspiration patterns ≠ copies.** `pattern_library.py` is a curated JSON of *layout shapes* (athlete-cutout-with-surname-bg, weekend-grid, medal-card, etc.) NOT image rips. Each pattern is a layout family the renderer can compose.
6. **Creative brief before render.** Always generate the brief, persist it, render from it. The brief includes "why this design" explainability.
7. **Multiple format variants.** Each visual produces 1080x1080, 1080x1350, 1080x1920 by default. Carousel + reel cover when relevant.
8. **Confidence-aware language.** High confidence → "NEW PB"; medium → "LIKELY PB"; low → no graphic until verified.
9. **Editable text layers.** After render, user can edit headline / athlete name / result / caption / alt text and re-render in seconds.
10. **Source tracking + permission warnings everywhere.** Every visual has an audit trail: source assets, permission status of each, brand profile, brief.
11. **Modular for non-swimming.** Use participant/team/event/achievement abstract concepts at the engine level; swim-specific fields live in detectors only.
12. **Content pack integration.** Visuals appear inside the existing content_pack workflow, not a parallel page. Card status, approval, export — all reuse existing UI patterns.

## Rendering pipeline

For each ContentPackItem the recogniser surfaces:

```
content_item
  → MediaRequirements.evaluate()  # what does this post need?
  → media_library.selector.pick()  # match best available + flag missing
  → if missing critical (e.g. athlete photo for individual achievement):
      surface "needs_media" UI; do NOT render until provided
  → if all required present:
      → creative_brief.generate()   # AI-driven design direction
      → graphic_renderer.render(brief)
        → HTML/CSS template + brand + photos + brief data
        → Playwright headless chromium → PNG
        → produce 3 sizes
      → caption.generate(achievement, voice_id="ai" or saved voice)
      → alt_text.generate()
      → save GeneratedVisual rows linked to content_item
```

## UI surfaces to add/extend

1. **Recognition page** (`/review/<run_id>`):
   - Each achievement card gets a "Create graphic" button.
   - Below: small media badge — "ready" / "needs photo of {swimmer}" / "needs venue image".
   - Click → expands inline panel with:
     - Suggested layout (from creative_brief.layout_template)
     - Source images preview (athlete cutout, venue photo)
     - Live preview iframe (1080x1350 by default)
     - Tone selector (AI / data_led / hype / warm_club / + saved voices)
     - Format tabs (Feed Square / Feed Portrait / Story / Reel Cover)
     - Upload athlete photo button (if missing)
     - Search venue button (if no venue image)
     - Regenerate / Edit text / Export PNG / Add to pack
2. **New `/media-library` page**:
   - Upload dropzone with multi-file
   - List + grid views; filters by athlete/meet/venue/type/permission
   - Click asset → side-pane with structured metadata, edit description, change permission, delete
   - Rich free-text description box. AI parses on save: extracts athlete names, venue, meet, suggested tags, "best for" recommendations.
3. **`/profiles` extended**:
   - Add brand kit fields: primary/secondary/accent colours, logo upload, sponsor logo upload, hashtag set, tone of voice, banned phrases, design strictness (strict/balanced/creative)
4. **`/content-pack/<run_id>`** (new or extend existing):
   - Grid of all generated visuals with thumbnails
   - Caption + alt text editable in place
   - Approve / Reject / Export bulk
   - Download all as ZIP with structure matching paste.txt section "/meet-name-date-content-pack/..."

## LLM integration

Use Computer's LLM bridge first; fall back to direct Anthropic SDK with `os.environ["ANTHROPIC_API_KEY"]`. Wrap it in `media_ai/llm.py` so the rest of the code calls `llm.generate(messages)` and doesn't care.

LLM responsibilities:
- Caption generation (live, per click)
- Alt text generation
- Description parsing (free-text photo description → structured tags)
- Creative brief synthesis (achievement + brand + library + inspiration → brief)
- Vision: analyse user-uploaded exemplar posts → style features

## Background removal

Default: local `rembg` via `media_ai/providers/rembg_local.py`. It's free, decent, works in published sandbox.
Optional upgrade: Replicate API via `replicate_provider.py` if user provides `REPLICATE_API_TOKEN`. Switch via env var.

## Public-domain venue photos

`venue_search.search(meet_name, venue_name)`:
- Query Wikimedia Commons via its API for the venue (e.g. "Wales National Pool Swansea" → returns CC-licensed images)
- Each result has `source_url`, `licence`, `attribution_required`, `dimensions`
- User clicks "Use" → asset added to library with permission_status=approved_public, source_url stored.
- For when Wikimedia has nothing: also try Unsplash/Openverse free APIs (both have free tiers).

## Tests

`tests_v75/test_v8_*.py` covering:
- MediaAsset CRUD round-trip
- Description parsing extracts structured fields
- MediaRequirements.evaluate() correctly says "needs photo" for individual achievements without a matching headshot
- selector.pick() prefers approved + correct athlete + landscape over wrong-athlete + portrait
- creative_brief.generate produces non-empty brief with required fields
- graphic_renderer renders synthetic test brief to a real PNG file with non-zero size
- format variants produce 3 PNGs with correct dimensions
- live caption endpoint regenerates fresh on every call
- AI fallback to voice when no API key
- venue_search returns results with source URL set

Plus a smoke test: full pipeline on Manchester PDF → at least 5 generated visuals saved with non-zero PNGs.

## Quality bar (≫ Canva)

The user said "100x better than Canva". Concretely that means:
- Real athlete cutouts (not stock-clipart silhouettes)
- Type pairings using premium open fonts (Bebas Neue / Inter / Space Grotesk / Druk-style headlines)
- Composition: athlete cutout + oversized surname behind + result chip + brand corner — modern sports IG vocabulary
- Subtle texture/gradient background that's specific to the meet (e.g. water ripple for swim)
- Confidence-tier visual language (gold/silver/bronze tints for medals; PB shockwave; record glow)
- Story versions optimised for thumbs-zone with safe margins; reel covers with first-frame readability
- Auto-balanced contrast so text is always legible on athlete cutout (use luminance-aware text colour)

After build, render 6 test cards (1 per achievement type), screenshot them, **inspect side-by-side against a Canva sports template**. Iterate until the test cards visibly outclass the Canva versions on: typography, composition, colour, photo treatment, brand-consistency.

## Anti-shortcut rules

- Do NOT build a parallel page. Integrate into existing `/review/<run_id>` and `/content-pack/<run_id>`.
- Do NOT hardcode swim vocabulary in the engine layer (use abstractions).
- Do NOT skip the "why this design" explainability text.
- Do NOT auto-render visuals that have unverified data — surface as "needs review".
- Do NOT use copyrighted IG content as inspiration source — use only the curated pattern library + user-supplied exemplars.

## Deliverable
- All modules above implemented and integrated
- Tests passing
- Live demo on mediahub.pplx.app: upload Manchester → see generated visuals on review page → can edit text + regenerate + export
- `V8_BUILD_REPORT.md` summarising what was built, what's pending, and how the user opens/tests it
