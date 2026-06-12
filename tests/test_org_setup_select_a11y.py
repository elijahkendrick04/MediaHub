"""Regression: /organisation/setup select[name="org_type"] must have an accessible name.

axe-core rule 'select-name' (critical) requires every <select> to be associated with
a <label> via matching for/id attributes so screen readers can announce its purpose.
Both the AI-build panel (posts to /organisation/setup/capture) and the manual-build
panel were missing for/id pairs on the org-type selects.
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def setup_html(app_client):
    return app_client.get("/organisation/setup").get_data(as_text=True)


def _label_fors(html: str) -> set[str]:
    return set(re.findall(r'<label[^>]+\bfor="([^"]+)"', html))


def _select_ids(html: str) -> set[str]:
    return set(re.findall(r'<select[^>]+\bid="([^"]+)"', html))


def test_ai_panel_org_type_select_has_label(setup_html):
    assert 'for="ai-org-type"' in setup_html, (
        "axe-core 'select-name' violation: AI-panel select[name=org_type] "
        "has no associated <label for=...>"
    )


def test_ai_panel_org_type_select_has_id(setup_html):
    assert 'id="ai-org-type"' in setup_html, (
        "axe-core 'select-name' violation: AI-panel select[name=org_type] "
        "missing id='ai-org-type'"
    )


def test_manual_panel_org_type_select_has_label(setup_html):
    assert 'for="ms-org-type"' in setup_html, (
        "axe-core 'select-name' violation: manual-panel select[name=org_type] "
        "has no associated <label for=...>"
    )


def test_manual_panel_org_type_select_has_id(setup_html):
    assert 'id="ms-org-type"' in setup_html, (
        "axe-core 'select-name' violation: manual-panel select[name=org_type] "
        "missing id='ms-org-type'"
    )


def test_label_for_matches_select_id(setup_html):
    fors = _label_fors(setup_html)
    ids = _select_ids(setup_html)
    assert "ai-org-type" in fors & ids, (
        "ai-org-type: for/id pair must exist in both label and select"
    )
    assert "ms-org-type" in fors & ids, (
        "ms-org-type: for/id pair must exist in both label and select"
    )
