# Technical Debt

## Legacy that still runs in production

These packages live in `legacy/` and are imported by `pipeline_v4`:

| Package | What it does | Why it's still here | Plan |
| --- | --- | --- | --- |
| `swim_content` | V3 detectors, captions, grouper, ranker | The V5/V8 detector suite hasn't fully replaced V3 grouping/captions | Migrate `grouper.py` + `ranker_v3.py` into `mediahub.recognition` then delete |
| `swim_content_v5` | V5 achievement detectors (PB, qualifier, medal, etc.) | Active. The swim detector suite. | Move to `mediahub.recognition_swim.achievements/` and rewire |
| `swim_content_pb` | First-gen PB engine | Superseded by `mediahub.pb_discovery` | Delete after one production cycle without imports |
| `engine_v4` | V4-era pre-cursor of `pipeline_v4` | Reference for diff'ing decisions; not imported live | Delete |

## Dual canonical schema

`mediahub.canonical` (sport-agnostic SportEvent / SwimMeet) coexists with
`mediahub.web.canonical` (the V4 `Meet` dataclass). Both are alive because
`pipeline_v4` consumes the V4 `Meet` shape and downstream code converts.
Plan: pick one, write a 1-pass converter, delete the other.

## sys.path hack for legacy/

`mediahub/__init__.py` appends `legacy/` to `sys.path` so historical packages
keep importing. This is fine but means every `import` of those packages bypasses
the package boundary check. Moving them under `mediahub.legacy.*` would be
cleaner — the only blocker is the volume of internal `swim_content.foo` imports
inside `legacy/swim_content` itself which we agreed not to rewrite.

## Tests reference both layouts

`test_no_hardcode_in_live_paths.py` walks paths that include both old top-level
`voice/` and new `src/mediahub/voice/`. The test passes either way but the
double-walk is wasted work.

## Scattered cwd-relative paths

Several modules used `Path(__file__).parent.parent / "data"` to find the
`data/` dir, which only works when files sat at the workspace root. We patched
`interpreter.ontology_loader`, `interpreter.patterns`, and
`voice.learned.store` to also check the V9 path; the rest still uses cwd.
Audit is in `docs/AUDIT_REPORTS.md`.

## Single SQLite file for media library

`media_library/store.py` writes to `data.db`. The path is hardcoded relative
to the package. For multi-tenant deployments this needs to be per-club.

## No structured logging

The app uses `logging.basicConfig`. Operational tracing across the pipeline
phases would benefit from JSON logs with `run_id` correlation.

## No type hints in legacy/

Legacy packages have partial type hints. The new packages are 80% typed but
not enforced with mypy in CI.

## Tests don't exercise renderer cold path

`test_v8_graphic_renderer.py` patches Playwright. We don't have a slow CI
job that runs the actual rasterisation — production regressions in the
renderer aren't caught until manual review.
