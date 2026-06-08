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

## `web/web.py` is a 22,500-line monolith (114 routes)

Every route, every f-string Jinja template, and most request glue live in one
file. It still works and the CLAUDE.md conventions keep it coherent, but it is
the single biggest maintainability and merge-conflict risk in the repo, and the
hardest file to review. **Plan (incremental, gated):** peel cohesive surfaces
into Flask **Blueprints** one at a time — `privacy`, `media-library`,
`organisation/brand`, the motion/reel API, the research console — each behind
the CLAUDE.md 15-step route-removal/replacement checklist so persisted state,
`url_for()` targets, and templates don't break. Do **not** attempt a big-bang
split; one Blueprint per PR, suite green between each. No behaviour change —
pure relocation. (Tracked here rather than done in one pass precisely because a
rushed carve-up of this file is higher-risk than the debt it pays down.)

## Mixed persistence: JSONL ledgers + a shared SQLite `data.db`

Some modules persist to a shared SQLite `data.db` (`workflow/schedule.py`,
`memory/store.py`, `observability/`, `publishing/posting_log.py`,
`media_library/store.py`, the run-metadata table), while others still use JSONL
ledgers (`context_engine/trust.py`, `brand/playbooks.py`, `workflow/autonomy.py`,
`interpreter/patterns.py`) and run *snapshots* are per-run JSON files under
`DATA_DIR/runs_v4/`. The split is historical, not principled. **Plan:** treat
`data.db` as the system-of-record for cross-worker/queryable state and keep JSON
only for large immutable run snapshots; migrate the JSONL ledgers that need
cross-worker consistency (trust, audit) into `data.db` tables. Decide
per-ledger; don't migrate the append-only audit logs casually.

## Two `AutonomyLevel` enums with different semantics

`sport_profiles/autonomy.py` defines a *publishing-policy* enum
(`draft_only`/`approval_required`/`fully_autonomous`, inert) while
`autonomy/tools.py` defines a *runner-reach* `IntEnum`
(`OFF`/`SUGGEST`/`DRAFT`/`PREPARE`, live). They describe different axes and must
not be collapsed blindly, but having two types named `AutonomyLevel` invites
confusion. **Plan:** when Phase 2's per-type toggle is built, rename one (e.g.
the runner's to `RunnerReach`) and make the sport-profile policy the single
public "how autonomous is this post type" type.

## Auto-generated inventories had rotted (partially resolved)

`scripts/build_inventories.py` hard-coded `ROOT` to the one-off V9 export path,
so none of the `docs/*_INVENTORY.md` files could be regenerated in the repo and
they drifted stale (ENV_INVENTORY listed 16 of 64 vars). **Resolved** for the
generator (ROOT now derives from `__file__`; the env regex catches indirect
`get_secret()` keys) and for `ENV_INVENTORY.md`. **Remaining:** the other
inventories (`ROUTE_`, `API_`, `DEPENDENCY_`, `DETECTOR_`, `INVENTORY.md`) are
now regenerable but were not refreshed in that pass to keep the diff focused —
run `python scripts/build_inventories.py` to bring them current (note
`INVENTORY.md` includes byte sizes and will churn).
