"""mediahub/log_sentinel/playbook.py — what the sentinel may DO about a finding.

Mirrors the publishing-gate philosophy (``publishing/publish_gate.py``): every
finding is notified; an *action* additionally requires every gate to pass, and
every decision is auditable. Defaults are deliberately conservative:

* **Notify-first.** Out of the box the sentinel only ever notifies — auto-fix is
  a double opt-in: ``MEDIAHUB_SENTINEL_AUTOFIX=1`` (global) AND
  ``MEDIAHUB_SENTINEL_AUTOFIX_<ISSUE_ID>=1`` (per issue).
* **Kill switch.** ``MEDIAHUB_SENTINEL_KILL=1`` stops all actions immediately
  (notifications keep flowing — observability never turns off).
* **Rate caps.** At most ``MEDIAHUB_SENTINEL_MAX_ACTIONS_PER_DAY`` (default 4)
  actions per UTC day, plus a per-issue cooldown
  (``MEDIAHUB_SENTINEL_ACTION_COOLDOWN``, default 6h).
* **Boot grace.** No action within ``MEDIAHUB_SENTINEL_RESTART_GRACE`` (default
  600s) of process start — a restart loop must never feed itself.

Only issues listed in ``PLAYBOOK`` can ever be auto-fixed; everything else is
permanently notify-only. v1's only action type is ``restart_service`` — the one
remediation that is generic, reversible, and matches what an operator would do
by hand for a wedged/OOM state. Fixes that need code or config changes belong
in a human's hands (or a Claude session), not a log-watching daemon.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

_PROCESS_START = time.time()

DEFAULT_MAX_ACTIONS_PER_DAY = 4
DEFAULT_ACTION_COOLDOWN = 6 * 3600.0
DEFAULT_RESTART_GRACE = 600.0
DEFAULT_NOTIFY_COOLDOWN = 3600.0


@dataclass(frozen=True)
class Remediation:
    action: str  # v1: "restart_service"
    description: str


# Issues with a safe generic remediation. Notify-only issues are simply absent.
PLAYBOOK: dict[str, Remediation] = {
    "worker_timeout": Remediation(
        action="restart_service",
        description="Restart the Render service to clear wedged worker state.",
    ),
    "out_of_memory": Remediation(
        action="restart_service",
        description="Restart the Render service to recover from memory exhaustion.",
    ),
}


def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _seconds(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return max(0.0, float(raw)) if raw else default
    except ValueError:
        return default


def kill_switch_on() -> bool:
    return _flag("MEDIAHUB_SENTINEL_KILL")


def autofix_enabled(issue_id: str) -> bool:
    """Double opt-in: the global flag AND the per-issue flag."""
    return _flag("MEDIAHUB_SENTINEL_AUTOFIX") and _flag(
        f"MEDIAHUB_SENTINEL_AUTOFIX_{issue_id.upper()}"
    )


def max_actions_per_day() -> int:
    raw = os.environ.get("MEDIAHUB_SENTINEL_MAX_ACTIONS_PER_DAY", "").strip()
    try:
        return max(0, int(raw)) if raw else DEFAULT_MAX_ACTIONS_PER_DAY
    except ValueError:
        return DEFAULT_MAX_ACTIONS_PER_DAY


def action_cooldown() -> float:
    return _seconds("MEDIAHUB_SENTINEL_ACTION_COOLDOWN", DEFAULT_ACTION_COOLDOWN)


def notify_cooldown() -> float:
    return _seconds("MEDIAHUB_SENTINEL_NOTIFY_COOLDOWN", DEFAULT_NOTIFY_COOLDOWN)


def in_boot_grace() -> bool:
    return (time.time() - _PROCESS_START) < _seconds(
        "MEDIAHUB_SENTINEL_RESTART_GRACE", DEFAULT_RESTART_GRACE
    )


def action_decision(
    issue_id: str,
    *,
    last_acted_epoch: float,
    actions_today: int,
) -> tuple[bool, str]:
    """Evaluate every gate for auto-fixing ``issue_id`` right now.

    Returns ``(allowed, reason)`` — the reason string goes into the audit
    ledger either way, so "why did/didn't the bot act?" is always answerable.
    """
    remediation = PLAYBOOK.get(issue_id)
    if remediation is None:
        return False, "notify-only issue (no playbook remediation)"
    if kill_switch_on():
        return False, "kill switch on (MEDIAHUB_SENTINEL_KILL=1)"
    if not autofix_enabled(issue_id):
        return False, (
            "auto-fix not enabled (needs MEDIAHUB_SENTINEL_AUTOFIX=1 and "
            f"MEDIAHUB_SENTINEL_AUTOFIX_{issue_id.upper()}=1)"
        )
    if in_boot_grace():
        return False, "within boot grace period"
    if actions_today >= max_actions_per_day():
        return False, f"daily action cap reached ({actions_today})"
    cooldown = action_cooldown()
    if last_acted_epoch and (time.time() - last_acted_epoch) < cooldown:
        return False, f"issue action cooldown active (~{int(cooldown)}s)"
    return True, f"all gates passed: {remediation.description}"


__all__ = [
    "Remediation",
    "PLAYBOOK",
    "kill_switch_on",
    "autofix_enabled",
    "max_actions_per_day",
    "action_cooldown",
    "notify_cooldown",
    "in_boot_grace",
    "action_decision",
]
