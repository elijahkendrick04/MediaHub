"""B5 — a minimal OpenAPI spec generated from the Flask url_map.

MediaHub has no hand-written OpenAPI document, so contract tooling (Schemathesis)
and a plain "no endpoint 5xxs" smoke have nothing to read. Flask can't tell us
request/response bodies, but it CAN enumerate routes — so this introspects the
``create_app()`` url_map (the same source ``run.discover_get_routes`` uses) and
emits the safely-fuzzable GET endpoints as the starting contract:

    "every advertised no-argument GET endpoint answers without a server error."

Routes that take URL arguments (``/api/runs/<id>/...``) are excluded — we can't
synthesise a valid id, and fuzzing a bad one only proves the 404 path. Destructive
routes are excluded too (read-only contract). This is deliberately conservative:
it catches 5xx / serialisation regressions on the public surface without inventing
a schema the app doesn't actually promise.
"""
from __future__ import annotations

from typing import Any

# Never include these in a read-only contract sweep (they mutate / end the session).
_DESTRUCTIVE = ("/delete", "/disconnect", "/clear", "/logout", "/sign-out",
                "/destroy", "/remove")


def get_routes(app: Any, *, no_arg_only: bool = True) -> list[str]:
    """Sorted GET route paths from the app's url_map. ``no_arg_only`` drops routes
    with URL arguments (the safely-fuzzable set) and the static endpoint."""
    out: set[str] = set()
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        if no_arg_only and rule.arguments:
            continue
        if "GET" not in (rule.methods or set()):
            continue
        path = str(rule.rule)
        if any(h in path for h in _DESTRUCTIVE):
            continue
        out.add(path)
    return sorted(out)


def build_spec(app: Any) -> dict[str, Any]:
    """A minimal OpenAPI 3.0 document of the no-argument GET routes. The negative
    contract Schemathesis enforces against it is ``not_a_server_error`` — a healthy
    app answers every path with < 500 (200, or 401/403/409 when an org is required)."""
    paths = {
        path: {"get": {"responses": {"200": {"description": "ok"}}}}
        for path in get_routes(app, no_arg_only=True)
    }
    return {
        "openapi": "3.0.0",
        "info": {"title": "MediaHub API (introspected)", "version": "0"},
        "paths": paths,
    }
