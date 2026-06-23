"""mediahub/mcp_server/client.py — a thin HTTP client for the platform API.

The MCP server is a protocol translator: every tool call becomes a request to
MediaHub's own ``/api/v1`` surface, authenticated with the operator's API token.
Wrapping the public API (rather than reaching into internals) means there is one
capability definition and one set of gates — the MCP tools can do exactly what
the token's scopes allow, no more.

The transport is injectable so the server is testable without a live socket: the
default uses ``requests`` against a base URL; tests pass a callable backed by the
Flask test client.
"""

from __future__ import annotations

import json
import os
from typing import Callable, Optional

# A transport: (method, url, headers, params, body_bytes) -> (status, text)
Transport = Callable[..., tuple[int, str]]


def _requests_transport(method, url, headers, params, body):
    import requests  # noqa: PLC0415

    r = requests.request(method, url, headers=headers, params=params, data=body, timeout=30)
    return r.status_code, r.text


class ApiClient:
    """Calls the MediaHub platform API as a bearer-token integration."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        *,
        transport: Optional[Transport] = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("MEDIAHUB_API_BASE_URL", "")).rstrip("/")
        self.token = token or os.environ.get("MEDIAHUB_API_TOKEN", "")
        self._transport = transport or _requests_transport

    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        body: Optional[bytes] = None,
    ) -> tuple[int, object]:
        """Make one API call. Returns (status_code, parsed_json_or_text)."""
        url = self.base_url + path
        headers = {"Authorization": f"Bearer {self.token}"}
        data = body
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(json_body).encode("utf-8")
        status, text = self._transport(method, url, headers, params or {}, data)
        try:
            return status, json.loads(text) if text else {}
        except (ValueError, TypeError):
            return status, text


def flask_test_transport(client) -> Transport:
    """A transport backed by a Flask test client (for tests / in-process use)."""

    def _t(method, url, headers, params, body):
        # url is base_url + path; strip the base so the test client sees the path.
        path = url
        for prefix in ("http://", "https://"):
            if path.startswith(prefix):
                path = "/" + path.split("/", 3)[3] if path.count("/") >= 3 else "/"
                break
        resp = client.open(path, method=method, headers=headers, query_string=params, data=body)
        return resp.status_code, resp.get_data(as_text=True)

    return _t


__all__ = ["ApiClient", "flask_test_transport", "Transport"]
