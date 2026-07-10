"""H-23 — "Build spotlight post" must be disabled while nothing is approved.

The build button was always active; with no approved achievements the POST landed
on a full-page 400 ("No achievements approved yet…") that lost the tone selection
and page position. The button is now disabled (with an explaining title) whenever
zero achievements are approved, while the server check stays as a fallback.

The spotlight view needs a processed run + swimmer to render, so this guards the
disable wiring at the source level.
"""

from __future__ import annotations

import pathlib

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


def test_build_button_disabled_when_zero_approved():
    # The disable attr is derived from whether any achievement is approved…
    assert "_sp_has_approved = bool(_approved_ras)" in _SRC
    assert '_sp_build_attr = "" if _sp_has_approved else " disabled"' in _SRC
    # …and applied to the actual Build button.
    assert (
        '<button type="submit" class="btn"{_sp_build_attr} title="{_h(_sp_build_title)}"' in _SRC
    )


def test_server_precondition_kept_as_fallback():
    # The 400 for a genuine race is still the backstop.
    assert "No achievements approved yet" in _SRC
