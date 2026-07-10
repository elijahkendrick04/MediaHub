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
| F7 | P2 | Legacy dir-form meet selectable but opens blank | select a run stored only as `runs_v4/<id>/run.json` → the picker keeps it (self-heal accepts the dir form) but `_load_run` can't read it → blank page, no roster, no message | `_load_run` read only the flat `<id>.json` | **fixed (caveat round):** dir-form fallback centralised in `_load_run` so it opens; honest message retained for other unopenable cases | 2419686 |
| F8 | P3 | Dead `QualityBand` map + one literal em dash | `band_labels`/`QualityBand` import unused (`athlete_spotlight.py`); literal `—` in the "Everything is approved" status line | dead code left after refactor; house style uses `&mdash;` | **fixed** | b806a11, ec3c955 |
| F9 | P3 | `spotlight_build` mints a duplicate draft on re-submit | POST `/spotlight/<run>/<sw>/build` twice → two independent drafts | `save_pack` mints a fresh uuid each call; no `(run_id, swimmer_key)` dedupe | **fixed (caveat round):** rebuild-in-place — same `(run_id, swimmer_key)` refreshes the existing draft, preserving approved status | 2419686 |
| F10 | P2 | Unbounded roster render on the landing page | a meet with ~400 swimmers renders ~400 inline-styled cards → 1.3s / 820KB page | no cap/pagination on the swimmer grid | **fixed (caveat round):** capped at 120 (sorted by achievements) + a "see the rest in the full review" note | 2419686 |
| F11 | P3 | Meet/tone `<select>` lacked a programmatic label | only an adjacent heading / `title` attribute; no `<label for>` for AT | a11y gap | **fixed (caveat round):** both selects carry `<label for>` + `aria-label` | 2419686 |
| F12 | P1 | Path-traversal sink not hardened at source (defense-in-depth) | any future caller passing an unsanitised run_id to `_load_run` could traverse | the F3 fix was local to `spotlight_landing` only | **fixed (caveat round):** `_load_run` now rejects `/`, `\`, `..` for every caller | 2419686 |

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

**Caveat round (`2419686`), fixing the §8 residual items:**
- **`src/mediahub/web/web.py` — `_load_run`:** centralised the legacy `runs_v4/<id>/run.json` dir-form fallback
  (~15 routes hand-rolled it) so every run-scoped surface — including the spotlight picker — opens dir-form runs
  (F7); added a path-separator/`..` guard so the traversal sink is closed for *every* caller, not just
  `spotlight_landing` (F12, the F3 defense-in-depth residual).
- **`spotlight_build`:** idempotent rebuild-in-place — a matching `(run_id, swimmer_key)` spotlight pack is updated
  in place (same pack id, preserving an already-approved card's status and any planned date) instead of minting a
  duplicate draft (F9).
- **`spotlight_landing`:** caps the roster render at 120 swimmers (already sorted by achievement count) with an
  honest "showing N, open the full meet review for the other M" note (F10); meet `<select>` gets `<label for>` +
  `aria-label` (F11).
- **`spotlight_view`:** caption-tone `<select>` gets `<label for>` + `aria-label` (F11).

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

**Caveat round** (same module, `e462a3b`):
- `test_spotlight_landing_opens_legacy_dir_form_run` — F7 (dir-form now loads + shows the roster; unit on
  `_load_run` reading the nested form).
- `test_load_run_rejects_path_traversal` — F12 (`/`, `\`, `..`, empty all → `None`).
- `test_spotlight_landing_caps_large_roster` — F10 (200 swimmers → 120 links + the note + honest total).
- `test_spotlight_selects_are_labelled` — F11 (both selects carry `<label for>`).
- `test_spotlight_build_idempotent_rebuild_in_place` — F9 (3 builds → 1 pack, same redirect, approved status
  preserved on rebuild).
- `test_spotlight_landing_message_for_unopenable_run` updated to use a corrupt flat file now that the dir-form
  legitimately loads.

The existing `tests/test_spotlight_build_brand_grounding.py` and `tests/test_ui2_athlete_tooltips.py` still pass
unchanged, as do the run-loading routes that share `_load_run` (review, content pack, public wall, drafts, reel).

---

## 7. Cross-cutting changes

The first round (F1–F8) touched **no** shared helper signature or behaviour — every edit was inside the spotlight
route bodies / helpers / core module.

**The caveat round makes ONE shared-helper change, called out here for reconciliation:**

- **`src/mediahub/web/web.py` — `_load_run(run_id)`** now (a) falls back to the legacy `runs_v4/<id>/run.json`
  dir-form when the flat `<id>.json` is absent, and (b) returns `None` for any `run_id` containing `/`, `\`, or
  `..`. This is a run-loading helper used by ~all run-scoped routes (`/review`, `/pack`, `/audit`, `/drafts`,
  public wall, reel, …). The change is **strictly additive and backward-compatible**: the flat path is tried
  first and unchanged; the dir-form is only consulted when the flat file is missing (the same fallback ~15 routes
  already implemented locally); the guard only rejects values no legitimate uuid-hex run id ever contains.
  Verified against the run-loading test modules (review body, content pack, public wall, drafts, reel, gen-v2
  end-to-end, large-meet durability, phase-w web, caption assist — all green) plus the full suite. Other sessions
  editing `_load_run` should reconcile against this.

---

## 8. Residual risks / cross-feature items (not fixed here)

- **Same-name swimmers with blank `swimmer_id`** are merged by name — a genuine data-model limitation *upstream*
  of this module (the interpreter keys swimmers as `club:last,first`; two distinct people with identical names and
  no member id are indistinguishable everywhere, not just in spotlight). Fixing it means an identity/disambiguation
  change in the pipeline, outside this feature's blast radius.
- **Idempotency dedupe scans the 200 most-recent drafts.** `spotlight_build`'s rebuild-in-place match uses
  `list_packs(limit=200)`; an org with >200 drafts *and* an older matching spotlight beyond that window could still
  mint a second draft. 200 is far beyond any realistic per-org draft count; raising it or adding a
  `(run_id, swimmer_key)` index is a `stub_pack_store` change left for the owner if it ever bites.
- **Roster cap hides the long tail.** The 120-swimmer cap is sorted by achievement count and links to the full
  meet review for the rest, which suits the "feature your top swimmers" purpose; a searchable/paginated roster
  would be the fuller answer if clubs routinely spotlight from 400-swimmer invitational uploads.

---

## 9. Feature verdict

**WORKS.** The happy path is correct and the intelligence layer (filter → rank → approve → compose) behaves as
specified with correct data isolation. The audit found and fixed one reachable crash (null priority), two genuine
security holes (a stored-XSS/JS-injection vector through swimmer names, and a path-traversal PII leak via
`?run_id=`), and several correctness/robustness/UX gaps (reel tenant+type guards, literal-`\n` clipboard,
misleading errors, dead code). The **caveat round** then closed every actionable residual: the legacy dir-form
now opens (F7), the traversal sink is hardened for all callers (F12), rebuilds are idempotent (F9), the roster
render is bounded (F10), and both selects are labelled (F11). Post-fix all reproductions are green and no
regressions were seen across the run-loading routes that share `_load_run`. The only items left open are a
genuine upstream identity-model limitation (same-name/blank-id swimmers) and two deliberate design ceilings
(200-draft dedupe window, top-120 roster) — none a defect in this feature.

*(Verdict lifted from WORKS-WITH-CAVEATS to WORKS after the caveat round, 2026-07-10.)*

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

### Caveat round (2026-07-10) — residual items fixed, verdict lifted to WORKS

- **Caveat commits on `main`:** `d5d2586` (fixes: dir-form loading, `_load_run` traversal guard, idempotent
  build, roster cap, select labels), `d93a4ee` (regression tests), `208cea1` (this report update). All three are
  SSH-signed (the earlier first-round commits were unsigned because the ephemeral signer was absent that session;
  GitHub verifies these against the `claude` bot key — local `git %G?` still reads "N" only because the
  environment ships no `allowedSignersFile` to verify against).
- **Merge status: MERGED to `main`.** Full suite on the integrated tree at `origin/main` `9b7d0a7`:
  **12553 passed, 10 skipped, 1 failed** — the single failure, `test_log_sentinel.py::test_boot_grace_blocks`, is
  an order/timing flake unrelated to this feature (it asserts a since-boot grace window and trips on the 48-minute
  full-run length; it **passes in isolation** in 0.25s and references none of the changed code). `main` then
  advanced to `2a34d72` (a large batch of other audit sessions touching `web.py`, `public_wall.py`,
  `documents/*`, `content_types.py`, …); the branch was rebased onto it (re-signing each commit) and re-gated with
  a targeted feature + incoming-changed-area + run-loading regression run (**141 passed**), since the full run one
  base prior covers the byte-identical spotlight code. Landed via the atomic-push protocol
  (`git push origin HEAD:main`, fast-forward `2a34d72..208cea1`; the branch-protection PR rule bypassed under the
  operator's push permission).
- **Cross-cutting note (see §7):** this round changed the shared `_load_run` helper (dir-form fallback + traversal
  guard) — additive and backward-compatible, verified green against the run-loading routes (`/review`, `/pack`,
  public wall, drafts, reel, gen-v2 end-to-end, large-meet durability) both in the full run and the re-gate.
- **Review the caveat diff:** `git show d5d2586 d93a4ee`.
