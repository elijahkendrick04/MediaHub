# ADR-0031 — Carve web surfaces as add_url_rule modules, not name-prefixing Blueprints

**Status:** accepted (maintainer-directed refactor, 2026-07-14)
**Context:** deep-review finding #15 (the `create_app` closure), stage 4 of
`docs/REFACTOR_WEB_BLUEPRINTS.md`.

## Decision

The four carved route surfaces — `routes_api_runs.py` (74 routes),
`routes_organisation.py` (29), `routes_media_library.py` (32),
`routes_video.py` (19) — are self-contained modules exposing
`register(app)`, which attaches every route with
`app.add_url_rule(rule, endpoint=<original function name>, view_func=…)`.
They are **not** registered as Flask `Blueprint` objects.

## Why not a real Blueprint?

A `Blueprint` unconditionally prefixes every endpoint name
(`api_run_card` → `api_runs.api_run_card`). Endpoint names in this app are
load-bearing, measured at carve time:

- **258 literal `url_for("…")` sites** target moved endpoints from the rest
  of the monolith and its f-string templates;
- **16 dynamic `url_for(variable)` sites** build endpoint names at runtime —
  impossible to rewrite with static confidence;
- `_csrf_protect` keys the raised upload body-cap on
  `request.endpoint in ("api_video_footage_upload", "api_card_photo_upload")`;
- `_gate_until_org_ready` / `_gate_until_terms_accepted` exempt endpoints by
  name (`_SETUP_EXEMPT_ENDPOINTS`, `_TERMS_GATE_EXEMPT`) — several of the
  exempted names are organisation-surface endpoints that would silently stop
  matching, i.e. a **tenant-gate behaviour change**, exactly what this
  refactor is forbidden to cause;
- tests reference endpoint names (e.g. `test_visible_intelligence.py`).

`register(app)` with explicit `endpoint=` keeps the `url_map` — rule strings,
endpoint names, and methods — **byte-identical** to the pre-refactor app
(verified by snapshot diff), which makes the whole failure class unrepresentable.

## What the modules do adopt from the Blueprint pattern

Mirroring `api_public/blueprint.py`: one self-contained module per surface, an
explicit registration entry point called from `create_app`, handlers importable
and unit-testable without building the app. Handler bodies are the closure
originals except that web-module globals are reached as `W.<name>`
(`from mediahub.web import web as W`) — call-time resolution keeps
`importlib.reload(web)` and `mock.patch("mediahub.web.web.x")` working exactly
as the ~300 reload-based test files expect — and the captured `app` became
`current_app` (or an explicit `current_app._get_current_object()` where a
background thread needs the real object). The `@require_run` tenant guard
(finding #18, landed in parallel) moves with its handlers as
`@W.require_run` — the guard function itself is hoisted to module level by
the stage-2 spine extraction, so it resolves at routes-module import time.

## Revisit when

If a surface ever needs Blueprint-only machinery (per-surface
`before_request`, url_prefix mounting, `static_folder`), migrate that surface
to a real Blueprint **together with** a repo-wide endpoint-name rewrite and a
url_for/`request.endpoint`/gate-set audit — as its own PR.

## Completion note (2026-07-18)

Stage 5 finished the carve: the remaining 311 routes moved into seven more
`add_url_rule` surface modules (`routes_auth`, `routes_site`, `routes_review`,
`routes_planner`, `routes_creative`, `routes_api_misc`, `routes_operator`)
under this ADR's pattern — original endpoint names, `W.<name>` call-time
references, `current_app` for the captured `app`. All 464 routes now live in
eleven surface modules; `create_app` is wiring only. The url_map snapshot
(rules, endpoint names, methods) stayed byte-identical at every step.
