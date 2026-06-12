# Autonomy Model

> **In plain words.** MediaHub can do three things with a post: just *draft* it,
> draft it and *wait for a person to approve* it, or — for low-risk post types a
> team explicitly trusts — *publish it on its own*. Each **post type** has its own
> setting, so a club can let "final-score posts" go out automatically while still
> personally approving "new signing" announcements. The default is always **wait
> for a human**. This page explains the three settings, the safety checks that
> guard automatic posting, and exactly where a human steps in.

Evidence base: [`research/ROADMAP_RESEARCH_2026.md`](research/ROADMAP_RESEARCH_2026.md)
§A.3, §D.3. Related: [`POST_TYPE_TAXONOMY.md`](POST_TYPE_TAXONOMY.md) (what carries
the setting), [`SPORT_PROFILES.md`](SPORT_PROFILES.md) (where it's stored),
[`ARCHITECTURE_TARGET.md`](ARCHITECTURE_TARGET.md) (the orchestration backbone),
[`adr/0003-pilot-safety-invariant-lock.md`](adr/0003-pilot-safety-invariant-lock.md)
(the safeguarding precedent this builds on).

> **Standing product rule, unchanged:** *human approval before any external
> publishing — always* is the default. "Fully autonomous" is a per-type **opt-in**
> a team turns on for itself, never a system default. MediaHub never auto-connects
> accounts or auto-publishes out of the box.

---

## 1. The three levels (`AutonomyLevel`)

Implemented (live) as `mediahub.sport_profiles.autonomy.AutonomyLevel` — the
canonical publishing-policy enum, stored per org/type by
`publishing.per_type_policy` (P2.4) and enforced by the publish gate (§4).
The *runner's* pre-approval reach is the separate
`autonomy.tools.RunnerReach` axis (OFF/SUGGEST/DRAFT/PREPARE) — renamed in
P2.3 so the two axes can never be conflated:

| Level | What happens | Human approval? | Can auto-publish? |
|---|---|---|---|
| `draft_only` | Generate a draft and stop. Never enters the schedule/publish queue automatically; a human exports or hand-posts. | n/a (manual) | No |
| `approval_required` **(default)** | Generate a draft, then wait for a human to approve before it can be scheduled/published. | **Yes** | No |
| `fully_autonomous` | May publish without a human approval step — **only if every guardrail (§4) passes** and confidence ≥ the configured threshold. | No | Yes (guardrail-gated) |

The enum is `str`-backed and serialises as the bare string. `AutonomyLevel.default()`
is `approval_required`. Parsing is tolerant (`from_str`) and **degrades to the
gated default** on an unknown value — a config typo can never silently unlock
autonomy.

## 2. What the per-type toggle controls

Flipping a single post type's level changes exactly three things — nothing else:

1. **Whether a human-approval step runs.** `approval_required`/`draft_only` insert
   the approval checkpoint (§3); `fully_autonomous` skips it.
2. **The confidence threshold to auto-publish.** Only meaningful for
   `fully_autonomous`: a per-type minimum confidence (the ranker/recognition
   confidence already produced for swimming, generalised). Below it, the post
   falls back to `approval_required` even when the type is autonomous.
3. **Which guardrails fire (§4).** All guardrails always run for autonomous posts;
   some (provenance, brand-safety) also run for gated posts as advisory warnings.

The toggle does **not** change what is generated, how it's branded, or the data —
only the path to publication.

## 3. Human-in-the-loop checkpoints (mapped to shipped code)

The approval lifecycle already exists as `mediahub.workflow.status`:

- `CardStatus`: `QUEUE → APPROVED / REJECTED → POSTED`, plus `EDITED`.
- `ScheduleStatus`: `QUEUED → SCHEDULED → PUBLISHED / FAILED`.
- `CardWorkflowState` persists the card's status, edits, schedule status, and the
  Buffer update id.

The autonomy level decides who drives the `QUEUE → APPROVED` transition:

```
                       ┌──────────── approval_required / draft_only ───────────┐
 generate ─▶ QUEUE ─▶  │  human reviews on /review/<run_id> ─▶ APPROVED/REJECTED │
                       └────────────────────────────────────────────────────────┘
                       ┌──────────────── fully_autonomous ─────────────────────┐
 generate ─▶ QUEUE ─▶  │  guardrails (§4) + confidence gate ─▶ auto-APPROVED     │
                       └────────────────────────────────────────────────────────┘
                                                   │
                                            SCHEDULED ─▶ PUBLISHED
                                          (draft_only stops at QUEUE/EDITED)
```

Mandatory human checkpoints that **always** remain, regardless of level:

- **Onboarding / account connection.** A human connects each publishing account
  (no auto-connect). Least-privilege per integration.
- **The kill switch (§4).** A human can halt all autonomous publishing instantly.
- **Post-hoc review.** Every autonomous post is logged and reviewable; a human can
  intervene, and repeated guardrail trips can auto-demote a type back to gated.

## 4. Guardrails for autonomous posting

A `fully_autonomous` post must clear **all** of these before it publishes. They are
the autonomous-publish extension of MediaHub's existing trust/safety primitives.

All five are **shipped (P2.3)** as one chokepoint —
`publishing.publish_gate.evaluate_publish_gate` — which evaluates every
guardrail (no short-circuit) and returns an explainable per-check verdict:

| Guardrail | What it checks | Shipped as |
|---|---|---|
| **Data-provenance / trust** | The card's deterministic safe-to-post verdict must be affirmatively safe (`safe`/`post`); `needs_review`/`hold`/missing/unknown all fail closed. | `publish_gate._check_provenance` over `recognition.schema.SafeToPost` + the run trust report's vocabulary. |
| **Confidence gate** | Deterministic confidence ≥ the per-type threshold (default 0.85, floor 0.5; operator-tunable in Settings → Autonomy). | `publish_gate.threshold_for` + the threshold store beside the P2.4 policy. |
| **Brand-safety** | Caption non-empty, no AI-tell ban-list phrases, none of the org's `brand_phrases_to_avoid`, within platform length. (Prose guideline rules stay with generation prompts + human review — a regex can't honestly enforce prose.) | `publish_gate._check_brand_safety` over the PAR-1 ban-list + `ClubProfile`. |
| **Safeguarding** | A card known to concern a minor (age < 18 in its facts) never auto-publishes — always a human decision (ADR-0003). | `publish_gate._check_safeguarding`. |
| **Rate limiting** | Per-workspace posting caps over the posting log (`MEDIAHUB_AUTONOMOUS_HOURLY_CAP`, default 4; `MEDIAHUB_AUTONOMOUS_DAILY_CAP`, default 12). | `publish_gate._check_rate_limit` over `publishing.posting_log`. |
| **Global kill switch** | `MEDIAHUB_PUBLISH_KILL_SWITCH` halts all autonomous publishing instantly — checked first on every evaluation AND re-asserted inside the Buffer call, so an engagement mid-cycle still halts. | `publishing.kill_switch` (P2.4) wired through the gate. |
| **Immutable audit trail** | Every evaluation (allowed AND blocked), every auto-approval and every publish attempt is appended to the per-org ledger; posting attempts also land in `publishing.posting_log`. | `workflow.autonomy.AuditLog` (`publish_gate` / `auto_approve` / `auto_publish` entries). |

These satisfy MediaHub's standing rule that *every step should be explainable and
auditable*, and the safeguarding posture locked in
[`adr/0003-pilot-safety-invariant-lock.md`](adr/0003-pilot-safety-invariant-lock.md)
(minors' competition data). A `fully_autonomous` type that handles minors' personal
data should be treated as the highest-scrutiny case.

## 5. Reference implementation (shipped — in-process, not Temporal)

Temporal was evaluated and **rejected by the Council** in favour of the
in-process substrate (no new infra): the `scheduler/` exactly-once SQLite
runner + `workflow/` stores (P2.1). The approval signal itself ships as
**`workflow.approval.apply_approval_signal`** (P2.2): gated types pause on
the signal (cards stay QUEUE/EDITED until the human approves on the review
page); a `fully_autonomous` type's cards run the full publish gate against
the **exact caption that would ship** — passing cards auto-APPROVE and, when
the org has chosen autonomous channels (Settings → Autonomy; requires its own
Buffer token), publish through the same Buffer path a human click uses.
Failing cards stay queued for the human with the blockers recorded —
autonomy degrades to approval, never the other way round. Trigger it on
demand (`POST /api/autonomy/sweep`, with or without a `run_id` — the Settings
page's "Run autonomy check now" button) or on the cadence: saving a policy
with any `fully_autonomous` type auto-creates the org's hourly
`approval_signal` scheduler task (`workflow.approval.
ensure_approval_signal_cadence`); reverting to fully gated removes it.
Machine-approved captions deliberately do **not** feed the voice-learning
store. Every decision is visible in Settings → Autonomy ("Autonomy activity
log", the `workflow.autonomy.AuditLog` read surface). End-to-end pinned by
`tests/test_autonomous_publishing.py`.

## 6. What is NOT in scope

- No auto-connecting of social accounts. Ever.
- No autonomy default above `approval_required`. A human opts in per type.
- No bypass of the deterministic engine: autonomy changes the *publish path*, never
  the *data* (parsers/detectors/ranker stay authoritative — see
  [`../CLAUDE.md`](../CLAUDE.md) "Critical engine stays deterministic").
