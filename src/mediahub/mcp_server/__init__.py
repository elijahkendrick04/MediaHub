"""mediahub.mcp_server — the MCP server MediaHub *exposes* (roadmap 1.21).

So a club volunteer can drive MediaHub from Claude/ChatGPT/Gemini — MediaHub's
own version of "Canva in Claude", pointed at our engine. It is a thin Model
Context Protocol translator over the public ``/api/v1`` surface: one capability
definition, one set of scopes and gates.

MediaHub itself depends on **no external MCP** (CLAUDE.md). This package only
*exposes* one. Run it with ``python -m mediahub.mcp_server``.
"""

from __future__ import annotations

from .client import ApiClient, flask_test_transport
from .server import MCPServer
from .tools import dispatch, tool_list

__all__ = ["MCPServer", "ApiClient", "flask_test_transport", "tool_list", "dispatch"]
