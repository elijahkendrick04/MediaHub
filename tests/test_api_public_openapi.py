"""1.21 public API — the OpenAPI contract is valid and never drifts from routes."""

from __future__ import annotations

import re

from flask import Flask

from mediahub.api_public.blueprint import BASE_PATH, build_api_v1_blueprint
from mediahub.api_public.openapi import build_spec


def test_spec_is_well_formed():
    spec = build_spec()
    assert spec["openapi"].startswith("3.1")
    assert spec["info"]["version"] == "v1"
    assert "bearerAuth" in spec["components"]["securitySchemes"]
    assert spec["paths"], "spec has paths"


def test_scoped_endpoints_declare_security():
    spec = build_spec()
    runs = spec["paths"][BASE_PATH + "/runs"]
    assert "security" in runs["get"]  # runs:read
    # The public health probe carries no security requirement.
    assert "security" not in spec["paths"][BASE_PATH + "/health"]["get"]


def _flask_to_openapi(rule_path: str) -> str:
    # Flask "<run_id>" / "<int:x>" -> OpenAPI "{run_id}" / "{x}".
    return re.sub(r"<(?:[^:>]+:)?([^>]+)>", r"{\1}", rule_path)


def _blueprint_operations() -> set[tuple[str, str]]:
    app = Flask(__name__)
    app.register_blueprint(build_api_v1_blueprint())
    ops = set()
    for rule in app.url_map.iter_rules():
        path = str(rule)
        if not path.startswith(BASE_PATH):
            continue
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            ops.add((method.lower(), _flask_to_openapi(path)))
    return ops


def _spec_operations() -> set[tuple[str, str]]:
    spec = build_spec(BASE_PATH)
    ops = set()
    for path, methods in spec["paths"].items():
        for method in methods:
            ops.add((method.lower(), path))
    return ops


def test_no_drift_between_spec_and_routes():
    routes = _blueprint_operations()
    spec = _spec_operations()
    # Normalise the index path ("/api/v1" vs "/api/v1/").
    norm = lambda s: {(m, p.rstrip("/") or p) for m, p in s}
    missing_from_spec = norm(routes) - norm(spec)
    missing_from_routes = norm(spec) - norm(routes)
    assert not missing_from_spec, f"routes not documented: {missing_from_spec}"
    assert not missing_from_routes, f"documented but not routed: {missing_from_routes}"
