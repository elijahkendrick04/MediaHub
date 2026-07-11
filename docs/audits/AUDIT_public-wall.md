# Feature Audit — Public Wall (Create)

**Mode:** AUDIT+FIX · **Auditor session branch:** `claude/audit-public-wall-14m718`
**Date:** 2026-07-09 (extended 2026-07-10) · **Verdict:** WORKS-WITH-CAVEATS (see §9)

> **Update 2026-07-10.** A second, adversarial audit pass (5 parallel dimension
> finders + reproductions) revisited the residual/needs-coordination items below
> and found minimal, fail-closed, in-blast-radius fixes for three of them that the
> first pass had deferred. **F2, F3, plus four new findings (F7–F10) are now
> fixed**, with tests. The §4 table and per-finding notes reflect the reconciled,
> post-fix state; the original first-pass wording is preserved where still true.

---

## 1. Scope contract

**Definition.** The *Public Wall* (internal id PC.10 / roadmap C-8) is a per-club,
opt-in, token-keyed public celebration page of a club's *approved* content cards,
plus a website embed, RSS/JSON feeds, and oEmbed discovery. It is reached from the
**Create** hub tile ("Public wall"). "Working" means: a club member can switch the
wall on (minting an unguessable token) and off (structurally revoking it); the
public surfaces show **only** APPROVED/POSTED cards for **that one org**, honour
per-athlete consent on every exit, render read-only with no side effects, and
resist injection, IDOR, path traversal, and cross-tenant access.

**Routes owned.**

| Method | Path | Endpoint | Access |
|---|---|---|---|
| GET | `/public-wall` | `public_wall_settings` | members-only (active profile) |
| POST | `/public-wall/update` | `public_wall_update` | members-only, CSRF-protected form |
| GET | `/wall/<token>` | `public_wall_page` | public (token = access control) |
| GET | `/wall/<token>/embed` | `public_wall_embed` | public |
| GET | `/wall/<token>/feed.json` | `public_wall_json` | public |
| GET | `/wall/<token>/feed.rss` | `public_wall_rss` | public |
| GET | `/wall/<token>/card/<run_id>/<card_id>.png` | `public_wall_card_png` | public |
| GET | `/oembed?url=…` | `oembed` | public |

**Files owned (blast radius).**
- `src/mediahub/web/public_wall.py` — the whole module (token resolution, `wall_cards`,
  `card_labels`, `wall_image_path`, `rendered_card_png`, consent helpers). **Primary.**
- The wall routes + `_wall_page_html` / `_resolve_wall_or_404` inside `src/mediahub/web/web.py`
  (a **shared** monolith — read freely, edit only minimally and loudly).
- `tests/test_public_wall.py`, `tests/test_wall_consent.py`,
  `tests/test_usability_f12_wall_hidden_labels.py` (feature tests).

**Shared files depended on but NOT freely rewritten:** `src/mediahub/web/web.py`
(app factory, CSRF/auth/CSP hooks, the Create-hub tile), `web/club_profile.py`
(ClubProfile persistence), `compliance/gate.py` + `safeguarding/` (consent),
`workflow/store.py` (APPROVED state), `content_pack/builder.py`.

**Inputs / outputs / state.** Input: the member's toggles (enable/disable, initials-only,
per-card hide/show) via `/public-wall/update`; plus, indirectly, the run pipeline's
approved+rendered cards. Output: the public HTML page, embed, RSS/JSON feeds, oEmbed
JSON, and card PNGs. State persisted on `ClubProfile`: `public_wall_enabled`,
`public_wall_token`, `public_wall_initials_only`, `public_wall_excluded_cards[]`
(under `SWIM_CONTENT_PROFILES_DIR`); read-through of run snapshots under `RUNS_DIR`.

**Happy path (concrete expected results).** Member opens `/public-wall` → clicks
"Switch on" → a token is minted and `/wall/<token>` returns 200 listing each approved,
rendered card as a `<figure>` with the card PNG and a consent-honouring title (initials
by default). Feeds mirror the same set. Hiding a card removes it from every public exit
within the 5-minute cache; switching the wall off 404s the old URL immediately.

**Assumptions recorded.** (1) The designated push branch is `claude/audit-public-wall-14m718`
(per session config), used as the `audit/public-wall` working branch. (2) Offline: no
provider keys set; the wall path makes no LLM calls, so no stubbing was required beyond
`TESTING=True`. (3) Prod config sets `RUNS_DIR == DATA_DIR/runs_v4` (render.yaml), so the
RUNS_DIR divergence (F1) is latent in prod but live under any custom `RUNS_DIR`.

---

## 2. Environment

- Python 3.11.15; `pip install -e ".[dev]"` (worked around a debian-managed PyYAML with
  `--ignore-installed PyYAML`). Flask 3.1.3, pytest 9.1.1.
- App boots clean via `mediahub.web.web.create_app()` — 502 routes. Warnings at boot are
  benign (no LLM provider configured; DATA_DIR unset in the sandbox).
- Tests driven with `python -m pytest`; feature exercised via Flask `test_client()` and
  direct calls to `public_wall` using the `tests/test_public_wall.py` fixture pattern
  (tmp `DATA_DIR`/`RUNS_DIR`, seeded run JSON + visual sidecars + WorkflowStore status +
  a `runs` DB row). No real API calls, no network, no external side effects.
- Repro scripts under the session scratchpad: `repro_runsdir.py`, `repro_consent.py`,
  `repro_robust.py`, `repro_inject.py`.

---

## 3. Test matrix results

| # | Dimension | Result | Note (evidence) |
|---|---|---|---|
| 1 | Functional correctness (happy path) | PASS | Approved+rendered card appears with consent-honouring title; feeds mirror it. |
| 2 | Every interactive control | PASS | enable/disable/settings(initials)/exclude(Hide)/include(Show again) all POST the right action and mutate state as labelled; F-12 labels + OFF/empty states render. |
| 3 | Input validation / edge cases | PARTIAL | Robust to corrupt JSON, unicode/emoji, oversized; **but** `exclude` stores arbitrary junk `card_key`s unvalidated (F4, P3). |
| 4 | UI state handling | PASS | ON/OFF, empty ("No approved, rendered cards yet"), consent-hidden block, hidden-cards list all render without undefined-var errors. |
| 5 | Server-side error handling | PASS | Corrupt run/visual JSON → page still 200, no traceback/paths leaked; bad token/missing card → 404 (not 500). |
| 6 | Data integrity | PARTIAL | Approved-only + tenant checks hold; **but** wall silently reads the wrong dir when `RUNS_DIR` diverges (F1, fixed). Truncation at 30 runs / 60 cards is by-design but inconsistent with the PNG route's 200-run reach (F5). |
| 7 | Security (authz/IDOR/injection/CSRF/secrets/traversal) | PASS (2 fixes) | Members-only routes gated; cross-tenant 404; path traversal all 404; XSS neutralised on page/RSS/JSON/oEmbed; CSRF auto-injected + enforced; no secrets/paths leaked. **Fixed:** consent fail-open on missing/corrupt snapshot (F2, P1) and CSS injection via brand colour into `<style>` (F7, P2). |
| 8 | Performance sanity | PASS-with-note | Bounded scan (≤30 runs, ≤60 cards) + HTTP caching; per-request filesystem + per-card consent lookups are not server-cached (F6, residual). PNG cache TTL lowered to 300s for prompt consent revocation (F8). |
| 9 | Responsive / accessibility | PASS | Card `<img>` carry consent-honouring alt text (now with a single shared title/alt fallback, F10); page has lang + title; grid responsive at 320px; contrast all ≥ 6.65:1 (AA). Settings initials checkbox is labelled. Embed badge no longer hijacks the host iframe (F9). |
| 10 | Rendered-graphic correctness / safeguarding | PASS (fix) | Wall serves the already-rendered portrait PNG; alt text matches the (initialled) title. **Fixed:** `no_photo`/`initials_only` consent now holds the full-name/photo graphic off the wall entirely (F3, P1) instead of leaking it via the image route. |
| 11 | Consistency / copy (British English) | PASS | Copy is clear, British, no placeholder/debug/TODO or em/en dashes in wall copy. |

---

## 4. Findings

| ID | Sev | Title | Status |
|---|---|---|---|
| F1 | P2 (latent P1) | `public_wall._runs_dir()` ignored the `RUNS_DIR` env override | **fixed** (commit `f3bf6c4`) |
| F2 | P1 | Consent gate fails **open** when the run snapshot is missing/corrupt — the run's real rendered cards are served with the consent gate skipped | **fixed** (2nd pass) |
| F3 | P1 | `no_photo` / `initials_only` consent still serves the full-name/photo card PNG on the wall (image route ignored `photo_ok`) | **fixed** (2nd pass) |
| F4 | P3 | `exclude` accepts and persists arbitrary/oversized `card_key` strings unvalidated | logged (data-hygiene; not a security hole) |
| F5 | P3 | Wall lists ≤30 recent runs but the PNG route reaches 200 — older approved cards silently drop off the list | logged (by-design "latest" window) |
| F6 | P3 | No server-side cache: every wall/feed hit re-scans the filesystem + runs a consent lookup per card | logged (residual, bounded ≤30 runs) |
| F7 | P2 | Club brand `primary_colour` was CSS-injected into the public wall page's `<style>` block (escaping doesn't neutralise CSS metacharacters) | **fixed** (2nd pass) |
| F8 | P2 | PNG route cached `public, max-age=3600` — a withdrawn child's card image could be served for up to an hour after consent revocation | **fixed** (2nd pass) |
| F9 | P2 | "Powered by MediaHub" badge had no `target` — inside an embedded (iframed) wall it hijacked the club-site iframe | **fixed** (2nd pass) |
| F10 | P3 | Degenerate-card fallback strings differed between title ("Club achievement") and alt ("Achievement card") — WCAG 2.5.3; plus non-deterministic run ordering on `created_at` ties | **fixed** (2nd pass) |

*(F2/F3 were "residual"/"needs-coordination" after the first pass; the second pass found in-blast-radius fail-closed fixes and implemented them. F7–F10 are second-pass findings.)*

### F1 — RUNS_DIR divergence (fixed)
- **Reproduction:** `scratchpad/repro_runsdir.py` — set `DATA_DIR=<x>/data`, `RUNS_DIR=<x>/custom_runs`
  (distinct), seed an approved+rendered card in `RUNS_DIR`. **Before:** `wall_cards` → 0 cards,
  `/wall/<tok>` shows nothing, card PNG → 404. **After:** 1 card, page 200, PNG 200.
- **Root cause:** `_runs_dir()` returned `_data_dir() / "runs_v4"`, hardcoding the default and
  ignoring `RUNS_DIR`. `web.py`'s `RUNS_DIR`, `content_pack.builder`, `compliance.retention`,
  `autonomy.app_env`, and `visual.pronunciation` all honour `RUNS_DIR`; `render.yaml` sets it and
  `.env.example` documents it. Any deployment pointing `RUNS_DIR` outside `DATA_DIR/runs_v4` served
  a permanently empty wall while cards were approved and rendered.
- **Fix:** `return Path(os.environ.get("RUNS_DIR", str(_data_dir() / "runs_v4")))` — identical
  default, honours the override. `src/mediahub/web/public_wall.py`.
- **Test:** `test_wall_honours_runs_dir_override_distinct_from_data_dir`.

### F2 — Consent fails open when the run snapshot is missing/corrupt (**fixed**, 2nd pass)
- **Reproduction:** `scratchpad/repro_consent.py` (A) and `repro_robust.py` — a run that is `done`
  with an APPROVED + rendered card, but whose `run.json` snapshot is missing or corrupt. `_load_run_json`
  returned `None`, which `wall_cards`/`wall_image_path` coerced to `{}` and carried on: the achievement
  lookup yields `{}`, so `swimmer_name` is empty, `_consent_block_reason` returns `None` for an empty
  name (fail **open**), and the run's real rendered card PNG — which depicts the actual athlete, possibly
  a `do_not_feature` one — is served publicly. This defeats the module's own stated fail-closed rule.
- **Root cause:** the empty-name early-return in `_consent_block_reason` is correct for genuinely
  athlete-less cards, but a *missing/corrupt snapshot* means we simply **cannot resolve** the athlete to
  check consent — which must fail closed, exactly like a failing consent-registry lookup already does.
- **Fix (blast-radius-local, `public_wall.py`):** when `_load_run_json(run_id)` returns `None`, **skip the
  whole run** in `wall_cards` and return `None` from `wall_image_path` — do not proceed with empty
  metadata. Genuinely athlete-less cards (team/recap) whose snapshot *loads fine* are unaffected. The
  shared `rendered_card_png` (used by share-links/newsletters, out of this feature's scope) was
  left untouched and its equivalent gap is logged in §8 for those features.
- **Test:** `test_corrupt_run_json_fails_closed` — the corrupt run's card is absent from the wall and its
  PNG route 404s, while the public page still renders 200.

### F3 — `no_photo` / `initials_only` consent still served the full-name/photo PNG (**fixed**, 2nd pass)
- **Reproduction:** `scratchpad/repro_consent.py` (B) — with an athlete's consent at `initials_only` (or
  `no_photo`), the wall **text** correctly shows `A.S.`, but `wall_image_path`/the PNG route still returned
  200 serving the already-rendered graphic, which carries the **full name and/or photo** if it was rendered
  while consent was `full`/absent. Both levels are `photo_ok=False` ("never use a photo"); the image exit
  ignored `photo_ok` and only checked `blocked`, so the tighten-after-render window leaked a minor's
  photo/full-name graphic on the most public surface.
- **First-pass note (superseded):** the first pass logged this as *needs-coordination*, reasoning the only
  fixes were re-rendering or asset-level name-visibility tracking (both out of scope). That missed the
  minimal option: **withhold** the photo-forward graphic (fail closed), entirely within `public_wall.py`.
- **Fix (blast-radius-local):** in `wall_cards`, `wall_image_path` (and the module docstring), after
  resolving the display policy, treat `photo_ok == False` like a block — drop the card from the page/feeds
  and 404 its PNG, recording it in `consent_hidden` with the level + reason so the members-only settings
  page explains *why*. Because `_consent_display_policy` only returns a policy under an **active W.2 regime**,
  this narrows the behaviour change to clubs that have deliberately consented an athlete to no-photo/initials
  — for whom holding the photo-forward card off the public wall is the correct, fail-closed outcome. Clubs
  with no consent regime, and full-consent athletes, are byte-identical to before.
- **Tests:** `test_photo_forbidding_consent_holds_card_off_the_wall` and `test_no_photo_consent_also_held_off_wall`
  (both assert the card is dropped from the wall + feeds + PNG 404). The prior
  `test_initials_only_level_binds_even_with_toggle_off` — which asserted the *leaky* behaviour (card shown
  with initialled text, image unchecked) — was rewritten to assert the new, stronger safeguarding behaviour;
  this is a tightening, not a weakening, of the test.

### F4 — `exclude` stores unvalidated `card_key` (logged)
- **Reproduction:** `scratchpad/repro_robust.py` — POST `/public-wall/update action=exclude
  card_key=<junk>` accepts `not-a-key`, a 5000-char string, and emoji keys, persisting them to
  `public_wall_excluded_cards`. No crash (reads tolerate junk; the hidden-list escapes with `_h`),
  but the profile JSON can be bloated with meaningless keys.
- **Assessment:** Members-only + CSRF-protected, so not a security hole — a data-hygiene weakness only.
  A guard belongs in the `public_wall_update` exclude branch (in the shared `web.py`); given it is P3
  and `web.py` is heavily contended by parallel audit sessions, **logged rather than edited** to keep
  the footprint to `public_wall.py` alone (zero shared-file merge risk). Recommended guard: reject a
  `card_key` that isn't `run_id::card_id` shaped or exceeds a small length bound.

### F5 — list/serve run-window mismatch (logged)
- `wall_cards` scans `_RUNS_SCANNED_LIMIT = 30` recent runs; `wall_image_path` uses `limit=200`. A
  card in run #31–200 is fetchable by direct PNG URL but never listed. Not a leak (still approved +
  owned + consent-gated); a busy club (>30 meets) silently loses older approved cards from the list.
  By-design "latest achievements" behaviour; the two limits should at least be documented as intentional.

### F6 — no server-side cache (residual)
- Each public hit re-scans up to 30 run dirs (run JSON + visual sidecars + WorkflowStore) and runs a
  consent lookup per card. Bounded (≤30 runs / ≤60 cards) and fronted by `Cache-Control: max-age=300`,
  so acceptable for a low-traffic public page, but a crawler hitting cold caches does real filesystem
  work per request. Residual perf note; a small per-token memoisation would help if the wall ever sees
  bot traffic.

### F7 — CSS injection via brand `primary_colour` into the wall `<style>` block (**fixed**, 2nd pass)
- **Reproduction:** `scratchpad/repro_inject.py` / the workflow's `test_wall_css.py` — a `brand_primary`
  set to a non-hex CSS payload (e.g. `#000;}body{background:url(//evil)}header{`, via a raw form POST that
  bypasses the `type=color` widget) flows through `get_brand_kit().primary_colour` into
  `_wall_page_html`'s `<style>` rule `border-bottom:3px solid {_h(primary)}`. `_h` (markupsafe HTML escaping)
  does **not** neutralise `{ } ; :`, so the payload breaks out of the `header` selector and injects an
  attacker-controlled CSS rule onto the public page/embed.
- **Assessment:** bounded — the global CSP (`img-src 'self'`) blocks external `url()` beacons and `_h`
  prevents any `</style>`/HTML/JS breakout, and it is self-scoped (a club's own colour on its own wall,
  token scopes one org). So **P2**, not a cross-tenant or script-execution hole — but a genuine
  wrong-context output-encoding defect on a public surface.
- **Fix (`web.py`, wall render only):** gate the colour to `^#[0-9A-Fa-f]{3,8}$` before interpolation and
  fall back to the existing `#0A2540` default otherwise. One line; no structural change.
- **Test:** `test_hostile_brand_colour_cannot_inject_css` (page + embed).

### F8 — PNG cache TTL outlived consent revocation (**fixed**, 2nd pass)
- The card PNG route set `Cache-Control: public, max-age=3600` while the page/feeds use `max-age=300`. On a
  children's-data surface where consent can be withdrawn or a card hidden at any moment, an intermediary/CDN
  cache could keep serving a withdrawn child's card image for up to an hour.
- **Fix (`web.py`, one line):** lower to `public, max-age=300, must-revalidate` to match the page/feed TTL so
  revocation propagates within minutes.

### F9 — "Powered by MediaHub" badge hijacked the embed iframe (**fixed**, 2nd pass)
- The badge rendered as `<a href=".../signup" rel="noopener">` with **no `target`**. Inside an embedded
  (iframed) wall — the feature's primary distribution surface — clicking it navigated the *club's own iframe*
  to MediaHub's signup page (`rel="noopener"` is inert without a `target`).
- **Fix (`web.py`, one line):** add `target="_blank" rel="noopener noreferrer"` so it opens in a new
  top-level context and never replaces the club's embedded wall.
- **Test:** `test_powered_by_badge_opens_in_new_context` (page + embed).

### F10 — degenerate-card label consistency + deterministic ordering (**fixed**, 2nd pass)
- Two small `public_wall.py` correctness/quality fixes: (a) the degenerate-card fallback used **different**
  strings for the visible title ("Club achievement") and the image alt ("Achievement card") — WCAG 2.5.3
  label-in-name; now a single shared `_FALLBACK_LABEL` for both. (b) `_recent_done_run_ids` ordered by
  `created_at DESC` with **no tiebreaker**, so runs sharing a `created_at` second had engine-defined order
  (and truncation boundary); added `, id DESC` for stable, reproducible ordering.

---

## 5. Fixes applied

All edits are minimal and feature-scoped. `public_wall.py` is the feature's own module (no merge risk);
the three `web.py` edits are one-liners confined to the wall's own render/route code (see §7).

| File | Change | Finding |
|---|---|---|
| `src/mediahub/web/public_wall.py` | `_runs_dir()` honours the `RUNS_DIR` env override (default unchanged) | F1 |
| `src/mediahub/web/public_wall.py` | `wall_cards` + `wall_image_path` skip a run whose snapshot is missing/corrupt (fail closed) | F2 |
| `src/mediahub/web/public_wall.py` | `wall_cards` + `wall_image_path` withhold the card/image when consent `photo_ok == False` (no_photo / initials_only) | F3 |
| `src/mediahub/web/public_wall.py` | shared `_FALLBACK_LABEL` for title+alt; `ORDER BY created_at DESC, id DESC` | F10 |
| `src/mediahub/web/web.py` | `_wall_page_html` validates the brand colour (hex or default) before the `<style>` interpolation | F7 |
| `src/mediahub/web/web.py` | PNG route `Cache-Control` lowered to `max-age=300, must-revalidate` | F8 |
| `src/mediahub/web/web.py` | "Powered by" badge gains `target="_blank" rel="noopener noreferrer"` | F9 |

---

## 6. Tests added / extended

First pass, `tests/test_public_wall.py`:
- `test_wall_honours_runs_dir_override_distinct_from_data_dir` — locks F1: a `RUNS_DIR` distinct from
  `DATA_DIR/runs_v4` is read correctly (cards listed, page + PNG 200).
- `test_hostile_names_are_neutralised_on_every_surface` — defence-in-depth: a hostile swimmer/meet/club
  name is neutralised on the HTML page, the RSS feed stays well-formed XML with no raw `<script>`, and
  the JSON feed is served as `application/json`.

Second pass:
- `test_corrupt_run_json_fails_closed` (`test_public_wall.py`) — locks F2: a corrupt-snapshot run's card
  is absent from the wall + feeds and its PNG 404s, page still 200.
- `test_hostile_brand_colour_cannot_inject_css` (`test_public_wall.py`) — locks F7: a non-hex brand colour
  cannot break out of the `<style>` block on the page or embed (falls back to `#0A2540`).
- `test_powered_by_badge_opens_in_new_context` (`test_public_wall.py`) — locks F9: the badge carries
  `target="_blank" rel="noopener noreferrer"` on page + embed.
- `test_photo_forbidding_consent_holds_card_off_the_wall` + `test_no_photo_consent_also_held_off_wall`
  (`test_wall_consent.py`) — lock F3: `no_photo`/`initials_only` athletes are held off the wall entirely
  (page, feeds, PNG 404) and recorded in `consent_hidden`; full-consent athletes unaffected.
- `test_initials_only_level_binds_even_with_toggle_off` (`test_wall_consent.py`) — **rewritten** to assert
  the new fail-closed behaviour (the initials_only athlete is now held off the wall, not shown with
  initialled text + full-name image). This tightens the assertion; it is not a weakening to pass the gate.

---

## 7. Cross-cutting changes

**Three one-line edits to the shared `web.py`, all confined to the wall's own render/route code**
(the `_wall_page_html` helper and the `public_wall_card_png` route — code that only the Public Wall uses,
so cross-session merge risk is low, but flagged here for reconciliation):

1. `_wall_page_html` — validate `primary` to a hex colour before interpolating it into the `<style>` block
   (F7). No behaviour change for valid brand colours.
2. `public_wall_card_png` — `Cache-Control` `max-age=3600` → `max-age=300, must-revalidate` (F8).
3. `_wall_page_html` — add `target="_blank" rel="noopener noreferrer"` to the "Powered by" badge (F9).

No changes to base templates, shared CSS/JS, config, `requirements.txt`, or `pyproject.toml`. The three
web.py lines pass the pinned pre-commit (`ruff` v0.8.4 + `ruff-format`). The shared `rendered_card_png`
(consumed by share-links/newsletters) was **deliberately not** modified — see §8.

---

## 8. Residual risks / cross-feature work (not attempted here)

- **Shared `rendered_card_png` photo-consent gap (out of scope):** the F3 fix was applied to the wall's own
  `wall_image_path`, but the sibling `rendered_card_png` (used by 1.18 share-links and newsletters) still gates only on `blocked`, not `photo_ok`. Those surfaces have the same
  tighten-after-render photo-leak for `no_photo`/`initials_only` athletes. Left for those features' own
  audits so this change stays inside the Public Wall's blast radius; recommend the same `photo_ok` gate there.
- **F2 upstream durability:** the wall now fails closed on an *unloadable* snapshot; a belt-and-braces upstream
  guarantee that individual-athlete cards always carry a resolvable name would also close the (low-reachability)
  id-mismatch variant where a run loads but a specific athlete card has no achievement entry.
- **F4/F5/F6:** small hardening (card_key validation in the `public_wall_update` branch of `web.py`; document
  the 30-run list window / align it with the PNG route's 200; optional per-token wall memoisation) — logged,
  not blocking.

---

## 9. Feature verdict

**WORKS-WITH-CAVEATS** (materially strengthened by the second pass). The Public Wall is a mature,
well-tested feature: approved-only gating, structural token revocation, cross-tenant isolation, CSRF, CSP
framing, path-traversal safety, error resilience, accessibility (AA contrast, consent-honouring alt text),
and British copy all hold up under adversarial testing. The second pass closed two genuine **P1**
children's-data safeguarding gaps that the first pass had deferred — the missing/corrupt-snapshot consent
fail-**open** (F2) and the `no_photo`/`initials_only` full-name/photo image leak (F3) — plus a public-surface
CSS-injection (F7), an over-long children's-image cache TTL (F8), and an embed iframe-takeover (F9), each with
a locking test. Remaining items are non-blocking hardening and one explicitly-scoped cross-feature carry-over
(`rendered_card_png`).

---

## 10. Handover and merge status

- **Branch:** `claude/audit-public-wall-14m718` (the designated push branch; working `audit/public-wall`).
- **Green gate:** app boots (502 routes); pinned pre-commit (`ruff` v0.8.4 + `ruff-format`) passes on all
  changed files; the wall + adjacent suites pass; the full `tests/` run was executed on the rebased result
  (see the PR / final turn for the exact pass count and the `origin/main` BASE SHA).
- **Merge status:** _completed in Phase 5_ — see the PR / final turn for the merge/commit SHA (or, if the
  green gate or a shared-file conflict blocked it, the exact reason and the branch left pushed for manual merge).
- **Review the diff:** `git diff origin/main...claude/audit-public-wall-14m718`
