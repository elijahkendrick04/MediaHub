# Feature audit — Season Wraps (W.8)

**Mode:** AUDIT+FIX · **Branch:** `claude/season-wraps-audit-mz8tyj` · **Date:** 2026-07-09
**Auditor:** automated QA+fix session (one of several parallel feature audits)

---

## 1. Scope contract (Phase 0)

**Definition.** "Season Wraps" is the Create-area feature (roadmap **W.8**, ADR-0016)
that looks back over a workspace's already-stored meet runs and adds them up into a
shareable "month in numbers" / season-recap **draft pack**: total PBs, medals (by
colour), club records, debuts, milestones, qualifying hits, the busiest swimmer, the
biggest improver, a per-swimmer leaderboard, and a ranked highlights list. It is
**deterministic counting only** — no LLM, no network, no publishing. A draft is
persisted, reviewed by a human, and can be printed as an A4 noticeboard poster (PDF).
"Working" means: the counts are correct and tenant-isolated; the review page and the
printed poster faithfully show *what was counted* (swimmer, event, achievement) with
nothing silently dropped; every control does what its label claims; and it fails
cleanly (honest empty/zero states, no 500s, no cross-org leakage).

**Routes owned (method + path → endpoint):**
- `GET  /wraps` → `season_wraps_page` — list drafts + generate/schedule controls
- `POST /wraps/action` → `season_wraps_action` — `month` / `season` / `monthly_on` / `monthly_off`
- `GET  /wraps/<draft_id>` → `season_wrap_view` — one draft: stat chips + highlights table
- `GET  /wraps/<draft_id>/poster.pdf` → `season_wrap_poster` — A4 poster PDF (`?print=1` = bleed + crop marks)
- Create-hub tile registration (`/make`) linking to `/wraps`

**Files owned (blast radius):**
- `src/mediahub/season_wrap/aggregate.py` — `WrapStats`, `aggregate_window`, window/counting maths
- `src/mediahub/season_wrap/drafts.py` — draft builders + `DATA_DIR` persistence, `_slug` traversal guard
- `src/mediahub/season_wrap/task.py` — monthly scheduler handler + registration
- The four `/wraps*` route functions and the Create tile block in `src/mediahub/web/web.py`
- `tests/test_season_wrap.py`, `tests/test_phase_w_web.py` (extend), `tests/test_create_hub_live_tiles.py`

**Shared files it depends on but must NOT freely rewrite:**
- `src/mediahub/graphic_renderer/print_export.py` (`build_poster_html` / `render_html_to_pdf` / `export_poster_print_pdf`)
- `_phase_w_org` / `_PW_NO_ORG` / `_active_profile_id` / `_layout` / `_h` / CSRF layer / `workflow.schedule`

**Inputs / outputs / state.** Input: the workspace's stored `runs_v4/*.json` recognition
snapshots + the current signed-in org (session). Output: a JSON draft persisted at
`DATA_DIR/season_wraps/<profile_id>/<id>.json`, rendered as a review page and an A4 PDF.
No external side effects; nothing is published.

**Intended happy path.** Sign in → open Create → Season wraps → "Draft last month's wrap"
→ a `monthly-YYYY-MM` draft is written with correct counts → open it → stat chips + a
highlights table showing **swimmer, event, what happened** → print the A4 poster with the
same swimmer/event/highlight data → optionally enable a monthly auto-draft schedule.

---

## 2. Environment

- Python 3.11.15; installed `requirements.txt` (worked around a Debian-managed PyYAML
  with `pip install -r requirements.txt --ignore-installed PyYAML`) plus `pytest`,
  `pytest-xdist`, `pytest-rerunfailures`.
- Playwright: the pinned `playwright>=1.61,<1.62` wants Chromium rev 1228; the container
  prebaked rev 1194, so `python -m playwright install chromium` was run once to fetch the
  matching rev-1228 Chrome-Headless-Shell into `/opt/pw-browsers`. The poster PDF route
  then renders end-to-end locally.
- App boots clean (`create_app()`, 502 routes) with only the expected honest-error warning
  "No LLM provider configured" — the correct offline behaviour; no real provider calls are
  made anywhere in this feature (it is LLM-free by design).
- Driven via Flask's test client with a pinned org (the repo's own `test_phase_w_web.py`
  pattern) against tmp `DATA_DIR`s; no live Render URL touched; no secrets used.

Method: read the canonical docs (`FEATURE_INVENTORY`, `ROUTE_INVENTORY`, `ADR-0016`,
`KNOWN_ISSUES`, `USABILITY_AUDIT`, `CLAUDE.md`); drove every route with the Flask test
client; verified the deterministic core against fixtures; and ran a 5-lens finder +
adversarial-verify workflow over the feature code. Provider calls are never reached (the
feature is LLM-free); the only external dependency is the shared Playwright poster
renderer, which is stubbed in tests.

---

## 3. Test matrix results

| # | Dimension | Result | Note (evidence) |
|---|---|---|---|
| 1 | Functional correctness | PASS | Counts/leaderboard/tie-breaks correct (existing + new unit tests); happy path drafts the right window. |
| 2 | Every interactive control | PASS (after fix) | Create tile → `/wraps` (tile test); month/season/toggle/Open/poster all act as labelled; swimmer column now populated. |
| 3 | Input validation / edge cases | PASS (after fix) | Empty window = honest zero; malformed JSON no longer crashes; unpadded/slash-ISO dates now windowed. Residual: ambiguous `MM/DD/YYYY` dates. |
| 4 | UI state handling | PASS | Honest empty/zero states for drafts, chips and highlights. Residual: no loading state on the 30-90s poster download (SW-8). |
| 5 | Server-side error handling | PASS (after fix) | Draft-build failure now redirects with an honest message instead of a raw 500 stack trace. |
| 6 | Data integrity | PASS (after fix) | Swimmer + display time now flow end-to-end; tenant-isolated; monthly and (now) season drafts idempotent. |
| 7 | Security | PASS (after fix) | XSS escaped via `_h`; brand-colour injection sanitised in the wraps poster; IDOR/traversal/CSRF/auth verified safe. Shared root cause logged (SW-7). |
| 8 | Performance | PASS (note) | Each generate scans the org's run files once (O(runs)); fine at club scale; no N+1. |
| 9 | Responsive / a11y basics | PASS (note) | Tables use `<th>` headers; chips grid is responsive; poster has an honest empty state. Minor residual: no `scope`/`aria-busy` on the download links. |
| 10 | Rendered-graphic correctness | PASS (after fix) | Poster renders a valid PDF (200, `application/pdf`); swimmer/time correct; brand safe; stable re-render. |
| 11 | Consistency / copy quality | PASS (after fix) | British English throughout; season title en-dash → " to " (plain-hyphen rule); honest messages, no placeholder/debug text. |

Security sub-checks proven safe (Flask test client): cross-org draft view/poster → 404;
path-traversal draft ids → 404; no-org view → sign-in prompt, no-org action/poster → 403;
POST forms carry an auto-injected CSRF token.

---

## 4. Findings

| ID | Sev | Title | Reproduction | Root cause | Status |
|---|---|---|---|---|---|
| SW-1 | P1 | Swimmer name blank in the review highlights table **and** the printed poster | Draft a wrap with any highlight → `/wraps/<id>`: Swimmer column empty; poster Swimmer column empty | `drafts.py` stores key `swimmer`; both web routes read `swimmer_name` → always `''` | **Fixed** (`8adf…`—see §5) |
| SW-2 | P2 | Poster "Time" column structurally always empty | Print any poster → Time column blank for every row | `aggregate` candidates never carried a time; poster read a non-existent `raw_facts.time` | **Fixed** — time threaded `aggregate → draft → poster` |
| SW-3 | P1 | Runs with a non-ISO `meet.start_date` silently excluded from every wrap | A run dated `2026-6-5` or `2026/06/20` never appears in the June wrap | Window filter is a plain string compare assuming canonical ISO; parsers emit unpadded/slash/`MM/DD/YYYY` | **Partially fixed** — unambiguous year-first forms normalised; ambiguous `MM/DD/YYYY` logged (§7/§8) |
| SW-4 | P2 | `POST /wraps/action` month/season branches raise a raw 500 (no try/except) | Draft with a run that makes aggregation raise → 500 + stack trace | Only the toggle branches were guarded; the draft branches were not | **Fixed** |
| SW-5 | P2 | `aggregate_window` crashes on malformed-but-valid run JSON | A run with a non-dict `recognition_report`/`achievement`/`raw_facts`/`meet` or non-list `ranked` | Fallback loops + `raw_facts`/`meet` access were unguarded (only the main loop guarded `ra`) | **Fixed** — isinstance guards on every shape |
| SW-6 | P2 | "Draft this season" is not idempotent — a new draft file per day; no delete | Click it today + tomorrow → two rows; repeat → unbounded growth | Season draft id embedded the moving `today` end-date | **Fixed** — id keyed to season start (idempotent). Delete control logged as P3 (§8) |
| SW-7 | P2 (sec) | Stored brand colour injects HTML/CSS into the poster PDF (server-side Chromium render) | Set `brand_primary` to `#000;}</style><img onerror=…><style>{` → GET the poster | Shared `print_export._brand_hex` only checks `startswith('#')`; `_apply` substitutes raw into a `<style>` | **Fixed locally** (wraps route sanitises); shared root cause = coordination (§7) |
| SW-8 | P2 | Poster download has no loading state and no caching (double-click = duplicate 30-90s renders) | Click "Print A4 poster" → up to 90s with no feedback; a second click starts a second render | GET anchor to a synchronous render; route always re-renders `out` | **Logged** (residual, §8) — a JS busy-state in the f-string monolith is out of proportion here |

Verified **not** defects (checked, no change): CSRF (tokens auto-injected into every POST
form by `after_request`); cross-org isolation (`load_draft` is pid-scoped → 404); path
traversal (`_slug` + Flask string converter → 404); route auth (`_phase_w_org` gate → 403 /
sign-in prompt); XSS in the view (all sinks pass through `_h`).

---

## 5. Fixes applied

All within the feature blast radius except the locally-scoped defence in SW-7.

- **`season_wrap/aggregate.py`** — (a) SW-2: each `top_achievements` candidate now carries a
  `time` (honest key-fallback `time/time_str/result/final_time`); (b) SW-3: new `_iso_date()`
  normalises unambiguous year-first dates and `_run_date` uses it (+ guards a non-dict `meet`);
  (c) SW-5: isinstance guards on `recognition_report`, `ranked_achievements`, `swim_traces`
  elements, the busiest-swimmer fallback `ra`/`ach`, and `raw_facts`.
- **`season_wrap/drafts.py`** — SW-2: highlight dict now includes `time`; SW-6: season draft id
  is `season-<start>` (idempotent) and the title uses " to " (plain-hyphen rule, was an en-dash).
- **`web/web.py`** (four wrap routes only) — SW-1: view + poster read `swimmer` (was
  `swimmer_name`); SW-2: poster reads the threaded `time`; SW-4: month/season branches wrapped
  in try/except with an honest message + server-side log; SW-7: `season_wrap_poster` sanitises
  brand colours to a strict hex literal before handing them to the shared renderer.

---

## 6. Tests added / extended

- **`tests/test_season_wrap.py`** (+6): `test_highlights_carry_swimmer_and_time_keys`,
  `test_display_time_flows_from_raw_facts`, `test_iso_date_normalisation_windows_unpadded_and_slash_iso`,
  `test_ambiguous_slash_date_is_not_guessed` (documents the SW-3 residual),
  `test_aggregate_survives_malformed_runs` (SW-5), `test_season_draft_id_stable_across_end_dates`
  (SW-6); plus updated the season-shape golden (new id/title).
- **`tests/test_phase_w_web.py`** (+`TestSeasonWrapsSurface`, 3):
  `test_view_shows_swimmer_name_in_its_own_column` (SW-1),
  `test_poster_html_shows_swimmer_time_and_sanitises_brand` (SW-1/SW-2/SW-7, render stubbed),
  `test_action_draft_failure_is_graceful_not_500` (SW-4).

---

## 7. Cross-cutting changes

- **No shared file was rewritten.** SW-7's root cause lives in the shared
  `graphic_renderer/print_export.py` (`_brand_hex` accepts anything starting with `#`; `_apply`
  substitutes brand values raw into a `<style>` block) and the shared org-settings save path
  (`brand_primary`/`brand_secondary` stored without a strict hex check). That injection affects
  **every** poster/certificate export, not just Season Wraps. I fixed it **locally** inside the
  wraps poster route (in blast radius) and am flagging the shared root cause here for a
  coordinated global fix — recommended: tighten `_brand_hex` to `re.fullmatch(r"#[0-9A-Fa-f]{3,8}", v)`
  (one line, strictly stricter, no legitimate value affected). **Not done here** to avoid a
  shared-file edit that collides with other in-flight sessions and changes rendering for
  features outside this audit.

---

## 8. Residual risks / needs coordination

- **SW-3 residual (P1-ish, engine-adjacent):** ambiguous `MM/DD/YYYY` / `DD/MM/YYYY` dates from
  HY3/SDIF exports (and some PDFs) still cannot be windowed without guessing month-vs-day, so
  those runs are still dropped from wraps. The correct fix is ISO date normalisation at the
  **interpreter/canonical seam** (`interpreter/*_parser.py` + `web/canonical.py`, whose model
  already documents `start_date  # ISO`). That is the protected deterministic engine — needs
  explicit sign-off per `CLAUDE.md`. Logged for coordination.
- **SW-7 shared root cause** — see §7 (global `_brand_hex` tightening).
- **SW-8 (P2 UX):** poster render has no loading state and no cache; a busy-state needs JS in
  the f-string monolith. Left as a documented residual.
- **SW-6 follow-on (P3):** no per-draft delete control; the idempotency fix removes the
  unbounded-growth harm, but a "Remove draft" action would still be a nice-to-have.
- **a11y (P3):** poster download links lack `aria-busy`; highlight tables could add `scope="col"`.

None of the above were attempted here (engine boundary, shared surface, or out-of-scope).

---

## 9. Feature verdict

**WORKS-WITH-CAVEATS.** The core aggregation is correct and now the two customer-facing
outputs (review page + printed poster) faithfully show the swimmer and time that were
previously dropped; error handling, malformed-input robustness, season idempotency and a
poster injection vector are fixed and locked with tests. The one material caveat is SW-3:
clubs whose stored results carry ambiguous non-ISO meet dates can still get an under-counted
wrap until date normalisation lands at the interpreter seam (out of this feature's scope).

---

## 10. Handover & merge status

- **Branch:** `claude/season-wraps-audit-mz8tyj`
- **Review the diff:** `git diff origin/main...claude/season-wraps-audit-mz8tyj`
- **Merge status:** _to be updated after the Phase 5 green gate + integrate-on-green push._

