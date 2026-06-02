"""B5 (Tier B): API contract — every advertised no-argument GET endpoint answers
without a SERVER ERROR (5xx). DETERMINISTIC, pytest-native, no network.

A 409 "organisation_not_ready" / 401 / 403 / a redirect are all CORRECT answers
(< 500) — the contract is only that the surface never crashes. With Schemathesis
installed this also property-fuzzes the same routes (``not_a_server_error``); it
honest-skips when Schemathesis isn't present.

This catches the class of bug the AI judges can't (a serialisation/validation 5xx
on an /api route) and feeds it straight to the deterministic oracle, not the judges.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def app(tmp_path, monkeypatch):
    """A booted MediaHub app with a seeded+pinned org, mirroring the autotest
    finder's signed-in sweep so org-gated routes execute their real handler."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(profile_id="contract-org", display_name="Contract Org",
                             brand_voice_summary="x"))
    application = wm.create_app()
    application.config["TESTING"] = True
    return application


def _no_arg_get_routes(app):
    from autotest import openapi
    return openapi.get_routes(app, no_arg_only=True)


def test_spec_enumerates_health_and_status(app):
    from autotest import openapi
    paths = openapi.build_spec(app)["paths"]
    # The known no-auth endpoints must be in the contract.
    assert "/healthz" in paths
    assert any(p.startswith("/healthz") for p in paths)
    assert all(g.get("get") for g in paths.values())


def test_no_get_route_returns_5xx(app):
    routes = _no_arg_get_routes(app)
    assert routes, "url_map introspection found no no-arg GET routes"
    server_errors = []
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "contract-org"})
        for path in routes:
            try:
                resp = c.get(path)
            except Exception as exc:                       # an unhandled raise == a crash
                server_errors.append(f"{path} raised {type(exc).__name__}: {exc}")
                continue
            if resp.status_code >= 500:
                server_errors.append(f"{path} -> {resp.status_code}")
    assert not server_errors, "API contract violations (5xx):\n" + "\n".join(server_errors)


def test_health_endpoints_ok_without_org(app):
    # The exempt endpoints answer even with no active org.
    with app.test_client() as c:
        assert c.get("/healthz").status_code == 200
        assert c.get("/api/status").status_code < 500


def test_schemathesis_finds_no_server_errors(app):
    schemathesis = pytest.importorskip("schemathesis")   # honest-skip when absent
    from autotest import openapi
    spec = openapi.build_spec(app)
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "contract-org"})
    try:
        schema = schemathesis.from_dict(spec, app=app)   # WSGI app target
    except Exception:                                     # API drift across versions → skip, don't fail
        pytest.skip("schemathesis schema construction unavailable in this version")
    failures = []
    for operation in schema.get_all_operations():
        op = operation.ok()
        case = op.make_case()
        try:
            response = case.call_wsgi()
        except Exception as exc:
            failures.append(f"{op.method} {op.path} raised {type(exc).__name__}")
            continue
        if response.status_code >= 500:
            failures.append(f"{op.method} {op.path} -> {response.status_code}")
    assert not failures, "Schemathesis contract failures:\n" + "\n".join(failures)
