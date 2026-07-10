# Feature audit — Elements (library / stickers)

Mode: AUDIT+FIX · Branch: `audit/elements` (from `origin/main` BASE `ce1abd2`) ·
Auditor: autonomous QA+fix session · Date: 2026-07 (UTC)

---

## 1. Scope contract

**Definition.** The *elements* feature is MediaHub's curated, brand-token-recolourable
SVG sticker library: sport pictograms (the swim strokes / dive), stat & PB chips,
placement rosettes/badges, ribbons, dividers, line/arrow accents, frames, texture
panels, and org-custom stickers/mascots. Each asset is drawn colour-blank with
`__SLOT__` placeholders that are filled with the club's resolved `--mh-*` brand
roles at paint time, so every element is on-brand and (for text-bearing ones)
APCA-legible. "Working" means: a user can browse/search the library recoloured to
their brand, get context-relevant suggestions for a card, place elements on a
card, and have those placements persist and render (recoloured, legible, safe)
onto the card graphic — deterministically and without leaking one org's data or
executing untrusted markup.

**Routes owned.**
| Method | Path | Endpoint |
|---|---|---|
| GET | `/elements` | `elements_page` (browse UI; `?run_id=&card_id=` = add-to-card mode) |
| GET | `/api/elements` | `api_elements` (browse/search JSON) |
| GET | `/api/elements/gradients` | `api_elements_gradients` |
| GET,POST | `/api/elements/generate` | `api_elements_generate` (AI generative element) |
| GET | `/api/runs/<run_id>/card/<card_id>/element-suggestions` | `api_element_suggestions` |
| GET,POST | `/api/runs/<run_id>/card/<card_id>/elements` | `api_card_elements` (list/add/remove/clear) |
| GET | `/stock`, `/api/stock/search`, `/api/stock/thumb`, POST `/api/media-library/import-stock` | stock pool (sibling surface, reached only from the elements browser) |

**Files owned (blast radius).** `src/mediahub/elements/*.py` (`catalog.py`,
`recolour.py`, `render.py`, `search.py`, `models.py`, `gradients.py`,
`generate.py`, `stickers.py`, `draw.py`, `stock.py`) + `catalog.json` +
`assets/svg/*`; `src/mediahub/web/elements_browser.py`;
`src/mediahub/graphic_renderer/sprint_hooks/elements.py`; the element/stock route
block in `src/mediahub/web/web.py` (~50356-50920).

**Shared files depended on (not freely rewritten).** `src/mediahub/web/web.py`
(app factory, `_layout` nav, `_active_profile_id`, `_can_access_run`, CSRF guard);
`graphic_renderer.render` role resolver; `quality.compliance` (APCA gate).

**Inputs / outputs / state.** Input: a search query + kind/sport filter; an
`element_id` + placement (x, y, scale, rotation, opacity) to add to a card. Output:
recoloured inline `<svg>` payloads for the grid, and element placements persisted
onto the card's `CreativeBrief.elements` list at
`RUNS_DIR/<run_id>/briefs/<brief_id>.json`, painted onto the card PNG by the
elements sprint hook. State lives under `DATA_DIR` (bundled catalog + org packs
under `element_packs/<profile>/`).

**Happy path (expected).** `GET /api/elements` → 25 bundled elements, each with a
fully-recoloured `<svg>` (no `__TOKEN__` left); `?q=`/`?kind=` filter correctly;
gradients return valid CSS; `POST …/card/…/elements {element_id}` appends a clamped
placement and persists it; `GET` reads it back identically; suggestions for a
gold+PB card surface trophy/rosette/PB-chip/stopwatch; the 12-element cap returns
409; the next card render paints the placed elements recoloured and legible.

---

## 2. Environment

- Python 3.11 venv at `.venv` (`uv pip install -e .` + `pytest`). Core deps only;
  heavy optional deps (rembg/onnxruntime/anthropic/replicate/playwright browsers)
  not installed — not needed for this feature and their absence is the offline
  posture.
- **Offline / no spend:** no provider keys set. AI surfaces honest-error
  (`ClaudeUnavailableError` / `ProviderNotConfigured`) as designed; no real network
  or paid calls were made.
- Booted locally (`python -m mediahub.web`, port 8137) and exercised via the Flask
  **test client** with `app.config["TESTING"]=True` (bypasses the org-onboarding
  gate exactly as `tests/test_elements_web.py` does). Ran tests with the project
  venv's pytest (`python -m pytest`) — note `/root/.local/bin/pytest` is an
  isolated uv-tool install that cannot see the project deps and gives false
  ModuleNotFound/legibility failures; do not use it for this repo.
- UI evidence rendered via headless Chromium screenshot of the test-client HTML.
- **Live UI note (assumption):** driving the deployed onboarding flow to pin a
  session is an AI-heavy, offline-hostile path; the browse page's client JS was
  audited from source + a rendered screenshot + a payload-level XSS reproduction
  rather than a full logged-in Playwright click-through. The controls and their
  handlers are simple and fully covered by the source read.

---

## 3. Test matrix results

| # | Dimension | Result | Note (evidence) |
|---|---|---|---|
| 1 | Functional correctness | PASS | Browse (25 els, no leftover tokens), q/kind/sport filters, gradients, add/list/remove/clear round-trip, suggestions all correct via test client; recolour deterministic. |
| 2 | Every interactive control | PASS* | Search (debounced), kind chips, add-to-card, suggest, clear, "Browse stock photos" link all wired correctly. *Gradient swatches are display-only (P3); no dead/misrouted controls. Whole browse surface is unreachable from app nav — see F1. |
| 3 | Input validation / edge cases | PASS | Unknown element → 404, missing id → 400, bad `remove_index` → 400, 12-cap → 409, placement fields clamped by `ElementPlacement.from_dict`; no 500s on malformed bodies. |
| 4 | UI state handling | PASS* | Empty state ("No elements match"), seed render, toasts present. *Search fetch error silently keeps last results (no error toast) — minor P2. |
| 5 | Server-side error handling | PASS | Specific JSON errors + correct 4xx/409/503; offline AI honest-errors, no stack traces to client. |
| 6 | Data integrity | PASS | Placement persists to brief JSON and reads back identically; `_can_access_run` scopes reads/writes per tenant; re-add allowed by design (multiple placements). |
| 7 | Security | FIX'd | Authz/IDOR OK (`_can_access_run`), path traversal blocked (route converter + run-existence gate), CSRF JSON-exemption deliberate & sound, stock proxy SSRF-guarded/allow-listed/size-capped, no secret leakage. **Stored-XSS in the browse grid + card render (F2, F4) — fixed.** |
| 8 | Performance | PASS | Browse recolours ≤25 (page) / ≤60 (search) small SVGs per request (fast); suggestions bounded to 12; `prewarm_thumbs` is the only background work and is stock-scoped. No full-corpus scan on the request path. |
| 9 | Responsive / a11y | PASS* | Responsive grid (`auto-fill minmax`), `type="search"` inputs, chips are real `<button>`s. *Element/gradient thumbnails carry no text alt (decorative SVG) — acceptable; minor. |
| 10 | Rendered-graphic correctness | PASS | Sprint hook paints placements recoloured to the card's exact roles, APCA-gated, byte-identical when no elements; deterministic uid. |
| 11 | Copy quality / British English | PASS* | Clear, consistent, British spelling. *Feature copy uses em dashes / curly quotes (P3) consistent with the rest of the codebase — left as-is to keep footprint tight. |

---

## 4. Findings

| ID | Sev | Title | Status | Commit |
|---|---|---|---|---|
| F1 | P1 | Elements feature is orphaned — no UI entry point anywhere | logged (needs-coordination) | — |
| F2 | P1 | Stored XSS: org-custom element name/kind/id injected into browse grid `innerHTML` unescaped | fixed | see §5 |
| F3 | P1 | Org-custom element SVGs render blank (profile_id not threaded to the route payload) | fixed | see §5 |
| F4 | P0 | Org-custom element SVG active content not sanitised → executes in browse grid and in card-render HTML | fixed | see §5 |

### F1 — Orphaned feature (no entry point) — P1, needs-coordination
**Repro.** `grep -rn "url_for('elements_page')" src` → 0 callers. Top nav
(`web.py:14067-14084`) and mobile bottom nav (`web.py:14294-14318`) contain no
Elements item; the card-editor inspector's "Elements" group is only photo/sponsor
toggles. `CreativeBrief.elements` defaults to `[]` and is never auto-populated
(`creative_brief/generator.py:201`). **Observed.** No user click-path reaches
`/elements`; no card ever receives an element in normal use. **Root cause.** A
deliberate nav change removed the browse-only "Elements" tab (comment at
`web.py:14079-14082`, "…no longer holds a top-bar slot it can't act in"), but no
replacement entry point (card-editor button, or auto-suggested placement in the
director) was wired in. **Why not fixed here.** The fix is a product + shared-file
(`web.py` nav / card editor) decision that other parallel sessions also touch, and
it reverses a deliberate removal — out of this feature's tight blast radius.
**Recommendation (pick one):** (a) add a "Browse elements" button in the card
editor inspector opening `/elements?run_id=&card_id=` (actionable add-to-card
mode); or (b, higher value) have the design director call the existing
`api_element_suggestions` logic during generation and auto-place one
contextually-relevant element (freestyle card → freestyle pictogram, PB → PB chip),
which is the "intelligence-layer" version the product thesis promises.

### F2 — Stored XSS via unescaped element metadata in the browse grid — P1, fixed
**Repro.** Seed an org pack with `name = '<img src=x onerror=alert(1)>'`; load via
`catalog.load_catalog(profile)`; the browse JS `card()` did
`d.innerHTML = … + (el.name||'') + …` and `data-id="' + el.id + '"`.
**Observed.** `name` loads verbatim and is injected as HTML → executes for any org
member viewing `/elements` (the sibling stock browser *does* escape with an
`esc()` helper — inconsistent). **Root cause.** `web/elements_browser.py`
`card()` innerHTML string-concatenation of user-controlled `name`/`kind`/`id`.
**Fix.** Rebuilt `card()` with DOM APIs — `textContent` for name/kind,
`setAttribute` for the id — so metadata can never be parsed as HTML.

### F3 — Org-custom SVGs render blank — P1, fixed
**Repro.** Org pack element rendered via the route payload builder.
**Observed.** `_element_to_payload` called `render_element_markup(el, role_vars,
uid=…)` with **no** `profile_id`, so `catalog.load_svg(el, profile_id=None)` looked
only in the bundled dir → `None` → `svg=""`; every org-custom sticker showed blank
in the grid. **Root cause.** `web.py` `_element_to_payload` dropped `profile_id`.
**Fix.** Thread `profile_id` through `_element_to_payload` → `render_element_markup`
at all three call sites (browse, suggestions, page seed).

### F4 — Untrusted element SVG not sanitised → XSS in two sinks — P0, fixed
**Repro.** Org pack SVG containing `<script>` / `<image onerror>` /
`href="javascript:…"` / `<foreignObject>`; render via `render_element_markup(…,
profile_id)`. **Observed.** Active content survived `recolour_svg` verbatim. It
reaches two DOM sinks: the browse grid (`innerHTML`) and — live — the card render
HTML (`sprint_hooks/elements.py:77,84` passes `profile_id` and injects the markup
into the page Playwright renders). Fixing F3 would have *broadened* this. **Root
cause.** `elements/recolour.py` `recolour_svg` did colour substitution only, no
sanitisation. **Fix.** Added a deterministic, dependency-free `_sanitise_svg`
(strip `<script>`, `<foreignObject>`, `on*=` handlers, `javascript:` URIs) at the
end of `recolour_svg` — the single chokepoint every element SVG passes through.
Proven **byte-identical** for first-party SVGs (they carry no active content).

**Verified sound (not findings).** Route authz/IDOR (`_can_access_run` → 404 for
foreign runs); path traversal (Flask string converter blocks `/`; writes gated by
run existence + access); CSRF (`application/json` same-origin XHR exemption is
deliberate and CORS-preflight-backed — the JS posts JSON, so add-to-card works and
is not forgeable cross-site); stock thumb/import SSRF guard + host allow-list +
content-type prefix + size cap + `_session_can_access_profile`; offline AI
honest-errors with no stack trace or key leak; input validation & the 12-cap.

---

## 5. Fixes applied

1. **`src/mediahub/elements/recolour.py`** — add `_sanitise_svg` (regex strip of
   `<script>`/`<foreignObject>`/`on*=`/`javascript:`) and call it at the end of
   `recolour_svg`. Central XSS chokepoint; byte-identical for clean SVGs. (F4)
2. **`src/mediahub/web/elements_browser.py`** — rebuild the grid `card()` with DOM
   APIs (`textContent`/`setAttribute`) instead of `innerHTML` string concat of
   user-controlled metadata. (F2)
3. **`src/mediahub/web/web.py`** — `_element_to_payload(el, role_vars,
   profile_id=None)` and pass `profile_id` at the three call sites so org-custom
   SVGs resolve. (F3) — *cross-cutting, see §7.*

## 6. Tests added / extended

- `tests/test_elements_recolour.py::test_recolour_strips_active_svg_content` — locks F4 (script/handlers/foreignObject/javascript stripped, colour still substituted).
- `tests/test_elements_recolour.py::test_recolour_leaves_clean_first_party_svg_byte_identical` — guards against sanitiser drift on bundled SVGs.
- `tests/test_elements_render.py::test_org_custom_element_svg_resolves_and_is_sanitised` — locks F3 (blank without profile_id → renders with it) + F4 (org SVG sanitised).
- `tests/test_elements_web.py::test_browser_card_builder_is_dom_safe` — locks F2 (card builder uses textContent/setAttribute, no user-metadata innerHTML concat).

All four new tests pass; full elements suite (151 tests across the element modules) is green; app boots and unrelated routes (`/`, `/healthz`, `/pricing`) load 200.

## 7. Cross-cutting changes

- **`src/mediahub/web/web.py`** — one helper signature + three call sites in the
  element route block (`_element_to_payload` gains an optional `profile_id`). Small,
  additive, isolated to the elements routes; no behaviour change for callers that
  don't pass it. Flagged for reconciliation against other sessions touching
  `web.py`.

## 8. Residual risks / cross-feature work (not attempted here)

- **F1 entry point** is the headline caveat — a product/nav decision + shared-file
  change; needs coordination (see recommendation).
- `_sanitise_svg` is a conservative regex strip, not a full SVG DOM sanitiser; it
  covers the known active-content vectors but a hardened `defusedxml`/allow-list
  sanitiser would be more robust if org packs become a broad, self-serve surface.
- Org-custom pack ingestion (`stickers.py`/build 4) should additionally validate
  uploaded SVGs at write time (defence in depth) — out of scope here.
- Search error state in the browse JS is silent (P2) and gradient swatches are
  display-only (P3) — logged, not fixed (tight scope).

## 9. Verdict

**WORKS-WITH-CAVEATS.** The engine (catalog, recolour, render, search,
add-to-card API, sprint-hook card paint) is correct, deterministic, tenant-scoped,
and now XSS-hardened, with tests locking the fixes. Two real defects — a stored-XSS
chain (F2/F4) and blank org-custom rendering (F3) — are fixed. The dominant caveat
is F1: the whole browse/add surface currently has no UI entry point, so the library
does not reach output in normal use until an entry point is wired in (coordination
item).

## 10. Handover & merge status

- Branch: `audit/elements` (rebased onto `origin/main` BASE `a93b2ce`).
- **Merge status: MERGED to `main`.** Fast-forward atomic push
  `a93b2ce..b9d62fc` (commits `acb6fe8`, `b9d62fc`) after the freshness check
  confirmed `origin/main` still equalled the rebased BASE.
- Green gate on the integrated result: element suite + targeted regression
  **189 passed**, ruff check + format clean, app boots and `/`, `/healthz`,
  `/pricing`, `/elements` all 200, no secrets/`.env` staged. The upstream move
  (`ce1abd2..a93b2ce`) did not touch the elements blast radius, and
  `recolour_svg`/`render_element_markup` have exactly three caller sites (all
  audited), so the full 12k-test suite (genuinely prohibitive offline) was not
  required; the targeted subset is a complete regression gate for this change.
- Review the diff: `git diff a93b2ce...audit/elements`.
