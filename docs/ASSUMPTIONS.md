# Assumptions

Explicit list of things this codebase assumes, so future maintainers don't
discover them by surprise.

## Deployment

- **One Gunicorn worker.** `runs_v4/<id>.json` is read/written by a Python
  thread; multi-worker requires a shared lock or a queue. The Procfile uses
  `--workers 1 --threads 4`.
- **Persistent disk for `data/` and `runs_v4/`.** Ephemeral storage is fine for
  a demo but loses the PB cache and uploaded brand kits between restarts.
- **Outbound HTTPS** is required for `swimmingresults.org`,
  `api.anthropic.com`, `api.replicate.com`, and `api.photoroom.com`.

## Data

- **HY3 files are well-formed.** The parser does not handle truncated streams.
- **PDF tables have horizontal rule separators** (Hy-Tek default). Custom
  reports without rule lines parse degrade by falling back to whitespace
  inference.
- **Swimmers have unique `(name, dob)` tuples.** The PB cache key collides
  otherwise.
- **Times are in `MM:SS.SS` format.** Other formats are normalised by the
  interpreter but the V3 ranker still expects this canonical form.

## Sport scope

- **Single sport: swimming.** `recognition_<sport>/` is the seam, but no
  other sport ships in this build.
- **Pool meets only.** Open-water support is V8.3.

## Identity

- **swimmingresults.org public profiles are open.** No login flow.
- **Club identity via discovered name match** — `data/discovered/clubs/` is
  built from observed names, not from a closed list. New clubs auto-create.

## Visuals

- **Brand kits supply ≥ 3 colours.** Renderer falls back to defaults if not.
- **Hero photos exist in `media_library` for the swimmer or generic placeholders are acceptable.**
- **All cards render at 1080-px-wide formats.** Larger sizes are out of scope.

## LLM

- **At least one cloud LLM provider key is required.** The operator must
  configure `GEMINI_API_KEY` and/or `ANTHROPIC_API_KEY` on the deployment.
  Without a configured provider, AI-driven surfaces (captioning, brand
  interpretation, creative direction) raise a clear "AI unavailable" error
  rather than silently degrading to local heuristic output.
- **Claude Sonnet 4.6 is the production-preferred Anthropic model.** Override
  via `MEDIAHUB_LLM_MODEL`. Gemini 2.5 Flash is the default free-tier model.

## Concurrency

- **Two simultaneous uploads from the same browser are fine.** They get
  separate run ids and separate threads.
- **Concurrent edits to one card** — last write wins. No optimistic locking.

## Privacy

- **No PII is sent to LLMs by default.** The caption prompt redacts swimmer
  DOBs and uses public name + event + time only.
- **Data retention is the operator's responsibility.** `/privacy/run/<id>/delete`
  is provided for manual erase.
