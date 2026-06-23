"""mediahub.api_public — the versioned public platform API (roadmap 1.21).

MediaHub exposes a first-party REST API (`/api/v1`) so clubs, federations, and
external agents can drive the engine they already use: submit results, list and
approve cards, export packs, query the data hub. It is org-scoped (bearer
tokens), least-privilege (per-endpoint scopes), and approval-honest — approving
via the API runs the *same* consent / brand-lock / group-approval gates as the
UI, and nothing here posts to an external social account.

This package is the **single capability definition**: ``service`` is the
transport-agnostic layer, ``blueprint`` is the HTTP adapter, and the MCP server
(``mediahub.mcp_server``) wraps the same surface for agent use.

Layout:
- ``scopes``    — the least-privilege scope catalogue (one source of truth)
- ``tokens``    — org-scoped bearer tokens (sha256-hashed, revocable)
- ``service``   — capabilities over the existing engine internals
- ``blueprint`` — the Flask ``/api/v1`` adapter (auth, scopes, rate limit)
- ``openapi``   — the OpenAPI 3.1 contract (drift-tested against the routes)
- ``ratelimit`` — per-token fixed-window limiter
- ``errors``    — the JSON error-envelope helpers
"""

from __future__ import annotations

from .blueprint import BASE_PATH, build_api_v1_blueprint
from .scopes import ALL_SCOPES, DEFAULT_SCOPES, SCOPE_GROUPS, SCOPES
from .tokens import ApiToken, ApiTokenStore

__all__ = [
    "build_api_v1_blueprint",
    "BASE_PATH",
    "ApiToken",
    "ApiTokenStore",
    "SCOPES",
    "SCOPE_GROUPS",
    "ALL_SCOPES",
    "DEFAULT_SCOPES",
]
