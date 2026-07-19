# System Flow

A trace of one upload, with code references. Read alongside
[`ARCHITECTURE.md`](ARCHITECTURE.md).

## 1. Upload received

`POST /upload` — handled in `mediahub/web/web.py::upload_post`.

The route saves the file under `uploads_v4/<run_id>/`, allocates a run id,
writes a stub `runs_v4/<run_id>.json` with `phase = "queued"`, and starts a
background thread.

## 2. Pipeline thread

`mediahub/pipeline/pipeline_v4.py::run_pipeline_v4` is the orchestrator:

```python
def run_pipeline_v4(run_id, upload_path, ...):
    set_phase("interpreting")
    meet = interpret_to_meet(upload_path)        # interpreter_bridge
    infer_missing(meet)                          # mediahub.web.inference
    set_phase("pb_discovery")
    pb_snapshots = build_pb_snapshots(meet)      # pb_bridge → pb_discovery
    set_phase("detecting")
    parsed_v3 = canonical_to_v3(meet)            # mediahub.web.v3_shim
    claims = detect_v3(parsed_v3, ...)           # legacy swim_content.detector_v3
    cards = group_claims_into_cards(claims)
    cards = rank_cards(cards, ...)               # legacy swim_content.ranker_v3
    set_phase("rendering")
    for card in top_cards(cards):
        render_one_card(card, run_id)
    set_phase("done")
```

Each phase update writes the JSON status atomically so the browser poll picks
up the change.

## 3. Interpreter

`mediahub/interpreter/__init__.py::interpret_document` does:

1. Format detection — `hytek_parser.detect_hy3`, `sdif_parser.detect_sdif`,
   else fall through to `pdf_extractor` or `ingest.ingest` (HTML).
2. Pattern application — `patterns.PatternStore` matches known table layouts
   from `data/patterns.jsonl`.
3. Schema induction — `schema_induce.induce_schema` proposes column meanings
   when patterns don't fully match.
4. Event induction — `events_induce.induce_events` groups rows into events.
5. Returns an `InterpretedMeet`.

`mediahub/pipeline/interpreter_bridge.py` translates `InterpretedMeet` into the
`Meet` schema used downstream (see `mediahub.web.canonical.Meet`).

## 4. Recognition (detector bus)

The detector bus has two parts:

- **Live detector** in `recognition_swim.achievements.official_pb` — the only
  detector that uses verified PB data from `pb_discovery`.
- **Legacy V5 detectors** in `legacy/swim_content_v5/achievements/` (PB,
  barrier, qualifier, medal_final, return_to_form, standout_field,
  standout_history, relay) — preserved verbatim and still in active use.

Both are invoked by `pipeline_v4`. New detectors should be added under
`recognition_swim/achievements/` and registered via
`recognition.registry.register_sport(...)` (see [`DETECTOR_BUS.md`](DETECTOR_BUS.md)).

## 5. PB verification

`pb_discovery.discover_swimmer_pbs(swimmer)`:

1. Looks up `data/discovered/swimmers/<key>.json` (cache).
2. If stale or missing: fetches the swimmer's profile page from
   swimmingresults.org, parses with `parse_pbs.parse_pbs_from_page`.
3. Records each fetch attempt in `data/discovered/search_cache/` for the trust ledger.
4. Compares each result-row time against the known PB and stamps the swim
   with `pb_status ∈ {NEW_PB, LIKELY_PB, NOT_PB, UNKNOWN}` based on the
   confidence rules in [`PB_VERIFICATION.md`](PB_VERIFICATION.md).

## 6. Cards + visual rendering

`graphic_renderer.render.render_brief(brief)`:

1. Picks the layout HTML from `mediahub/graphic_renderer/layouts/` based on
   the brief's `template_id` (e.g. `individual_hero`, `medal_card`,
   `weekend_numbers`).
2. Renders the Jinja template with the brief's payload.
3. Rasterises HTML → PNG via Playwright (Chromium installed in the deployed
   container).
4. Generates each requested format size from `FORMAT_SIZES`. The default render
   is the square/portrait/story trio (1080×1080, 1080×1350, 1080×1920);
   landscape & extended aspect ratios (16:9 1920×1080, 3:2 1620×1080, 4:3
   1440×1080) are opt-in — requested explicitly — and carry per-format
   composition rules (`render.py`: `_format_aspect` / `_scale_for_format` /
   `_v2_fit_boxes` / `_format_composition_css`).

`creative_brief.generator.generate(card, club_profile)` decides:
- Which template to use
- Which palette colour
- Which hero photo to fetch (via `media_library.selector`)
- What headline to write

`creative_brief` calls the configured cloud LLM (Gemini or Claude) for
vision-aware direction. Without a configured provider it surfaces
`ClaudeUnavailableError` so the operator knows an LLM key is missing.

## 7. Caption generation

For each card `mediahub.web.ai_caption.generate_caption_for_card(card)`:

- Builds the system prompt + user message and calls the cloud LLM via
  `media_ai.llm.generate`. The voice style is selected from the active
  brand kit's `voice_id`.
- Raises `ClaudeUnavailableError` when no provider is configured — the UI
  surfaces an "AI unavailable; contact your administrator" message rather
  than fabricating a templated caption.

See [`PROMPT_INVENTORY.md`](PROMPT_INVENTORY.md) for the actual prompts.

## 8. Review page

`GET /review/<run_id>` — renders all cards in a grid with:
- Image preview
- Caption editor (POST `/api/runs/<run_id>/cards/<card_id>` to edit)
- "Download pack" button → `GET /api/runs/<run_id>/export` returns a ZIP.

## 9. Persistence

- `runs_v4/<id>.json` is the single source of truth for one upload.
- Cards live inside the run JSON; assets in `runs_v4/<id>/visuals/`.
- A nightly maintenance script (not yet shipped) is intended to GC runs
  older than 90 days.
