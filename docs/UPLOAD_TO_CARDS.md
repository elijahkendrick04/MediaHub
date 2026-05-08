# Upload → Cards: an end-to-end trace

A 60-second walkthrough of what happens between `POST /upload` and a card
appearing on `/review/<run_id>`.

## 0. The user clicks "Upload"

Browser sends `POST /upload` with `multipart/form-data`:
- `file` — the results blob
- `club_id` — selected from the home page dropdown (or `"auto"`)

## 1. `mediahub.web.web::upload_post`

```python
@app.route("/upload", methods=["POST"])
def upload_post():
    f = request.files["file"]
    run_id = uuid.uuid4().hex
    upload_dir = UPLOADS_ROOT / run_id
    upload_dir.mkdir(parents=True)
    saved = upload_dir / f.filename
    f.save(saved)
    write_run_status(run_id, phase="queued", ...)
    threading.Thread(target=run_pipeline_v4,
                     args=(run_id, saved, club_id),
                     daemon=True).start()
    return redirect(f"/runs/{run_id}")
```

The browser is sent to `/runs/<run_id>` which is a poller page.

## 2. Polling

`GET /api/runs/<run_id>/status` returns `{"phase": "...", "progress": 0.4}`.
The poller redirects to `/review/<run_id>` once `phase == "done"`.

## 3. `run_pipeline_v4` thread

Phases written to the status JSON in order:

| Phase | What happens | Module |
| --- | --- | --- |
| `interpreting` | format detected, schema induced | `interpreter` |
| `inferring` | implied event metadata filled | `mediahub.web.inference` |
| `pb_discovery` | swimmer profiles fetched | `pb_discovery` |
| `detecting` | V3 + V5 + V8 detectors run | `swim_content.detector_v3`, `swim_content_v5.achievements`, `recognition_swim.achievements.official_pb` |
| `grouping` | claims clustered into cards | `swim_content.grouper` |
| `ranking` | cards scored and sorted | `swim_content_v5.ranker` |
| `briefing` | creative briefs written per card | `creative_brief.generator` |
| `rendering` | PNGs rendered per format | `graphic_renderer.render` |
| `captioning` | captions written | `mediahub.web.ai_caption` |
| `done` | final JSON written | — |

## 4. `/review/<run_id>` (GET)

`mediahub.web.web::review` reads the run JSON and renders a Jinja template
with one `<article>` per card. Each card has:

- The hero PNG (1:1 by default; 4:5 and 9:16 selectable in the inspector)
- An editable caption textarea
- The detector trace (collapsible "Why this card?" panel)
- A "Replace photo" button → opens `/api/media_library` modal

## 5. `/api/runs/<run_id>/export` (GET)

Returns a ZIP:

```
mediahub_pack_<run_id>.zip
├── card_001/
│   ├── 1080x1080.png
│   ├── 1080x1350.png
│   ├── 1080x1920.png
│   └── caption.txt
├── card_002/
│   └── ...
└── manifest.json
```

`manifest.json` describes each card's content type, swimmer(s), event, and
voice id.

## Code map

| Step | File | Function |
| --- | --- | --- |
| Upload | `src/mediahub/web/web.py` | `upload_post` |
| Pipeline orchestrator | `src/mediahub/pipeline/pipeline_v4.py` | `run_pipeline_v4` |
| Format detection | `src/mediahub/interpreter/__init__.py` | `interpret_document` |
| HY3 parser | `src/mediahub/interpreter/hytek_parser.py` | `parse_hy3` |
| SDIF parser | `src/mediahub/interpreter/sdif_parser.py` | `parse_sdif` |
| PDF parser | `src/mediahub/interpreter/pdf_extractor.py` | `extract_text` |
| HTML parser | `src/mediahub/interpreter/ingest.py` | `ingest` |
| Schema inducer | `src/mediahub/interpreter/schema_induce.py` | `induce_schema` |
| Event inducer | `src/mediahub/interpreter/events_induce.py` | `induce_events` |
| Canonical bridge | `src/mediahub/pipeline/interpreter_bridge.py` | `interpret_to_meet` |
| PB lookup | `src/mediahub/pb_discovery/discover.py` | `discover_swimmer_pbs` |
| Detector (V8) | `src/mediahub/recognition_swim/achievements/official_pb.py` | `OfficialPBDetector.detect` |
| Detectors (V5) | `legacy/swim_content_v5/achievements/*.py` | `*Detector.detect` |
| Grouping | `legacy/swim_content/grouper.py` | `group_claims_into_cards` |
| Ranking | `legacy/swim_content_v5/ranker.py` | `rank_achievements` |
| Brief | `src/mediahub/creative_brief/generator.py` | `generate` |
| Renderer | `src/mediahub/graphic_renderer/render.py` | `render_brief` |
| Caption (AI) | `src/mediahub/web/ai_caption.py` | `generate_caption_for_card` |
| Caption (fallback) | `src/mediahub/web/humanise.py` | `humanise` |
| Review page | `src/mediahub/web/web.py` | `review` |
| ZIP export | `src/mediahub/web/web.py` | `export_run` |
