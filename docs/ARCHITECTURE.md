# Architecture

> **In plain words:** MediaHub works like a kitchen. A results file comes in the
> door and someone reads it (**Interpreter**). The cooks spot what's special — a
> personal best, a medal (**Recognition**). The dish is plated as a picture
> (**Visual Renderer**) with a written **caption**, and it all goes out on a tray
> you can download (**Content Pack**). Each "station" below is one folder in
> `src/mediahub/`. New here? Read [`../START_HERE.md`](../START_HERE.md) and
> [`../GLOSSARY.md`](../GLOSSARY.md) first — the rest of this page is the engineer
> version.

MediaHub is a single-process Flask app organised around a **content spine** that
runs once per upload:

```
                  ┌──────────────────────────────────────────────────────────┐
 user upload ───▶ │ Interpreter ─▶ Pipeline ─▶ Recognition ─▶ Content Pack   │
                  │                                                          │
                  │                                  ├▶ Visual Renderer ─┐   │
                  │                                  ├▶ Caption (LLM)     ─┼▶ /review/<run_id>
                  │                                  └▶ Trust + PB        ─┘   │
                  └──────────────────────────────────────────────────────────┘
```

Every box is a Python package under `src/mediahub/`. Nothing else routes
through Celery, no external queue, no external store — the whole spine runs
inside one Flask request thread (or a background `threading.Thread` that
publishes JSON status to `/api/runs/<id>/status`).

## Module responsibility table

| Package | Responsibility | Entry function |
| --- | --- | --- |
| `mediahub.web` | Flask UI, upload form, review/queue pages, JSON APIs | `web.create_app()` |
| `mediahub.pipeline` | Orchestrates upload → interpreter → detectors → cards | `pipeline_v4.run_pipeline_v4()` |
| `mediahub.interpreter` | Format-agnostic ingest of HY3 / SDIF / PDF / HTML | `interpret_document()` |
| `mediahub.canonical` | Canonical SportEvent / SwimMeet schema | `canonical.swim.SwimMeet` |
| `mediahub.recognition` | Sport-agnostic detector bus + ranker | `recognition.registry.register_sport()` |
| `mediahub.recognition_swim` | Swim-specific achievement detectors | `recognition_swim.achievements.official_pb` |
| `mediahub.pb_discovery` | Web-verified PB lookup against swimmingresults.org | `pb_discovery.discover_swimmer_pbs()` |
| `mediahub.context_engine` | Identity, ontology, research, trust ledger | `context_engine.identity.discover_meet_identity()` |
| `mediahub.voice` | Learned caption voice styles | `voice.learned.render.render_caption()` |
| `mediahub.brand` | Club brand kit (colours, fonts, tone) | `brand.kit.BrandKit` |
| `mediahub.workflow` | Card status + queue persistence | `workflow.store.WorkflowStore` |
| `mediahub.graphic_renderer` | HTML/CSS templates → PNG via Playwright/WeasyPrint | `graphic_renderer.render.render_brief` |
| `mediahub.creative_brief` | LLM-driven creative direction for graphics | `creative_brief.generator.generate` |
| `mediahub.media_ai` | LLM + cutout providers (Anthropic, Replicate, PhotoRoom, rembg) | `media_ai.generate` |
| `mediahub.media_library` | User-uploaded media assets + asset tags | `media_library.store.MediaLibraryStore` |
| `mediahub.media_requirements` | Maps content-type → required media | `media_requirements.evaluator.evaluate` |
| `mediahub.content_pack` | Bundles cards + assets into a downloadable ZIP | `content_pack.builder.build_grouped_pack` |
| `mediahub.content_pack_visual` | Renders pack-level visuals | `content_pack_visual.integration` |
| `mediahub.club_platform` | High-level content-type registry (recap, spotlight, etc.) | `club_platform.content_types.REGISTRY` |
| `mediahub.venue_search` | Pool venue image search | `venue_search.search.search` |
| `mediahub.web_research` | Generic web research client (used by context_engine) | `web_research.search.WebResearcher` |
| `mediahub.inspiration` | Pattern library + exemplar analyser for content angles | `inspiration.pattern_library.PATTERNS` |
| `mediahub.history` | Swimmer historical results provider | `history.provider.HistoryProvider` |

## Data flow (one upload)

1. **POST `/upload`** receives a multipart file.
2. `pipeline_v4.run_pipeline_v4` spawns a thread, writes `runs_v4/<id>.json` with status.
3. `interpreter_bridge.interpret_to_meet` calls `interpret_document(...)` and returns a `Meet`.
4. `inference.infer_missing` fills implied event metadata.
5. `pb_bridge.build_pb_snapshots` calls `pb_discovery.discover_swimmer_pbs` for each swimmer.
6. `pipeline_v4` calls into the legacy `swim_content.detector_v3` + `swim_content_v5.recommender` (preserved verbatim) plus the new `recognition_swim.achievements.official_pb` detector.
7. Achievements feed `swim_content_v5.ranker` for scoring; the top N become cards.
8. For each card, `graphic_renderer.render_brief` produces PNGs at multiple sizes; `creative_brief.generator.generate` decides the layout/colour/copy direction; `ai_caption` writes a caption via the configured cloud LLM (Gemini or Anthropic). Without a configured provider the caption pipeline raises `ClaudeUnavailableError` so the UI surfaces an honest "AI unavailable" message rather than fabricating a templated stand-in.
9. The user lands on `/review/<run_id>` with the cards laid out + a "Download pack" button.

## Why two recognition packages?

- `recognition` is the **sport-agnostic** bus: every sport plugs in via
  `register_sport(...)` and shares the ranker, copy text, and report builder.
- `recognition_swim` is the swim-specific implementation. New sports get their
  own `recognition_<sport>` package without changing the bus.
- The legacy `swim_content_v5/achievements/` package is the V5 detector set;
  it still runs in production via `pipeline_v4`. We did not delete it because
  the trust signals it produces (e.g. `RelayMedalDetector`) have not yet been
  re-implemented in `recognition_swim`.

## Persistence

| Where | What |
| --- | --- |
| `runs_v4/<id>.json` | Per-upload pipeline state, claims, cards |
| `runs_v4/<id>/visuals/` | Rendered PNGs |
| `uploads_v4/<id>/` | The original uploaded file |
| `data/discovered/clubs/*.json` | Per-club profile snapshots from `club_discovery` |
| `data/discovered/swimmers/*.json` | PB ledger from `pb_discovery` |
| `data/voices/seed/*.json` | Hand-tuned voice profiles |
| `data/brand_kits/*.json` | User-uploaded brand kits |
| `data/secrets.json` | (Optional) user-supplied API keys; never committed |
| `data/ontology/*.json` | Course / stroke / governing-body lookup tables |
| `data/patterns.jsonl` | Learned ingest patterns from V7.5 |
| `data.db` | SQLite — only used by `media_library.store` |

## Threading model

- One Gunicorn worker, four threads: `gunicorn ... --workers 1 --threads 4`.
- Each upload runs in a `threading.Thread`; status updates write atomically to
  `runs_v4/<id>.json`.
- The browser polls `/api/runs/<id>/status` until `phase == "done"`, then redirects to `/review/<id>`.

## Where to read next

- New to the code? Start with [`UPLOAD_TO_CARDS.md`](UPLOAD_TO_CARDS.md) — it walks one request end to end.
- Adding a sport? See [`EXTENSION_GUIDE.md`](EXTENSION_GUIDE.md).
- Deploying? See [`DEPLOYMENT.md`](DEPLOYMENT.md).
