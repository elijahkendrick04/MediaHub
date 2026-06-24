# AI governance (roadmap 1.23)

**Date:** 2026-06-24 · **Scope:** new `governance/` package +
`observability/feature_quota.py`, metering/permission gates on the AI surfaces,
provenance manifests, and the governance dashboard + `/settings/governance`
surface · **Status:** shipped in four sub-builds on one branch → one PR.

## What 1.23 is

The control plane over every AI surface. It answers four questions, each
explainable and auditable:

- **How much** AI is each org using, and is it over a limit? (per-org /
  per-feature **quotas**)
- **Who** inside an org may use which AI feature? (role-based **permissions**)
- **What** did the AI produce, from what, and when — and what was AI vs
  deterministic? (**provenance** manifests)
- (Deliberately *not* **content moderation** — see "Scope decision" below.)

It builds on what already shipped: the per-org generative-imagery quota
(`imagine_usage`, P6.3), the workspace role→capability matrix
(`collab/permissions.py`, 1.18), the plan tiers (`auth.py`), and the existing
imagery/motion provenance sidecars.

## How it was built (four sub-builds, one branch)

1. **Quota ledger + policy foundation** — `observability/feature_quota.py` (a
   general per-org/per-feature usage ledger mirroring `imagine_usage.py`) and the
   `governance/` package: `features.py` (the shared registry of governed AI
   features), `quota.py` (limit resolution → `check`/`enforce`/`record` + an
   honest `QuotaExceeded`), `context.py` (request-scoped org/plan + the
   `feature_scope` guard). Nothing wired into request paths yet, so it could not
   affect a live club.
2. **Metering + enforcement at the caption surface** — a `before_request` binds
   the active org+plan into the governance context; the live-caption route
   enforces the caption quota and records exactly one feature-use per request
   (success counts toward quota; a failed attempt is logged, not charged).
3. **Role-based permissions** — `governance/permissions.py` maps each AI feature
   to the capability it needs (content generation → `edit`; brand-defining AI →
   `manage`/owner), enforced on the caption route and the generative-imagery
   routes (generate + the edit-family asset ops). Deterministic subject-lift /
   grab-text spend no budget and stay ungated.
4. **Provenance + dashboard + docs** — `governance/provenance.py` (one honest
   manifest schema + sidecar I/O + a `normalise()` reader spanning our manifests,
   the imagine `*.imagine.json`, and motion `<hash>.json`); `persist_visual`
   now stamps a `<png>.provenance.json` beside every rendered card; the operator
   `/healthz/governance` per-org usage view and the org-facing
   `/settings/governance` section (usage + quota headroom + the role→feature
   matrix + a provenance note).

## The rules it respects

- **Meter everything; hard-block only where a limit is set** (maintainer
  decision 2026-06-24). The built-in plan-limit table and the per-feature
  min-plan table both ship **empty**, so this build changes no live club's flow;
  a feature blocks only once an operator sets a specific limit (built-in table,
  `MEDIAHUB_QUOTA_<FEATURE>[_<PLAN>]`, or a per-org override). An over-quota call
  raises an honest `QuotaExceeded` — never a fabricated caption.
- **Honest errors, never substitutes.** Quota-exceeded → `quota_reached`;
  insufficient role → `forbidden`. No fake content is ever returned in their
  place.
- **Deterministic engine untouched.** Parsers, detectors, the ranker and
  colour-science are not involved. Quotas/permissions are pure data + predicates;
  provenance is pure stdlib. The mathematical photo selector and the renderer are
  unchanged — the provenance sidecar is written beside the PNG without touching
  its bytes, so render caches and parity stay byte-identical.
- **Honest provenance.** A result card is stamped as a **deterministic composite
  of real photography** (its pixels are not AI — only caption/creative direction
  may be, and the manifest lists which); a generated image stays marked
  `ai_generated`/`ai_composite`. We never overclaim a card as a synthetic image.
- **Multi-tenant + least privilege.** Usage is org-scoped; quota fails *open* on
  a DB read error (a transient hiccup never wrongly blocks a paying club); unknown
  roles fall to least privilege.
- **Layering kept clean.** `permissions` (which reaches the web layer via
  `collab`) is imported lazily from the `governance` package, so the
  render/integration paths import `governance.provenance` without dragging the
  web stack in.

## Scope decision — moderation descoped

The roadmap line for 1.23 listed **generative moderation** as a component. The
maintainer removed it from scope on 2026-06-24: MediaHub keeps a **human in the
loop before any external publishing** (no machine path posts to a social
account), and the existing prompt-injection guard (`ai_core/prompt_guard`),
child-policy backstop (`compliance/child_policy`) and LLM data-minimisation
already cover the safety surface that matters. No moderation/censorship layer
was built. This report and the `governance/` README record that decision so the
gap is explicit, not silent.

## Tests

~94 new tests across six files — the ledger (`test_feature_quota_log`), the
quota policy (`test_governance_quota`), the request context + guard
(`test_governance_context`), the permission matrix + a bound-org web gate
(`test_governance_permissions`, `test_governance_feature_permissions_web`),
caption metering/enforcement end-to-end (`test_governance_caption_metering`),
provenance manifests + `persist_visual` wiring (`test_governance_provenance`),
and the dashboard + settings surfaces (`test_governance_dashboard_web`). The
imagery, caption, settings, status and render suites stay green; ruff clean.

## Deferred (by design, with a home)

- **Per-org limit overrides in the UI** — `quota.limit_for` already accepts an
  `org_override`; persisting it from `/settings/governance` is a small follow-on.
- **Commercial plan-tier numbers** — `_PLAN_FEATURE_LIMITS` /
  `_FEATURE_MIN_PLAN` are the single place to fold in real tier limits when the
  commercial pass (PC.4) lands.
- **Unifying the imagery/motion manifests onto `governance.provenance`** — they
  keep their shipped sidecars today; `normalise()` already reads all three, so a
  future pass can converge the writers without a reader change.
