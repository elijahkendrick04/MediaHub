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

Implemented (inert) as `mediahub.sport_profiles.autonomy.AutonomyLevel`:

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

| Guardrail | What it checks | Built on (today) |
|---|---|---|
| **Data-provenance / trust** | Every fact traces to a verified source above a trust threshold; unverified claims block auto-publish. | `context_engine.trust` (domain trust scoring), `pb_discovery` trust ledger, `recognition.schema.SafeToPost`. |
| **Brand-safety / profanity** | Caption + overlay text pass profanity/brand-safety and on-brand checks; HTML-escaped (`_h()`). | Caption pipeline; XSS escaping already in `web`. |
| **Rate limiting** | Per-workspace, per-platform posting caps; no flooding. | New (Phase 2). |
| **Global kill switch** | One control halts all autonomous publishing immediately, workspace-wide. | New (Phase 2). |
| **Immutable audit trail** | Append-only record of every autonomous decision (inputs, confidence, guardrail results, output) — explainable & auditable. | Extends the run audit trail + `publishing.posting_log`. |

These satisfy MediaHub's standing rule that *every step should be explainable and
auditable*, and the safeguarding posture locked in
[`adr/0003-pilot-safety-invariant-lock.md`](adr/0003-pilot-safety-invariant-lock.md)
(minors' competition data). A `fully_autonomous` type that handles minors' personal
data should be treated as the highest-scrutiny case.

## 5. Reference implementation (roadmap Phase 2)

The orchestration that physically enforces this is **Temporal** (MIT, truly free
to self-host — [`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md)): each content
type is a workflow with an **optional human-approval signal**. Gated types pause on
the signal; autonomous types skip the wait. This is the
langchain-social-media-agent "Agent Inbox" + Temporal-signal pattern from the
research (§B.1, §D.3). Today's `workflow.store` is the lightweight precursor; the
backbone is Phase 2 work in [`ROADMAP.md`](ROADMAP.md) (P2.*). Nothing here is
wired in yet — `AutonomyLevel` ships as inert scaffolding.

## 6. What is NOT in scope

- No auto-connecting of social accounts. Ever.
- No autonomy default above `approval_required`. A human opts in per type.
- No bypass of the deterministic engine: autonomy changes the *publish path*, never
  the *data* (parsers/detectors/ranker stay authoritative — see
  [`../CLAUDE.md`](../CLAUDE.md) "Critical engine stays deterministic").
