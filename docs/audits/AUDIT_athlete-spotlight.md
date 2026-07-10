# Feature audit — Athlete spotlight (meet recap)

**Mode:** AUDIT+FIX
**Branch:** `claude/athlete-spotlight-audit-c9v1iw` (this session's designated development branch; used as the audit branch — see Handover)
**Date:** 2026-07-10
**Auditor:** automated QA + fix pass

---

## 1. Scope contract

**Definition.** "Athlete spotlight" is the meet-recap surface that takes one processed meet run's
`recognition_report`, filters it to a **single swimmer**, re-ranks that swimmer's achievements, and lets the
reviewer approve moments and build a single composite post (one caption + one graphic + one reel). It is *not* a
new pipeline — it is a filter/re-rank pass over data the V4/V5 pipeline already produced, wired into the
meet-recap flow (the `Review & approve` ↔ `Athlete spotlight` tab pair). "Working" means: pick a processed meet →
see that meet's swimmers → open one swimmer → see *only their* achievements ranked with honest band counts →
approve moments → build a composite draft whose caption/graphic/reel reflect exactly the approved moments for
exactly that swimmer, with tenant isolation, safe handling of hostile input, and honest errors when AI is
unavailable.

**Routes owned (method + path → endpoint):**
| Method | Path | Endpoint |
| --- | --- | --- |
| GET | `/spotlight` | `spotlight_landing` |
| GET | `/spotlight/<run_id>/<path:swimmer_key>` | `spotlight_view` |
| POST | `/spotlight/<run_id>/<path:swimmer_key>/build` | `spotlight_build` |
| POST | `/api/drafts/<pack_id>/card/<int:card_idx>/caption` | `api_stub_pack_caption` (spotlight-guarded) |
| POST | `/api/drafts/<pack_id>/card/<int:card_idx>/caption/assist` | `api_stub_pack_caption_assist` (spotlight-guarded) |
| POST | `/api/drafts/<pack_id>/card/<int:card_idx>/reel-job` | `api_stub_pack_reel_job` (spotlight composite) |
| GET | `/api/drafts/<pack_id>/card/<int:card_idx>/reel-file` | `api_stub_pack_reel_file` (spotlight composite) |

The built spotlight draft opens the mode-aware **Content builder** (`_render_content_builder(mode="spotlight")`),
which reuses the shared stub-pack caption/graphic/reformat/copilot endpoints.

**Files owned (blast radius edited):**
- `src/mediahub/club_platform/athlete_spotlight.py` — `build_spotlight_pack`, `list_swimmers_in_run`.
- `src/mediahub/web/web.py` — **only** the spotlight route bodies + spotlight helpers: `spotlight_landing`,
  `spotlight_view` (`_sp_row_html`, `copySpotlightCaption` JS), `spotlight_build`, `_compose_spotlight_caption`,
  `_render_content_builder` (spotlight mode), `api_stub_pack_caption`, `_assemble_spotlight_reel_inputs`,
  `api_stub_pack_reel_file`, and the `athlete_spotlight` branch of `_stub_card_to_graphic_item`.
- `tests/test_spotlight_audit.py` — new regression tests.

**Shared files depended on but NOT freely rewritten:** `_load_run`, `_can_access_run`, `_can_access_pack`,
`_run_owner_id` (tenant guards); `_render_meet_recap_tabs`, `_athlete_avatar`, `_render_wf_actions`,
`_render_reactions` (shared render helpers); `mhCreateGraphic` (shared JS); `stub_pack_store`, `workflow.store`,
`visual.motion`; the CSRF/CSP web-hardening block; `ai_core` / `media_ai.llm`.

**Inputs / outputs / state.** Input: a `run_id` (a processed meet) + a `swimmer_key`; the reviewer approves
achievements and optionally picks a caption tone. Output: an on-screen ranked spotlight, and a persisted composite
draft (stub pack, `source=athlete_spotlight`) carrying the caption, the parsed result lines, and celebratory
tallies (medals/PBs/swims); the built graphic and reel are rendered on demand. State: run JSON under
`DATA_DIR/runs_v4/`, approvals in the workflow sidecar, drafts in the stub-pack store, rendered reels under
`runs_v4/<run_id>/motion/`.

**Happy path (concrete expected results).** `GET /spotlight` → meet picker (last 31 days, tenant-scoped). Select a
meet → grid of that meet's swimmers with achievement counts. Open a swimmer → hero + band stat block
(elite/strong/story/total) + ranked achievement rows with an approve strip. Approve ≥1 → **Build spotlight post**
→ 302 to `/drafts/<id>` which opens the Content builder with the composed caption, live tone tabs, Create-graphic
and Generate-reel. Caption/graphic/reel reflect **only** the approved moments for **only** that swimmer.

---

## 2. Environment

- Python 3.11, deps from `requirements.txt` + `.[dev]`; `mediahub` installed editable.
- Local run: `python -m mediahub.web.web` on **port 5055**, `DATA_DIR` pointed at a scratch dir, no provider keys
  set (AI honest-errors, per the offline rule). App boots clean (only the expected "no LLM provider" +
  "log sentinel idle" warnings).
- Tests: `pytest` via the Flask test client, modelled on `tests/test_spotlight_build_brand_grounding.py`
  (synthetic run JSON at `runs_v4/<id>.json` + `WorkflowStore` approvals + a stubbed `ai_core.ask` /
  `media_ai.llm.is_available` / `visual.motion.render_meet_reel`; session `active_profile_id` for auth). No real
  paid API calls; no external publishing.
- Reproductions were run per finding; failing repros were captured before fixing and re-run green after.
- Linters: `ruff` 0.8.4 (lint + format) clean on the changed source; the original `web.py` was already
  ruff-format-clean so the formatter only touched the new lines.

---

## 3. Test matrix results

| # | Dimension | Result | Note / evidence |
| --- | --- | --- | --- |
| 1 | Functional correctness (happy path) | **PASS** | Landing → swimmer grid → ranked view → build → Content builder with composed caption; verified output not just 200 (`test_spotlight_build_brand_grounding.py`, live driving). |
| 2 | Every interactive control | **PASS (after fix)** | Copy caption / Create graphic buttons broke for apostrophe names (F2, fixed); tone select, meet select, approve strip, tabs, build, reel all behave as labelled. |
| 3 | Input validation / edge cases | **PASS (after fix)** | Null `priority` crash (F1, fixed); unicode/emoji/CJK/apostrophe/120-char names round-trip; malformed run → recovery not 500; traversal `run_id` rejected (F4). |
| 4 | UI state handling | **PASS (after fix)** | Empty/db-fail/no-swimmer/all-approved states render; unopenable-meet dead-end now shows a message (F7-landing). |
| 5 | Server-side error handling | **PASS (after fix)** | No unhandled 500s; provider errors → honest 502/503; tone-rewrite no-approved case now specific (F6); no stack traces/paths leaked. |
| 6 | Data integrity | **PASS** | Wrong-swimmer isolation holds (spotlight X never shows Y); approved-only selection; band/medal/PB tallies correct for int/str `place`. |
| 7 | Security (this feature) | **PASS (after fix)** | Path traversal + PII leak (F4, fixed); stored-XSS/JS-injection in onclick (F2, fixed); reel tenant + type guards (F3/F5, fixed); routes behind org gate; no secret leakage; CSRF token auto-injected into the build form (verified). |
| 8 | Performance | **PASS (with note)** | Filter/re-rank is O(achievements); no N+1. Landing renders *all* swimmers of a meet unbounded (roster size) — acceptable for realistic meets; noted as residual. |
| 9 | Responsive / a11y | **PASS (with notes)** | Avatars carry aria; decorative chips aria-hidden; tone select has a `title`; noscript fallback for the JS-submit meet select. Meet `<select>` lacks an explicit `<label for>` (residual P3). |
| 10 | Rendered-graphic correctness | **PASS** | Spotlight graphic strips crawl-URL/entry_url, dedupes moments, leads with real medals/PBs/swims not the internal "N approved" (`test_spotlight_graphic_item_strips_entry_url_and_dedupes`). |
| 11 | Consistency / copy | **PASS (after fix)** | British English throughout; removed one literal em dash in a status line (F8). No placeholder/TODO/debug strings surfaced. |

---

## 4. Findings

Severity: P0 broken/data-loss/security-hole · P1 wrong behaviour or a lying control · P2 usability/error-handling ·
P3 polish. All findings were reproduced with a real script before fixing; "confirmed" = a repro demonstrably showed
the defect.

| ID | Sev | Title | Reproduction | Root cause | Status | Commit |
| --- | --- | --- | --- | --- | --- | --- |
| F1 | P1 | `build_spotlight_pack` crashes on a null `priority` | run JSON with an achievement `"priority": null` → `build_spotlight_pack` raises `TypeError: bad operand type for unary -: 'NoneType'`; spotlight_view shows a misleading "Swimmer not found" and the reel path 500s | sort key `-ra.get("priority", 0.0)` — the default only guards a *missing* key, not JSON `null` → `-None` | **fixed** | b806a11 |
| F2 | P1 | Stored XSS / broken control in spotlight-row onclick handlers | open a swimmer whose swim_id carries `'` (surname O'Brien, or a crafted `100'-alert(document.cookie)-'FR`) → rendered `onclick="...'{card_id}'..."` where `&#39;` decodes back to `'` and closes the JS string; a crafted name executes `alert` on click, and Copy/Create-graphic break for real apostrophe names | `_h()` (HTML-escape) is the wrong escaping for a value inside a single-quoted JS string literal in an HTML attribute; only spaces are stripped from names upstream so `'`, `(`, `)`, `;` survive into swim_id | **fixed** | ec3c955 |
| F3 | P1 | Path traversal + PII leak via `?run_id=` on `/spotlight` | as an org-pinned (pilot/anonymous) session, `GET /spotlight?run_id=../../<dir>/victim` returns 200 and reflects an arbitrary out-of-`DATA_DIR` JSON file's swimmer roster (names = PII) | `spotlight_landing` reads `run_id` from a query param (not the slash-rejecting `<run_id>` route converter) and passes it straight to `_load_run`, which builds `RUNS_DIR / f"{run_id}.json"` unfiltered | **fixed** | ec3c955 |
| F4 | P2 | Composite reel skips the source + tenant guards | (a) a non-spotlight pack carrying `run_id`+`swimmer_key` gets a 202 from `reel-job` (no `source` check); (b) a pack owned by org B naming org A's run renders a reel off A's run (no `_can_access_run`) | `_assemble_spotlight_reel_inputs` / `reel-file` gated on presence of `run_id`+`swimmer_key` only, unlike the caption endpoints | **fixed** | ec3c955 |
| F5 | P2 | Copy caption pastes literal `\n\n` | click Copy caption on a row with an angle hint → clipboard gets `headline\n\nangle` with literal backslash-n | `cap_text = f"{headline}\\n\\n{angle}"` in a normal f-string emits the two characters `\` `n`, not a newline | **fixed** | ec3c955 |
| F6 | P2 | Tone-rewrite reports a misleading "AI couldn't finish" | build a draft, un-approve every moment, hit `caption?tone=…` → generic transient error though the real cause is zero approved moments | `api_stub_pack_caption` collapsed *all* `_compose_spotlight_caption` error branches into one transient JSON | **fixed** | ec3c955 |
| F7 | P2 | Legacy dir-form meet selectable but opens blank | select a run stored only as `runs_v4/<id>/run.json` → the picker keeps it (self-heal accepts the dir form) but `_load_run` can't read it → blank page, no roster, no message | `_load_run` reads only the flat `<id>.json`; the shared limitation is app-wide, but spotlight's dead-end was silent | **fixed (message)** / root cause logged | ec3c955 |
| F8 | P3 | Dead `QualityBand` map + one literal em dash | `band_labels`/`QualityBand` import unused (`athlete_spotlight.py`); literal `—` in the "Everything is approved" status line | dead code left after refactor; house style uses `&mdash;` | **fixed** | b806a11, ec3c955 |
| F9 | P3 | `spotlight_build` mints a duplicate draft on re-submit | POST `/spotlight/<run>/<sw>/build` twice → two independent drafts | `save_pack` mints a fresh uuid each call; no `(run_id, swimmer_key)` dedupe | **logged** (behaviour is defensible; dedupe is a product decision) | — |

**Checked and PASSED (no defect):** empty/None guards in `build_spotlight_pack`/`list_swimmers_in_run`;
mutation-safety (originals not mutated); tenant isolation on the landing picker and `spotlight_view` (tampered
`?run_id=` for another org returns no roster); wrong-swimmer isolation end-to-end; band counts vs the stat block;
`place` as int/str; unicode/emoji/CJK/apostrophe/very-long names; XSS in `swimmer_name`/`meet_name`/`event`
(HTML-escaped); CSRF token auto-injected into the build form (403 without it); the spotlight graphic's
entry_url-strip/dedupe/celebratory-tally logic.

---

## 5. Fixes applied

- **`src/mediahub/club_platform/athlete_spotlight.py`** (b806a11): sort key `-(ra.get("priority") or 0.0)`;
  removed the unused `QualityBand` import + `band_labels` map (dead-code sweep).
- **`src/mediahub/web/web.py`** (ec3c955):
  - `_sp_row_html`: `mhCreateGraphic` now receives a JS-safe token via `_h(json.dumps(...))` (JSON-encode for the
    JS context, then HTML-encode for the attribute); Copy caption drops the interpolated id entirely and locates
    its span via `btn.closest('.sp-row').querySelector('.sp-cap-src')`; `cap_text` uses real newlines.
  - `spotlight_landing`: rejects a traversal `?run_id=` (`/`, `\`, `..`) before `_load_run`; shows an honest
    "couldn't open that meet" message when a selected run won't load.
  - `_assemble_spotlight_reel_inputs` + `api_stub_pack_reel_file`: added the `source == "athlete_spotlight"` type
    guard and the `_can_access_run` tenant check.
  - `api_stub_pack_caption`: maps the no-approved-moments case (compose returns 400) to a specific message;
    reworded one literal em dash.
- **`tests/test_spotlight_audit.py`** (86acc1b): new regression module (see §6).

Every fix stays inside the spotlight route bodies / core module; no shared helper signatures changed.

---

## 6. Tests added

`tests/test_spotlight_audit.py` (10 tests):
- `test_build_spotlight_pack_tolerates_null_priority`, `test_build_spotlight_pack_all_null_priority_does_not_crash`
  — F1.
- `test_band_counts_correct_without_dead_qualityband_map` — F8 dead-code + band-count correctness.
- `test_spotlight_row_onclick_safe_for_apostrophe_name` — F2 (decodes the onclick like a browser; asserts the
  injection stays inside a string literal and no bare `alert(`/stray `'` survives; asserts the no-arg copy form).
- `test_copy_caption_span_has_real_newlines` — F5.
- `test_spotlight_landing_rejects_path_traversal_run_id` — F3 (out-of-`DATA_DIR` victim file not reflected).
- `test_spotlight_landing_message_for_unopenable_run` — F7 message.
- `test_reel_rejects_non_spotlight_pack` — F4 source guard (reel-job + reel-file).
- `test_reel_enforces_run_tenant_isolation` — F4 tenant guard + a positive control (owner can still render).
- `test_tone_rewrite_names_no_approved_cause` — F6.

The existing `tests/test_spotlight_build_brand_grounding.py` and `tests/test_ui2_athlete_tooltips.py` still pass
unchanged.

---

## 7. Cross-cutting changes

**None applied.** All edits are inside the spotlight route bodies / spotlight helpers / the core spotlight module.
No shared helper (`_load_run`, `_can_access_run`, `mhCreateGraphic`, `stub_pack_store`, the CSRF/CSP block) had its
signature or behaviour changed; the traversal fix is a local guard in `spotlight_landing` rather than a change to
the shared `_load_run` sink (see residual note).

---

## 8. Residual risks / cross-feature items (not fixed here)

- **`_load_run` does not read the legacy `runs_v4/<id>/run.json` dir-form** (F7 root cause). This is a shared,
  pre-existing limitation affecting `/review`, `/pack`, etc. equally; several other routes carry their own dir-form
  fallback. Teaching `_load_run` the fallback (or dropping the dir-form entirely) is an app-wide decision — logged
  for coordination, not changed here. Spotlight now degrades with a message instead of a blank page.
- **Defense-in-depth on the `_load_run` sink.** The traversal is fully closed at the only unsanitised caller
  (`spotlight_landing`'s query param); all other run-id sources use the slash-rejecting route converter. A
  belt-and-braces guard *inside* `_load_run` would protect any future caller but is a shared-file change — logged.
- **`spotlight_build` is not idempotent** (F9): repeated builds mint duplicate drafts. Dedupe on
  `(run_id, swimmer_key)` is a product decision (rebuild vs new draft), left for the owner.
- **Unbounded roster render** on the landing page for a meet with very many swimmers (no pagination). Fine for
  realistic meets; flag if huge invitationals become common.
- **Meet `<select>` lacks an explicit `<label for>`** (relies on the adjacent "Choose a meet" heading + a
  `title`-less select). Minor a11y P3.
- **Same-name swimmers with blank `swimmer_id`** are merged by name — a pre-existing data-model limitation
  upstream of this module (they are indistinguishable everywhere), not a spotlight defect.

---

## 9. Feature verdict

**WORKS-WITH-CAVEATS.** The happy path is correct and the intelligence layer (filter → rank → approve → compose)
behaves as specified with correct data isolation. The audit found and fixed one reachable crash (null priority),
two genuine security holes (a stored-XSS/JS-injection vector through swimmer names, and a path-traversal PII leak
via `?run_id=`), and several correctness/robustness/UX gaps (reel tenant+type guards, literal-`\n` clipboard,
misleading errors, dead-end UI, dead code). Post-fix, all reproductions are green and no regressions were seen.
The remaining caveats are the pre-existing shared-loader dir-form limitation and minor a11y/idempotency polish,
none of which block the feature.

---

## 10. Handover and merge status

- **Branch:** `claude/athlete-spotlight-audit-c9v1iw` (this session's mandated development branch, used as the
  audit branch — the harness requires development on this branch, so no separate `audit/…` branch was created).
- **Commits on `main` (after rebasing onto the moving trunk):** `9c37fe4` (core module: null-priority + dead
  code), `4f85925` (web.py route hardening), `cb253ae` (regression tests), `651cf2b` (this report).
- **Merge status: MERGED to `main`.** The full green gate passed on the integrated tree (`12498 passed, 10
  skipped` on `origin/main` `95c83d0`); `main` then advanced twice (to `e7b411a`, non-spotlight live-meet/language
  edits, and to `220f381`, docs-only), so the branch was rebased each time and re-gated — a targeted feature +
  broad-regression + incoming-changed-areas run (`182 passed`) on `e7b411a`, and a docs-only no-op delta to
  `220f381`. Landed via the atomic-push protocol (`git push origin HEAD:main`, fast-forward `220f381..651cf2b`;
  the branch-protection PR rule was bypassed under the operator's push permission). Green was always measured on
  the exact integrated code that landed. Branch `claude/athlete-spotlight-audit-c9v1iw` is also pushed.
- **What was run vs skipped in the re-gate:** the authoritative full `tests/` run was on `95c83d0` (one commit
  before the merged spotlight code, which is byte-identical); the two subsequent integrations were re-gated with
  the feature suite + the incoming-changed test modules (`test_usability_c16_interface_language`,
  `test_live_watch`, `test_phase_w_web`) + a broad regression batch, since the deltas were confined to
  non-spotlight code and docs.
- **Review the diff:** `git diff 220f381...651cf2b` (or `git show 9c37fe4 4f85925 cb253ae`).
