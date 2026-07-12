"""mediahub/api_public/scopes.py — least-privilege scope catalogue.

The public API (roadmap 1.21) is driven by org-scoped bearer tokens. Every
token carries an explicit set of **scopes** — fine-grained `resource:action`
permissions — and every endpoint declares the single scope it requires. A token
can only do what its scopes allow, so an integration that just needs to read
results never gets the power to approve or export.

Scopes are plain strings so they serialise cleanly into the token row, the
OpenAPI spec, the MCP tool annotations, and the management UI. This module is
the **single source of truth**: the blueprint, the MCP server, and the UI all
import the catalogue from here so the three surfaces can never drift.

Design rules:
- **Read is separate from write is separate from approve.** Approving a card is
  the human-publish signal (CLAUDE.md: human approval before external posting),
  so it is its own scope (`cards:approve`) — never folded into `cards:write`.
- **No implicit grants.** Holding `runs:write` does not imply `runs:read`; a
  token lists exactly the scopes it needs. The UI offers sensible bundles.
- **Unknown scopes are dropped, never honoured.** `validate_scopes` filters to
  the known set so a typo can never silently widen access.
"""

from __future__ import annotations

# --- the catalogue ---------------------------------------------------------
# Each scope: stable string -> human label (shown in the management UI and the
# OpenAPI security docs). Keep these short and verb-first.
SCOPES: dict[str, str] = {
    "runs:read": "Read pipeline runs and their status",
    "runs:write": "Submit results and trigger pipeline runs",
    "cards:read": "Read generated cards and captions",
    "cards:write": "Edit card captions",
    "cards:approve": "Approve or reject cards (the human-publish signal)",
    "content:export": "Export approved content packs and cards",
    "data:read": "Read the organisation data hub",
    "data:write": "Write to the organisation data hub",
    "brand:read": "Read brand kits and export palettes",
    "media:read": "Read the media library",
    "media:write": "Upload to the media library",
    "webhooks:read": "List webhook endpoints and recent deliveries",
    "webhooks:manage": "Create, update, and delete webhook endpoints",
}

# Ordered bundles for the management UI — a volunteer picks a bundle rather than
# ticking twelve boxes. The keys are presentation only; the values are the
# canonical scope strings above.
SCOPE_GROUPS: dict[str, tuple[str, ...]] = {
    "Read-only": (
        "runs:read",
        "cards:read",
        "content:export",
        "data:read",
        "brand:read",
        "media:read",
        "webhooks:read",
    ),
    "Review & approve": ("cards:write", "cards:approve"),
    "Ingest": ("runs:write", "data:write", "media:write"),
    "Integrations": ("webhooks:manage",),
}

# The read-only bundle the token-creation UI suggests as a starting point. It is
# NOT auto-applied: a token minted with no scopes is intentionally fail-closed
# (``validate_scopes([]) -> []``, i.e. no access) — never silently granted the
# read-only set. Widening is always an explicit choice.
DEFAULT_SCOPES: tuple[str, ...] = SCOPE_GROUPS["Read-only"]

ALL_SCOPES: tuple[str, ...] = tuple(SCOPES.keys())


def is_known(scope: str) -> bool:
    """True iff ``scope`` is a recognised scope string."""
    return scope in SCOPES


def scope_label(scope: str) -> str:
    """Human-readable label for a scope (falls back to the raw string)."""
    return SCOPES.get(scope, scope)


def validate_scopes(scopes) -> list[str]:
    """Filter an arbitrary iterable down to known scopes, de-duplicated and
    ordered by the catalogue. Unknown / malformed entries are dropped so a typo
    can never silently grant or remove power."""
    if not scopes:
        return []
    wanted = {str(s).strip().lower() for s in scopes if str(s).strip()}
    # Preserve catalogue order for stable serialisation / display.
    return [s for s in ALL_SCOPES if s in wanted]


def has_scope(token_scopes, required: str) -> bool:
    """True iff ``required`` is present in the token's granted scopes."""
    return required in set(token_scopes or ())


__all__ = [
    "SCOPES",
    "SCOPE_GROUPS",
    "DEFAULT_SCOPES",
    "ALL_SCOPES",
    "is_known",
    "scope_label",
    "validate_scopes",
    "has_scope",
]
