"""Run the MediaHub MCP server over stdio:

    MEDIAHUB_API_BASE_URL=https://your-mediahub.example/api/v1 \\
    MEDIAHUB_API_TOKEN=mhk_... \\
    python -m mediahub.mcp_server

Point your agent client (Claude/ChatGPT/Gemini-class) at this command. The token
determines what the tools can do — grant it only the scopes you want the agent
to have.
"""

from __future__ import annotations

import logging
import sys

from .client import ApiClient
from .server import MCPServer


def main() -> int:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    client = ApiClient()
    if not client.configured():
        sys.stderr.write(
            "MediaHub MCP: set MEDIAHUB_API_BASE_URL (…/api/v1) and MEDIAHUB_API_TOKEN.\n"
        )
    MCPServer(client).serve_stdio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
