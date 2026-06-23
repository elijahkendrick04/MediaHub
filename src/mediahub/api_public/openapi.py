"""mediahub/api_public/openapi.py — the OpenAPI 3.1 description of /api/v1.

The endpoint registry below is the **documentation source of truth**. The spec
is generated from it, and a test asserts the registry and the live blueprint
routes describe the same set of operations — so the published contract can never
silently drift from the code.

Later builds (webhooks, embed) append their operations to ``OPERATIONS``.
"""

from __future__ import annotations

from typing import Optional

from .scopes import SCOPES

API_VERSION = "v1"
API_TITLE = "MediaHub Platform API"


# Each entry documents one operation. ``scope`` is the single scope the endpoint
# requires (None for public endpoints). ``path`` is relative to the base path.
OPERATIONS: list[dict] = [
    {
        "method": "get",
        "path": "/",
        "operation_id": "getIndex",
        "summary": "Service index — links and version",
        "scope": None,
        "tag": "Meta",
    },
    {
        "method": "get",
        "path": "/health",
        "operation_id": "getHealth",
        "summary": "Liveness probe",
        "scope": None,
        "tag": "Meta",
    },
    {
        "method": "get",
        "path": "/openapi.json",
        "operation_id": "getOpenapi",
        "summary": "This OpenAPI document",
        "scope": None,
        "tag": "Meta",
    },
    {
        "method": "get",
        "path": "/me",
        "operation_id": "getMe",
        "summary": "The calling token's org and granted scopes",
        "scope": None,  # any valid token
        "tag": "Meta",
        "auth": True,
    },
    {
        "method": "get",
        "path": "/runs",
        "operation_id": "listRuns",
        "summary": "List the organisation's pipeline runs",
        "scope": "runs:read",
        "tag": "Runs",
        "query": [("limit", "integer"), ("offset", "integer")],
    },
    {
        "method": "post",
        "path": "/runs",
        "operation_id": "createRun",
        "summary": "Submit a results file and start a pipeline run",
        "scope": "runs:write",
        "tag": "Runs",
        "body": "binary",
        "query": [("file_name", "string"), ("fetch_pbs", "boolean"), ("club", "string")],
    },
    {
        "method": "get",
        "path": "/runs/{run_id}",
        "operation_id": "getRun",
        "summary": "Get one run",
        "scope": "runs:read",
        "tag": "Runs",
        "params": ["run_id"],
    },
    {
        "method": "get",
        "path": "/runs/{run_id}/cards",
        "operation_id": "listCards",
        "summary": "List a run's generated cards",
        "scope": "cards:read",
        "tag": "Cards",
        "params": ["run_id"],
        "query": [("status", "string")],
    },
    {
        "method": "get",
        "path": "/runs/{run_id}/cards/{card_id}",
        "operation_id": "getCard",
        "summary": "Get one card",
        "scope": "cards:read",
        "tag": "Cards",
        "params": ["run_id", "card_id"],
    },
    {
        "method": "post",
        "path": "/runs/{run_id}/cards/{card_id}/approve",
        "operation_id": "approveCard",
        "summary": "Approve a card (counts as the human-publish signal; gated by "
        "consent/brand-lock/review rules)",
        "scope": "cards:approve",
        "tag": "Cards",
        "params": ["run_id", "card_id"],
    },
    {
        "method": "post",
        "path": "/runs/{run_id}/cards/{card_id}/reject",
        "operation_id": "rejectCard",
        "summary": "Reject a card",
        "scope": "cards:approve",
        "tag": "Cards",
        "params": ["run_id", "card_id"],
    },
    {
        "method": "patch",
        "path": "/runs/{run_id}/cards/{card_id}",
        "operation_id": "editCard",
        "summary": "Edit a card's caption overrides",
        "scope": "cards:write",
        "tag": "Cards",
        "params": ["run_id", "card_id"],
        "body": "json",
    },
    {
        "method": "get",
        "path": "/runs/{run_id}/export",
        "operation_id": "exportPack",
        "summary": "Download the run's approved content pack as a ZIP",
        "scope": "content:export",
        "tag": "Content",
        "params": ["run_id"],
    },
    {
        "method": "get",
        "path": "/brand-kits",
        "operation_id": "listBrandKits",
        "summary": "List the organisation's brand kits",
        "scope": "brand:read",
        "tag": "Brand",
    },
    {
        "method": "get",
        "path": "/data/tables",
        "operation_id": "listDataTables",
        "summary": "List the organisation's data-hub tables",
        "scope": "data:read",
        "tag": "Data",
    },
    {
        "method": "get",
        "path": "/webhooks",
        "operation_id": "listWebhooks",
        "summary": "List the organisation's webhook endpoints",
        "scope": "webhooks:read",
        "tag": "Webhooks",
    },
    {
        "method": "post",
        "path": "/webhooks",
        "operation_id": "createWebhook",
        "summary": "Register a webhook endpoint (returns the signing secret once)",
        "scope": "webhooks:manage",
        "tag": "Webhooks",
        "body": "json",
    },
    {
        "method": "get",
        "path": "/webhooks/{endpoint_id}",
        "operation_id": "getWebhook",
        "summary": "Get one webhook endpoint",
        "scope": "webhooks:read",
        "tag": "Webhooks",
        "params": ["endpoint_id"],
    },
    {
        "method": "delete",
        "path": "/webhooks/{endpoint_id}",
        "operation_id": "deleteWebhook",
        "summary": "Delete a webhook endpoint",
        "scope": "webhooks:manage",
        "tag": "Webhooks",
        "params": ["endpoint_id"],
    },
    {
        "method": "get",
        "path": "/webhooks/{endpoint_id}/deliveries",
        "operation_id": "listWebhookDeliveries",
        "summary": "Recent delivery attempts for a webhook endpoint",
        "scope": "webhooks:read",
        "tag": "Webhooks",
        "params": ["endpoint_id"],
    },
]


def _param_obj(name: str, where: str = "path", typ: str = "string") -> dict:
    return {
        "name": name,
        "in": where,
        "required": where == "path",
        "schema": {"type": typ},
    }


def build_spec(base_path: str = "/api/v1", *, server_url: Optional[str] = None) -> dict:
    """Assemble the OpenAPI 3.1 document from the endpoint registry."""
    paths: dict[str, dict] = {}
    for ep in OPERATIONS:
        full = base_path.rstrip("/") + ep["path"]
        if full.endswith("/") and full != base_path.rstrip("/") + "/":
            full = full.rstrip("/")
        op: dict = {
            "operationId": ep["operation_id"],
            "summary": ep["summary"],
            "tags": [ep.get("tag", "API")],
            "responses": {
                "200": {"description": "Success"},
                "401": {"description": "Missing or invalid token"},
                "403": {"description": "Insufficient scope"},
                "404": {"description": "Not found"},
                "429": {"description": "Rate limited"},
            },
        }
        params = [_param_obj(p) for p in ep.get("params", [])]
        for qname, qtyp in ep.get("query", []):
            params.append(_param_obj(qname, "query", qtyp))
        if params:
            op["parameters"] = params
        if ep.get("body") == "json":
            op["requestBody"] = {
                "content": {"application/json": {"schema": {"type": "object"}}}
            }
        elif ep.get("body") == "binary":
            op["requestBody"] = {
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
                }
            }
        # Security: scoped endpoints (and the authenticated meta endpoints)
        # require the bearer scheme. Public meta endpoints omit it.
        if ep.get("scope") or ep.get("auth"):
            op["security"] = [{"bearerAuth": ([ep["scope"]] if ep.get("scope") else [])}]
        paths.setdefault(full, {})[ep["method"]] = op

    spec: dict = {
        "openapi": "3.1.0",
        "info": {
            "title": API_TITLE,
            "version": API_VERSION,
            "description": (
                "The MediaHub platform API. Authenticate with an organisation API "
                "token as a bearer credential. Tokens carry least-privilege scopes; "
                "every endpoint declares the one scope it needs. Approving a card via "
                "the API still counts as the human-publish signal and runs the same "
                "consent and brand-lock gates as the UI — MediaHub never posts to an "
                "external social account."
            ),
        },
        "servers": [{"url": server_url or base_path}],
        "tags": [
            {"name": "Meta"},
            {"name": "Runs"},
            {"name": "Cards"},
            {"name": "Content"},
            {"name": "Brand"},
            {"name": "Data"},
            {"name": "Webhooks"},
        ],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "An organisation API token (mhk_…).",
                }
            },
            "schemas": {
                "Error": {
                    "type": "object",
                    "required": ["error", "message"],
                    "properties": {
                        "error": {"type": "string", "description": "Machine-readable code"},
                        "message": {"type": "string"},
                    },
                }
            },
        },
        "x-scopes": dict(SCOPES),
    }
    return spec


__all__ = ["build_spec", "OPERATIONS", "API_VERSION", "API_TITLE"]
