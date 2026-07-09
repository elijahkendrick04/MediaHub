# Audit — the "Plan" feature (Create → Plan, the Cross-Source Planner)

Mode: AUDIT+FIX · Auditor session · Branch: `claude/audit-plan-feature-t0a7hi`

> Branch-name note: Hard Rule 1 asks for `audit/<slug>`; this session was
> assigned the fixed development branch `claude/audit-plan-feature-t0a7hi` by
> the harness and told never to push elsewhere without permission, so all work
> lands there. The invariant that matters — branch first, never commit to
> `main`, merge only through the Phase 5 green gate — is honoured.

## 1. Scope contract

**What the feature is.** The Plan feature is MediaHub's *strategy brain* (roadmap
P1.3 + 1.14): the `/plan` page, reached from the **Create** tab, answers "what
should we post next?" It fuses three deterministic, read-only signal sources —
**own** (processed runs, card workflow state, draft-pack recency, measured post
performance), **external** (discovered meet context, calendar anniversaries,
curated key dates), and **direct** (operator-entered upcoming events, blackout
dates, structured goals) — into a **ranked, explainable content plan** where every
line traces to a signal. Around the ranked plan sit five companion surfaces: a
month **calendar** (drag-to-schedule planned drafts), an Instagram-style **grid**
preview, per-channel **previews**, a committee **board** (Kanban idea cards →
promote to draft), a first-party **performance** loop (log posts → deterministic
attribution feeds the ranker + optional AI digest), and **sponsor ad-variant**
export sets. An AI free-text box (`/api/plan/interpret`) turns a plain-language
note into structured direct inputs for review. **"Working" means:** the ranked
plan is correct + deterministic + source-grounded; every control does what it
says; inputs validate cleanly; state persists and reads back per-org with no
leakage; nothing publishes; and the AI surfaces honest-error without a provider.

**Routes owned (method · path):**

| Method | Path | Handler |
|---|---|---|
| GET | `/plan` | `plan_page` — ranked plan + direct-inputs form + NL box |
| GET | `/api/plan/latest` | `api_plan_latest` |
| POST | `/api/plan/generate` | `api_plan_generate` |
| GET/POST | `/api/plan/inputs` | `api_plan_inputs` |
| POST | `/api/plan/interpret` | `api_plan_interpret` (AI, honest-error) |
| GET | `/plan/calendar` | `plan_calendar_page` |
| GET | `/api/plan/calendar` | `api_plan_calendar` |
| POST | `/api/plan/calendar/schedule` | `api_plan_calendar_schedule` |
| GET | `/plan/grid` | `plan_grid_page` |
| GET | `/plan/preview/<pack_id>` | `plan_preview_page` |
| POST | `/api/channel-preview` | `api_channel_preview` |
| GET | `/plan/board` | `plan_board_page` |
| GET | `/api/plan/board` | `api_plan_board` |
| POST | `/api/plan/board/add\|move\|delete\|promote` | board APIs |
| GET | `/plan/analytics` | `plan_analytics_page` |
| POST | `/api/plan/analytics/record\|delete\|digest` | analytics APIs |
| GET | `/plan/ad-variants/<pack_id>` | `plan_ad_variants_page` |
| GET | `/api/plan/ad-variants/<pack_id>/export` | `api_plan_ad_variants_export` |

**Files owned (blast radius):**
- `src/mediahub/content_engine/{planner,signals,inputs,nl_inputs,calendar,key_dates,board}.py`
- `src/mediahub/analytics/{store,attribution,digest}.py`
- The plan route handlers + inline templates/JS inside `src/mediahub/web/web.py`
  (lines ~31047-32778) and their local helpers.

**Shared files depended on but NOT freely rewritten:** `web/web.py` app factory
and `_layout`/`_h`/`_active_profile_id` (edit only the plan routes, minimally);
`club_platform/{post_types,stub_pack_store,content_types}.py`; `sport_profiles`;
`channel_preview`; `ad_export`; `workflow/store`; base CSS/JS.

**Inputs/outputs/state.** In: sport (from org type), operator events/goals/
blackouts, free-text note, logged post metrics, board idea cards, draft schedule
dates. Out: ranked `ContentPlan` (per-org JSON under `DATA_DIR/content_plans/`),
calendar model, attribution table, ad manifests. State persists per-org under
`DATA_DIR/{content_plans,planner_inputs,plan_board,analytics,stub_packs}/`.

**Happy path (concrete expected results).** Ready swimming org → open `/plan` →
"Generate plan" → deterministic ranked list of post types, each with a score and
signal-traced reasons, result-led types honest about "no results yet"; add an
event/goal/blackout → Save → regenerate → the ranking shifts and cites the new
signal; drag a draft on the calendar → `planned_date` set, blackout warns softly;
log posts → attribution table + planner nudge; nothing publishes anywhere.

## 2. Environment

- Python 3.11.15; installed `-r requirements.txt` + `.[dev]` (`--ignore-installed PyYAML`).
- `.env` (gitignored) with dummy `SECRET_KEY`, empty provider keys (offline — AI
  surfaces honest-error), `DATA_DIR` under the session scratchpad.
- App booted via `python -m mediahub.web` on **port 5055**; 502 routes, 22 `/plan*`
  routes registered; clean startup (one expected warning: "No LLM provider configured").
- A **ready** unbound swimming-club org `audit-club` seeded on disk; a valid signed
  Flask session cookie minted (same SECRET_KEY) to drive the authenticated pages.
- Reproductions use the in-process Flask test client with a tmp `DATA_DIR`
  (matches the existing `tests/` pattern). Provider calls are never made (no keys).
- Playwright drives the live pages via the prebaked Chromium
  (`/opt/pw-browsers/chromium-1194/chrome-linux/chrome`, `executable_path`).

<!-- FINDINGS, FIXES, TESTS, VERDICT, MERGE STATUS appended after Phase 3-5 -->
