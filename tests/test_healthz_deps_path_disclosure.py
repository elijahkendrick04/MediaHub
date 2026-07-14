"""/healthz/deps must not disclose absolute server paths to anonymous callers.

`/healthz/deps` is a public operations probe (uptime monitors poll it for the
`ok`/availability booleans and it is linked from the operator Developer settings
page). It used to return absolute filesystem paths to *anyone* — the Chromium
executable, the node binary and the Remotion install directory — which leaks the
deployment's internal layout and aids path-targeting.

Those path fields are now operator-only (mirroring `/healthz/sentinel`, which
gives its raw audit tail to the signed-in operator alone). The endpoint stays
public and keeps every availability boolean and version, so monitoring is
unaffected.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def app(web_module, monkeypatch):
    # DATA_DIR isolation + one-time web.py import come from the autouse
    # ``_isolate_data_dir`` fixture in conftest.py. SECRET_KEY must be set before
    # create_app() reads it (signed-session tests).
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-signed-sessions")
    return web_module.create_app()


@pytest.fixture
def anon_client(app):
    return app.test_client()


@pytest.fixture
def operator_client(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s["dev_operator"] = True
    return c


def _abs_paths(data) -> list[str]:
    """Every string value in the payload that is an absolute filesystem path."""
    found: list[str] = []

    def walk(node, prefix=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{prefix}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{prefix}[{i}]")
        elif isinstance(node, str) and node.startswith("/"):
            found.append(f"{prefix}={node}")

    walk(data)
    return found


# ---- anonymous callers get no absolute paths ---------------------------


def test_anonymous_deps_leaks_no_absolute_paths(anon_client):
    resp = anon_client.get("/healthz/deps")
    assert resp.status_code == 200
    assert resp.content_type.startswith("application/json")
    data = resp.get_json()
    leaks = _abs_paths(data)
    assert leaks == [], f"anonymous /healthz/deps disclosed server paths: {leaks}"


def test_anonymous_deps_still_reports_health(anon_client):
    """Redaction must not break monitoring: the availability booleans and the
    top-level ok flag are still there for anonymous uptime monitors."""
    data = anon_client.get("/healthz/deps").get_json()
    assert "ok" in data
    deps = data["deps"]
    # Availability is still reported; only the *paths* were removed.
    assert "available" in deps["playwright"]
    assert "available" in deps["node"]
    assert "available" in deps["remotion"]
    # The specific path fields are gone for the anonymous caller.
    assert "executable" not in deps["playwright"]
    assert "path" not in deps["node"]
    assert "dir" not in deps["remotion"]


# ---- the operator still gets the full detail ---------------------------


def test_operator_deps_keeps_paths(operator_client):
    """The signed-in operator still sees the diagnostic paths — this is an
    operations endpoint and the operator is exactly who it is for."""
    data = operator_client.get("/healthz/deps").get_json()
    deps = data["deps"]
    # At least one real path field is present for the operator (node is the
    # most reliably present across environments; guard each independently).
    present = []
    if deps.get("node", {}).get("available"):
        assert "path" in deps["node"]
        present.append("node.path")
    if "executable" in deps["playwright"]:
        present.append("playwright.executable")
    if "dir" in deps["remotion"]:
        present.append("remotion.dir")
    assert present, "operator saw no diagnostic path fields at all"
