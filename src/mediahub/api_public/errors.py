"""mediahub/api_public/errors.py — consistent JSON error envelopes.

Every public-API failure returns the same shape so external integrations can
branch on a stable machine code rather than scraping prose:

    {"error": "<machine_code>", "message": "<human sentence>", ...extra}

This mirrors the monolith's existing convention (``{"error": ...,
"message": ...}``) and keeps status codes predictable. ``ApiError`` is raised
from the service layer and deep in handlers; the blueprint's error handler turns
it into the envelope so individual endpoints stay terse.
"""

from __future__ import annotations

from typing import Any, Optional


class ApiError(Exception):
    """A public-API failure with a machine code, HTTP status, and extras.

    Raise this anywhere under the blueprint; the registered handler renders the
    JSON envelope and status. ``extra`` carries structured detail (e.g. the set
    of missing scopes, a retry hint) without breaking the stable top-level shape.
    """

    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        *,
        extra: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = int(status)
        self.extra = dict(extra or {})
        self.headers = dict(headers or {})

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"error": self.code, "message": self.message}
        body.update(self.extra)
        return body


# --- common, reusable failures --------------------------------------------
def unauthorized(message: str = "A valid API token is required.") -> ApiError:
    # 401 advertises the scheme so a client knows to send a bearer token.
    return ApiError(
        "unauthorized",
        message,
        401,
        headers={"WWW-Authenticate": 'Bearer realm="MediaHub API"'},
    )


def forbidden_scope(required: str) -> ApiError:
    return ApiError(
        "insufficient_scope",
        f"This token is missing the required scope: {required}.",
        403,
        extra={"required_scope": required},
    )


def not_found(resource: str = "resource") -> ApiError:
    # Anti-enumeration: "doesn't exist" and "not yours" return the same 404,
    # so a token can't probe another org's run/card ids by status code.
    return ApiError("not_found", f"No such {resource}.", 404)


def bad_request(message: str, *, extra: Optional[dict[str, Any]] = None) -> ApiError:
    return ApiError("bad_request", message, 400, extra=extra)


def rate_limited(retry_after: int) -> ApiError:
    return ApiError(
        "rate_limited",
        "Rate limit exceeded. Slow down and retry after the indicated delay.",
        429,
        extra={"retry_after": retry_after},
        headers={"Retry-After": str(int(retry_after))},
    )


def unavailable(message: str) -> ApiError:
    # Honest error when a capability genuinely isn't wired (e.g. run-trigger
    # requested from a context with no pipeline) — never a fabricated success.
    return ApiError("unavailable", message, 503)


__all__ = [
    "ApiError",
    "unauthorized",
    "forbidden_scope",
    "not_found",
    "bad_request",
    "rate_limited",
    "unavailable",
]
