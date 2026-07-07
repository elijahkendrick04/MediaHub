"""athletes — the workspace-scoped athlete identity spine (Phase W.1).

Gives every swimmer a durable identity across runs so milestones
(50th race, debuts, first-ever events), club records, consent state and
season totals have something to hang on. Names arriving from parsed
results are matched against a per-org alias table; merge decisions made
in review persist and are audited.

Identity is an *optional enrichment*: every consumer must keep working
when no registry row exists (null-identity default). Nothing in here
calls an LLM — identity and milestone logic are deterministic by rule
(see CLAUDE.md "Critical engine stays deterministic").
"""

from .registry import (
    AthleteRecord,
    athlete_swims,
    backfill_from_runs,
    ensure_schema,
    get_or_create,
    initials_of,
    list_athletes,
    merge_athletes,
    milestone_context,
    normalise_name,
    record_run_swims,
    resolve,
    resolve_and_swims_bulk,
    set_details,
    sync_run_payload,
)

__all__ = [
    "AthleteRecord",
    "athlete_swims",
    "backfill_from_runs",
    "ensure_schema",
    "get_or_create",
    "initials_of",
    "list_athletes",
    "merge_athletes",
    "milestone_context",
    "normalise_name",
    "record_run_swims",
    "resolve",
    "resolve_and_swims_bulk",
    "set_details",
    "sync_run_payload",
]
