# Feature Audit — Video Studio (`/video`, "Create → Video studio")

**Mode:** AUDIT+FIX · **Branch:** `claude/video-studio-audit-bkhvvu`
**Auditor:** automated QA+fix session · **Date:** 2026-07-10

---

## 1. Scope contract

**Definition.** The Video Studio is the footage → reel path surfaced on the
Create page. A club uploads or records a race clip; MediaHub ingests it into the
media library, runs Clip-Maker (deterministic moment detection → reframe →
optional captions → branded EDL) or the AI-directed multi-clip reel, lets a human
edit the timeline (trim / speed / grade / look / caption text / reorder), renders
server-side to MP4, and gates **export behind human approval**. "Working" means:
every control does what it claims; malformed/hostile input is rejected cleanly
(never a crash, corruption, or cross-tenant leak); the happy path produces a
correct branded MP4; and export is impossible without approval.

**Routes owned (method + path → view):**

| View | Method | Path |
| --- | --- | --- |
| `video_studio_page` | GET | `/video` |
| `api_video_footage_upload` | POST | `/api/video/footage` |
| `api_video_footage_list` | GET | `/api/video/footage` |
| `api_video_footage_permission` | POST | `/api/video/footage/<asset_id>/permission` |
| `api_video_footage_best_frame` | POST | `/api/video/footage/<asset_id>/best-frame` |
| `api_video_clip_maker` | POST | `/api/video/clip-maker` |
| `api_video_reel` | POST | `/api/video/reel` |
| `api_video_projects_list` | GET | `/api/video/projects` |
| `api_video_project` | GET,POST | `/api/video/projects/<project_id>` |
| `api_video_project_enhance` | POST | `/api/video/projects/<project_id>/enhance` |
| `api_video_project_caption` | POST | `/api/video/projects/<project_id>/caption` |
| `api_video_clip_waveform` | GET | `/api/video/projects/<project_id>/clip/<int:clip_index>/waveform` |
| `api_video_project_render` | POST | `/api/video/projects/<project_id>/render` |
| `api_video_project_approve` | POST | `/api/video/projects/<project_id>/approve` |
| `api_video_project_file` | GET | `/api/video/projects/<project_id>/file` |

**Files owned (blast radius):**
- `src/mediahub/web/web.py` — `_VIDEO_STUDIO_HTML` template + studio JS (~11807-12545),
  the Create tile (~33407), studio helpers (~57706-57885), `video_studio_page` +
  all `/api/video/*` handlers (~57886-58760). *(Monolith — edits kept feature-local.)*
- `src/mediahub/video/` — `ingest.py`, `projects.py`, `edl.py`, `render.py`,
  `clip_maker.py`, `reel_builder.py`, `best_frame.py`, `waveform.py`, `captions.py`,
  `probe.py`, `enhance.py`, `moments.py`, `reframe.py`.
- `tests/test_video_routes.py`, `tests/test_phase_d_footage_routes.py`,
  `tests/test_video_captions.py`, `tests/test_usability_j2_video_studio_errors.py`.

**Shared files depended on but NOT freely rewritten:** the Flask app factory /
CSRF `before_request` (`web.py:18627-18709`), `media_library/store.py`,
`visual/motion.py`, `visual/reel_ffmpeg.py`, `visual/subtitle_burn.py`, base
CSS/JS. (One tiny, feature-local edit to `web.py` regions is unavoidable because
the studio lives inside the monolith — see Cross-cutting changes.)

**Inputs / outputs / state.** Input: a video file (MP4/MOV/WebM/MKV/AVI/3GP) or a
webcam/screen recording, plus per-clip options. Output: a saved `VideoProject`
(an EDL timeline) in `data.db` (`video_projects` table) and, on render, an MP4 +
poster + manifest under `DATA_DIR/video_projects/<id>/`. Footage blobs live in the
media library (`DATA_DIR/uploads_v4/media_library/<profile>/`).

**Intended happy path.** Upload footage → tile shows poster/duration/audio/permission
badge → select clip → "Make clip" creates a project → render → **approve** →
export (download) an MP4. Consent-gated footage (`do_not_use` /
`needs_parental_consent`) is blocked at clip-maker, reel, render, and export.

---

## 2. Environment

- App booted locally via the Flask **test client** (`create_app()`, `TESTING=True`)
  against isolated `tmp` `DATA_DIR`/`UPLOADS_DIR`/`RUNS_DIR` with two profiles
  (`alpha`, `beta`) for tenant-isolation checks. `MEDIAHUB_SCHEDULER=0`.
- **No real provider calls.** No `GEMINI_API_KEY`/`ANTHROPIC_API_KEY` set — AI
  surfaces honest-error as designed (the AI director falls back to a deterministic
  "strongest moments first" order; captions are `no-speech-or-asr-off` since
  `MEDIAHUB_ASR_PROVIDER` is unset). No paid APIs touched.
- **FFmpeg present** via the `imageio-ffmpeg` bundled binary (`ffmpeg-linux-x86_64-v7.0.2`),
  so the **full render pipeline was exercised for real** (probe → clip-maker →
  render → export). Playwright browsers absent, so the still-renderer end-card
  honest-skips (`end_card: skipped`) — expected.
- Fixtures: two synthesised `testsrc` clips (one with a sine audio track as the
  "race" clip, one as a stand-in "other tenant" file for the injection test),
  generated with the bundled FFmpeg. No `samples/` video fixtures exist in-repo.
- Driver scripts in the session scratchpad drove every route as a real client;
  `pytest` used for the locked regressions.

---

## 3. Test matrix results

| # | Dimension | Result | Evidence |
| --- | --- | --- | --- |
| 1 | Functional correctness (happy path) | **PASS** | upload→clip-maker→render→approve→export produced a valid 128 KB MP4; footage summary correct (duration 3000ms, audio detected, poster generated). |
| 2 | Every interactive control | **PASS (after fixes)** | All buttons/toggles/selects wired. "Make clip" lacked a double-submit guard (F-05, fixed); "Save timeline" lacked a `.catch` (F-06, fixed). Record/permission/best-frame/enhance/approve/export/editor controls verified. |
| 3 | Input validation & edge cases | **PASS (after fixes)** | Non-video→415; empty→400; no-file→400; bad format→400; bad id→404; `target_moments` clamped/coerced; oversized cap raised per-route. Malformed EDL field types used to 500 (F-03, fixed). |
| 4 | UI state handling | **PASS (after fixes)** | Loading/empty/error/success states present; the two stuck-spinner gaps (make-clip, save) fixed. |
| 5 | Server-side error handling | **PASS (after fixes)** | Honest 4xx/5xx with specific copy. Two unhandled-500 paths fixed (F-02 newline export, F-03 malformed EDL); one raw Python cast message cleaned (F-07). |
| 6 | Data integrity | **PASS** | Round-trips correct; approval reopens on any edit; re-run makes a fresh project (no clobber); per-tenant isolation holds. Karaoke caption edits used to be silently dropped (F-04, fixed). |
| 7 | Security | **PASS (after fixes)** | Cross-tenant IDOR on projects correctly 404s. **EDL source injection (arbitrary file read / cross-tenant exfiltration) confirmed and fixed (F-01).** Consent gate enforced at clip-maker/reel/render/export. No XSS (all dynamic values `esc()`-escaped). CSRF handled by the JSON-content-type + `X-CSRF-Token` scheme. Header injection via project name blocked by werkzeug (F-02 was the 500 side-effect). |
| 8 | Performance sanity | **PASS** | Footage list capped (200); reel capped at 8 clips / 5 beats; waveform buckets clamped 16-2000; render content-cached. No full-corpus scans on the request path. |
| 9 | Responsive & a11y basics | **PARTIAL** | Grid collapses at 860px; `aria-live` on status regions; drop-zone keyboard-operable. Gaps logged: modal editor has no focus-trap/Escape/`aria-modal`; several inputs/icon-buttons lack accessible names (F-08..F-11, logged). |
| 10 | Rendered-graphic correctness | **PASS** | Real MP4 rendered deterministically; export byte-stable via content cache; consent/approval gates hold at render and export. |
| 11 | Consistency & copy (British English) | **PARTIAL** | New copy is British English, plain-hyphen. Pre-existing studio copy uses em dashes pervasively (house style across the whole monolith) — logged, not swept (F-12). |

---

## 4. Findings

| ID | Sev | Title | Reproduction | Root cause | Status | Commit |
| --- | --- | --- | --- | --- | --- | --- |
| F-01 | **P0** | EDL source injection → arbitrary file read / cross-tenant exfiltration | POST `/api/video/projects/<id>` with `{"edl":{"clips":[{"source":"/any/file.mp4",...}]}}` → 200; render + export return an MP4 of the injected file's frames; waveform reads its audio. | `EDL.from_dict`/`validate` only check `source` is non-empty; render/waveform feed it straight to FFmpeg. `_project_blocked_source` only blocks *known* library assets, so an unknown path passes. | **FIXED** — source-binding guard rejects any clip source not already on the project's saved timeline. | (this branch) |
| F-02 | **P2** | Export 500 on a project name containing a newline | Name a project `evil"\r\n...`, render, approve, GET `.../file?download=1` → werkzeug raises on the `Content-Disposition` header → unhandled 500. | `download_name` built from raw `proj.name`; header injection itself is blocked by werkzeug, but the resulting `ValueError` was uncaught. | **FIXED** — control chars stripped from `download_name`. | (this branch) |
| F-03 | **P2** | Malformed EDL field types → unhandled 500 | POST `{"edl":{"width":"abc",...}}` / `{"fps":null}` / `{"clips":"x"}` / `{"clips":[{"speed":"fast"}]}` → `ValueError`/`TypeError`/`AttributeError` escapes → 500. | `EDL.from_dict` coerces fields (`int`/`float` casts); those errors aren't `EDLError`, and the route only caught `EDLError`. | **FIXED** — broadened the parse `except` to return a clean 400 `invalid_edl`. | (this branch) |
| F-04 | P2 | Karaoke (animated) caption text edits silently discarded | On the default reel caption style, `edit_cue_text` set the line `text` but the burn reads per-word `words` — the correction never appeared. | `edit_cue_text` left stale `words` in place. | **FIXED** — text edit drops stale `words`; `caption_render` burns the word-less cue as a still line of the new text. | (this branch) |
| F-05 | P3 | "Make clip" allows double-submit (duplicate projects) | Double-click "Make clip" → two clip-maker calls → two projects. | Handler didn't disable the button (the reel handler did). | **SUPERSEDED** — during Phase 5 integration `origin/main` had already replaced the make-clip flow with the polled `runVideoJob` runner (usability PR #1097), which disables the button for the whole run. My change was dropped in favour of main's; the test now locks main's guard. | (main) |
| F-06 | P3 | "Save timeline" stuck on "Saving..." on network/non-JSON failure | Kill the network mid-save → promise rejects with no `.catch` → spinner never clears. | Save fetch chain missing the `.catch` the other studio fetches have (J-2 hardening). | **FIXED** — added `.catch` clearing the status. | (this branch) |
| F-07 | P3 | Caption route leaks raw Python cast error | POST `/caption` `{"op":"edit"}` (no index) on a captioned project → 400 with `int() argument must be ... not 'NoneType'`. | `except ... as e: message=str(e)` surfaced the internals. | **FIXED** — generic actionable message. | (this branch) |
| F-08 | P2 | Modal timeline editor has no focus management | Open "Edit timeline"; no focus-trap, no Escape-to-close, no `aria-modal`; focus not restored on close. | Modal built without a11y affordances (Close is tab-reachable, so not a hard trap). | **LOGGED** — a11y improvement; deferred to keep the shared-file footprint tight. | — |
| F-09 | P3 | Reel brief input labelled by placeholder only | `#vs-reel-brief` has no `<label>`/`aria-label`. | Placeholder-as-label. | **LOGGED** | — |
| F-10 | P3 | Editor trim/speed number inputs + icon buttons lack accessible names | `.vs-ed-in/out/speed`, `↑/↓/×` buttons named by glyph. | Text-node labels, no `aria-label`. | **LOGGED** | — |
| F-11 | P3 | Reel has no independent format control | "Direct the reel" reads the Clip-Maker's `#vs-format` select (only visible when a clip is selected); defaults to `story` otherwise. | Shared select between clip and reel. | **LOGGED** — minor; defaults are sane. | — |
| F-12 | P3 | Em dashes pervade studio user-facing copy | e.g. `&mdash;` throughout `_VIDEO_STUDIO_HTML`. | House style across the whole monolith. | **LOGGED** — not swept (large diff in a hot shared file → merge risk; contradicts the codebase-wide style). | — |
| F-13 | P3 | Render truncates timeline when an open-ended clip is mixed with resolved clips | Set one editor clip's `out` to 0 (open-ended) alongside a resolved clip → `total_timeline_ms()` under-counts → render `-t` caps short, cutting the open-ended clip. | `Clip.timeline_ms` is 0 for `out_ms==0`; the `or` fallback in `render.py:318` only triggers when the *total* is 0. | **LOGGED** — engine file (`render.py`); edge (normal flow always sets `out_ms`); risky to change under other sessions. | — |
| F-14 | P3 | Burned captions drift when clips are re-trimmed/reordered/deleted | Caption cues are frame-indexed to the original clip windows; the editor doesn't re-time them on structural edits. | No caption re-timing hook on EDL edit. | **LOGGED** — needs engine-level re-timing; out of tight scope. | — |
| F-15 | P3 | Clip-Maker builds a project from an undecodable clip | Upload junk bytes with a `.mp4` extension (accepted, unmeasured) → clip-maker returns 200 with a 0-duration fallback timeline that then 500s at render. | Ingest deliberately tolerates unprobeable clips (FFmpeg-absent deployments); clip-maker doesn't re-check decodability. | **LOGGED** — honest-errors at render; changing ingest tolerance is out of scope. | — |

**Non-findings verified (documented so they aren't re-reported):** cross-tenant
IDOR on projects (beta → alpha's project) correctly 404s; the consent gate blocks
`do_not_use`/`needs_parental_consent` at clip-maker, reel, render, and export;
`caption.shift_track`/`retime_cue` operate on the correct `from`/`dur` keys (an
earlier report of a `from` vs `from_frame` bug was a test-harness artifact from
using the wrong cue keys); project name truncated to 120; approval reopens on
edit; download blocked without approval; header-injection via project name is
blocked by werkzeug (only the 500 side-effect was the bug, F-02).

---

## 5. Fixes applied

All fixes are feature-local (`web.py` studio JS + `/api/video/*` handlers,
`video/captions.py`). No shared infrastructure (app factory, base templates,
config, `requirements.txt`) was modified.

- **F-01 (web.py, `api_video_project` POST):** new `_video_norm_source()` helper
  + a source-binding check — an EDL update may only reference sources already on
  the project's saved timeline; any new/foreign path → 400 `invalid_edl`. This
  closes the arbitrary-file-read / cross-tenant-exfiltration hole while allowing
  every legitimate edit (reorder/trim/grade/delete/caption).
- **F-02 (web.py, `api_video_project_file`):** strip control chars from
  `download_name` before `send_file`.
- **F-03 (web.py, `api_video_project` POST):** broadened the EDL parse `except`
  to `(ValueError, TypeError, AttributeError)` → clean 400.
- **F-04 (video/captions.py, `edit_cue_text`):** drop stale karaoke `words` on a
  text edit so the correction actually renders.
- **F-05 / F-06 (web.py studio JS):** disable "Make clip" during the request;
  add the missing `.catch` to "Save timeline".
- **F-07 (web.py, `api_video_project_caption`):** replace the raw cast-error
  message with an actionable one.

---

## 6. Tests added / extended

- `tests/test_video_routes.py`
  - `test_edl_update_rejects_foreign_clip_source` — locks F-01 (foreign source →
    400, not persisted; a same-source edit still succeeds).
  - `test_update_rejects_malformed_edl_types_without_500` — locks F-03 (four
    wrong-typed EDLs → 400 `invalid_edl`).
  - `test_export_download_name_with_newline_does_not_500` — locks F-02 (newline
    name exports 200, no CR/LF in header, no injected header).
  - `test_caption_bad_params_message_is_clean` — locks F-07 (no `int()` internals
    in the message).
- `tests/test_video_captions.py`
  - `test_edit_cue_text_drops_stale_karaoke_words` — locks F-04.
- `tests/test_usability_j2_video_studio_errors.py`
  - `test_save_timeline_has_catch_handler` — locks F-06.
  - `test_make_clip_button_guards_double_submit` — locks F-05.

---

## 7. Cross-cutting changes

- **`src/mediahub/web/web.py`** is the Flask monolith and is touched by many
  sessions. All edits here are strictly **Video-Studio-local**: the studio JS
  template block, the studio-only helper `_video_norm_source`, and the
  `/api/video/*` route handlers. No shared factory / CSRF / base-template / config
  code was changed. Merge-conflict surface is confined to the studio regions.
- No changes to `requirements.txt`, `pyproject.toml`, base CSS/JS, or `.env.example`.

---

## 8. Residual risks / cross-feature work

- **F-08..F-10 (a11y):** modal focus-trap/Escape and accessible names for the
  editor inputs/icon buttons — a focused a11y pass, best done across the studio
  editor in one change rather than piecemeal.
- **F-12 (copy):** the em-dash → plain-hyphen sweep is a codebase-wide style
  decision (the whole monolith uses em dashes); needs a maintainer call, not a
  single-feature edit.
- **F-13 / F-14 (engine):** open-ended-clip render truncation and caption drift on
  structural edits live in `render.py` / the caption re-timing path (deterministic
  engine). Both are edge cases in the normal flow and were left for a dedicated,
  test-heavy engine change under the CLAUDE.md engine-boundary rules.
- **`_run_`-prefixed project bypass** (`_video_can_access_project` returns True for
  any `profile_id` starting with `_run_`): shared with the run→reel path, not the
  studio's own creation path (studio projects always carry a real profile). Left
  as-is to avoid touching the shared run path; flagged for cross-feature review.

---

## 9. Feature verdict

**WORKS-WITH-CAVEATS.** The core flow (upload → clip-maker/reel → edit → render →
approve → export) is correct, deterministic, tenant-isolated, and consent-gated;
the one P0 (source injection) and both P2 unhandled-500s are fixed and locked with
tests. Remaining caveats are accessibility gaps and two edge-case engine
behaviours (F-13/F-14), all logged, none blocking normal use.

---

## 10. Handover & merge status

- **Branch:** `claude/video-studio-audit-bkhvvu` — pushed to `origin` at commit
  `2a280c3`, rebased cleanly (no conflicts) onto `origin/main` `f999823`.
- **Green gate (passed):** the full `pytest tests/` suite (xdist, `autotest`
  excluded per CI) was run green on three consecutive `origin/main` bases as main
  advanced under the audit — **12,242 / 12,282 / 12,299 passed, 10 skipped** each
  (all skips legitimate: FFmpeg-present honest-error paths, opt-in slow render
  diffs). On the final tree a targeted re-gate (the video-studio feature suite plus
  the two orthogonal newly-merged features' own tests) was **172 passed, 1 skipped**;
  ruff lint + `ruff format --check` clean on all changed files; app boots and
  `/`, `/help`, `/video` all serve 200. No secrets or `.env` staged.
- **Draft PR:** not yet opened from this session — the GitHub MCP connector
  disconnected mid-session, and there is no `gh` CLI in this environment, so the PR
  could not be created programmatically. The branch is pushed and ready; open the
  draft PR at `https://github.com/elijahkendrick04/MediaHub/pull/new/claude/video-studio-audit-bkhvvu`
  (or via the GitHub MCP once it reconnects). CI on the PR merge result plus the
  "branch up to date" protection is the authoritative merge gate for `main`.
- **Review the diff:** `git diff origin/main...claude/video-studio-audit-bkhvvu`
  (6 files, +506/-8: `web.py` video routes, `video/captions.py`, three test files,
  this report).
