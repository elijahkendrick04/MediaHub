# The Cross-Source Planner (the strategy brain)

> **In plain words.** MediaHub works out *what a club should post next* — not
> only how to turn one results file into posts. The planner looks at three
> kinds of evidence: what's already in MediaHub (your processed results and
> drafts), what's happening in the world (discovered meet context, the
> calendar), and what you've told it (upcoming events, goals, blackout
> dates). It fuses those into a **ranked list of post types with the
> reasoning shown for every line**. It recommends — you decide. Nothing
> publishes from the plan.

Shipped as roadmap **P1.3**. Code: `src/mediahub/content_engine/`
(`signals.py`, `planner.py`, `inputs.py`, `nl_inputs.py`); surface: the
**Plan** page (`/plan`) — reached from the **Create** tab (it answers "what
should we make?"), not the top bar — plus `/api/plan/*`. Data-model spine: the
slug-canonical post-type layer ([`POST_TYPE_TAXONOMY.md`](POST_TYPE_TAXONOMY.md),
ADR-0013) over the sport profiles ([`SPORT_PROFILES.md`](SPORT_PROFILES.md)).

Operators can fill the **direct** inputs by hand (events with dates + venues,
blackout dates, goals targeting an enabled post type) or **describe them in
plain language** and let `nl_inputs.interpret_planner_inputs` turn the note
into the same structured inputs for review — the Free-Text feature's LLM
interpretation + optional web research, applied to planning. The AI only
*proposes* inputs; the deterministic ranker below is untouched.

## 1. The three signal sources

| Source | What it reads | Where from |
|---|---|---|
| **own** | Processed runs + their card workflow state (queued / approved / posted), saved draft packs per type, draft recency | `DATA_DIR/runs_v4/`, `stub_packs/` |
| **external** | Meet identities the context engine has discovered; calendar anniversaries of the club's own past meets | `data/discovered/meets/`, calendar × run history |
| **direct** | Operator-entered upcoming events, **structured goals** (each goal targets a post type picked from the profile — no free-text guessing), blackout dates; sponsor-configured fact from the org profile | `DATA_DIR/planner_inputs/<org>.json`, `ClubProfile` |

Gathering is deterministic and read-only — no network, no LLM. Every signal
carries `provenance` (the file/store it was read from). Tenant isolation: a
gatherer only ever reads the active org's records.

## 2. How ranking works (deterministic, explainable)

The planner generalises the swim newsworthiness ranker's transparent
additive-scoring pattern: a **category base** (result-led 40 · pre-event 35 ·
evergreen 25 · sponsor 24 · seasonal 18 · live 12) plus **signal-driven
modifiers**, each of which appends one reason line quoting the signal it
fired from. Examples:

- fresh results (≤7d) with cards in the review queue → result-led types +30;
- an operator-entered event 2 days out → pre-event types +25 (−15 if its
  date is a blackout);
- a structured goal targeting a type → +15;
- a configured sponsor **and** a fresh result to activate → sponsor +8/+12;
- a one-year anniversary of a past meet → history/milestone types +18;
- nothing drafted in a type for 21+ days → +6; drafted ≤3 days ago → −10.

Honesty rules: result-led boosts only fire when the run's engine sport
matches the profile's (`football` types never ride swimming results — they
carry the reason *"no football results ingested yet"* instead), and a plan
built with zero signals says so in `notes` rather than inventing context.
Per CLAUDE.md the ranking is deterministic engine territory — **no LLM in
the loop**; same inputs → same plan. AI judgement (copy, design) stays in
the downstream generation surfaces.

## 3. The plan object

`build_content_plan(sport, profile_id)` → `ContentPlan`: ranked `PlanItem`s
(`post_type` slug, `title`, `score`, `reasons[]`, `sources_used ⊆
{own,external,direct}`, `signal_refs[]` provenance, the profile's
`default_autonomy`, and the `implemented` badge linking to the Create
surface where one exists), plus the gathered `signals`, `source_counts` and
honest `notes`. Plans persist per org under
`DATA_DIR/content_plans/<org>/<plan_id>.json` with a `latest.json` pointer
(ownership-checked on load).

## 3a. The calendar (roadmap 1.14)

The ranked plan answers *what* to post; the **calendar** answers *when*. The
**Plan → Open calendar** page (`/plan/calendar`) lays a month out as a grid and
fuses six date sources, all org-scoped and read-only:

| On the grid | From |
|---|---|
| **Planned drafts** (draggable) | draft packs carrying a `planned_date` (`stub_pack_store`) |
| **Key dates** | curated, provenance-stamped packs per sport (`content_engine.key_dates` ← `data/key_dates/<sport>.yaml`) |
| **Events** · **Blackouts** | operator direct inputs (`content_engine.inputs`) |
| **Anniversaries** | the club's own past meet dates × the month |
| **Posted** | `workflow` card states with a `posted_at` in the month |

Code: `content_engine/calendar.py` (`build_calendar` → `CalendarModel`, pure +
deterministic + URL-free) and `content_engine/key_dates.py`
(`load_key_date_pack` / `key_dates_in_range`; every key date resolves to an
**exact** date — a `fixed` month/day or an `nth_weekday` rule — nothing is
approximated onto the calendar). Routes: `/plan/calendar` (month page),
`/api/plan/calendar` (JSON), `/api/plan/calendar/schedule` (the drag mutation).

**Scheduling is planning, not publishing.** A draft's `planned_date` is the day
the club intends to post it *by hand*; MediaHub never places content on a social
account (standing rule). Dragging a draft re-evaluates the **soft blackout
gate** — a planned draft landing on a blackout date is flagged with a warning,
never hard-blocked: it's the club's own plan, so the human decides. Curated key
packs never invent a club's fixtures — precise meet dates and deadlines stay
operator-entered. Tests: `tests/test_planner_calendar.py`.

## 3b. The board + the performance loop (roadmap 1.14)

Two more surfaces hang off the plan, both reached from the calendar bar:

- **The board** (`/plan/board`, `content_engine/board.py`) — a committee
  **whiteboard / Kanban** of free-form idea cards in four columns mirroring the
  content lifecycle (idea → drafted → approved → scheduled). Drag a card as it
  progresses; **promote** a good idea into a real free-text draft (seeded from
  the idea text verbatim — no AI, so it works with no provider) which then flows
  into the previews and the calendar.
- **The performance loop** (`/plan/analytics`, `analytics/`) — the club logs how
  a posted card did (manual entry; auto-ingest is a documented **post-P4** seam,
  since MediaHub never auto-publishes), and the **deterministic** attribution
  (`analytics/attribution.py`) feeds the planner: `gather_performance_signals`
  turns each well-sampled type's index-vs-own-average into a source-grounded
  **own** signal, and the ranker applies a small, bounded, *explained* nudge
  (`+8 / −6` max; a type needs ≥2 posts to count). The ranker stays
  deterministic — same recorded metrics → same plan. An optional AI **digest**
  only *phrases* the same numbers (number-guarded, honest-errors without a
  provider); the loop works without it.

## 4. Boundaries

- **Planner ≠ publisher.** The plan only recommends; nothing publishes from it.
  Approved content is exported or downloaded for manual posting. The plan shows
  each type's default review disposition (`draft_only` / `approval_required`)
  for context only. The calendar's "schedule" is the same: a planning date the
  club posts by, not a machine-publish trigger. The performance loop is
  manual-entry first-party data — no third-party aggregator, no auto-collection.
- **Planner ≠ detector.** "Is this a PB?" and card ranking inside a run stay
  with the deterministic recognition engine; the planner reads its outputs
  (achievement counts, queue states) and never overrides them.
- **≥2 sports by construction.** Any profile in `data/sport_profiles/`
  plans; swimming plans on all three sources end-to-end today, football
  plans on profile + direct/external signals until its engine lands (P3).

Tests: `tests/test_cross_source_planner.py` (signals, fusion, determinism,
honesty, isolation, persistence, routes).
