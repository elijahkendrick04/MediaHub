"""tests/test_make_page_endpoints.py — Phase 1.5 stability regression.

The /make page reads ContentTypeMeta entries from
``mediahub.club_platform.content_types`` and calls ``url_for()`` on each
`primary_route_endpoint`. A renamed-but-not-updated endpoint name used
to crash the whole page with a 500 Werkzeug BuildError.

These tests pin two contracts:

  1. Every ``primary_route_endpoint`` in the REGISTRY resolves to a
     registered Flask route. (Catches future drift at suite time, not
     in production.)
  2. Even if a single entry's endpoint is missing, /make still renders
     200 — the offender degrades to a disabled tile.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def gated_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(
        profile_id="t",
        display_name="Test club",
        brand_voice_summary="Friendly.",
    ))
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "t"})
        yield c, app


class TestMakePageEndpoints:
    def test_every_registry_endpoint_resolves(self, gated_app):
        """A renamed endpoint anywhere in REGISTRY must fail loudly at
        test time, not silently in prod via a BuildError 500."""
        _, app = gated_app
        from mediahub.club_platform.content_types import REGISTRY
        with app.test_request_context():
            from flask import url_for
            missing = []
            for ct, meta in REGISTRY.items():
                if not meta.is_implemented:
                    # Stub-only tiles are allowed to point at a missing
                    # endpoint — they render disabled in production.
                    continue
                try:
                    url_for(meta.primary_route_endpoint)
                except Exception as exc:
                    missing.append((ct, meta.primary_route_endpoint, str(exc)))
            assert not missing, (
                f"REGISTRY entries reference unknown endpoints: {missing}"
            )

    def test_make_page_renders_200_with_active_org(self, gated_app):
        """/make must not 500 just because the active org is set."""
        c, _ = gated_app
        resp = c.get("/make")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Something went wrong" not in body
        assert "Create" in body or "make" in body.lower()

    def test_make_page_survives_a_broken_endpoint_via_guard(self, gated_app, monkeypatch):
        """Defensive: if a future commit reintroduces a stale endpoint
        name, /make must degrade to a disabled tile instead of 500ing.

        Monkeypatch one entry in REGISTRY to a known-bad endpoint and
        confirm /make still returns 200.
        """
        c, app = gated_app
        from mediahub.club_platform import content_types as ct_mod
        # Patch the first implemented entry's endpoint to garbage.
        first_key = next(iter(ct_mod.REGISTRY))
        original = ct_mod.REGISTRY[first_key].primary_route_endpoint
        try:
            ct_mod.REGISTRY[first_key].primary_route_endpoint = "_definitely_not_a_real_endpoint"
            resp = c.get("/make")
            assert resp.status_code == 200, (
                f"/make crashed instead of degrading; body: "
                f"{resp.get_data(as_text=True)[:300]}"
            )
        finally:
            ct_mod.REGISTRY[first_key].primary_route_endpoint = original
