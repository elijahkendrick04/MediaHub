# Autonomous Build Log

Append-only log for the autonomous build engine. Each autobuild cycle reads the
**HANDOFF (latest)** block, does the single next task, then prepends a new cycle
entry under **Cycles (newest first)** and refreshes the handoff. Newest state
lives at the top.

---

## HANDOFF (latest)

1. ✅ **Production health: healthy.** `https://mediahub-gzwc.onrender.com`
   `/healthz` returns `{"ok":true,"version":"v4.0.0"}`. PR #272 is deployed live
   on Render (commit `0d8a45e`, build green).
2. 🟡 **Mid-flight: nothing half-merged.** No work is left in a partial state.
   ⚠️ NOTE: a concurrent actor merged **PR #273** (graphics archetype **PAR-7**)
   to `main` immediately after #272, so a second autobuilder — or the operator —
   may be working in parallel. Watch for collisions (rebase before you push, and
   re-check `main` head before merging).
3. ⛔ **Single next task.** **PC.3** (true multi-tenancy, org → workspace) is
   **BLOCKED** pending operator/Council sign-off on the schema, because it
   touches the locked cross-tenant isolation invariant (**ADR-0003**). Until that
   sign-off lands, the next unblocked autonomous item is **P1.4 graphics Tier B**
   (sellable-wedge bar) **or P0.1 Remotion free-fallback**. Add **no new running
   cost**.
   `/healthz/deps` returns `{"ok":true,…,"deps":{"reel_engine":{"active":"remotion",
   "remotion_available":true,…}}}`. PR #280 is deployed live on Render
   (commit `13f776d`, all CI checks green).
2. 🟢 **Mid-flight: nothing half-merged.** Several sibling PRs (#278 strategy,
   others) merged to `main` in parallel and landed clean alongside #280.
3. ➡️ **Single next task.** **P0.1 slice 2** — implement the actual free
   **Satori+FFmpeg** renderer behind the `satori` engine name. The seam is the
   drop-in point: `_dispatch_engine()` in `motion.py` already returns for
   `'satori'`; the concrete renderer goes in `reel_engine.py` (or a new
   `satori_engine.py`). When it ships, flip `satori_available` to `True` in
   `reel_engine_status()` and drop the `ReelEngineUnavailable` guard. No new
   running cost (Satori is pure Node, no cloud API).

---

## Cycles (newest first)

### 2026-06-09 — P2.4 per-type autonomy controls in workspace

**Task chosen and why.** P2.4 was the next unblocked autonomy surface task:
the runner substrate (P2.1) and global kill switch (P2.3 partial) already
shipped; P2.2/P2.4 (the per-type toggle + workspace UI) were the missing product
surface. All work is additive and default-gated — the production path is
byte-identical with everything off.

**Shipped via PR #297** (merged to `main`, commit `c63df08`, deployed live):

- **`src/mediahub/publishing/per_type_policy.py`** (new) — per-profile JSON
  policy store under `DATA_DIR/per_type_autonomy/<org_id>.json`. Maps each
  `ContentType` to `AutonomyLevel`; defaults every type to `approval_required`
  (most gated); old profiles with no file load cleanly as fully gated.
- **`src/mediahub/publishing/type_gate.py`** (new) —
  `assert_type_publishing_allowed(org_id, type)` checks the global kill switch
  then the per-type policy; raises `TypeGated` (queue for human approval) unless
  the type is `fully_autonomous`.
- **`src/mediahub/web/web.py`** — `GET/POST /api/autonomy/policy` routes scoped
  to the active org (403 with no active org); Settings > Autonomy controls tab
  listing all 6 `ContentType`s with selects, a `fully_autonomous` warning callout,
  and AJAX save; `/healthz/deps` additively exposes `per_type_autonomy` summary
  (never affects `ok` flag).
- **`tests/test_per_type_autonomy.py`** (new) — 25 tests: defaults are fully
  gated; setting a level persists per-profile; cross-profile isolation; publish
  gate blocks unless `fully_autonomous` AND kill switch off; old profiles load as
  gated; UI round-trips (GET + POST).

**Tests.** 3567 passed, 1 skipped (pre-existing opt-in render-diff regression),
0 new failures. All 6 CI checks green. No test deleted/skipped/weakened. `ruff`
v0.8.4 clean. Self-corrected two issues mid-build: (1) hex-literal CSS-var
fallbacks (e.g. `var(--bg,#1a1a1a)`) tripping the theme-tokens hex-budget test
— removed fallbacks; (2) ruff-format pre-commit CI failed on `web.py` cosmetic
reformatting — re-ran `pre-commit run ruff-format` and pushed.

**PR.** https://github.com/elijahkendrick04/MediaHub/pull/297

**Canonical enum.** `sport_profiles.autonomy.AutonomyLevel`
(`draft_only` / `approval_required` / `fully_autonomous`) — the publishing-policy
axis. `autonomy.tools.AutonomyLevel` (`OFF/SUGGEST/DRAFT/PREPARE`) is the
runner-reach axis; the two enums are NOT collapsed (ROADMAP.md guidance).
Reconciliation queued for a future cycle.

**Live-verify.** Post-deploy: `/healthz/deps` returns `per_type_autonomy` key
with `ok:true`; `/settings` renders Autonomy tab with 6 selects defaulted to
Approval required; persistence round-trip (`draft_only` → save → reload → restore)
confirmed; core journey (`/` 200, `/make` 200) intact.

---

### 2026-06-09 — P0.1 slice 1: reel render-engine selection seam

**Task chosen and why.** The HANDOFF listed **P0.1 Remotion free-fallback** as
the next unblocked autonomous item with no new running cost. The first slice is
the necessary prerequisite: a clean engine-selection seam that makes the
production path byte-identical while registering the future `satori` slot.
Building the seam first (rather than the full renderer) keeps the change
purely additive, easy to verify, and safe to merge even with concurrent sibling
PRs landing.

**Shipped via PR #280** (merged to `main`, commit `13f776d`, Render-deployed
live):

- **`src/mediahub/visual/reel_engine.py`** (new) — `select_reel_engine()`
  reads `MEDIAHUB_REEL_ENGINE` (default `'remotion'`); `reel_engine_status()`
  returns `{configured, active, remotion_available, satori_available,
  available_engines}`; `ReelEngineUnavailable` honest-error exception.
- **`src/mediahub/visual/motion.py`** — `_dispatch_engine()` no-op helper
  inserted at the top of both `render_story_card` and `render_meet_reel`;
  `remotion` path unchanged; `satori` raises `ReelEngineUnavailable` (no fake
  asset — CLAUDE.md AI-surfaces rule).
- **`src/mediahub/web/web.py`** — `/healthz/deps` additively exposes
  `reel_engine_status()` under `deps.reel_engine`; `ok` flag unchanged.
- **`docs/ENV_INVENTORY.md`** — regenerated to include `MEDIAHUB_REEL_ENGINE`.
- **`tests/test_reel_engine.py`** (new) — 21 tests: default selects remotion;
  unknown/satori raises honest error; `reel_engine_status()` shape; dispatch
  mocks confirm `_run_remotion` called on default, not called for satori.

**Tests.** 3482 passed, 1 skipped (pre-existing opt-in render-diff regression),
0 failures. All 6 CI checks green (ruff-format one-line fix re-pushed before
merge). No test deleted/skipped/weakened. `ruff` v0.8.4 clean.

**PR.** https://github.com/elijahkendrick04/MediaHub/pull/280

**Live-verify.** Post-deploy, `/healthz/deps` returns
`{"reel_engine":{"active":"remotion","remotion_available":true,
"satori_available":false,"available_engines":["remotion"]}}`, `ok:true`.
Core render flow (story card, meet reel) unaffected.

---

### 2026-06-09 — Phase C reconciliation + foundation-lock

**Task chosen and why.** Phase C is roadmap **#1**. Its shippable code items —
**PC.1** signup/auth and **PC.2** Stripe billing — were already merged in **PR
#267** and are live, but the roadmap still badged them **NOT STARTED**: a stale
source of truth that misdirects every subsequent cycle. The remaining Phase-C
code item, **PC.3**, is a cross-org isolation rearchitecture: CLAUDE.md
governance says to Council-pressure-test it, and the catastrophe boundary forbids
weakening the cross-tenant isolation invariant. So PC.3 was **escalated** for
operator/Council sign-off rather than built unattended, and this cycle did the
safe, high-value work that was actually actionable — reconciling the roadmap to
reality and locking the billing-isolation foundation with a regression test.

**Shipped via PR #272** (merged to `main`, commit `0d8a45e`, Render-deployed
live):

- `docs/ROADMAP.md` badge reconcile — **PC.1 done**, **PC.2 done (awaits operator
  `STRIPE_*` keys)**, **Phase C in-progress**, plus the **PC.3 escalation note**.
- Additive cross-account billing-isolation regression test
  `test_billing_does_not_leak_another_accounts_plan` in `tests/test_auth.py`.

**Tests.** 3455 passed, 1 skipped (pre-existing opt-in render-diff regression),
5 CI checks green. No test deleted/skipped/weakened. `ruff` v0.8.4 clean.
Secrets env-only.

**PR.** https://github.com/elijahkendrick04/MediaHub/pull/272

**Live-verify.** Post-deploy, `/login`, `/make` → `/sign-in` org picker,
`/pricing`, and `/healthz` all render; core flow intact.
