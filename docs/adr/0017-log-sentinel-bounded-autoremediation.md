# ADR 0017 — Log sentinel: notify-first, bounded auto-remediation

- **Status:** accepted (2026-06-12)
- **Context:** operator request — "a bot that constantly monitors the Render
  logs page and applies fixes when they come up" — landing right after the
  June 2026 SearXNG incident (silently broken image-build step + per-query
  warning spam that nobody was watching for).

## Decision

Build `src/mediahub/log_sentinel/` as an **in-process watchdog** over the
Render Logs API with a strict autonomy posture:

1. **Detection is deterministic.** Known failure patterns are regexes with
   thresholds, in code, reviewable — consistent with the deterministic-engine
   boundary. The LLM may only summarise a traceback for the notification text;
   it never decides whether something fired and never picks an action.
2. **Notify-first by default.** Out of the box the sentinel is read-only +
   notifications (ntfy/webhook via `mediahub.notify`). This mirrors the
   product's own "human approval before external action" default.
3. **Auto-fix is a double opt-in allowlist, not a capability.** Only issues in
   the playbook can ever act; v1's only action is a Render service restart —
   generic, reversible, and identical to the operator's manual move. Enabling
   requires the global flag AND a per-issue flag, and every action passes a
   kill switch, a daily cap, a per-issue cooldown and a boot-grace window
   (anti restart-loop), with the claim persisted *before* execution. This is
   the publish-gate philosophy (`publishing/publish_gate.py`) applied to ops.
4. **Everything is auditable.** Findings, notifications, gate decisions and
   action outcomes append to `DATA_DIR/log_sentinel/audit.jsonl`;
   `/healthz/sentinel` exposes the live snapshot.

## Rejected alternatives

- **LLM-decided remediation** ("read the logs, do whatever fixes them"): an
  unbounded actor with production credentials contradicts the bounded-autonomy
  model (`docs/AUTONOMY_MODEL.md`) and the deterministic-engine principle.
- **Auto-editing env vars / triggering deploys** as v1 actions: durable config
  mutations from a daemon are harder to reason about and to undo than a
  restart; deferred until a concrete need shows up, behind the same gates.
- **A separate Render background worker**: costs money and still can't see a
  total outage any better; the in-app leader-elected thread is £0 and the
  total-outage case is Render's own `/healthz` health check's job.

## Consequences

- A degraded-but-up deployment now pings the operator within ~1 minute with a
  diagnosis written from this repo's own production history, instead of
  failing silently until someone reads the logs page.
- The operator can grow the playbook deliberately (new detector + new gated
  remediation + tests), and every widening of autonomy is a reviewed code
  change, not a config drift.
