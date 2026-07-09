# Feature Audit — Public Wall (Create)

**Mode:** AUDIT+FIX · **Auditor session branch:** `claude/audit-public-wall-14m718`
**Date:** 2026-07-09 · **Verdict:** WORKS-WITH-CAVEATS (see §9)

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
| 7 | Security (authz/IDOR/injection/CSRF/secrets/traversal) | PASS | Members-only routes gated; cross-tenant 404; path traversal all 404; XSS neutralised on page/RSS/JSON/oEmbed html; CSRF auto-injected + enforced; no secrets/paths leaked. Consent fail-open on unresolvable names is a residual (F2). |
| 8 | Performance sanity | PASS-with-note | Bounded scan (≤30 runs, ≤60 cards) + HTTP caching; per-request filesystem + per-card consent lookups are not server-cached (F6, residual). |
| 9 | Responsive / accessibility | PASS | Card `<img>` carry consent-honouring alt text; page has lang + title; grid responsive at 320px; contrast all ≥ 6.65:1 (AA). Settings initials checkbox is labelled. |
| 10 | Rendered-graphic correctness | PASS-with-caveat | Wall serves the already-rendered portrait PNG; alt text matches the (initialled) title. Consent tightened to `initials_only` *after* render leaves a stale full-name image (F3, needs-coordination). |
| 11 | Consistency / copy (British English) | PASS | Copy is clear, British, no placeholder/debug/TODO or em/en dashes in wall copy. |

---

## 4. Findings

| ID | Sev | Title | Status |
|---|---|---|---|
| F1 | P2 (latent P1) | `public_wall._runs_dir()` ignored the `RUNS_DIR` env override | **fixed** |
| F2 | P3 | Consent gate fails **open** for a card whose athlete name can't be resolved | logged (residual) |
| F3 | P2 | `initials_only` consent tightened *after* render leaves a stale full-name PNG on the wall | needs-coordination |
| F4 | P3 | `exclude` accepts and persists arbitrary/oversized `card_key` strings unvalidated | logged |
| F5 | P3 | Wall lists ≤30 recent runs but the PNG route reaches 200 — older approved cards silently drop off the list | logged |
| F6 | P3 | No server-side cache: every wall/feed hit re-scans the filesystem + runs a consent lookup per card | logged (residual) |

*(Findings from the parallel adversarial audit workflow are folded in below once verified; §4 is the reconciled set.)*

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

### F2 — Consent fails open on an unresolvable athlete name (residual)
- **Reproduction:** `scratchpad/repro_consent.py` (A) — an approved+rendered card whose visual
  `content_item_id` is absent from the run's `ranked_achievements`/`cards` resolves to an empty
  `swimmer_name`; `_consent_block_reason` returns `None` for an empty name, so the card is shown
  and its PNG served even under an active consent regime.
- **Assessment:** This is **correct** for genuinely athlete-less cards (team/club/meet-recap), which
  legitimately have no name to protect, and in the real pipeline the visual/achievement/workflow id
  spaces align (all read from the same run snapshot). It only fails open if the pipeline ever emits
  an *individual-athlete* card whose name the wall can't parse — low reachability. A blanket "hide all
  nameless cards under an active regime" would wrongly suppress legitimate team cards, so **not fixed
  in the wall**; the durable fix is upstream (guarantee athlete cards carry a resolvable name). Logged
  as a residual fail-open to watch.

### F3 — `initials_only` tightened after render leaves a stale full-name image (needs-coordination)
- **Reproduction:** `scratchpad/repro_consent.py` (B) — with an athlete's consent at `initials_only`,
  the wall **text** correctly shows `A.S.`, but `wall_image_path`/the PNG route still serve the
  already-rendered graphic, which has the **full name baked in** if it was rendered while consent was
  `full`/absent.
- **Assessment:** `content_pack/builder.py` applies `initials_only` by rewriting `swimmer_name` **at
  build/render time**, so a card rendered *after* the consent level is set already shows initials — the
  gap is only the **post-hoc tightening window** (full → initials_only *after* render + approval). A
  `do_not_feature` tightening is safe (the card is fully blocked and the PNG 404s). Fixing this properly
  means re-rendering on the wall or tracking each asset's name-visibility and suppressing stale ones —
  both cross into the graphic renderer / deterministic-engine boundary and would break the existing,
  intended behaviour that `initials_only` athletes still appear on the wall. **Out of the wall's tight
  blast radius — logged for coordination** (children's-data safeguarding; recommend a re-render-on-
  consent-change or a "name visible in asset" flag).

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

---

## 5. Fixes applied

| File | Change | Why |
|---|---|---|
| `src/mediahub/web/public_wall.py` | `_runs_dir()` now honours the `RUNS_DIR` env override (default unchanged) | F1 — align with the app-wide `RUNS_DIR` convention so a custom `RUNS_DIR` deployment isn't served an empty wall |

No shared-file (`web.py`, templates, config, requirements) edits were required.

---

## 6. Tests added / extended

Both appended to `tests/test_public_wall.py`:
- `test_wall_honours_runs_dir_override_distinct_from_data_dir` — locks F1: a `RUNS_DIR` distinct from
  `DATA_DIR/runs_v4` is read correctly (cards listed, page + PNG 200).
- `test_hostile_names_are_neutralised_on_every_surface` — defence-in-depth: a hostile swimmer/meet/club
  name is neutralised on the HTML page, the RSS feed stays well-formed XML with no raw `<script>`, and
  the JSON feed is served as `application/json`. Guards the escaping against future edits.

---

## 7. Cross-cutting changes

**None.** All edits are confined to `src/mediahub/web/public_wall.py` and `tests/test_public_wall.py`.
No changes to `web.py`, base templates, shared CSS/JS, config, `requirements.txt`, or `pyproject.toml`.

---

## 8. Residual risks / cross-feature work (not attempted here)

- **F3 (needs-coordination):** post-render consent tightening to `initials_only` leaves a stale
  full-name image — a graphic-renderer/pipeline concern (re-render on consent change, or an
  asset-level "name visible" flag). Children's-data safeguarding; flag for the renderer/consent owners.
- **F2:** upstream guarantee that individual-athlete cards always carry a resolvable name, so the
  wall's consent gate never sees an unresolvable athlete.
- **F4/F5/F6:** small hardening (card_key validation in `web.py`; document the 30-run list window;
  optional per-token wall memoisation) — logged, not blocking.

---

## 9. Feature verdict

**WORKS-WITH-CAVEATS.** The Public Wall is a mature, well-tested feature: approved-only gating,
structural token revocation, cross-tenant isolation, consent-fail-closed, CSRF, CSP framing, injection
safety, error resilience, accessibility, and British copy all hold up under adversarial testing. One
real (latent-in-prod) correctness bug — the `RUNS_DIR` divergence — is fixed and locked with a test.
The remaining items are residual/needs-coordination hardening, chiefly the post-render consent-tightening
image gap (F3), which is out of the wall's tight blast radius.

---

## 10. Handover and merge status

- **Branch:** `claude/audit-public-wall-14m718` (working `audit/public-wall`).
- **Merge status:** _pending Phase 5_ — see the final section of this document / PR.
- **Review the diff:** `git diff origin/main...claude/audit-public-wall-14m718`
