"""mediahub.autonomy — a bounded, narrow-tool autonomy runner.

A deliberately minimal internal engine that can orchestrate MediaHub's EXISTING
deterministic pipeline + caption AI on a club's behalf and **queue the result
for human approval** — never an open-ended agent. Per the council:

- It exposes only a FIXED allow-list of narrow, org-scoped, id-only tools
  (``mediahub.autonomy.tools``). There is no shell / file / generic-web / MCP
  tool, by construction.
- It NEVER publishes and holds no posting credentials. Its only forward action
  is "queue for human review" — approving/posting/rejecting are human-only and
  structurally unreachable from here.
- It runs only on operations AFTER the deterministic engine (parsing, PB
  detection, ranking, colour-science) has already decided everything; it never
  writes back into that engine's state.
- Off by default, bounded, £0 (rides the existing LLM tool-loop), per-org
  audited, multi-tenant-isolated (org bound once at session start).

Public surface: :func:`run_autonomy`, :class:`AutonomyLevel`.
"""

from __future__ import annotations

from mediahub.autonomy.tools import AutonomyLevel
from mediahub.autonomy.run_loop import (
    AutonomyDisabled,
    AutonomyResult,
    is_enabled,
    run_autonomy,
)

__all__ = [
    "AutonomyLevel",
    "AutonomyResult",
    "AutonomyDisabled",
    "run_autonomy",
    "is_enabled",
]
