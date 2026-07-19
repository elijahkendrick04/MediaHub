"""Regression: /organisation/setup select[name="org_type"] must have an accessible name.

axe-core rule 'select-name' (critical) requires every <select> to be associated with
a <label> via matching for/id attributes so screen readers can announce its purpose.
Both the AI-build panel (posts to /organisation/setup/capture) and the manual-build
panel were missing for/id pairs on the org-type selects.
"""

from __future__ import annotations

import re

import pytest


@pytest.fixture
def setup_html(client):
    return client.get("/organisation/setup").get_data(as_text=True)


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
    assert (
        "ai-org-type" in fors & ids
    ), "ai-org-type: for/id pair must exist in both label and select"
    assert (
        "ms-org-type" in fors & ids
    ), "ms-org-type: for/id pair must exist in both label and select"
