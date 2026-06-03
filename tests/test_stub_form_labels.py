"""Regression test: stub form inputs must have programmatically associated labels.

WCAG / axe-core rule 'label' requires every <input> and <textarea> to be linked
to a <label> via matching for/id attributes (or be wrapped inside the label).
Without this, screen readers can't announce what a field is for.

Covers the /free-text/quick page where the violation was first detected.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from mediahub.club_platform.stubs import (
    FreeTextStub,
    _PHOTO_INPUT_HTML,
)


def _label_for_values(html: str) -> set[str]:
    """Return all `for` attribute values found on <label> elements."""
    return set(re.findall(r'<label[^>]+\bfor="([^"]+)"', html))


def _input_ids(html: str) -> set[str]:
    """Return all `id` attribute values on <input> elements."""
    return set(re.findall(r'<input[^>]+\bid="([^"]+)"', html))


def _textarea_ids(html: str) -> set[str]:
    """Return all `id` attribute values on <textarea> elements."""
    return set(re.findall(r'<textarea[^>]+\bid="([^"]+)"', html))


class TestPhotoInputHtmlLabels:
    def test_label_has_for_attribute(self):
        assert _label_for_values(_PHOTO_INPUT_HTML), (
            "_PHOTO_INPUT_HTML label must have a `for` attribute to be "
            "programmatically associated with its input"
        )

    def test_input_has_matching_id(self):
        fors = _label_for_values(_PHOTO_INPUT_HTML)
        ids = _input_ids(_PHOTO_INPUT_HTML)
        assert fors & ids, (
            f"_PHOTO_INPUT_HTML: label for={fors!r} but input id={ids!r}; "
            "they must match so screen readers link label → control"
        )

    def test_for_and_id_are_stub_attached_photo(self):
        assert "stub-attached-photo" in _label_for_values(_PHOTO_INPUT_HTML)
        assert "stub-attached-photo" in _input_ids(_PHOTO_INPUT_HTML)


class TestFreeTextStubFormLabels:
    def setup_method(self):
        self.html = FreeTextStub().render_form_html()

    def test_textarea_has_id(self):
        ids = _textarea_ids(self.html)
        assert ids, (
            "FreeTextStub form: <textarea> must have an id so its label can "
            "reference it via `for`"
        )

    def test_label_references_textarea_id(self):
        fors = _label_for_values(self.html)
        ids = _textarea_ids(self.html)
        assert fors & ids, (
            f"FreeTextStub form: label for={fors!r} does not match any "
            f"textarea id={ids!r}; association is broken"
        )

    def test_for_and_id_are_free_text_notes(self):
        assert "free-text-notes" in _label_for_values(self.html)
        assert "free-text-notes" in _textarea_ids(self.html)
