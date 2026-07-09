# Audit — Brand platform (Settings)

**Feature:** MediaHub "Brand platform" (Settings surface, roadmap 1.12)
**Mode:** AUDIT+FIX
**Branch:** `claude/brand-platform-audit-rrgi64`
**Date:** 2026-07-09

---

## 1. Scope contract

**Definition.** The Brand platform is the per-organisation brand home at `GET /brand`
(reached from Settings → "Brand platform") plus its management API. It lets a
workspace admin see and manage every brand *kit* the engine can apply to content —
the primary club livery and any sponsor / event / team-section / personal
co-brands. For each kit an admin can edit the palette (colour pickers), font
pairing, caption tone, token locks (palette/fonts/logo) and group-approver rules;
create and delete kits; set the default; import an Adobe `.ase` or Color-JSON
palette file; and run a kit-edit → re-render sweep (preview the affected cards,
then apply, which re-renders from persisted briefs and re-queues them for human
re-review). A companion per-card API scores any design against its kit
deterministically (Brand Check) and offers optional AI advice / auto-fix
(honest-erroring when no provider is configured). "Working" means: every control
does what its label claims; state persists to `ClubProfile.brand_kits` /
`default_kit_id` and reads back on the page; access is limited to workspace
admins; inputs are validated and rejected cleanly; and no route crashes, leaks a
secret, or is XSS/CSRF/IDOR-exploitable.

**Routes owned (method + path → endpoint).**

| Method | Path | Endpoint |
|---|---|---|
| GET | `/brand` | `brand_home_page` |
| POST | `/api/brand/kits` | `api_brand_kit_create` |
| POST | `/api/brand/kits/<kit_id>` | `api_brand_kit_update` |
| POST | `/api/brand/kits/<kit_id>/delete` | `api_brand_kit_delete` |
| POST | `/api/brand/kits/<kit_id>/default` | `api_brand_kit_set_default` |
| POST | `/api/brand/kits/<kit_id>/palette/import` | `api_brand_kit_palette_import` |
| GET/POST | `/api/brand/kits/<kit_id>/resweep/preview` | `api_brand_kit_resweep_preview` |
| POST | `/api/brand/kits/<kit_id>/resweep/apply` | `api_brand_kit_resweep_apply` |
| GET | `/api/runs/<run_id>/card/<card_id>/brand-check` | `api_card_brand_check` |
| POST | `/api/runs/<run_id>/card/<card_id>/brand-check/advise` | `api_card_brand_advise` |
| POST | `/api/runs/<run_id>/card/<card_id>/brand-check/autofix` | `api_card_brand_autofix` |

**Files owned (blast radius).** `src/mediahub/brand/kits.py`, `brand/check.py`,
`brand/palette_file.py`, `brand/resweep.py`, `brand/tone.py`; the brand-platform
route/helper block and constants in `src/mediahub/web/web.py`
(`_brand_can_admin`, `_render_brand_home`, `_brand_kit_card_html`,
`_brand_swatch_row`, `_brand_identity_html`, `_form_palette`, `_brand_redirect`,
the `api_brand_kit_*` and `api_card_brand_*` routes, `_brand_check_context`,
`_BRAND_FONT_PAIRINGS`, `_BRAND_LOCK_LABELS`). Tests under `tests/test_brand_*`.

**Shared files depended on but NOT freely rewritten.** `web.py` CSRF layer
(`_csrf_protect`, `_security_headers` — auto-inject), `web/club_profile.py`
(`ClubProfile`, `save_profile`/`load_profile`), `workflow/governance.py`,
`brand/palette.py`, `brand/kit.py`, `graphic_renderer/render.py`
(`resolved_role_vars_for_brief`), `quality/compliance.py`, `theming/logo_chip.py`,
`assistant/patch.py`, `media_ai/llm.py`, `tenancy`/`auth`/`perms` helpers.

**Inputs / outputs / persistence.** Input: form fields (kit name/role/palette
pickers/fonts/tone/locks/approver rules) and an uploaded palette file; query
params for resweep chunking and `?msg=`/`?err=` banners. Output: the rendered
`/brand` page and JSON from the API routes. State persists on the `ClubProfile`
(`brand_kits: list[dict]`, `default_kit_id: str`) via `save_profile`
under `DATA_DIR`; the resweep writes re-rendered visuals under the run dir and
sets `CardStatus.EDITED`.

**Happy path (concrete expected results).** Signed-in admin opens `/brand` →
sees one synthesised "Primary" kit for an un-migrated club (or all explicit
kits). Creates "Acme co-brand" (sponsor) → `brand_kits` gains it and the
materialised primary; page re-renders with both. Edits its palette via colour
pickers, locks "palette", saves → values persist and read back. Imports a
`.ase`/JSON palette → first four colours map to primary/secondary/accent/fourth.
"Make default" pins `default_kit_id`; "Delete" removes a non-primary kit
(primary is protected). Resweep "Preview" reports affected-card count; "Apply"
re-renders them in chunks and re-queues for review. Brand Check returns four
findings (palette/contrast/fonts/logo); advise/autofix honest-error without a
provider.

**Assumptions.** (1) I develop on the harness-designated branch
`claude/brand-platform-audit-rrgi64` (not a fresh `audit/…`) because the managed
environment forbids pushing to any other branch; the merge protocol is satisfied
via a draft PR rather than a direct `main` push, since the managed environment
mandates PRs and branch protection blocks direct pushes. (2) The per-card
Brand Check API is in scope as part of the same 1.12 feature even though its
(absent) review-page UI belongs to the review surface. (3) Existing em dashes in
copy are the established house style (ubiquitous in `web.py`) and are not treated
as findings; I avoid introducing new ones in copy I add.

---

## 2. Environment

- Python 3.11, `pip install -e .` (with `--ignore-installed PyYAML`), `pytest 9.1.1`.
- App booted offline via the `tests/test_brand_home_web.py` pattern: `DATA_DIR`,
  `RUNS_DIR`, `SWIM_CONTENT_PROFILES_DIR` set to a tmp dir; all provider keys
  (`GEMINI_API_KEY`, `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`)
  unset so AI surfaces honest-error (no real spend). `create_app()` with
  `app.config["TESTING"]=True`; production CSRF simulated with
  `app.config["ENFORCE_CSRF"]=True`.
- No live Render URL was exercised. No real paid API calls. No external publishing.
- Smoke: `/`, `/healthz`, `/sign-in`, `/pricing` all load (200); `/brand` → 302 to
  sign-in when anonymous.

---

<!-- Sections 3-10 filled after the audit workflow + fixes. -->
