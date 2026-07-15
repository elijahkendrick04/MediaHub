"""Regression: /developer login inputs must have programmatically associated labels.

WCAG / axe-core rule 'label' (critical) requires every <input> to be linked to a
<label> via matching for/id attributes. The username and password inputs on the
developer sign-in page were missing id attributes and their labels were missing
for attributes, so screen readers could not announce what each field was for.
"""

from __future__ import annotations

import re

import pytest


@pytest.fixture
def developer_page_html(client):
    return client.get("/developer").get_data(as_text=True)


def _label_for_values(html: str) -> set[str]:
    return set(re.findall(r'<label[^>]+\bfor="([^"]+)"', html))


def _input_ids(html: str) -> set[str]:
    return set(re.findall(r'<input[^>]+\bid="([^"]+)"', html))


def test_username_input_has_label(developer_page_html):
    assert (
        'for="dev_user"' in developer_page_html
    ), "axe-core 'label' violation: #dev_user input has no associated <label for=...>"


def test_username_input_has_id(developer_page_html):
    assert (
        'id="dev_user"' in developer_page_html
    ), "axe-core 'label' violation: username input missing id='dev_user'"


def test_password_input_has_label(developer_page_html):
    assert (
        'for="dev_password"' in developer_page_html
    ), "axe-core 'label' violation: #dev_password input has no associated <label for=...>"


def test_password_input_has_id(developer_page_html):
    assert (
        'id="dev_password"' in developer_page_html
    ), "axe-core 'label' violation: password input missing id='dev_password'"


def test_label_for_matches_input_id(developer_page_html):
    fors = _label_for_values(developer_page_html)
    ids = _input_ids(developer_page_html)
    assert (
        "dev_user" in fors & ids
    ), "label[for=dev_user] and input[id=dev_user] must both be present"
    assert (
        "dev_password" in fors & ids
    ), "label[for=dev_password] and input[id=dev_password] must both be present"
