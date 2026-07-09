# Usability audit — session hand-off

**Purpose.** Everything the next engineering session needs to pick up the
`docs/USABILITY_AUDIT.md` work list and keep going. Read this first, then the
"Implementation status" matrix at the top of `USABILITY_AUDIT.md`. When you've
absorbed it, **delete this file** (it's superseded the moment you start).

---

## Where things stand

- **105 of 161 findings shipped** (+ I-4 assessed N/A). Per-theme matrix is in
  `docs/USABILITY_AUDIT.md`.
- **Both large high-severity items are done**: **J-1** (Video Studio async jobs)
  and **H-5** (structured spec editor).
- **PRs**: #1082 (merged, 23), #1085 (merged, 47), #1093 (merged, 16), and the
  latest batch of **19** landed via **PR #1097** (merge this into the count when
  you check — it may already be merged).
- **When you start**: check whether the latest PR merged.
  - **If merged**: start a *fresh* branch from latest `main`
    (`git fetch origin main && git checkout -B <new-branch> origin/main`). Do
    **not** reuse a merged branch or stack on merged history.
  - **If still open**: continue on that branch.

### What the latest batch (PR #1097) shipped — 19 findings
- **Quick-win tail (12)**: D-10, E-6, E-7, G-13, G-15, H-21, H-22, H-23, J-5,
  J-7, J-10, J-13.
- **J-1 (large high) + H-19**: Video Studio render / make-clip / direct-reel /
  stabilise converted to disk-backed background jobs (see "Reusable
  infrastructure" below). Adversarially reviewed; 3 confirmed JS findings fixed.
- **H-5 (large high)**: structured content editor for microsites / newsletters /
  documents (new module `src/mediahub/web/spec_editor.py`).
- **Contained tail**: J-12, H-8, E-8, J-11.
- Also removed the previous hand-off doc; updated tests that pinned
  intentionally-changed behaviour (J-2, u6, i5) **preserving intent**.

---

## How to work each finding (the rhythm that works)

For **every** finding, in order:

1. **8-step plan** from the audit block: (1) pin the exact target route/symbol/
   data-structure, (2) define the replacement + new shape, (3) grep all callers,
   (4) routes & `url_for` links, (5) f-string Jinja templates, (6) JS/fetch
   callers, (7) `DATA_DIR` persistence, (8) feature-flags / AI-surfaces /
   deterministic-engine / tests.
2. **Grep all callers** — the audit's `file:line` refs drift; re-grep for the
   exact symbol/route/string in the current tree before editing.
3. **Implement** in `src/mediahub/web/web.py` (the ~63k-line Flask monolith of
   f-string Jinja templates) or the relevant module.
4. **Import the app after every edit** — `python -c "import mediahub.web.web as
   w; w.create_app()"` — to catch f-string/syntax errors immediately.
5. **Dedicated regression test** — `tests/test_usability_<id>_<slug>.py`.
6. **Per-finding commit** — one finding per commit, id in the subject, e.g.
   `feat(video): … (J-1 pt.1)`. (Two tiny related findings can share a commit —
   name both ids, e.g. `(J-12, H-8)`.)
7. **Targeted regression** — run the touched-area tests (`pytest <files>`), not
   the whole suite (see gotcha). Let CI's 4 shards be the full gate.
8. **Update `docs/USABILITY_AUDIT.md`** — mark the block `✅ DONE (PR #…)`, bump
   the matrix counts + remaining lists.

### Pre-merge adversarial review (do this before landing a large/risky batch)
Spawn read-only reviewer subagents (via the `Agent` tool, or the `Workflow` tool
if the user opts into "ultracode") across independent dimensions —
**concurrency/threading, security (XSS/CSRF/IDOR/open-redirect), server
correctness, JS correctness** — then adversarially *verify* each finding before
acting. This caught 4 real bugs on the #1093 batch and 3 on J-1. Write the branch
diff to a file first (`git diff origin/main...HEAD -- src/ > /tmp/…/branch.diff`)
and point the agents at it + the source. Fix only CONFIRMED findings; add a
regression test for each.

---

## Hard-won gotchas (don't relearn these)

- **ruff must be 0.8.4, and it is NOT the `ruff` on PATH.** The PATH `ruff` is
  newer and formats differently → CI "Hygiene hooks (pre-commit)" fails. Install
  `pip install ruff==0.8.4` and always use `python -m ruff format …` then
  `python -m ruff check …` (that's the pinned 0.8.4). `.pre-commit-config.yaml`
  pins `rev: v0.8.4` and scopes ruff to `src/mediahub/` only (tests aren't
  ruff-formatted, but keep them clean anyway).
- **`test_theme_tokens` caps inline hardcoded hex at 20.** Adding a `#rrggbb` in
  a `web.py` inline style/JS trips it. Use a CSS var — `var(--bad)` (danger,
  = `var(--mh-error)`), `var(--warn)`, `var(--lane)`, etc. — never a hex
  fallback like `var(--danger,#c0392b)`. (This bit me on a "danger" button.)
- **f-string vs `.replace()` templates — check before you edit.** Much of the JS
  in `web.py` lives in f-strings, where every literal `{`/`}` must be doubled
  `{{ }}`. But some big JS blocks (e.g. the **Video Studio** IIFE, the service
  worker) are *plain/raw strings* filled by `.replace("__TOKEN__", …)` — there,
  single braces are literal and you must NOT double them. Tell them apart: a
  `.replace()`-template uses `__UPPER_TOKENS__`; an f-string uses `{expr}`.
- **`_h()` HTML-escapes apostrophes to `&#39;`.** A test asserting the literal
  `"wasn't saved"` fails because the DOM has `wasn&#39;t saved`. Assert
  escape-free fragments, or write copy without apostrophes.
- **CSRF**: rendered POST forms get an auto-injected hidden `csrf_token`
  (response post-processor). JSON `fetch` is content-type-exempt; JS helpers set
  an explicit `X-CSRF-Token`. In TESTING mode CSRF is off, so `client.post(...,
  data=…)` works without a token. The H-5 `content-edit` routes read
  `request.form` (a plain server POST) — distinct from the JSON-hatch save routes
  that read `request.get_json`; do not conflate them.
- **Order-dependent shard flakes.** Heavy new tests shift the `pytest-split`
  partition, so a latent test-isolation bug elsewhere can surface in a shard even
  though it passes in isolation. To reproduce CI exactly:
  `python -m pytest tests/ --ignore-glob='tests/test_autotest_*.py' --splits 4
  --group <N> --durations-path .test_durations -q -p no:randomly` (add `-x` to
  stop at the first failure, drop it to see them all). **Fix for the class**:
  never write test fixtures to a hardcoded path like `tmp_path/"runs_v4"` — use
  the module global (`wm.RUNS_DIR`) so the write and the read agree regardless of
  what a prior test left in the env.
- **Don't run the full suite locally** (>30 min; times out). Run targeted files;
  reproduce a specific shard when chasing a CI failure. CI's 4 shards + full-suite
  job are the authoritative gate.
- **Reading a CI failure when the GitHub MCP is down** (it dropped repeatedly
  this session): you can't `get_job_logs`. Reproduce the failing shard locally
  (command above) with `-x --tb=short` to get the exact failing test, then bisect
  (`pytest <suspect_file> <failing_file> -p no:randomly`).
- **Commits show "Unverified" on GitHub** — this sandbox has only the *public*
  SSH signing key, so commits can't be signed. Cosmetic; committer email is
  already `noreply@anthropic.com`; doesn't block CI or merge. Nothing to fix.
- **Tenant isolation on any new per-run/per-asset/per-org endpoint** — gate with
  `_can_access_run` / `_video_can_access_project` / `_nl_load_owned` /
  `_doc_load_owned` / `load_site(pid, …)` and confirm a foreign-org request 404s.
- **Honest-error rule**: AI/engine surfaces must surface the real error
  (`ClaudeUnavailableError`, `ProviderNotConfigured`, `ProbeUnavailable`,
  `VideoEngineUnavailable`), never a fabricated caption/graphic/clip. No
  regex/template heuristic fallbacks.
- **Deterministic-engine boundary is off-limits** (parsers/detectors/ranker/
  colour-science). The "Ground-truth oracle" CI gate enforces it.

---

## Reusable infrastructure built this session (use it — don't reinvent)

### 1. Background job + poll pattern (for any long-running endpoint)
The Video Studio (J-1) now uses the same disk-backed job store as the reel/motion
routes. Reuse it for **any** endpoint that can take >~10s (proxies kill long
synchronous holds):
- Store: `_variant_job_save` / `_variant_job_load` / `_variant_jobs_gc` /
  `_job_heartbeat` (files under `DATA_DIR/_variant_jobs`, single-writer =
  the worker thread; `job_id` must be `uuid4().hex`).
- Route: run fail-fast gates (tenant/consent/engine) **synchronously**, build the
  `job` dict, `_variant_jobs_gc()` + `_variant_job_save(job)`, spawn a daemon
  `_worker` thread, return `202 {ok, job_id, poll_url: url_for("api_reel_job_status", job_id)}`.
- Poll route: **`api_reel_job_status`** is shared — add your `kind` to its
  allowlist tuple, and (if you need extra fields) extend its payload the way the
  `project_id`/`project`/`total` blocks do. Status vocabulary is strictly
  `{running, done, error}` (distinct from any domain status enum).
- Worker: wrap heavy work in `with _job_heartbeat(job):` (else a >5-min job is
  falsely reported `job_lost`); acquire `_render_slot("…", key, timeout=_RENDER_TRY_TIMEOUT)`
  for render-engine-bound work; on every branch (`_RenderBusy`, engine-unavailable,
  `Exception`) set `job["status"]="error"` + a plain `user_message` and
  `_variant_job_save(job)`. Capture everything (owner_pid, ids, paths) at enqueue
  — the worker has **no request context** (`_active_profile_id()` returns nothing).
- Client: copy `generateReel` / `generateMotion` (canonical 202→poll idiom) or
  the new **`runVideoJob`** helper — mount `MH.renderProgress` on a dedicated
  empty child (it replaces `innerHTML`), keep the outer POST `.catch` fatal and
  the inner poll `.catch` a retry, restore the button on every terminal path, and
  clear the panel on completion.
- Reference implementations: `api_stub_pack_reel_job`, `api_video_project_render_job`,
  `api_video_clip_maker_job`, `api_video_reel_job`, `api_video_project_stabilize_job`.

### 2. `src/mediahub/web/spec_editor.py` — structured spec editor (H-5)
A **pure** (no web deps), descriptor-driven editor that turns any
pages→sections→blocks spec into a per-section title/text/link form and applies an
edited form back **by stable id**, leaving non-whitelisted fields byte-for-byte
untouched.
- To expose more fields, just add to the per-surface tables: `FIELD_WHITELIST`
  (block kind → `[(prop_path, label, "text"|"textarea"|"url")]`, dotted paths for
  nested props like `button.label`), `LINK_LIST_KINDS`, `SPEC_CHROME`,
  `SECTION_CHROME`. v1 deliberately whitelists only text/link props — leave
  images (`src`), charts, tables, nested columns to the JSON hatch.
- Wire a new surface with an `api_<x>_content_edit` route that reads
  `request.form` and does `load → to_dict() → apply_structured(data, form, surface)
  → force identity id → from_dict → save`, plus a "Edit content" card
  (`render_structured(spec.to_dict(), surface)`) rendered above the raw-JSON
  hatch (relabel the hatch "Advanced — raw spec (JSON)"). Every emitted id/value
  goes through `_h`.
- Wired surfaces: site (`sites_ui.render_editor` + `api_site_content_edit`),
  newsletter (`newsletter_view` + `api_newsletter_content_edit`), document
  (`document_view` + `api_document_content_edit`).

### 3. `sign_in_error` flash channel
The sign-in picker pops `session["sign_in_error"]` and renders it on **both** the
empty-state and the picker (hoisted this session). Use it for any signed-out /
non-owner bounce that should explain itself (E-8, J-11 both do).

---

## Test patterns

- **JS-in-template changes**: source-level substring assertions on
  `web.py`'s text (read once as `_SRC`), asserting the OLD pattern is gone AND the
  NEW one present. See `test_usability_j2_*`, `test_usability_g13_*`.
- **Behavioural page renders**: the `client`/`page_html` fixture — set
  `DATA_DIR`/`RUNS_DIR`/`SWIM_CONTENT_PROFILES_DIR`, `importlib.reload(cp);
  importlib.reload(wm)`, `save_profile(ClubProfile(...))`, pin
  `s["active_profile_id"]`. Media/video tests also set `_mls._default_store` and
  `_vproj._store = None`; skip when `not wm._v8_ok` / `_email_design_ok` /
  `_documents_ok`.
- **Background-job routes**: mock the heavy call (`mediahub.video.render.render_edl`,
  `…clip_maker.clip_maker`, `…reel_builder.make_reel`, `…enhance.is_stabilize_available`)
  via `monkeypatch.setattr` (the routes import inside the worker, so patching the
  module attr works), POST → assert 202 + `job_id`/`poll_url`, then poll
  `/api/reel-jobs/<id>` until `done`/`error`. See `test_usability_j1_video_render_job.py`.

---

## Remaining work — prioritized

### A. Contained tail — just build (no owner input needed)
Highest-leverage first, roughly:
- **D-11** silent empty `.catch` handlers (comment delete/react at `web.py`
  ~`commentsMutate`/`commentsReact`, photo-editor Enhance) → surface `MH.toast`.
- **D-12** 30–90s renders behind plain links with no progress → reuse the reel
  job+poll UI (pattern above).
- **J-15** paid-tier "Pricing TBC" disabled CTA / **J-14** shared-NAT remote code
  lockout recovery / **J-16** / **J-6** plan "open the tool with that idea" seeds
  nothing / **J-8** `/print` catalogue dead end / **J-3** review page has no
  pagination (huge meets) / **J-4** repurpose-pack has no copy/download + `alert()`.
- **G-1, G-2, G-6, G-7, G-8, G-10, G-11, G-14** consistency (G-14 = standardise
  the many ad-hoc busy-button states onto one `MH.btnState`/`mhBusy` helper).
- **H-9…H-18, H-20** forms (H-20 = 2FA QR + recovery codes; the `mediahub.sites.qr`
  module already exists).
- **E-5, E-10…E-14** destructive/data-safety confirms & impact previews.
- **C-10, C-11, C-12, C-15, C-17, C-20** discoverability/IA.
- **D-13, D-32** feedback tail.

### B. Owner-facing — ASK first (`AskUserQuestion`, concrete options)
Do **not** guess on these; they change product shape:
- **B-1…B-8** — reduce steps/clicks in the core flow (the "too many steps" theme).
- **C-19** — Settings is a flat wall of ~17 tiles; grouping is an IA decision.
- **G-9** — two consent stores; which is authoritative / how to consolidate.
- **J-9** — three publish vocabularies (wall / sites / newsletters); unify.
- **G-5** (dead voice UI removal), **D-15** (unsaved-analysis loss), **D-26**
  (planner reactivity), **C-19-adjacent** brand cleanup.

---

## Owner decisions on record (apply without re-asking)
- Customer vocabulary for a "run" = **"Results"** (confirm per-surface, not
  blanket).
- The Developer/operator sign-in link belongs on **`/login` only** (not the
  footer of customer pages).
- Nav: **Elements replaced with Activity** (done).
- **Collections finished**; sticker/mockup **picker wired** (done).
- Brand home: **`/organisation/setup` is canonical** (done); `/brand` keeps
  kit/governance; legacy `/organisation` demoted with a banner.
- **No customer-facing self-host tier** — hosted-only SaaS (ADR-0011). Don't
  reintroduce a "run it yourself" product path.
- **Merges to `main` are autonomous, gated only on green CI** (main auto-deploys
  to Render). **Merge commits, not squash.** A red build must never merge.

For any *new* nav-placement or orphaned-page (finish-vs-remove) decision, ask the
owner — don't guess.

---

## Dev setup (fresh container)

```bash
pip install -e ".[dev]" --ignore-installed PyYAML   # PyYAML is a debian pkg; --ignore-installed avoids the RECORD error
pip install ruff==0.8.4                              # for the hygiene check (python -m ruff)
python -m pytest tests/test_spec_editor.py -q        # fast smoke of the H-5 engine
```

No LLM key in the sandbox → AI surfaces honest-error
(`ClaudeUnavailableError`/`ProviderNotConfigured`); that's expected. `_v8_ok`
gates the media/video engine; `_email_design_ok`/`_documents_ok`/`_sites_ok`
gate those surfaces — tests skip when a flag is off.
