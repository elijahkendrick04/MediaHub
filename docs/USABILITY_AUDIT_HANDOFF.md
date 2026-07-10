# Usability audit — session hand-off

**Purpose.** Everything the next engineering session needs to pick up the
`docs/USABILITY_AUDIT.md` work list and keep going. Read this first, then the
status matrix at the top of `USABILITY_AUDIT.md`.

## Where things stand

- **86 of 161 findings shipped** (+ I-4 assessed N/A). See the per-theme matrix
  in `docs/USABILITY_AUDIT.md` ("Implementation status").
- **PR #1082** (merged) and **PR #1085** (merged) delivered the first 70.
- **PR #1093** delivered the latest **16** (this batch): E-4, G-12, B-6, J-2,
  H-4, H-3, E-1, C-16, G-3, C-1, C-2, C-8, C-13, C-18, C-14, C-9. All CI green,
  adversarially reviewed. When you start, check whether #1093 has merged:
  - **If merged**: start a *fresh* branch from the latest `main`
    (`git fetch origin main && git checkout -B <new-branch> origin/main`). Do
    **not** reuse a merged branch or stack on merged history.
  - **If still open**: continue on `claude/mediahub-usability-audit-87k07l`.

## How to work each finding (the rhythm that's been working)

For **every** finding, in order:

1. **8-step plan** from the audit block (pin target, replacement, callers,
   routes/links, templates, JS callers, persistence, flags/AI/engine/tests).
2. **Grep all callers** — the audit's `file:line` refs drift; re-grep for the
   exact symbol/route/string in the current tree before editing.
3. **Implement** in `src/mediahub/web/web.py` (the ~62k-line Flask monolith of
   f-string Jinja templates) or the relevant module.
4. **Dedicated regression test** — `tests/test_usability_<id>_<slug>.py`. Follow
   the existing ones: `importlib.reload(cp); importlib.reload(wm)` fixture,
   `DATA_DIR`/`RUNS_DIR`/`SWIM_CONTENT_PROFILES_DIR` env, pin
   `s["active_profile_id"]`. Media-library tests set
   `_mlstore._default_store` and `pytest.skip` when `not wm._v8_ok`.
5. **Per-finding commit** — one finding per commit, message ends with the
   finding id, e.g. `feat(media): … (H-4)`.
6. **Targeted regression** — run the touched-area tests (`pytest -k`), not the
   whole suite (see gotcha below).
7. **Update `docs/USABILITY_AUDIT.md`** matrix counts + remaining lists.

## Hard-won gotchas (don't relearn these)

- **ruff must be 0.8.4, and it is NOT the `ruff` on PATH.** The PATH `ruff` is
  0.15.8 and formats differently → CI "Hygiene hooks (pre-commit)" fails.
  Before committing any `.py`: `python -m ruff format src/mediahub/web/web.py`
  then `python -m ruff check src/mediahub/web/web.py` — `python -m ruff` is the
  pinned 0.8.4 (installed via `pip install ruff==0.8.4`). `.pre-commit-config.yaml`
  pins `rev: v0.8.4`.
- **The full local suite is >30 min** (it timed out at 1800 s). Don't run
  `pytest tests/` whole; run targeted `-k` batches and let CI's 4 shards do the
  full run. CI is the authoritative gate.
- **f-strings can't contain a backslash in the `{...}` expression** — compute
  any string with an escape into a local var first (bit me on a `<option>`
  fallback).
- **Page-wide chrome changes trip content-assertion tests.** The C-16 footer
  `<select … selected>` matched a test's broad `" selected>" not in body` scan;
  a nav change can shift `<option>`/`<select>` counts. After a chrome change,
  grep tests for broad structural assertions and run the responsive/nav/review
  suites.
- **Reading a failed CI test name**: a failing page-render test dumps the whole
  HTML page, burying the `tests/…::test_…` header thousands of lines up. Use
  `mcp__github__get_job_logs` with a large `tail_lines`; it saves oversized
  output to a file — `grep -oaE "tests/[A-Za-z0-9_/]+\.py::[A-Za-z0-9_:.]+"` that
  file for the id.
- **Tenant isolation on any new per-asset/per-run endpoint** — gate with
  `_session_can_access_profile(asset.profile_id)` (media) or
  `_can_access_run(...)`; mirror the H-3/H-4 endpoints. Never echo
  `request.path`/args into a rendered page (a path segment can be a swimmer
  name — the C-16 cross-tenant leak). Use the `Referer` for return-to, validated
  same-origin (reject `//host` and `/\host`).
- **All interpolated data through `_h()`**; `_h` is quote-safe for
  double-quoted attributes (used for `data-*` metadata attrs).
- **CSRF**: rendered POST forms get an auto-injected hidden `csrf_token` (a
  response post-processor). JSON `fetch` is content-type-exempt; explicit
  `X-CSRF-Token` header is used by the JS helpers. `sendBeacon` carries the
  token in its `FormData`.
- **Deterministic-engine boundary is off-limits** (parsers/detectors/ranker/
  colour-science). The "Ground-truth oracle" CI gate enforces it.

## Dev setup (fresh container)

```bash
pip install -e ".[dev]" --ignore-installed PyYAML   # PyYAML is a debian pkg; --ignore-installed avoids the RECORD error
pip install ruff==0.8.4                              # for the hygiene check (python -m ruff)
python -m pytest tests/test_usability_e4_remote_end_guard.py -q   # smoke
```

No LLM key in the sandbox → AI surfaces honest-error (`ClaudeUnavailableError`);
that's expected. `_v8_ok` gates the media engine — media-library tests skip if
it's off (it was on here).

## Pre-merge adversarial review (do this before leaving draft)

The last two batches ran a multi-agent review and it caught real bugs each time.
Recreate it with the `Workflow` tool (5 read-only reviewer dimensions →
adversarial verify): JS correctness, security (XSS/CSRF/IDOR/open-redirect),
IA-change regression, server correctness, test quality. Write the branch diff to
a file first (`git diff origin/main...HEAD > …/branch.diff`) and point the agents
at it + the source. Fix only CONFIRMED findings; add a regression test for each.

## Remaining work — prioritized

**Highest-severity-first. The two large highs are next:**

- **J-1** (`high`/large) — Video Studio render/clip/stabilise endpoints run
  synchronously and block the request (proxies kill 30–90 s holds). Convert them
  to the disk-backed job + poll pattern the reel/motion routes already use
  (`_variant_job_save` + `api_reel_job_status` + `MH.renderProgress`): POST
  returns 202 `{job_id, poll_url}`, the tile shows the branded progress panel,
  completion flips to the preview. J-2 already made the failure paths graceful,
  so this is the throughput half. Files: `web.py` ~`56036` (`render_edl`),
  ~`12245`/`12153` (JS), ~`55764` (stabilise).
- **H-5** (`high`/large) — newsletters/documents can only be edited via a
  raw-JSON `<textarea>`. Ship a minimal structured editor (per-section
  title/intro/link fields generated from the spec schema) keeping the JSON
  textarea as the "advanced" escape hatch. Start with newsletters/documents
  (`web.py` ~`59249`/`59651`).

**Then the medium quick-win tail** (each small, contained, low-risk):
D-10 (Documents/Newsletters `alert()`→toast + busy-state + AI-draft checkbox),
H-19 (disable "Make clip" during the run), H-21 (board Idea "Add" button),
H-22 (remote-code length check before submit), H-23 (disable "Build spotlight"
when 0 approved), G-13 (audience autoplay 6s→`state.autoplay_seconds`),
G-15 (demo: one CTA when signed in), J-5/J-7/J-10/J-13 (dead-end fixes),
E-6/E-7 (merge-athletes / consent-enforcement confirms + impact preview).

**Larger / owner-facing (ask via `AskUserQuestion` before building):**
B-1..B-8 (step reduction), C-19 (Settings grouping), G-9 (two consent stores —
consolidation), J-9 (publish-vocab unification), the D planner-reactivity tail
(D-26), G-3-adjacent brand cleanup (G-5 dead voice UI, D-15 unsaved-analysis
loss).

## Owner decisions already on record (apply without re-asking)

- Customer vocabulary for a "run" = **"Results"** (not "meet" everywhere —
  confirm per-surface).
- The Developer/operator sign-in link belongs on **`/login` only** (not the
  footer of customer pages).
- Nav: **replace Elements with Activity** (done).
- Collections: **finish it** (done). Sticker/mockup: **wire a picker** (done).
- Brand home: **`/organisation/setup` is canonical** (done); `/brand` keeps
  kit/governance; legacy `/organisation` demoted with a banner (kept reachable
  for org-delete + voice).

For any *new* nav-placement or orphaned-page (finish-vs-remove) decision, ask
the owner — don't guess.
