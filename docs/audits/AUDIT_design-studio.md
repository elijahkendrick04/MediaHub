# Audit — Design Studio (Create ▸ Design studio)

**Feature:** The "Design Studio" — the interactive brief/design editor reached from the Create tab.
**Mode:** AUDIT+FIX.
**Branch:** `claude/design-studio-audit-x8856m` (this session's designated audit branch; see *Handover* for the branch-name reconciliation).
**Auditor:** Claude (Opus). Autonomous, ultracode.
**Date:** 2026-07-10.

---

## 1. Scope contract

**Definition.** The Design Studio is MediaHub's explicit, deterministic playground for a *single* still
graphic. A user dials four design levers — **archetype, style pack (ground/texture/accent/density),
palette (+ advanced colour-role assignment), and text layers** — plus an output **format**, and the
server re-renders the card **live on the real engine** (`creative_brief.CreativeBrief` →
`graphic_renderer.render_brief`), returning a PNG data-URI preview and an explainability sidecar
(resolved `--mh-*` roles, the pack's *why*, the archetype summary, and honest notices when a colour-role
swap is rejected for legibility or the style-pack levers are eased under the taste cap). "Working" means:
every lever faithfully changes the rendered pixels; the preview is a light but geometry-faithful mirror
of the full-resolution download; garbage input is coerced to safe defaults and never 500s or corrupts;
every control does exactly what its label implies; and the explainability sidecar is honest.

**Routes owned.**
| Method | Path | Endpoint |
| --- | --- | --- |
| GET | `/studio` | `design_studio` |
| POST | `/api/studio/render` | `api_studio_render` |

**Files owned (blast radius, freely editable).**
- `src/mediahub/web/design_editor.py` — the pure/Flask-free studio module: vocabulary, `coerce_params`
  (the trust boundary), `StudioParams`, brief construction, `explain`, `render_editor_body` (page HTML +
  scoped CSS + client JS).
- `tests/test_design_editor_g1_27.py` — the feature's test module (extended here).

**Shared files depended on (NOT freely rewritten).**
- `src/mediahub/web/web.py` — the two routes `design_studio` / `api_studio_render`, and the shared render
  helpers `_studio_render_cache` (BoundedCache), `_render_slot`/`_render_semaphore` gate,
  `_render_busy_response`, `_layout` (nav). One 1-line change made here — see *Cross-cutting changes*.
- `graphic_renderer/` (`render_brief`, `resolved_role_vars_for_brief`, `archetypes`, `style_packs`) — the
  deterministic engine; consumed, not modified.

**Inputs / outputs / state.** Input: a JSON body of coerced levers (or an all-defaults request). Output:
`{ok, image (data-uri PNG), meta (explainability), render_ms}`, or an honest error payload. **No tenant
data is read or written** — the brief is built entirely from the (coerced, renderer-safe) request; the
only per-session read is the GET page seeding its colour pickers from the signed-in org's brand kit. The
in-memory `_studio_render_cache` (max 48) dedupes identical requests.

**Happy path (concrete expected result).** Open `/studio` → the editor renders with the org palette seeded
and an initial preview of the default archetype → change any lever → a debounced POST re-renders the exact
card and updates the preview + explainability → "Download PNG" ships the full-resolution PNG named
`<archetype>_<format>.png`.

---

## 2. Environment

- Ran locally from `create_app()` on `http://127.0.0.1:8765` (Werkzeug dev server, threaded), `DATA_DIR`
  pointed at an out-of-tree scratch dir. No real API keys (the app honest-errors on AI surfaces; the
  studio itself needs no AI).
- Playwright/Chromium: the prebaked `/opt/pw-browsers` Chromium (rev 1194) matches the session's pinned
  Playwright 1.56; real renders work. The Playwright MCP browser was pointed at the same binary.
- A ready org profile ("Manchester Swimming Club", manual palette) was seeded on disk so the first-run
  org-gate could be passed via the normal sign-in picker to reach `/studio` as a real user would.
- Backend repros used `app.test_client()` with `TESTING=True` (bypasses the org gate, exactly as the
  existing tests do) and monkeypatched `render_html_to_png` to stub Chromium where a real render wasn't
  the point.
- No real paid API calls, no external publishing, no destructive actions.

---

## 3. Test matrix results

| # | Dimension | Result | Note / evidence |
| --- | --- | --- | --- |
| 1 | Functional correctness | PASS | Happy path renders the correct card; every lever reaches the brief and the pixels (real renders across 3 formats). Existing Tier-3 tests + live drive. |
| 2 | Every interactive control | PASS (after fix) | All selects/inputs/buttons drive a re-render. Fixed: silent Download failure (F4), 3-digit-hex swatch desync (NEW-2), invalid-hex preview/download mismatch (F5). |
| 3 | Input validation & edge cases | PASS | Garbage coerces to safe defaults; text capped/whitespace-collapsed; unicode/emoji safe; empty/non-JSON body → defaults. Fixed the `full:"false"` truthy-string footgun (NEW-4). |
| 4 | UI state handling | PASS (after fix) | Loading/empty/success states correct; overlay hides via `[hidden]`. Fixed: error overlay wiped on Download failure (F4); 429 shown as generic failure (NEW-1). |
| 5 | Server-side error handling | PASS | 503 renderer-unavailable / 500 render-failed / 429 busy all return correct status + safe copy, no stack trace / path leak (bare `Exception` → generic message, detail server-side only). |
| 6 | Data integrity | PASS (after fix) | What you type is what renders; no cross-tenant leak (no tenant data touched). Fixed: cache key omitted `pack_eased` → stale/false "eased" explainability notice (F2). |
| 7 | Security | PASS | XSS: text layers **and** the club-name→lettermark path are HTML-escaped (verified with `<script>`/`<img onerror>`/`</style><svg>` payloads — no raw tag reaches the card HTML). CSS injection: palette is hex-gated by `_clean_hex` (rejects `url()`, `;`, `}`, 4/5/7/8-digit). No auth/IDOR risk (routes read/write no tenant state; JSON CSRF-exempt by content-type is correct). No secret/key leak in any response. |
| 8 | Performance | PASS | Render gated by the shared Chromium semaphore; identical requests deduped by the signature cache; `explain()`'s extra role-resolves are cheap (no Chromium) and only on a cold render. No O(3193-pack) or O(34-archetype) work on the request path. |
| 9 | Responsive & a11y | PASS (after fix) | 390px → single column, no horizontal overflow; `:focus-visible` outlines present. Fixed: unlabelled Archetype/Format selects + hex inputs (F1); non-live render/error overlay (NEW-3). |
| 10 | Rendered-graphic correctness | PASS (1 logged, out of scope) | Real PNGs are valid, at the exact target geometry, non-blank, and re-render byte-stable (Tier-3 tests pin single-card/orientation/geometry; preview composes at native geometry like the download — QA-011). Logged F7: `mega_surname_bleed` collides a long club name with the result chip — an archetype-layout defect in `graphic_renderer/`, outside the studio's blast radius. |
| 11 | Consistency & copy | PASS (1 logged) | British English throughout; no placeholder/debug/TODO strings. Logged: em dashes in the studio's own copy (house style across the whole product — see F-em). |

---

## 4. Findings

Severities: P0 broken/data-loss/security · P1 wrong behaviour or a control that lies · P2 usability/a11y/error-handling · P3 polish.

| ID | Sev | Title | Reproduction | Root cause | Status | Commit |
| --- | --- | --- | --- | --- | --- | --- |
| F1 | P2 | Archetype/Format selects + palette hex inputs unlabelled (a11y) | Screen-reader name probe on `/studio`: archetype & format selects resolve to no accessible name; the 3 hex inputs are nameless (the wrapping `<label>` binds to the colour swatch only). | Selects sit after an `<h2>`, not inside a `<label>`; hex input is the 2nd control under a shared `<label>`. | **Fixed** | 39a10ed |
| F2 | P2 | Render cache key omits `pack_eased` → stale/false "levers eased" notice | Two requests over the same decorative levers at Bold (eased) vs Standard (direct) resolve to the same `pack_id` → identical `signature()` → the 2nd is served the 1st's cached `meta`, so the honest "eased" notice is dropped or fabricated. Reproduced via `coerce_params` + route. | `StudioParams.signature()` did not include `pack_eased`, which changes `meta.notices` but not pixels. | **Fixed** | 39a10ed |
| F3 | P2 | Design Studio orphaned in the nav (nothing highlighted) | On `/studio`, no top-nav item has the `active` class; the Create link is not lit. | Route passed `active="studio"`, which matches no nav key (same class as the documented Video-Studio `active="video"` orphan, G-7). | **Fixed** | 39a10ed |
| F4 | P2 | Download PNG failure is a silent no-op | Hold the render slot so `/api/studio/render` 429s (or supersede a cold full render by changing a control mid-flight), click Download PNG: the "Rendering…" overlay flashes then vanishes — no file, no error. | The download handler ran `hideOverlay()` before the `if (!data) return` guard, erasing `render()`'s error overlay. | **Fixed** | 39a10ed |
| F5 | P3 | Invalid hex left in a field → preview/download mismatch | Set a valid colour, then edit the hex field to an invalid value (e.g. `#ff`): no re-render, no feedback; a subsequent Download sends the invalid hex → server coerces to the DEFAULT palette → the downloaded card differs from the shown preview. | `collect()` read the raw (invalid) hex field; the server defaults it while the preview still shows the last valid colour. | **Fixed** | 39a10ed |
| NEW-1 | P2 | 429 "renderer busy" shows a misleading dead-end "Render failed." | Simulate/produce a 429: the overlay reads "Render failed." instead of the "try again in a moment" guidance. | The busy payload carries `user_message`; the client only read `message`. | **Fixed** | a2692e7 |
| NEW-2 | P3 | A valid 3-digit hex turns the colour swatch black | Type `#abc` into a hex box: the `<input type=color>` swatch collapses to `#000000`, desyncing from the typed (and rendered) colour. | The swatch only accepts `#rrggbb`; the handler assigned the raw `#rgb`. | **Fixed** | a2692e7 |
| NEW-3 | P2 | Render/error overlay is not an ARIA live region | A screen reader announces neither "Rendering…" nor render errors. | The overlay lacked `role="status"`/`aria-live`. | **Fixed** | a2692e7 |
| NEW-4 | P3 | `full` accepts truthy junk (e.g. the string `"false"`) | `POST {"full":"false"}` renders the heavier full-resolution image. | `coerce_params` used `bool(data["full"])`; `bool("false")` is `True`. | **Fixed** | a2692e7 |
| F6 | P3 | Spurious legibility notice on a no-op role assignment | In advanced colour roles, set Ground → Primary (Primary is already the default ground): the "your swap was set aside to keep the text legible" notice fires, though nothing was rejected. Genuine rejections (Ground → Accent) still notice correctly. | `explain()` infers "rejected" from `resolved == plain`, which is also true for a no-op assignment; it cannot tell a no-op from a gate rejection without a hook into the engine's per-slot default-token map. | **Logged** (fix would touch the deterministic-engine boundary — out of scope for a tight, safe change) | — |
| F7 | P2 | `mega_surname_bleed` collides a long club name with the result chip | Real render of `mega_surname_bleed` with `club_full="Stockport Metropolitan Swimming Club"` (screenshot `scratch_audit/mega_surname_longclub.png`): the club name is painted starting at the gold result chip's right edge, with the "SM" superscript overlapping the chip — the footer crowds/obscures the time. | The archetype's footer row lays the result chip and the club line side by side with no width constraint / truncation for long club names. Lives in `graphic_renderer/` (the archetype layout), **not** the studio module. | **Logged — needs coordination** (out of the studio's blast radius; it is a deterministic-engine/archetype-layout defect that affects the archetype on *every* surface, with golden/parity-test implications — must not be fixed under a narrow studio audit) | — |
| F-em | P3 | Em dashes in the studio's own user-facing copy | The subtitle and explainability notices use "—". | House style — em dashes are used pervasively across every MediaHub surface; changing only the studio's would create inconsistency. Grammatically correct British English. | **Logged** (deliberately not "fixed" — would diverge from the product's consistent copy style) | — |

All fixed findings were reproduced first, then re-verified gone (live in the browser and via tests). The
independent audit workflow (fan-out finders + adversarial verifiers) corroborated F2, F4, F5, NEW-1,
NEW-2, NEW-3, NEW-4 with matching repros; F1, F3, F6 came from the live-browser accessibility/behaviour
probes.

---

## 5. Fixes applied

All engine/logic fixes are inside the blast radius (`design_editor.py`); one 1-line nav change is in the
shared `web.py` route (flagged below).

**`src/mediahub/web/design_editor.py`**
- `StudioParams.signature()` now includes `pack_eased` (F2) — distinct cache entries for eased vs direct
  resolutions of the same pack, so the honest notice is never stale.
- `coerce_params` — `full` now requires an explicit JSON boolean `true` (NEW-4).
- `render_editor_body` HTML — `aria-label` on the Archetype/Format selects and the three hex inputs (F1);
  `role="status" aria-live="polite"` on the render/error overlay (NEW-3).
- Client JS — download handler bails **before** `hideOverlay()` so a failure keeps its error on screen
  (F4); `collect()` falls back to the swatch's last-valid colour for an invalid hex (F5); the render-error
  branch reads `message || user_message` so a 429 shows its retry guidance (NEW-1); a new `expandHex()`
  widens `#rgb` → `#rrggbb` before assigning the swatch (NEW-2).

**`src/mediahub/web/web.py`** (shared — cross-cutting)
- `design_studio()` route: `active="studio"` → `active="create"` (F3), lighting the Create nav item.

---

## 6. Tests added / extended

All added to the existing `tests/test_design_editor_g1_27.py` under an "Audit hardening" section (40 → 51
tests, all pass):

- `test_studio_selects_and_hex_inputs_are_labelled` — F1: archetype/format/hex `aria-label`s present.
- `test_signature_distinguishes_eased_from_non_eased_same_pack` — F2 unit: same `pack_id`, different
  `pack_eased` → different signature.
- `test_render_cache_does_not_serve_a_stale_eased_notice` — F2 end-to-end: Standard-then-Bold notices stay
  correct through the real cache.
- `test_studio_page_highlights_the_create_nav` — F3: the Create nav link is `active` on `/studio`.
- `test_download_handler_keeps_its_error_overlay_on_failure` — F4: the failure guard precedes `hideOverlay()`.
- `test_collect_falls_back_to_swatch_for_an_invalid_hex` — F5: swatch fallback in `collect()`.
- `test_render_error_reads_busy_user_message` + `test_render_busy_payload_actually_uses_user_message` —
  NEW-1: the client reads `user_message`, and the real busy payload actually carries it (contract pinned
  on both sides).
- `test_three_digit_hex_widens_the_swatch` — NEW-2: `expandHex` used in the hex→swatch sync.
- `test_render_overlay_is_an_aria_live_region` — NEW-3: overlay is `role="status" aria-live="polite"`.
- `test_coerce_full_requires_an_explicit_boolean_true` — NEW-4: string/int junk for `full` → preview.

---

## 7. Cross-cutting changes

- **`src/mediahub/web/web.py` — 1 line in the `design_studio` route:** `active="studio"` → `active="create"`
  (F3). This only affects which nav item is highlighted when viewing `/studio`; it touches no other route,
  helper, or template, and is guarded by `test_studio_page_highlights_the_create_nav`. Minimal and
  low-risk, but flagged here for reconciliation with any parallel session editing `web.py`.

No changes to `requirements.txt`, `pyproject.toml`, base templates, shared CSS/JS, or config.

---

## 8. Residual risks / follow-ups (not attempted here)

- **F6 (spurious legibility notice on a no-op role assignment)** — a correct fix needs the engine's
  per-slot default-token mapping to distinguish a no-op assignment from a gate rejection. That reaches
  into the deterministic colour-role resolver (CLAUDE.md's protected boundary), so it is logged rather
  than fixed under a tight audit scope. Impact is minor (only the notice; the card is correct; the user
  has to assign a slot to its own default).
- **F7 (mega_surname_bleed footer collision)** — a real graphic defect (verified with a screenshot), but
  it lives in the `graphic_renderer` archetype layout, affects the archetype on every surface (not just the
  studio), and sits on the deterministic-engine boundary with golden/parity-test coverage. Deliberately not
  fixed under this narrow studio audit; needs coordination with a graphic-engine owner (likely: constrain
  the club line's width / truncate it, or drop it to its own row when the result chip is present).
- **F-em (em dashes)** — a product-wide copy-style decision, not a studio bug; out of scope to change one
  surface.
- **Surprise me** randomises archetype + style-pack levers only (not palette/text/format/roles). This is a
  reasonable "surprise the *design*, keep *your* content and colours" choice, not a defect — noted for the
  product owner in case broader randomisation is wanted.

---

## 9. Feature verdict

**WORKS-WITH-CAVEATS** — the Design Studio is fundamentally sound (correct renders, safe input handling,
no security holes, honest errors), but it shipped with nine real defects across accessibility, error
feedback, explainability integrity, and navigation. All nine are fixed and locked with tests; two minor
items (F6, em dashes) are logged with rationale. With the fixes in, the verdict for the shipped code is
**WORKS**.

---

## 10. Handover & merge status

- **Branch:** `claude/design-studio-audit-x8856m` (this session's designated branch). The task brief named
  an `audit/design-studio` branch; the session's standing git rule pins the designated branch above and
  forbids pushing to any other, so all work is on the designated branch — the equivalent of the audit
  branch. Per the repo's PR workflow (and the "never push straight to another branch" rule), the change is
  delivered as a **draft PR** rather than a direct push to `main`.
- **Merge status:** delivered as **draft PR [#1122](https://github.com/elijahkendrick04/MediaHub/pull/1122)**
  (`claude/design-studio-audit-x8856m` → `main`). Not merged directly to `main`: the session's git rules
  forbid pushing to any branch but the designated one and require a PR, so CI + GitHub's up-to-date gate is
  the merge gate. `origin/main` moved several times during the audit (ce1abd2 → … → ca6f025, ~49 commits);
  the branch was rebased onto the latest each time — the final integration base is **`ca6f025`**, branch
  head **`7180262`**. The 15+15 new commits touched none of the studio's files, so every rebase was clean.
- **Green gate (on the integrated tree, base `ca6f025`):** the app boots clean (509 routes) and unrelated
  routes load; the 51 studio-module tests pass; and the **full suite ran 12,501 passed / 10 skipped / 2
  failed**. The 2 failures are `tests/test_p6_3_subject_lift.py` (rembg background-removal) — a pre-existing,
  environmental test-isolation flake, **not** caused by this change: they pass in isolation on this branch
  and on a clean `origin/main` worktree, and fail only under full-suite ordering because the sandbox blocks
  the rembg ONNX model download (`403 Forbidden`). The diff touches none of that code (proven: change set is
  exactly the 4 files below). No new failures were introduced.
- **Review the diff:** `git diff origin/main...claude/design-studio-audit-x8856m` (change set:
  `src/mediahub/web/design_editor.py`, `src/mediahub/web/web.py`, `tests/test_design_editor_g1_27.py`,
  `docs/audits/AUDIT_design-studio.md`).
