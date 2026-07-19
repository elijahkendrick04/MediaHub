"""G-14 — busy-button states were reinvented per handler instead of using the
shared ``MH.btnState`` (ui-kit.js), and loading labels mixed the "…" ellipsis
with three-dot "..." spellings.

The clearly-mechanical handlers (simple disable + label swap with a paired
restore on every terminal path) now also drive ``MH.btnState(btn, 'loading' |
'idle')`` — guarded with ``window.MH && MH.btnState`` so a page without the ui
kit degrades to the old behaviour — and every loading-word spelling uses the
single-character ellipsis. Handlers with bespoke multi-stage states (progress
panels, poll loops, recorder toggles, transient menu items) are deliberately
left alone: changing those risks breaking their terminal-state restores.
"""

from __future__ import annotations

import pathlib
from tests._helpers import web_surface_src

_SRC = web_surface_src()
_UI_KIT = pathlib.Path("src/mediahub/web/static/js/ui-kit.js").read_text(encoding="utf-8")


def _fn(name: str) -> str:
    """Slice a top-level ``function <name>(...)`` body out of the page JS."""
    start = _SRC.index("function " + name + "(")
    nxt = _SRC.index("\nfunction ", start)
    return _SRC[start:nxt]


def test_btn_state_helper_still_exists():
    assert "MH.btnState = function (btn, state)" in _UI_KIT


def test_btn_state_adoption_increased():
    # Before G-14 web.py referenced MH.btnState 3 times (one a comment).
    assert _SRC.count("MH.btnState") >= 15


# ---- converted handlers: busy AND every terminal restore ------------------


def test_reformat_uses_btn_state():
    body = _fn("_runReformat")
    assert body.count("MH.btnState(btn, 'loading')") == 1
    assert body.count("MH.btnState(btn, 'idle')") == 2  # then + catch


def test_copilot_preview_uses_btn_state():
    body = _fn("copilotPreview")
    assert body.count("MH.btnState(btn, 'loading')") == 1
    assert body.count("MH.btnState(btn, 'idle')") == 2  # then + catch


def test_translate_button_uses_btn_state():
    # The translate handler lives inside the caption closure; pin the pair by
    # its unique busy label.
    start = _SRC.index("trBtn.textContent = 'Translating…'")
    body = _SRC[start : start + 3000]
    assert "MH.btnState(trBtn, 'loading')" in body
    assert body.count("MH.btnState(trBtn, 'idle')") == 2  # then + catch


def test_regenerate_draft_uses_btn_state():
    # The handler is a standalone <script> constant; bound the slice by its
    # closing tag (the next top-level `function` is a different page's JS).
    start = _SRC.index("function mhRegenerateDraft(")
    body = _SRC[start : _SRC.index("</script>", start)]
    assert body.count("MH.btnState(btn, 'loading')") == 1
    # Success navigates away (stays loading); error branch + catch restore.
    assert body.count("MH.btnState(btn, 'idle')") == 2


def test_use_why_in_caption_uses_btn_state():
    start = _SRC.index("window.mhUseWhyInCaption = function(")
    body = _SRC[start : _SRC.index("data-mh-flash", start)]
    assert body.count("MH.btnState(btn, 'loading')") == 1
    assert body.count("MH.btnState(btn, 'idle')") == 2  # then + catch


def test_editorial_gen_busy_helper_uses_btn_state():
    body = _fn("_genBusy")
    # The shared editorial helper flips the kit state for every generate
    # button that funnels through it.
    assert "MH.btnState(btn, on ? 'loading' : 'idle')" in body


# ---- loading-word spellings: single-character ellipsis only ----------------


def test_three_dot_loading_labels_gone():
    for old in [
        "'Recording...'",
        "'Applying...'",
        "'Saving...'",
        "'Starting...'",
        "'Reading the site...'",
        "'Done - opening configure...'",
        "+'...'",  # 'Uploading '+file.name+'...'
    ]:
        assert old not in _SRC, old


def test_ellipsis_loading_labels_present():
    for new in [
        "'Recording…'",
        "'Applying…'",
        "'Saving…'",
        "'Starting…'",
        "'Reading the site…'",
        "'Uploading '+file.name+'…'",
    ]:
        assert new in _SRC, new
