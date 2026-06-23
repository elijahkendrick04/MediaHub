"""mediahub/mcp_server/server.py — a dependency-free MCP server over stdio.

Speaks the Model Context Protocol (JSON-RPC 2.0, newline-delimited over stdin/
stdout) so an external agent — Claude, ChatGPT, Gemini-class — can drive
MediaHub through the tools in ``tools.py``. This is the server MediaHub
*exposes*; MediaHub itself depends on no external MCP (CLAUDE.md / ADR).

No SDK dependency: the protocol surface we need (``initialize``, ``tools/list``,
``tools/call``, ``ping``) is small and implemented directly, in keeping with the
"thin, in-house, no new infra" ethos. ``handle_message`` processes one decoded
message and returns the response dict (or ``None`` for a notification), so the
whole server is unit-testable without a socket.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Optional

from .client import ApiClient
from .tools import dispatch, tool_list

log = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "mediahub"

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def _server_version() -> str:
    try:
        from importlib.metadata import version

        return version("mediahub")
    except Exception:
        return "0"


class MCPServer:
    def __init__(self, client: Optional[ApiClient] = None) -> None:
        self.client = client or ApiClient()

    # --- response helpers ---
    @staticmethod
    def _result(msg_id, result) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _error(msg_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}

    def handle_message(self, msg: dict) -> Optional[dict]:
        """Process one JSON-RPC message; return a response dict or None."""
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return self._error(
                msg.get("id") if isinstance(msg, dict) else None,
                INVALID_REQUEST,
                "Invalid JSON-RPC request",
            )
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        # Notifications (no id) get no response.
        is_notification = "id" not in msg

        try:
            if method == "initialize":
                return self._result(
                    msg_id,
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": SERVER_NAME, "version": _server_version()},
                    },
                )
            if method == "ping":
                return self._result(msg_id, {})
            if method in ("notifications/initialized", "initialized"):
                return None  # acknowledged, no response
            if method == "tools/list":
                return self._result(msg_id, {"tools": tool_list()})
            if method == "tools/call":
                return self._handle_tool_call(msg_id, params)
            # Unknown method: only answer if it expected a reply.
            if is_notification:
                return None
            return self._error(msg_id, METHOD_NOT_FOUND, f"Method not found: {method}")
        except Exception as e:  # never crash the loop on one bad message
            log.warning("mcp handle_message error on %s: %s", method, e, exc_info=True)
            if is_notification:
                return None
            return self._error(msg_id, INTERNAL_ERROR, "Internal error")

    def _handle_tool_call(self, msg_id, params: dict) -> dict:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not name:
            return self._error(msg_id, INVALID_PARAMS, "tools/call requires a 'name'")
        if not self.client.configured():
            return self._result(
                msg_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": "MediaHub MCP is not configured: set MEDIAHUB_API_BASE_URL "
                            "and MEDIAHUB_API_TOKEN.",
                        }
                    ],
                    "isError": True,
                },
            )
        ok, body = dispatch(name, arguments, self.client)
        return self._result(
            msg_id,
            {
                "content": [{"type": "text", "text": json.dumps(body, indent=2, default=str)}],
                "isError": not ok,
            },
        )

    # --- stdio transport ---
    def serve_stdio(self, stdin=None, stdout=None) -> None:
        """Read newline-delimited JSON-RPC from stdin, write responses to stdout."""
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                self._write(stdout, self._error(None, PARSE_ERROR, "Parse error"))
                continue
            response = self.handle_message(msg)
            if response is not None:
                self._write(stdout, response)

    @staticmethod
    def _write(stdout, obj: dict) -> None:
        stdout.write(json.dumps(obj) + "\n")
        stdout.flush()


__all__ = ["MCPServer", "PROTOCOL_VERSION", "SERVER_NAME"]
