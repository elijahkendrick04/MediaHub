"""mediahub/mcp_server/tools.py — the MCP tools MediaHub exposes.

Each tool is a thin wrapper over one ``/api/v1`` call. The token's scopes decide
what actually works — a read-only token's ``approve_card`` call comes back 403,
exactly as it would over HTTP. There is **no publishing tool**: the most powerful
action is approving a card, which (as everywhere in MediaHub) ends at the
approval queue and is the human-publish signal — nothing here posts to an
external account.

Schemas (``inputSchema``) are JSON Schema, the shape MCP clients expect.
"""

from __future__ import annotations

import base64
from typing import Callable

from .client import ApiClient

# A handler: (client, arguments) -> (ok: bool, result_obj)
Handler = Callable[[ApiClient, dict], tuple[bool, object]]

_STR = {"type": "string"}


def _ok(status: int) -> bool:
    return 200 <= status < 300


def _h_whoami(c: ApiClient, a: dict):
    s, b = c.request("GET", "/me")
    return _ok(s), b


def _h_list_runs(c: ApiClient, a: dict):
    params = {}
    if a.get("limit") is not None:
        params["limit"] = a["limit"]
    if a.get("offset") is not None:
        params["offset"] = a["offset"]
    s, b = c.request("GET", "/runs", params=params)
    return _ok(s), b


def _h_get_run(c: ApiClient, a: dict):
    s, b = c.request("GET", f"/runs/{a['run_id']}")
    return _ok(s), b


def _h_list_cards(c: ApiClient, a: dict):
    params = {"status": a["status"]} if a.get("status") else {}
    s, b = c.request("GET", f"/runs/{a['run_id']}/cards", params=params)
    return _ok(s), b


def _h_get_card(c: ApiClient, a: dict):
    s, b = c.request("GET", f"/runs/{a['run_id']}/cards/{a['card_id']}")
    return _ok(s), b


def _h_approve_card(c: ApiClient, a: dict):
    s, b = c.request("POST", f"/runs/{a['run_id']}/cards/{a['card_id']}/approve", json_body={})
    return _ok(s), b


def _h_reject_card(c: ApiClient, a: dict):
    s, b = c.request("POST", f"/runs/{a['run_id']}/cards/{a['card_id']}/reject", json_body={})
    return _ok(s), b


def _h_edit_caption(c: ApiClient, a: dict):
    s, b = c.request(
        "PATCH",
        f"/runs/{a['run_id']}/cards/{a['card_id']}",
        json_body={"edits": a.get("edits", {})},
    )
    return _ok(s), b


def _h_export_pack(c: ApiClient, a: dict):
    s, b = c.request("GET", f"/runs/{a['run_id']}/export")
    if _ok(s):
        # The body is a binary ZIP; don't shovel it through MCP — hand back a
        # download pointer the operator can fetch with their token.
        return True, {
            "exported": True,
            "download_url": f"{c.base_url}/runs/{a['run_id']}/export",
            "note": "Pack is ready. Download the ZIP at download_url with your API token.",
        }
    return False, b


def _h_submit_results(c: ApiClient, a: dict):
    try:
        content = base64.b64decode(a.get("content_base64", ""))
    except Exception:
        return False, {"error": "bad_request", "message": "content_base64 is not valid base64"}
    params = {"file_name": a.get("filename", "results")}
    s, b = c.request("POST", "/runs", params=params, body=content)
    return _ok(s), b


def _h_list_brand_kits(c: ApiClient, a: dict):
    s, b = c.request("GET", "/brand-kits")
    return _ok(s), b


def _h_list_data_tables(c: ApiClient, a: dict):
    s, b = c.request("GET", "/data/tables")
    return _ok(s), b


def _h_list_webhooks(c: ApiClient, a: dict):
    s, b = c.request("GET", "/webhooks")
    return _ok(s), b


# name -> (description, inputSchema, handler)
TOOLS: dict[str, tuple[str, dict, Handler]] = {
    "whoami": (
        "Return the calling token's organisation and granted scopes.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        _h_whoami,
    ),
    "list_runs": (
        "List the organisation's pipeline runs (newest first).",
        {
            "type": "object",
            "properties": {"limit": {"type": "integer"}, "offset": {"type": "integer"}},
            "additionalProperties": False,
        },
        _h_list_runs,
    ),
    "get_run": (
        "Get one pipeline run by id.",
        {"type": "object", "properties": {"run_id": _STR}, "required": ["run_id"]},
        _h_get_run,
    ),
    "list_cards": (
        "List the generated cards for a run (optionally filtered by status).",
        {
            "type": "object",
            "properties": {"run_id": _STR, "status": _STR},
            "required": ["run_id"],
        },
        _h_list_cards,
    ),
    "get_card": (
        "Get one card from a run.",
        {
            "type": "object",
            "properties": {"run_id": _STR, "card_id": _STR},
            "required": ["run_id", "card_id"],
        },
        _h_get_card,
    ),
    "approve_card": (
        "Approve a card. This is the human-publish signal and runs the same "
        "consent and brand checks as the app; it never posts to a social account. "
        "Requires the cards:approve scope.",
        {
            "type": "object",
            "properties": {"run_id": _STR, "card_id": _STR},
            "required": ["run_id", "card_id"],
        },
        _h_approve_card,
    ),
    "reject_card": (
        "Reject a card. Requires the cards:approve scope.",
        {
            "type": "object",
            "properties": {"run_id": _STR, "card_id": _STR},
            "required": ["run_id", "card_id"],
        },
        _h_reject_card,
    ),
    "edit_card_caption": (
        "Edit a card's caption overrides. Requires the cards:write scope.",
        {
            "type": "object",
            "properties": {
                "run_id": _STR,
                "card_id": _STR,
                "edits": {"type": "object"},
            },
            "required": ["run_id", "card_id", "edits"],
        },
        _h_edit_caption,
    ),
    "export_pack": (
        "Build the run's approved content pack and return a download pointer. "
        "Requires the content:export scope.",
        {"type": "object", "properties": {"run_id": _STR}, "required": ["run_id"]},
        _h_export_pack,
    ),
    "submit_results": (
        "Submit a results file (base64) and start a pipeline run. Requires the "
        "runs:write scope.",
        {
            "type": "object",
            "properties": {"filename": _STR, "content_base64": _STR},
            "required": ["filename", "content_base64"],
        },
        _h_submit_results,
    ),
    "list_brand_kits": (
        "List the organisation's brand kits. Requires the brand:read scope.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        _h_list_brand_kits,
    ),
    "list_data_tables": (
        "List the organisation's data-hub tables. Requires the data:read scope.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        _h_list_data_tables,
    ),
    "list_webhooks": (
        "List the organisation's webhook endpoints. Requires the webhooks:read scope.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        _h_list_webhooks,
    ),
}


def tool_list() -> list[dict]:
    """The serialisable tool catalogue for MCP ``tools/list``."""
    return [
        {"name": name, "description": desc, "inputSchema": schema}
        for name, (desc, schema, _h) in TOOLS.items()
    ]


def dispatch(name: str, arguments: dict, client: ApiClient) -> tuple[bool, object]:
    """Run a tool. Returns (ok, result_obj). Unknown tool -> (False, error)."""
    entry = TOOLS.get(name)
    if entry is None:
        return False, {"error": "unknown_tool", "message": f"No such tool: {name}"}
    _desc, _schema, handler = entry
    return handler(client, arguments or {})


__all__ = ["TOOLS", "tool_list", "dispatch"]
