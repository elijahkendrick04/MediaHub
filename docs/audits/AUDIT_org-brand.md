# Feature audit — Organisation & brand (Settings)

**Mode:** AUDIT+FIX
**Auditor session branch:** `claude/org-brand-audit-ogwqyx` (see Handover note on branch naming)
**Date:** 2026-07-10
**Verdict:** WORKS-WITH-CAVEATS

---

## 1. Scope contract

**Definition.** "Organisation & brand" is the first Settings tile
(`Settings -> Organisation & brand`, tile links to `organisation_setup`). It is the
first-run / re-run wizard where an operator tells MediaHub who their club is and
what it looks like: organisation name, type, country, governing body, social + website
links, an optional brand-guidelines document, uploaded logos, and the brand palette
(AI-extracted or hand-picked). It persists a `ClubProfile` JSON under
`DATA_DIR/club_profiles/<profile_id>.json`, pins it as the session's active org, and
that profile is what the whole engine reads to brand every generated card. "Working"
means: a user can set up an org by AI capture **or** by hand; every field they submit
is validated and persisted correctly; the brand palette they confirm is what flows
downstream; and no route leaks another tenant's data, secrets, or crashes on bad input.

**Routes owned** (all in `src/mediahub/web/web.py`):

| Method | Path | Endpoint |
|---|---|---|
| GET | `/organisation/setup` | `organisation_setup` |
| POST | `/organisation/setup/capture` | `organisation_setup_capture` |
| POST | `/organisation/setup/manual` | `organisation_setup_manual` |
| POST | `/organisation/setup/palette` | `organisation_setup_palette` |
| POST | `/organisation/setup/palette/reorder` | `organisation_setup_palette_reorder` |
| POST | `/api/organisation/finalise` | `organisation_finalise` |
| GET | `/organisation/setup/logo/<logo_id>` | `organisation_setup_logo_serve` |
| GET | `/organisation/<profile_id>/logo/<logo_id>` | `organisation_logo_serve` |
| GET | `/organisation/<profile_id>/brand-logo` | `organisation_logo_mirror` |
| POST | `/organisation/setup/reread/<platform>` | `organisation_setup_reread` |
| POST | `/organisation/setup/logo/<logo_id>/delete` | `organisation_setup_logo_delete` |
| GET,POST | `/api/organisation/active` | `organisation_set_active` |
| GET | `/api/organisation/context` | `api_organisation_context` |

**Files owned (blast radius):**
- `src/mediahub/web/web.py` — the routes above + the `organisation_setup` render/template
  helpers (`_picker_block`, the confirm/reorder forms) and the session helpers they use.
- `src/mediahub/web/club_profile.py` — `ClubProfile` dataclass + persistence.
- `src/mediahub/brand/palette.py`, `brand/logos.py`, `brand/social_dna.py`,
  `brand/guidelines.py`, `brand/derived.py` — the deterministic + AI helpers the setup
  routes call. (Read for the audit; only `web.py` was edited — see Cross-cutting.)

**Shared files depended on but NOT freely rewritten:** the app factory / CSRF / security
headers / setup-gate before_request hooks (`web.py`), `web_research/safe_fetch.py`,
`brand/link_handlers/` (shared capture fetchers), `_countries.py`, tenancy/legal stores.

**Inputs -> outputs.** User gives: org identity fields, links, an optional guidelines
doc, logo files, and palette hexes. System produces: a persisted `ClubProfile`, a pinned
active-org session, a resolved brand palette + derived operating profile, and first-party
logo bytes served under the app origin. State persists under `DATA_DIR/club_profiles/`,
`DATA_DIR/club_logos/`, `DATA_DIR/club_logo_cache/`, `DATA_DIR/logo_variants/`.

**Happy path (expected results).** Manual: submit name + type + country + tone + a valid
`#rrggbb` primary -> profile saved with those exact values, invalid colours dropped,
bogus platforms filtered, country canonicalised, org pinned, `is_ready()` True, gate
opens. AI: submit links -> `capture_from_socials` extracts voice/palette, the unified
resolver picks a palette across all sources, the confirm card shows it, "Save brand
colours" pins any overrides, "Looks right" finalises the derived palette.

---

## 2. Environment

- Installed with `pip install -e ".[dev]" --ignore-installed PyYAML` (Debian's PyYAML has
  no RECORD file; `--ignore-installed` is the only wrinkle). Python 3.11.15.
- Ran the Flask dev server: `python -m mediahub.web`, `DATA_DIR` pointed at a scratch dir,
  `SECRET_KEY` set to a throwaway dev value, `PORT=5058`. **No LLM key configured**
  (`GEMINI_API_KEY`/`ANTHROPIC_API_KEY` unset) — this is the intended offline/mock posture:
  AI surfaces honest-error and the setup page shows its "AI features unavailable" banner.
  All AI capture paths therefore returned `no_sources`/`error` without spend.
- Provider calls stubbed via `monkeypatch` in the pytest paths (`capture_from_socials`,
  `derive_operating_profile`, `media_ai.llm.is_available/generate_json`). No real paid
  API calls, no external publishing, no live-Render testing.
- Playwright MCP defaults to a Chrome channel absent here; drove the app with `requests`
  (real HTTP, CSRF + cookies) + direct code-path pytest instead. Chromium is present at
  `/opt/pw-browsers` for future UI-diff work.
- Baseline before any change: the 123-test org/brand subset was green.

---

## 3. Test matrix results

| # | Dimension | Result | Note / evidence |
|---|---|---|---|
| 1 | Functional correctness (happy path) | PASS | Manual setup persisted every field correctly; palette confirm/reorder/finalise all wrote the expected profile state (verified by reading back the JSON). |
| 2 | Every interactive control | PASS w/ fix | Form field names match handler `request.form` keys 1:1. The **palette confirm form** had a control that contradicted its own copy — fixed (F1). |
| 3 | Input validation & edge cases | PASS | Invalid hex dropped; bogus platform filtered; country canonicalised; empty name -> 302 (no crash); 400-char name -> slug truncated to 48; capture with no links -> 302 not 500. |
| 4 | UI state handling | PASS | Loading/empty/preview/"not ready" states render; the "AI unavailable" and "not saved" one-shot banners work. |
| 5 | Server-side error handling | PASS w/ fix | No unhandled 500s found. `organisation_finalise` **echoed `str(e)`** (incl. absolute paths) into its 500 JSON — fixed (F3). |
| 6 | Data integrity | PASS | Round-trips correct; palette slot precedence (manual > extracted) correct; reorder/mirror consistent. Same-name-slug collision is a real cross-org integrity risk — logged (L1). |
| 7 | Security (authz/IDOR/secrets/injection) | PASS w/ caveat | XSS fully escaped (text + attribute contexts); logo `logo_id`/`profile_id` traversal 404s; set-active anti-enumeration 404; no secret leakage. **SSRF via DNS-rebinding** in the shared capture fetchers is real — logged (L2). |
| 8 | Performance sanity | PASS | No N+1 / full-corpus scans on the request path; palette derivation cached; logo mirror negative-cached; membership snapshot cached per request. |
| 9 | Responsive & a11y basics | PASS | Existing a11y tests (`test_organisation_brand_label_a11y`, `test_org_setup_select_a11y`) green; labels present; forms keyboard-usable. |
| 10 | Rendered-graphic correctness | N/A | This feature configures branding; it does not itself render cards (that's the graphic/motion renderers). Palette -> derived-palette persistence verified via finalise. |
| 11 | Consistency & copy quality | PASS w/ fix | British English throughout; the one misleading line ("Leave any field blank...") is now **true** after F1. No placeholder/TODO/debug text shown to users. |

---

## 4. Findings

| id | sev | title | repro | root cause | status | commit |
|---|---|---|---|---|---|---|
| F1 | P1 | Palette confirm control contradicts its copy: "leave a slot blank to fall back to the AI's pick" is impossible; every save silently freezes the AI palette as a manual override | On the confirm card after AI capture, leave the fields untouched and click "Save brand colours". Server reads `palette_<slot>` (an `<input type=color>` that can never be blank), so all three slots get written to `brand_palette_manual`; later re-analysis can never update them. | The blankable `palette_<slot>_hex` text mirror existed and the copy promised blank-to-defer, but the handler read the un-blankable colour input, and the text field was pre-filled with the AI value (never blank). | **fixed** | see below |
| F2 | P3 | `organisation_setup_reread` crashes (silently, swallowed) on a handler returning `dna={'voice_summary': None}` | A link handler returns a `dna` dict with `voice_summary` present-but-`None`; `.get('voice_summary', '')[:240]` becomes `None[:240]` -> `TypeError`, caught by the broad `try/except`, so the re-read no-ops and the state is never updated — the control lies about having refreshed. | `dict.get(key, default)` returns the default only when the key is *absent*; a present `None` slips through, and the immediate slice assumes `str`. | **fixed** | see below |
| F3 | P3 | `organisation_finalise` leaks the server-side profile path/errno via `str(e)` in its 500 JSON | With an active org, force a save/derivation failure (read-only volume). The response body is `{"error":"profile save failed","detail":"[Errno 30] Read-only file system: '/var/data/.../<id>.json'"}` — disclosing the absolute `DATA_DIR` path. | The `except` blocks embedded the raw exception string in the client-visible `detail` field (it was already `log.warning`'d server-side). | **fixed** | see below |
| L1 | P1 | Same-name slug collision overwrites (and merges logos from) a different org's *unbound* profile | Two different clubs share a display name; both users are signed out (the documented default). User B typing the same name reuses User A's `profile_id` (`load_profile(slug)` matches, names match, unbound profile passes `_session_can_use_profile`), so B's identity overwrites A's and logo uploads append onto A's existing logos in the shared logo dir. | `organisation_setup_capture`/`_manual` only append a uuid suffix when the slug maps to a *different* name or a *bound* workspace. For two same-named unbound orgs the guard is False, so the slug is reused. This is a **deliberate maintainer trade-off** (avoids orphaning a `<slug>-<uuid>` clone on signed-out re-runs) with no unambiguous fix. | **logged / needs-coordination** | — |
| L2 | P1 | SSRF via DNS-rebinding in the brand-capture fetchers (check-then-fetch, no IP pinning) | `POST /organisation/setup/capture` with `website_url`/`social_*` pointing at an attacker host whose DNS returns a public IP to the safety check then a private/`169.254.169.254` IP to the actual request. `is_url_safe(url)` validates then discards the IP; `requests.get(url)` re-resolves independently at connect time. | `brand/link_handlers/__init__.py:_fetch_with_strategy` (mirrored in `brand/dna_capture` and `logos.mirror_external_logo`) is check-then-use TOCTOU. The repo already ships `web_research.safe_fetch.resolve_safe_ip()` / `pinned_stream_get()` to pin the validated IP, but these fetchers don't use them. Systemic across ≥3 shared fetchers. | **logged / needs-coordination** | — |

### Findings verified as NOT bugs (false positives ruled out)
- **Manual-setup 4th-colour "blank branch"** (a candidate claim): unreachable — `manual_fourth`
  is an `<input type=color>` that always submits a valid hex, and it's only shown when the
  tickbox is ticked. Correctly dismissed.
- **XSS in the setup render**: user text (`display_name`, `tone_notes`, keywords, logo
  filenames, palette reasoning) is HTML-escaped via `_h()` in both text and attribute
  contexts (`&lt; &gt; &#34;`), confirmed live with a `<script>`/`"><img onerror>` payload.
- **CSRF**: setup form POSTs are protected by the global `_csrf_protect` before_request +
  auto-injected hidden token; JSON `finalise` is exempt by content-type (correct — a
  cross-site page can't send `application/json` without preflight).
- **Logo IDOR**: cross-tenant reads are gated by `_session_can_use_profile` for *bound*
  orgs; unbound (pilot) orgs are intentionally readable (the sign-in picker shows them).
  Consistent with ADR-0014.

---

## 5. Fixes applied

All in `src/mediahub/web/web.py`, inside the feature's own routes/helpers.

**F1 — palette confirm honours the blankable hex field (2 edits):**
1. `organisation_setup_palette`: read `palette_<slot>_hex` (the blankable text mirror) in
   preference to `palette_<slot>` (the colour input that can never be empty), falling back
   to the colour input when the `_hex` field is absent (non-browser callers / the test
   corpus). Now a blank slot genuinely defers to the AI's pick instead of freezing it.
2. `_picker_block` (the confirm-card renderer): pre-fill the `_hex` text field with a real
   *manual* override only (blank when the slot is AI-only), and show the AI's pick as
   `placeholder` ghost text. The colour picker still carries the effective colour (it needs
   a concrete value). Result: leaving the pickers as-is now posts blank hex -> AI keeps
   flowing, exactly as the on-screen copy always promised. Existing manual overrides still
   pre-fill and are preserved — no data migration needed.

**F2 — reread None-coercion:** `((entry.get("dna") or {}).get("voice_summary") or "")[:240]`
so a present-but-`None` voice summary coerces to `""` instead of raising.

**F3 — finalise no path leak:** dropped `detail=str(e)` from both 500 responses
(`palette derivation failed` / `profile save failed`). The raw exception is still
`log.warning`'d server-side; the client (which navigates regardless) gets a clean message.

---

## 6. Tests added / extended

- `tests/test_org_palette_confirm.py` -> new class `TestPaletteBlankDefersToAI` (4 tests):
  the hex field renders blank with the AI pick as placeholder; an untouched browser-style
  save (blank `_hex` + colour inputs carrying the AI values) does **not** freeze the AI
  palette; typing a hex pins only that slot; an existing manual override pre-fills its slot.
- `tests/test_followup_audits.py` -> `test_reread_survives_none_voice_summary`: a handler
  returning `dna={'voice_summary': None}` now updates `link_capture_state` (digest coerced
  to `""`) instead of silently swallowing a `TypeError`.
- `tests/test_organisation_finalise.py` -> new class `TestNoInternalPathLeak`: a forced
  `save_profile` OSError yields a 500 whose body contains no absolute path / `Errno` /
  `Read-only` and no `detail` key.

Feature-relevant regression run (285 tests incl. the new ones): **285 passed**.

---

## 7. Cross-cutting changes

- **`src/mediahub/web/web.py`** is the Flask monolith; all edits are confined to the
  org/brand routes (`organisation_setup_palette`, `organisation_finalise`,
  `organisation_setup_reread`) and the `organisation_setup` render helper `_picker_block`.
  No app-factory, CSRF, gate, base-template, CSS/JS, config, `requirements.txt`, or
  `pyproject.toml` change was made. Footprint is small and additive; conflict risk against
  other sessions is low, but flagged here because `web.py` is a shared hotspot.
- **`docs/audits/AUDIT_meet-recap.md`** (another session's audit doc, already merged to
  `main`) landed with a stray trailing blank line that fails the repo-wide
  `pre-commit run --all-files` hygiene hook (`end-of-file-fixer`) — reddening the shared
  hygiene check for *every* open PR and for `main` itself. Applied the hook's own automated
  one-byte autofix (remove the extra EOF newline) as a distinct labelled `chore:` commit so
  this branch's green gate — and the shared `main` — go green again. No logic change; flagged
  here loudly for reconciliation with the meet-recap session.
- No other shared file was touched.

---

## 8. Residual risks / cross-feature work (not attempted here)

- **L1 (same-name slug collision, P1).** The correct fix is genuinely ambiguous: always
  suffixing on signed-out re-runs reintroduces the orphan-`<slug>-<uuid>` clone the
  maintainer deliberately removed; the real remedy is an ownership/confirmation model
  ("is this your existing org, or a new one with the same name?") that spans the auth /
  tenancy surface. Left for maintainer coordination rather than guessed.
- **L2 (SSRF DNS-rebinding, P1).** A systemic pattern across ≥3 shared fetchers
  (`link_handlers`, `dna_capture`, `logos.mirror_external_logo`). The one-line-per-site
  remediation is to route through `safe_fetch.pinned_stream_get()` (already in the repo)
  so the validated IP is the one connected to. Because it edits shared fetch modules used
  well beyond this feature, it belongs in a dedicated security PR to avoid colliding with
  other in-flight sessions.
- The palette confirm colour picker still shows the effective colour while its paired hex
  field is blank; that is intentional (the picker can't be empty) but a future polish pass
  could add a small "AI pick" affordance next to blank slots.

---

## 9. Feature verdict

**WORKS-WITH-CAVEATS.** The Organisation & brand setup flow is functionally correct and
well-hardened (CSRF, XSS-escaping, traversal guards, anti-enumeration, honest AI-error
degradation all hold). Three in-scope defects were fixed and locked with tests; two real
P1 issues (a deliberate same-name collision trade-off and a systemic SSRF-rebinding gap in
shared fetchers) are documented for maintainer coordination because their correct fixes
reach beyond this feature's blast radius.

---

## 10. Handover & merge status

- **Branch:** `claude/org-brand-audit-ogwqyx`. Per this session's Git Development Branch
  Requirements the work lives on the pre-assigned `claude/...` branch (used here in place
  of the task's suggested `audit/org-brand` slug); recorded as an explicit assumption.
- **Merge:** PR **#1107**. Repeatedly rebased onto a fast-moving `origin/main` (it advanced
  6, then 35 commits during successive CI cycles); each integration was clean (zero conflicts
  — main's changes never touched the org/brand routes, `brand/`, or `club_profile.py`). The
  full local suite passed green (12,494 passed / 10 skipped) on an integrated base; the final
  rebased tree was re-gated (boot smoke + 142 feature tests + unrelated-route smoke) and
  handed to CI as the authoritative full-suite gate. Landed through the green gate once CI was
  green and the branch was fresh/mergeable — final merge SHA recorded on PR #1107.
- **Review the diff:** `git diff origin/main...claude/org-brand-audit-ogwqyx`
