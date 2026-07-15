# System Map

ASCII diagram of how the live packages fit together.

```
 ┌────────────────────────────────────────────────────────────────────┐
 │                       mediahub.web (Flask app)                     │
 │   /upload → upload() → spawns thread → run_pipeline_v4             │
 │   /review/<id> ← reads runs_v4/<id>.json                           │
 │   /api/runs/<id>/* ← status / cards / trust / export               │
 └─────────────────────────────────┬──────────────────────────────────┘
                                   │
                     ┌─────────────▼────────────┐
                     │   mediahub.pipeline       │
                     │   pipeline_v4 + bridges   │
                     └──┬───────┬────────┬───────┘
                        │       │        │
          ┌─────────────▼─┐ ┌───▼────┐  ┌▼──────────────┐
          │ interpreter   │ │ pb_    │  │ recognition_  │
          │ (HY3/SDIF/   │  │ disc.  │  │ swim          │
          │  PDF/HTML)   │  │ +trust │  │ + V5 legacy   │
          └──────┬───────┘ └───┬────┘  └───────┬───────┘
                 │             │               │
                 └─────┐  ┌────┘     ┌─────────┘
                       ▼  ▼          ▼
                 ┌──────────────────────────┐
                 │  ranking (pipeline_v4):  │
                 │  V3 rank_cards → buckets │
                 │  V5 rank_achievements    │
                 └────────────┬─────────────┘
                              │
             ┌────────────────┼─────────────────┐
             ▼                ▼                 ▼
       creative_brief  graphic_renderer    web.ai_caption
       (LLM)           (HTML/CSS→PNG)        (LLM/fallback)
             │                │                 │
             └────────────────┴─────────────────┘
                              │
                              ▼
                       content_pack (ZIP)
```

## Sub-system dependencies

- `voice` ← used by `ai_caption`, `creative_brief`, `humanise`.
- `brand` ← used by `creative_brief`, `graphic_renderer`.
- `media_library` ← used by `creative_brief`, `graphic_renderer`.
- `media_requirements` ← used by `pipeline_v4` to validate readiness.
- `venue_search` + `web_research` ← used by `creative_brief` for hero photos.
- `context_engine` ← used by `pipeline_v4` (identity), `pb_discovery` (trust).
- `inspiration` ← used by `creative_brief` for angle selection.
- `history` ← used by V5 detectors for past-result lookups.
- `workflow` ← used by `web.web` to persist card states.
- `club_platform` ← used by `pipeline_v4` to dispatch by content type.
