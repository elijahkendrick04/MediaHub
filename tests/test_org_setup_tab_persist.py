"""tests/test_org_setup_tab_persist.py — the setup AI/Manual tab choice
survives reloads/redirects, and required fields have a legend (finding A-7).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_setup_persists_tab_choice(client):
    body = client.get("/organisation/setup?fresh=1").data.decode()
    # Chosen mode is remembered...
    assert "sessionStorage.setItem('mhSetupMode', mode)" in body
    # ...and restored on load (a ?mode= wins, else the remembered pick).
    assert "sessionStorage.getItem('mhSetupMode')" in body
    assert "mhSetupMode('manual')" in body


def test_setup_has_required_fields_legend(client):
    body = client.get("/organisation/setup?fresh=1").data.decode()
    assert "are required" in body
