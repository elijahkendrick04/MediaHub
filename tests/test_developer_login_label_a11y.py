"""Regression: /developer login inputs must have programmatically associated labels.

WCAG / axe-core rule 'label' (critical) requires every <input> to be linked to a
<label> via matching for/id attributes. The username and password inputs on the
developer sign-in page were missing id attributes and their labels were missing
for attributes, so screen readers could not announce what each field was for.
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
def developer_page_html(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    import mediahub.web.web as wm
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client.get("/developer").get_data(as_text=True)


def _label_for_values(html: str) -> set[str]:
    return set(re.findall(r'<label[^>]+\bfor="([^"]+)"', html))


def _input_ids(html: str) -> set[str]:
    return set(re.findall(r'<input[^>]+\bid="([^"]+)"', html))


def test_username_input_has_label(developer_page_html):
    assert 'for="dev_user"' in developer_page_html, (
        "axe-core 'label' violation: #dev_user input has no associated <label for=...>"
    )


def test_username_input_has_id(developer_page_html):
    assert 'id="dev_user"' in developer_page_html, (
        "axe-core 'label' violation: username input missing id='dev_user'"
    )


def test_password_input_has_label(developer_page_html):
    assert 'for="dev_password"' in developer_page_html, (
        "axe-core 'label' violation: #dev_password input has no associated <label for=...>"
    )


def test_password_input_has_id(developer_page_html):
    assert 'id="dev_password"' in developer_page_html, (
        "axe-core 'label' violation: password input missing id='dev_password'"
    )


def test_label_for_matches_input_id(developer_page_html):
    fors = _label_for_values(developer_page_html)
    ids = _input_ids(developer_page_html)
    assert "dev_user" in fors & ids, (
        "label[for=dev_user] and input[id=dev_user] must both be present"
    )
    assert "dev_password" in fors & ids, (
        "label[for=dev_password] and input[id=dev_password] must both be present"
    )
