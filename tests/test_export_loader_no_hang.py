"""tests/test_export_loader_no_hang.py — a file-download submit never leaves
the full-screen loader stuck (audit finding H-2).

The global form binder shows a fixed, full-viewport "Working on it" loader on
every POST and only hides it on a bfcache restore. A bulk "Export ZIP" is a
native submit that returns a Content-Disposition attachment and never
navigates the page — so the loader used to hang forever and the volunteer
thought the app had crashed.

No client JS harness exists, so this guards the two source-level fixes: the
export action hides the loader shortly after the download starts, and the
binder has a safety timeout that clears any stuck overlay.
"""
from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "src" / "mediahub" / "web" / "web.py"


def test_export_action_hides_loader():
    src = _WEB.read_text(encoding="utf-8")
    # The bulk export branch installs a hide-loader handler rather than just
    # returning and leaving the global loader up.
    idx = src.index("if (action === 'export') {")
    snippet = src[idx: idx + 700]
    assert "MH.hideLoader" in snippet, "export submit must hide the global loader"


def test_form_binder_has_safety_timeout():
    src = _WEB.read_text(encoding="utf-8")
    # The binder clears the loader after a bounded time so no non-navigating
    # POST can leave it stuck.
    assert "Safety net" in src
    assert "}, 20000);" in src
