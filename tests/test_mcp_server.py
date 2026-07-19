"""1.21 MCP server — protocol handshake + tools over the live /api/v1 surface."""

from __future__ import annotations

import json
import sqlite3

import pytest

from mediahub.mcp_server.client import ApiClient, flask_test_transport
from mediahub.mcp_server.server import PROTOCOL_VERSION, MCPServer
from mediahub.mcp_server.tools import tool_list


# --- protocol (no app needed) ----------------------------------------------
def _server():
    return MCPServer(ApiClient(base_url="", token=""))


def test_initialize_handshake():
    r = _server().handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r["id"] == 1
    assert r["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert r["result"]["serverInfo"]["name"] == "mediahub"
    assert "tools" in r["result"]["capabilities"]


def test_ping():
    r = _server().handle_message({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert r["result"] == {}


def test_initialized_notification_has_no_response():
    assert (
        _server().handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    )


def test_tools_list_exposes_the_catalogue():
    r = _server().handle_message({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    names = {t["name"] for t in r["result"]["tools"]}
    assert {"list_runs", "get_run", "approve_card", "export_pack", "whoami"} <= names
    for t in r["result"]["tools"]:
        assert t["description"] and t["inputSchema"]["type"] == "object"


def test_unknown_method_is_method_not_found():
    r = _server().handle_message({"jsonrpc": "2.0", "id": 4, "method": "nonsense"})
    assert r["error"]["code"] == -32601


def test_invalid_jsonrpc_is_rejected():
    r = _server().handle_message({"id": 5, "method": "ping"})  # no jsonrpc
    assert r["error"]["code"] == -32600


def test_no_publishing_tool_exists():
    # The strongest action is approve (ends at the approval queue). Nothing here
    # posts to an external account.
    names = {t["name"] for t in tool_list()}
    for forbidden in ("publish", "post", "share_to_instagram", "post_to_facebook"):
        assert forbidden not in names


def test_tools_call_unconfigured_is_error():
    r = _server().handle_message(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "list_runs", "arguments": {}},
        }
    )
    assert r["result"]["isError"] is True
    assert "not configured" in r["result"]["content"][0]["text"].lower()


# --- tools over the real API (isolated app + flask transport) --------------
def _seed_run(runs_dir, db_path, run_id, profile_id):
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{run_id}.json").write_text(
        json.dumps(
            {
                "profile_id": profile_id,
                "meet_name": "Gala",
                "meet": {"name": "Gala"},
                "recognition_report": {
                    "ranked_achievements": [
                        {"achievement": {"swim_id": "swim-1", "swimmer_name": "Alice"}}
                    ]
                },
            }
        )
    )
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name) "
        "VALUES (?,?,?,?,?)",
        (run_id, "2026-06-01T00:00:00Z", "done", profile_id, "Gala"),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def mcp(web_module, monkeypatch):
    # MEDIAHUB_SCHEDULER is read fresh inside create_app() (scheduler._enabled()),
    # not at web.py import time — so it must be set before create_app() runs, which
    # rules out the canonical `app` fixture (its create_app() call already happened
    # by the time this fixture body executes).
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")

    from mediahub.api_public import _db as api_db

    api_db._initialized.clear()

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-a", display_name="Org A SC"))

    flask_app = web_module.create_app()
    flask_app.config["TESTING"] = True
    _seed_run(web_module.RUNS_DIR, web_module.DB_PATH, "runmcp000001", "org-a")

    from mediahub.api_public.tokens import ApiTokenStore

    def server_with(scopes):
        _t, secret = ApiTokenStore().create("org-a", scopes=list(scopes), created_by="o@x.com")
        client = ApiClient(
            base_url="http://localhost/api/v1",
            token=secret,
            transport=flask_test_transport(flask_app.test_client()),
        )
        return MCPServer(client)

    return server_with


def _call(server, name, arguments=None):
    r = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
    )
    payload = json.loads(r["result"]["content"][0]["text"])
    return r["result"]["isError"], payload


def test_whoami_and_list_runs(mcp):
    server = mcp(["runs:read"])
    err, who = _call(server, "whoami")
    assert not err and who["profile_id"] == "org-a"
    err, runs = _call(server, "list_runs")
    assert not err and any(r["id"] == "runmcp000001" for r in runs["runs"])


def test_get_card_via_mcp(mcp):
    server = mcp(["cards:read"])
    err, card = _call(server, "get_card", {"run_id": "runmcp000001", "card_id": "swim-1"})
    assert not err and card["swimmer_name"] == "Alice"


def test_approve_via_mcp_respects_scope(mcp):
    # A read-only token cannot approve — the tool surfaces the 403 as isError.
    server = mcp(["cards:read"])
    err, body = _call(server, "approve_card", {"run_id": "runmcp000001", "card_id": "swim-1"})
    assert err and body["error"] == "insufficient_scope"

    # With the approve scope it works and ends at "approved".
    server2 = mcp(["cards:approve"])
    err2, body2 = _call(server2, "approve_card", {"run_id": "runmcp000001", "card_id": "swim-1"})
    assert not err2 and body2["status"] == "approved"


def test_tools_call_is_tenant_isolated(mcp):
    server = mcp(["runs:read"])  # token for org-a
    err, body = _call(server, "get_run", {"run_id": "does-not-exist"})
    assert err and body["error"] == "not_found"
