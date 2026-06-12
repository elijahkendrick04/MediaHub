"""Regression: /organisation colour inputs must have programmatically associated labels.

WCAG / axe-core rule 'label' (critical) requires every <input> to be linked to a
<label> via matching for/id attributes. #org-brand-primary and #org-brand-secondary
were missing `for` attributes, causing screen readers to be unable to announce what
the colour pickers are for.
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
        yield c, cp


def _seed_profile(cp):
    from mediahub.web.club_profile import ClubProfile
    prof = ClubProfile(profile_id="a11y-test", display_name="A11y Test Club")
    prof.brand_primary = "#0A2540"
    prof.brand_secondary = "#635BFF"
    cp.save_profile(prof)
    return prof


def _label_for_values(html: str) -> set[str]:
    return set(re.findall(r'<label[^>]+\bfor="([^"]+)"', html))


@pytest.fixture
def organisation_html(app_client):
    client, cp = app_client
    _seed_profile(cp)
    with client.session_transaction() as s:
        s["active_profile_id"] = "a11y-test"
    return client.get("/organisation").get_data(as_text=True)


def test_brand_primary_input_has_label(organisation_html):
    assert 'for="org-brand-primary"' in organisation_html, (
        "axe-core 'label' violation: #org-brand-primary has no associated <label for=...>"
    )


def test_brand_secondary_input_has_label(organisation_html):
    assert 'for="org-brand-secondary"' in organisation_html, (
        "axe-core 'label' violation: #org-brand-secondary has no associated <label for=...>"
    )


def test_label_for_matches_input_id(organisation_html):
    fors = _label_for_values(organisation_html)
    input_ids = set(re.findall(r'<input[^>]+\bid="([^"]+)"', organisation_html))
    assert "org-brand-primary" in fors & input_ids
    assert "org-brand-secondary" in fors & input_ids
