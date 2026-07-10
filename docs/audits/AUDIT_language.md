# Feature Audit — Interface Language (C-16 language switcher)

Auditor: autonomous QA+fix session · Mode: AUDIT+FIX · Date: 2026-07-10
Branch: `claude/language-feature-audit-i3892x` (this session's audit branch)
Feature commit of record: `445e9fe feat(i18n): visible interface-language switcher with an English off-ramp (C-16)`

---

## 1. Scope contract

**Definition.** The "Language" control at the bottom of every page is the
**interface-language switcher** (roadmap C-16): a globe + `<select>` dropdown in
the footer (and a card on `/settings`) that changes the language of the *website
chrome* — nav labels, primary-action words — with English always available as an
off-ramp. It is deliberately **distinct** from the org's *caption-output*
language (set under Organisation & brand). "Working" means: a visitor can pick a
shipped UI locale from the control, the chrome actually re-renders in that
locale, the choice persists for the session, English is always reachable to
revert, and the control never silently fails, crashes, leaks, or mis-redirects.

**Routes/endpoints owned.**
- `POST /settings/interface-language` → `set_interface_language` (sets
  `session["ui_lang"]`, redirects back to a validated same-origin Referer).
- The `?lang=<code>` query override, handled in `_ui_locale()` on every GET
  render (pins the session and returns the locale).

**Files owned (blast radius).**
- `src/mediahub/web/web.py`: `_ui_locale()` (~13533), `_ui_locale_label()`
  (~13579), `_interface_language_switcher_html()` (~13594), the `_layout`
  translator binding + `<html lang>` (~13957, ~13966), the footer placement
  (~14250), the mobile bottom-nav labels (~14294), the settings-card render
  (~29297), and the `set_interface_language` route (~29090).
- `src/mediahub/localize/ui_catalogue.py`: the curated UI string catalogue +
  `t()` / `available_ui_locales()` / `has_ui_locale()`.
- `tests/test_ui_catalogue.py`, `tests/test_ui_i18n_layout.py`,
  `tests/test_usability_c16_interface_language.py`.

**Shared files it depends on but must NOT freely rewrite.**
- `src/mediahub/web/web.py` is the Flask monolith shared by every feature; only
  the switcher-specific functions above and the two small gated edits noted in
  §7 were touched.
- `src/mediahub/web/languages.py` (caption-language registry) — read-only here;
  `_ui_locale_label` borrows its endonym labels.
- The org-setup gate `_gate_until_org_ready` + `_SETUP_EXEMPT_ENDPOINTS`
  (~18880/19291) and the CSRF layer (~18653) — shared middleware; one exempt-set
  addition was required (§7).

**Inputs / outputs / state.** Input: the chosen locale code (`ui_lang` POST
field, or `?lang=` query). Output: the whole page re-rendered with `<html
lang="…">` and catalogue-backed chrome in that locale. State: `session["ui_lang"]`
in the signed Flask cookie (no server-side persistence, no DB). Shipped UI
locales today: **English (`en`)** and **Welsh (`cy`)** only.

**Intended happy path.** Signed-out visitor on `/` sees "English / Cymraeg
(Welsh)" in the footer → selects Welsh → page reloads with `<html lang="cy">`
and nav "Hafan / Creu / Gosodiadau" → selects English → reverts to "Home /
Create / Settings". A `/?lang=cy` deep link does the same in one hop and pins it.

---

## 2. Environment

- Python 3.11.15; dependencies from `requirements.txt` + editable install.
- Local Flask app booted via `create_app().run(host=127.0.0.1)` on ports 5055
  (baseline/buggy, for the audit workflow), 5056/5057 (with fixes).
- Env: `DATA_DIR`/`RUNS_DIR`/`SWIM_CONTENT_PROFILES_DIR` under the scratchpad;
  `MEDIAHUB_SCHEDULER=0`; a gitignored `.env` with dummy values. No real
  provider keys — no AI/paid calls are on this feature's path (translation of
  *chrome* is a static curated catalogue, not an LLM call), so no stubs were
  needed for the switcher itself.
- Playwright pinned by the session-start hook to 1.56.0 (matches the prebaked
  Chromium at `/opt/pw-browsers/chromium-1194`); real-browser drives used the
  prebaked binary via `executable_path`.
- CSRF and the org-setup gate are **disabled under plain `TESTING`** and were
  explicitly **enforced** (`ENFORCE_CSRF`, `ENFORCE_ORG_GATE`) for the new
  regression tests and reproduced live via curl against the running server.

---

## 3. Test matrix results

| # | Dimension | Result | Note (evidence) |
|---|-----------|--------|-----------------|
| 1 | Functional correctness | **PASS (after fix)** | Signed-out switch was broken (L1); now `en→cy(Hafan)→en` verified via curl + real browser on 5057. |
| 2 | Every interactive control | **PASS (after fix)** | Footer dropdown + settings-card dropdown both drive `set_interface_language`; the noscript "Set" fallback exists. L1/L2 fixed the two silent-failure paths. |
| 3 | Input validation / edge cases | **PASS** | `?lang=` handles casing/region-subtag/whitespace (`CY`,`cy-GB`,`%20cy%20`→cy), and rejects unknown (`zz`,`klingon`,`cy;en`→en); bogus `ui_lang` POST is ignored (existing test). No crash on any input tried. |
| 4 | UI state handling | **PASS** | Switch renders only when ≥2 locales ship; selected `<option>` reflects current locale; off-ramp reverts. |
| 5 | Server-side error handling | **PASS** | No 500s; invalid locale is a clean no-op redirect; the org-gate path 302s (was the L1 bug — now exempt). |
| 6 | Data integrity | **PASS** | `session["ui_lang"]` is per-session; no cross-tenant field; L2 stops a stale `?lang=` from silently reverting a saved choice. |
| 7 | Security | **PASS (residuals logged)** | Open-redirect + protocol-relative Referer blocked (verified live: off-site & `//`,`/\` → `/settings`); options `_h()`-escaped; no secret leak; switcher does not echo the request path (PII). Residual: `?lang=` GET pins session with no CSRF (L5, P3, by-design deep-link). |
| 8 | Performance | **PASS** | Catalogue is an in-memory dict; `_ui_locale` reads a profile only when an org is pinned; no N+1, no scan. |
| 9 | Responsive / a11y | **PARTIAL (logged)** | Switcher present + visible at 375px; compact select has `aria-label`, settings card has `<label for>`. Logged: onchange auto-submit (L4, WCAG 3.2.2), 12px/`min-height:0` target (L10), no `dir`/RTL (L12), duplicate settings label (L11). |
| 10 | Rendered-graphic correctness | **N/A** | The switcher renders no card/PNG. |
| 11 | Consistency / copy | **PASS (after fix)** | British English ("Interface language", "organisation"), plain hyphens. L3 fixed the mobile-nav staying English for terms that have verified Welsh. |

---

## 4. Findings

Severity: P0 broken/data-loss/security-hole · P1 wrong behaviour / lying control
· P2 usability/a11y/error-handling · P3 polish. All findings are inside the
feature blast radius.

| ID | Sev | Title | Status | Commit |
|----|-----|-------|--------|--------|
| L1 | **P1** | Switcher POST silently fails for any visitor without a ready org: the org-setup gate intercepts `set_interface_language` and 302s to `/organisation/setup`, so the language never changes. The visible control is dead for the signed-out public audience (a Welsh prospect) — the only working path was hand-typing `?lang=cy`, the exact workaround C-16 was built to replace. | **Fixed** | `8c4109e` |
| L2 | **P2** | Off-ramp defeated on shared locale links: `_ui_locale` gives `?lang=` top precedence and re-pins from it, so a user who arrived on `/pricing?lang=cy` and then picked English was redirected back to `/pricing?lang=cy` and silently re-pinned Welsh next request. | **Fixed** | `1f39949` |
| L3 | **P2** | Partial localisation on mobile: the mobile bottom-nav hardcoded English for Home/Create/Settings even though verified Welsh (Hafan/Creu/Gosodiadau) exists and the desktop nav already used `t()`. Switching to Welsh left the phone nav fully English. | **Fixed** | `1f39949` |
| L4 | P2 | `onchange="this.form.submit()"` auto-submits on selection (WCAG 3.2.2 On Input, Level A change-of-context); the only explicit submit control is in `<noscript>`. | **Logged** | — |
| L5 | P3 | `?lang=` GET pins `session["ui_lang"]` with no CSRF, while the sibling POST is CSRF-enforced — a "forced-locale link" can pin a victim's UI language. Impact minimal (non-sensitive, en/cy only, SameSite=Lax, reversible). Adversarially **CONFIRMED**. | **Logged (by-design)** | — |
| L6 | P3 | `?lang=` silently overrides an explicit prior pin (URL param beats user's saved choice). Largely mitigated by L1 (visible off-ramp now works) + L2 (post-choice redirect strips `lang`); residual is documented deep-link behaviour. | **Logged** | — |
| L7 | P3 | `_ui_locale` tier-3 reads `session["active_profile_id"]` raw (no idle/deleted/revoked-membership validation), so on gate-exempt pages (`/pricing`, `/terms`) an idle-expired or membership-revoked session can still show that org's Welsh chrome. | **Logged** | — |
| L8 | P3 | `_ui_locale` wraps org-language detection in a broad `except Exception: pass`, masking a misconfigured non-English org as English chrome with no log. | **Logged** | — |
| L9 | P3 | Precedence: an org's *caption-output* language silently drives the *interface* language (tier 3), which sits in tension with the feature's stated interface-vs-caption separation. This is **documented** behaviour in the `_ui_locale` docstring. | **Logged (by-design)** | — |
| L10 | P3 | Switcher `<select>` uses `font-size:12px` (triggers iOS focus-zoom, <16px) and `min-height:0` (opts out of the app's touch-target floor; <24px WCAG 2.5.8). | **Logged** | — |
| L11 | P3 | Settings card labels "Interface language" twice — the card strap and the in-form `<label>`. | **Logged** | — |
| L12 | P3 | No `dir` attribute on `<html>` and no RTL handling in the UI-locale layer — latent breakage the moment an RTL UI locale (ar/ur exist in the caption registry) is added to the catalogue. | **Logged (latent)** | — |
| L13 | P3 | Footer control is a bare globe (aria-hidden) + dropdown with no visible "language" text; could be mistaken for the caption-output language by a sighted user. | **Logged** | — |
| L14 | P3 | `_ui_locale_label` depends on the separate caption registry (`web.languages`); a UI locale added to the catalogue but absent from that registry degrades to a bare code and gets no RTL flag. | **Logged (latent)** | — |

**Reproductions (key items).**
- **L1**: fresh session (no org), extract the auto-injected `csrf_token` from
  `GET /`, then `POST /settings/interface-language ui_lang=cy` with
  `Referer: /` → **302 to `/organisation/setup`**, and `GET /` still shows
  "Home"/`<html lang="en">`. Contrast: `GET /?lang=cy` **does** switch to Welsh —
  proving only the visible control was broken.
- **L2**: `POST … ui_lang=en` with `Referer: /settings?lang=cy&tab=x` →
  pre-fix Location `/settings?lang=cy&tab=x` (reverts); post-fix Location
  `/settings?tab=x` (lang stripped, other params kept).
- **L3**: `GET /?lang=cy` mobile bottom-nav → pre-fix "Home/Create/…/Settings"
  (all English); post-fix "Hafan/Creu/…/Gosodiadau" with Media/Activity English.

---

## 5. Fixes applied

**FIX A (L1) — `8c4109e`.** Added `set_interface_language` to
`_SETUP_EXEMPT_ENDPOINTS`. The handler only sets `session["ui_lang"]` after
validating the locale via `has_ui_locale`, does no org-scoped data access, and
keeps its hardened same-origin Referer redirect, so exempting it does not weaken
access control (mirrors `settings_page`, `pricing_page` and the legal pages
already exempt for the same "renders on public pages" reason). Files:
`src/mediahub/web/web.py`.

**FIX B (L2) — `1f39949`.** In `set_interface_language`, strip only the `lang`
key from the Referer-derived redirect target (`parse_qsl` → drop `lang` →
`urlencode`), preserving every other query param, so a deliberate dropdown choice
is not immediately reverted by a stale `?lang=` still in the address bar. Files:
`src/mediahub/web/web.py`.

**FIX C (L3) — `1f39949`.** Routed the mobile bottom-nav's Home/Create/Settings
labels (text + `aria-label`) through `t()`, matching the desktop nav. Only keys
that already have a verified Welsh translation were wired; Media/Activity stay
English because no verified translation exists (honest-translation rule — no
fabricated strings). Files: `src/mediahub/web/web.py`.

---

## 6. Tests added or extended

All in `tests/test_usability_c16_interface_language.py` (extended, not a parallel
harness):
- `test_switch_works_for_signed_out_visitor_through_the_gate` — **gate enforced,
  no active org**; POST must switch the locale and return to the page, not 302 to
  setup/sign-in. Locks L1. (Verified to fail on the pre-fix tree.)
- `test_switcher_form_carries_a_working_csrf_token` — **CSRF enforced**;
  token-less POST → 403, and the token auto-injected into the rendered switcher
  form is accepted. Locks that the control works under real CSRF.
- `test_explicit_choice_strips_stale_lang_query_from_redirect` — Referer
  `/activity?lang=cy&tab=stories` → redirect drops `lang`, keeps `tab`. Locks L2.
- `test_mobile_bottom_nav_localises_available_terms` — under `cy`, bottom-nav
  shows Hafan/Creu/Gosodiadau and keeps Media/Activity English. Locks L3.

The pre-existing 22 tests (`test_ui_catalogue`, `test_ui_i18n_layout`,
`test_usability_c16_interface_language`) all still pass. Note: those originals run
under plain `TESTING`, which disables both the CSRF and org-setup gates — which is
exactly why L1 shipped unnoticed. The new tests enforce those gates so the class
of bug cannot recur.

---

## 7. Cross-cutting changes (for reconciliation)

All edits are in the shared monolith `src/mediahub/web/web.py`, but tightly
scoped to this feature:
1. **`_SETUP_EXEMPT_ENDPOINTS` += `"set_interface_language"`** (one frozenset
   entry, ~line 18985). This is shared middleware config; the addition is the
   same pattern as the many existing per-endpoint exemptions and is required for
   the feature to work at all for public visitors. Low conflict risk (single
   line in an append-only-style set).
2. **Mobile bottom-nav labels** (~lines 14295–14317): three `Home/Create/Settings`
   literals → `t('nav.*')`. This is shared base-layout chrome; the change only
   affects the three items that already have catalogue keys and mirrors the
   desktop nav's existing `t()` usage. Flagged here in case a parallel session
   also edits the bottom-nav.

No changes to `requirements.txt`, `pyproject.toml`, base CSS/JS, or any other
feature's routes.

---

## 8. Residual risks / needs cross-feature or architectural work

- **L4 (a11y, P2)** — auto-submit-on-change is a change-of-context on input. A
  fully WCAG-3.2.2-clean version means an always-visible submit button instead of
  onchange auto-submit; that is a deliberate interaction-model decision (the
  maintainer built the noscript-button split intentionally), so it is left for an
  owner call rather than changed unilaterally.
- **L9/L6 (precedence, P3)** — that an org's caption language drives the chrome,
  and that `?lang=` outranks an explicit pin, are documented behaviours. If the
  product wants the interface locale to be strictly independent of caption
  language, that's a small `_ui_locale` precedence change but a **product**
  decision worth recording in an ADR.
- **L5 (CSRF on GET, P3)** — a session-mutating GET is intrinsic to shareable
  `?lang=` deep links; adding a token would break the deep-link. Accept as
  documented, or move pinning exclusively to the POST and treat `?lang=` as
  request-scoped only (a behaviour change).
- **L12/L14 (RTL, P3 latent)** — only en/cy (both LTR) ship as UI locales today,
  so there is no live RTL bug, but adding Arabic/Urdu chrome would need a `dir`
  attribute wired from an RTL flag and a UI-locale metadata source independent of
  the caption registry. Do this when an RTL UI locale is actually added.

None of these were attempted here (out of tight scope / owner decisions).

---

## 9. Feature verdict

**WORKS-WITH-CAVEATS.** The core promise — a visible control that changes the
website language with an English off-ramp — was **BROKEN for the public audience**
(L1: dead for signed-out/no-org visitors) and **partially self-reverting** (L2)
before this audit; both are now fixed and locked with gate-enforced tests, and
mobile localisation was completed (L3). The remaining caveats are a11y polish
(L4/L10), documented precedence choices (L6/L9), and latent RTL work (L12/L14) —
all P2/P3, none blocking, all logged for an owner decision.

---

## 10. Handover and merge status

- **Branch:** `claude/language-feature-audit-i3892x`
- **Commits:** `8c4109e` (L1 + regression tests), `1f39949` (L2 + L3 + tests).
- **Review the diff:** `git diff origin/main...claude/language-feature-audit-i3892x`
- **Merge status:** _(finalised in Phase 5 below — green gate + integrate latest
  `origin/main` + land)_
