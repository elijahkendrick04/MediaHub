# Audit — Event Preview (the "create" content type)

Mode: AUDIT+FIX. Auditor: automated QA + fix engineer session.
Feature branch: `claude/event-preview-audit-vhr4xq` (the harness-designated
branch; it fulfils the `audit/event-preview` role named in the task brief — the
same feature, the same blast radius, one branch to avoid a second head).

---

## 1. Scope contract

**Definition.** "Event Preview" is one of the four "create" content types. A user
opens `/weekend-preview`, tells us about an upcoming event (event name, optionally
the event website link, an uploaded meet pack, and a "ones to watch" choice — the
AI reads the entries source, or the user types the list), and the system builds an
English brief, runs it through the unified content engine (AI Director → writer),
and returns platform-ready preview caption cards (Instagram / Stories / Twitter)
that can be copied, turned into a branded graphic, approved, and saved. "Working"
means: the form renders and every control does what it claims; a submission with at
least one real, groundable source produces correct, on-brand, source-grounded
preview cards; an empty or unreadable submission is rejected cleanly rather than
guessed; the cards persist and can be approved; and none of this leaks secrets,
crashes, or is exploitable.

**Routes it owns**
- `GET/POST /weekend-preview` → `stub_weekend_preview` → `_render_stub("WeekendPreviewStub", …)`
- `POST /api/drafts/<pack_id>/card/<int:card_idx>/status` → `api_stub_pack_card_status` (approval pill; shared with the other three stubs)
- `POST /api/event-preview/parse-entries` → `api_event_preview_parse_entries` (W.6 entry-file helper — **currently unwired**, see F14)
- `POST /api/drafts/<pack_id>/regenerate` → `api_stub_pack_regenerate` (shared regenerate)

**Files it owns (blast radius)**
- `src/mediahub/club_platform/stubs.py` — `WeekendPreviewStub` (form, brief, guard) and `render_cards_html` (shared card renderer, but it is the Event Preview results surface)
- `src/mediahub/club_platform/content_types.py` — the `EVENT_PREVIEW` registry entry only
- The `WeekendPreviewStub` enrichment branch inside `_render_stub` in `src/mediahub/web/web.py` (lines ~34718-34817)

**Shared files it depends on but must NOT freely rewrite**
- `src/mediahub/web/web.py` app factory / CSRF / login layer, `_render_stub`, `api_stub_pack_card_status`
- `src/mediahub/web_research/safe_fetch.py` (SSRF-hardened fetcher)
- `src/mediahub/brand/guidelines.py` (`extract_text`), `src/mediahub/interpreter/lenex_parser.py` (LENEX), `src/mediahub/content_engine/…`, `src/mediahub/club_platform/stub_pack_store.py`, `post_types.py`

**Inputs / outputs / state.** Input: a multipart form (`meet_name`, `event_website_url`,
`event_pack`, `watch_mode` = ai|manual, `entries_url`, `entries_file`, `athletes`,
`angles`, optional `attached_photo` / library picks). Output: 1-N caption cards
rendered on the results page. State: the pack is persisted to
`DATA_DIR/stub_packs/<pack_id>.json` (with `profile_id` owner), approvable per card.

**Happy path (expected).** GET renders the hero + form + CSRF token. POST with a real
source enriches `form_data` (fetches the website/entries URL through `safe_fetch`,
extracts the pack/entries file via `extract_text` or the LENEX parser), builds a
brief that carries every provided source and instructs the model to ground the
preview and name only real entrants, generates cards, persists the pack, and renders
copy/approve/graphic controls. SSRF, XSS, path traversal, IDOR and CSRF are all
defended.

---

## 2. Environment

- Python 3.11.15 in a throwaway venv (`requirements.txt`; system PyYAML forced a venv).
- App booted via `mediahub.web.web.app` with `TESTING=True`; a production-CSRF path
  exercised with `app.config["ENFORCE_CSRF"]=True`.
- `DATA_DIR` pointed at a temp dir per run.
- **No real API spend:** `mediahub.content_engine.generate_content` monkeypatched to
  return deterministic cards. No Gemini/Anthropic/Photoroom/Replicate call was made.
- SSRF tested against `http://169.254.169.254/latest/meta-data/` (cloud metadata) —
  blocked by `safe_fetch` (no text reached the brief).
- Linters: **ruff 0.8.4** (the version pinned in `.pre-commit-config.yaml`; the
  sandbox's default ruff 0.15.8 reformats unrelated pre-existing quotes and was not
  used for the gate).

---

## 3. Test matrix results

| # | Dimension | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Functional correctness | PASS | POST with a source calls the engine with a brief carrying meet/site/pack/entries + club; AI-mode entries → "Accepted entries … for Otter SC" (see `test_ai_watch_mode_uses_entries_and_club`). |
| 2 | Every interactive control | PASS (after fix) | Approval pill was silently broken under production CSRF (**F1**, fixed); watch-mode toggle, Copy caption, Create graphic, View/export, Start over links all behave. |
| 3 | Input validation / edge cases | PASS (after fix) | Empty/whitespace now rejected 400 (**F2**, fixed); malformed `.lef`, corrupt files handled gracefully; unicode/emoji flow through; `parse-entries` returns 400/422 with helpful messages. |
| 4 | UI state handling | PASS | Loading (`data-loader-*`), empty ("No cards generated"), error (recovery pages), success states render. |
| 5 | Server-side error handling | PASS (caveat) | No stack traces leaked; 503 no-provider, 502 provider-error, 400 empty. Caveat: a *non-provider* engine exception still persists an empty pack + returns 200 (**F11**, logged). |
| 6 | Data integrity | PASS (caveat) | `form_data` persisted faithfully; IDOR guarded by `_can_access_pack`. Caveat: entries text is hard-capped at 6000 chars in the brief, which can drop the club on a huge multi-club meet (**F8**, logged). |
| 7 | Security | PASS | SSRF blocked (metadata IP refused); captions/inputs HTML-escaped via `_h()`; upload path uses uuid+forced-suffix (no traversal); IDOR guarded; CSRF now correct on the pill (**F1**); no secret leakage in error pages. |
| 8 | Performance | PASS (after fix) | Per-fetch leash tightened to 6s/2 hops (**F6**); typed brief fields capped (**F5**). No aggregate wall-clock budget across both fetches + LLM (residual, F6). |
| 9 | Responsive / accessibility | PASS (after fix) | Every field now has `id`+`for` label association (**F3**, fixed). Duplicate `<h1>` (**F10**) and JS-disabled manual panel (**F12**) logged. |
| 10 | Rendered-graphic correctness | N/A (delegated) | Event Preview cards are caption-led; "Create graphic" delegates to the shared graphic renderer (out of scope). Caption escaping verified. |
| 11 | Consistency / copy quality | PASS (after fix) | Stale "coming next" contract refreshed (**F2/F4**). Pre-existing em dashes in form copy logged (**F15**); new copy uses plain hyphens. British English throughout. |

---

## 4. Findings

| id | sev | title | reproduction | root cause | status | commit |
|----|-----|-------|--------------|------------|--------|--------|
| F1 | P0→P1 | Approval pill lost under production CSRF | With `ENFORCE_CSRF`, save an Event Preview pack, click a card's status pill → POST is 403'd, pill reverts, approval never persists | pill JS posts multipart `FormData` with no CSRF token; the CSRF layer only exempts `application/json` | **fixed** | pill posts JSON; route reads JSON |
| F2 | P2 | Empty/whitespace submission generates ungrounded cards | POST `/weekend-preview` with no fields → was 200 + an LLM call on "Event preview brief — the upcoming event" | no server-side "at least one real source" check | **fixed** | `has_meaningful_input` + 400 guard |
| F3 | P2 | Form inputs lack label association (a11y) | GET form: 7 `<label>` with 0 `for=`, 8 inputs with 0 `id=` | labels written without `for`/`id` | **fixed** | `pv-*` ids + `for=` |
| F4 | P3 | Stale "What you'll need" copy | GET form shows "Full entry-list parsing is coming next" and "athletes to watch, and any story angles" | `EVENT_PREVIEW.input_contract`/`how_it_works` predate the redesign | **fixed** | copy refresh |
| F5 | P2 | Typed brief fields unbounded | POST a ~1MB `angles` blob → whole blob enters the brief and the persisted pack | only extracted text was capped, not `meet_name`/`angles`/`athletes` | **fixed** | caps `[:300]/[:3000]/[:50]` |
| F6 | P2 | No tight fetch leash on the request path | two `safe_fetch` calls at the default 10s each + LLM, synchronous in one request | default timeout/hops | **fixed (partial)** | `timeout=6, max_hops=2`; aggregate budget still residual |
| F7 | P1 | AI-mode entries **URL** to a PDF psych sheet yields no/garbage watch-list | AI mode, paste a link to a psych-sheet PDF → `safe_fetch` returns page-text sanitisation of binary, not entries | `safe_fetch` only yields sanitised HTML text; PDFs/docs behind a URL aren't run through `extract_text` | **logged (needs-coordination)** | — |
| F8 | P2 | 6000-char entries cap can drop the user's own club | AI mode, upload a many-club LENEX; the club's rows may sit past char 6000 | `entries_text[:6000]` in `generate_brief`; no server-side club filter | **logged** | — |
| F9 | P2 | Oversized/unreadable pack silently dropped while loader says "reading the pack" | POST a 26-50MB PDF pack (passes 50MB Flask cap, fails 25MB extract cap) → used = nothing, no notice | only `status=='ok'` consumed; no user feedback on `too_large`/`unsupported` | **logged** | — |
| F10 | P2 | Two competing `<h1>` on the create page | GET `/weekend-preview`: hero `<h1>` + `render_stub_html`'s `<h1>` | `render_stub_html` (shared by all four stubs) always emits its own title | **logged (cross-cutting)** | — |
| F11 | P3 | Non-provider engine error persists empty pack + 200 | make `generate_content` raise a plain `ValueError` → empty pack saved, HTTP 200, `generation_error` discarded | generic `except` falls through to `save_pack` | **logged (shared handler)** | — |
| F12 | P3 | "Type them myself" panel unreachable with JS off | disable JS, choose manual → `#pv-watch-manual` stays `display:none` | reveal is JS-only | **logged** | — |
| F13 | P3 | Stub photo attachment saved without image-decode validation | POST `attached_photo` = non-image bytes named `x.jpg` → saved to disk on extension alone | extension whitelist, no decode gate (unlike the card-photo path) | **logged (shared path)** | — |
| F14 | P3 | `/api/event-preview/parse-entries` is dead + unbounded | route has no JS/template caller; its text branch decodes up to 50MB before slicing to 400 | W.6 helper never wired to the form | **logged** | — |
| F15 | P3 | Em dashes in existing form copy vs plain-hyphen house rule | GET form copy uses "…format — before it writes a word" | pre-existing copy predates the rule; app-wide convention uses em dashes | **logged** | — |

Note on severities: the audit workflow's finder tagged F1 P1 and F7 P1; the CSRF pill
(F1) is a data-loss-of-approval defect on a production build, so it was treated as the
top priority to fix. The adversarial verify pass could not run to completion (the
account hit its weekly model-usage limit mid-workflow), so each finding above was
re-adjudicated by hand against the code and by dynamic reproduction rather than by a
second model vote. The one verify that did run "rejected" F3 — but only because it read
`stubs.py` *after* the F3 fix had already landed; the pre-fix reproduction (0 of 7
labels associated) is the ground truth.

---

## 4b. Second pass — every logged caveat now fixed

A follow-up pass fixed all nine caveats (F7-F15) that the first pass had logged. Each
is locked with a test.

| id | sev | fix | test |
|----|-----|-----|------|
| F7 | P1 | New SSRF-safe `safe_fetch_bytes` + `html_bytes_to_text` in `web_research/safe_fetch.py`; the enrichment routes an entries/website **URL** that is a PDF/Word download through `extract_text`, and an HTML page through the sanitiser — a psych-sheet PDF link now yields real entries. | `test_entries_url_pdf_routed_through_extractor`, `test_entries_url_html_sanitized`, 5 `safe_fetch_bytes`/`html_bytes_to_text` tests (incl. internal-IP refusal) |
| F8 | P2 | The enrichment orders the **active club's** LENEX entries first (deterministic, stable sort) so they survive truncation; the brief cap is raised 6000 → 9000. | `test_active_club_entries_ordered_first`, `test_brief_entries_cap_is_generous` |
| F9 | P2 | A provided source that could not be read (`event_website_url` / `entries_url` / `entries_file` / `event_pack`) is called out in a notice on the results page instead of being silently dropped. | `test_unread_source_notice` |
| F10 | P2 | `render_stub_html` no longer emits its own `<h1>` + description — the editorial hero already carries the page's single `<h1>`. Fixes all four stub pages. | `test_no_duplicate_h1_on_form` |
| F11 | P3 | A non-provider `generate_cards` exception now returns an honest 502 recovery page and persists **no** empty pack (was: empty pack + HTTP 200; dead `generation_error` removed). | `test_generic_engine_error_returns_502_and_saves_no_pack` |
| F12 | P3 | The ones-to-watch toggle is pure CSS (`:has()`), so it works with JavaScript disabled; where `:has()` is unsupported both panels stay usable. JS handler removed. | `test_watch_toggle_is_css_and_degrades_without_js` |
| F13 | P3 | The photo attachment is decode-validated (PIL `verify()`) before it is stored; arbitrary bytes named `.jpg` are rejected. Fixes all four stub photo uploads. | `test_photo_upload_rejects_non_image`, `test_photo_upload_accepts_real_image` |
| F14 | P3 | `/api/event-preview/parse-entries` bounds its plaintext branch (decode ≤ 2 MB, entries text ≤ 20 000 chars) so a large upload can't build a giant intermediate. | `test_parse_entries_bounds_large_text` |
| F15 | P3 | Em dashes removed from the Event Preview form copy and the hero lede — plain hyphens, British English. | `test_form_copy_uses_plain_hyphens` |

Cross-cutting note: F10, F11 and F13 sit in code shared by all four "create" stubs
(`render_stub_html`, the `_render_stub` generic-except, the photo-upload gate), so the
fixes repair the Sponsor / Session / Free-Text surfaces too. One sibling test
(`test_media_library_profile_isolation.py::TestStubPickPersistence`) had a stale mock
whose wrong signature was previously masked by the F11 bug (its `TypeError` was
swallowed into the empty-pack-200 path); its mock signature was corrected so it now
exercises the real success path. `safe_fetch.py`'s additions are purely additive and
preserve every existing SSRF guard (they build on `pinned_stream_get`).

---

## 5. Fixes applied

All fixes are inside the feature's blast radius.

1. **F1 — approval pill (P1).** `render_cards_html` pill JS now posts
   `application/json` (`JSON.stringify({status})`) instead of a token-less multipart
   `FormData`, so the write rides the app's documented same-origin JSON CSRF exemption.
   `api_stub_pack_card_status` now reads the status from a JSON body (falling back to a
   form field for any legacy caller). Files: `stubs.py`, `web/web.py`. Verified: under
   `ENFORCE_CSRF`, multipart → 403, JSON → 200 and the pack persists `approved`.
   (This reconciled an incomplete `X-CSRF-Token`/`__CSRF_TOKEN__` placeholder attempt
   left in the working tree by this session's interrupted first request — that dead
   placeholder and its unused `csrf_token` param were removed.)
2. **F2 — empty-submission guard (P2).** New `WeekendPreviewStub.has_meaningful_input`;
   the enrichment branch returns a friendly 400 recovery page when no groundable source
   is present. Files: `stubs.py`, `web/web.py`.
3. **F3 — label association (P2).** Every text/url/file/textarea field in the form got a
   `pv-*` `id` and its `<label>` a matching `for=`. File: `stubs.py`.
4. **F4 — copy refresh (P3).** `EVENT_PREVIEW.input_contract` and `how_it_works` rewritten
   to describe the redesigned form (event name + website/pack + entries), plain hyphens,
   British English. File: `content_types.py`.
5. **F5 — bounded typed fields (P2).** `generate_brief` caps `meet_name[:300]`,
   `angles[:3000]`, `athletes[:50]`. File: `stubs.py`.
6. **F6 — bounded fetch (P2, partial).** Both Event Preview `safe_fetch` calls pass
   `timeout=6.0, max_hops=2`. File: `web/web.py`.

---

## 6. Tests added or extended (`tests/test_event_preview_redesign.py`)

- `TestEventPreviewInputGuard::test_empty_or_whitespace_form_is_not_meaningful` /
  `test_any_real_source_is_meaningful` — locks F2's guard predicate.
- `TestEventPreviewInputGuard::test_free_text_user_fields_are_capped_in_the_brief` — locks F5 caps.
- `TestEventPreviewFormAccessibility::test_every_field_has_label_association` — locks F3.
- `TestEventPreviewCopy::test_input_contract_is_current` — locks F4 (no "coming next", mentions entries, no em/en dashes).
- `TestEventPreviewRoute::test_empty_post_is_rejected_without_calling_the_engine` /
  `test_named_event_generates_cards` — route-level F2 guard (400, engine not called) + happy path (200, engine called).
- `TestApprovalPillCsrf::test_pill_js_posts_json_not_multipart` /
  `test_status_route_persists_json_under_enforced_csrf` — locks F1 (JSON pill; multipart 403, JSON 200 + persisted under `ENFORCE_CSRF`).

Full module: **15 passed**. Broad relevant regression subset (post types, content
intro, drafts list, free-text quick, stub-pack store, cross-tenant access, channel
preview, error-leak, no-fabricated-confidence, media-library isolation, cross-source
planner, planner board, v10 regen): **214 passed**.

---

## 7. Cross-cutting changes (for reconciliation)

Two edits touch shared files, both minimal and feature-driven:

- `src/mediahub/web/web.py`
  - Event Preview enrichment branch (feature-specific block): the empty-submission
    400 guard and the `timeout=6.0, max_hops=2` fetch leash.
  - `api_stub_pack_card_status` (shared by all four stubs' pills): now reads status from
    a JSON body with a form-field fallback. This is backward-compatible — any existing
    form/legacy caller still works — and is required to fix F1. **The composite-copilot
    pill at web.py ~13269 still posts multipart and remains CSRF-broken in production;
    it is out of this feature's scope and is flagged here for the owning session.**
- `src/mediahub/club_platform/stubs.py` — `render_cards_html` is shared by all four
  stubs; the JSON pill fix (F1) therefore also repairs the Sponsor/Session/Free-Text
  pills (a bonus, not a regression). The removed `csrf_token` param was never wired to a
  caller.

`content_types.py` was edited only within the `EVENT_PREVIEW` entry.

---

## 8. Residual risks / cross-feature work (not attempted here)

- **F7 (P1, needs-coordination):** entries **URL** → PDF/psych-sheet is the common
  real-world input, but `safe_fetch` only returns sanitised HTML text. A proper fix
  needs an SSRF-safe *byte* fetch (there is `pinned_stream_get` to build on) plus a
  content-type gate handing PDFs/docs to `extract_text` — a new capability in a shared
  module, better coordinated than bolted on under a rate limit. Until then the entries
  **file** upload path is the reliable route (and it works, including LENEX).
- **F8 (P2):** the robust fix for the entries truncation is a deterministic
  club-side pre-filter of parsed rows before the brief — it touches the parse flow and
  changes the existing brief-shape test expectation, so it wants its own change.
- **F9/F11 (honesty):** surfacing "we couldn't read your pack/entries" and not
  persisting an empty pack on a hard engine error both want a small results-page notice
  channel in the shared `_render_stub` handler.
- **F10/F13 (shared surfaces):** duplicate `<h1>` and unvalidated stub photo bytes live
  in code shared by all four stubs; fix once, for all of them, in a stub-wide change.
- **F14:** `/api/event-preview/parse-entries` is dead. Wiring it into the form (instant
  "read N entries" feedback) or removing it (with the 15-step gate, since it is in the
  route/API inventories) is a deliberate call.
- **Auth posture (app-wide):** `/weekend-preview` is reachable signed-out and will make
  an LLM call for an anonymous visitor. This is the whole "create" surface's posture,
  not Event Preview's alone, so it is left to an architectural decision.

---

## 9. Feature verdict

**WORKS.** The happy path is correct, source-grounded, and secure (SSRF, XSS, traversal,
IDOR all defended). The first pass fixed the two defects a paying customer hits first —
approvals silently lost in production (F1) and an empty form quietly producing a guessed
preview (F2). The second pass then fixed **every** remaining logged caveat (F7-F15),
including the P1 entries-by-URL-to-a-PDF path, each locked with a test. No open findings
remain in this feature's blast radius.

---

## 10. Handover and merge status

- Branch: `claude/event-preview-audit-vhr4xq`.
- Review the diff: `git diff origin/main...claude/event-preview-audit-vhr4xq`
- Merge status: recorded at the end of this session (see the final chat summary / the
  commit that stamps this line). The green gate is: app boots clean, the feature module
  + broad regression subset pass, ruff 0.8.4 lint+format clean on the changed files, no
  secrets/`.env` staged. The account hit its weekly model-usage limit during the audit,
  which disabled further multi-agent verification but does not affect the local git /
  pytest gate.
