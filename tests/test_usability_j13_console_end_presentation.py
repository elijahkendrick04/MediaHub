"""J-13 — the presenter console must be able to end the talk.

The console (the laptop driving the deck) exposed Prev/Next/Blackout/Autoplay/
Reset but no "End". A presenter who closed the laptop tab left the session live
for its 6-hour TTL, so the projector kept showing the last slide. The console now
has a confirmed "End presentation" that fires the ``end`` action and returns the
presenter to the document.

The console needs a live session + deck to render, so this guards the fix at the
source level, plus a check that the console route wires up the return URL.
"""

from __future__ import annotations

import pathlib

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


def test_console_has_confirmed_end_button():
    # A visible End button on the console button row…
    assert 'id="end-pres"' in _SRC
    assert 'onclick="endPres()"' in _SRC
    assert ">End presentation</button>" in _SRC
    # …wired to a confirm + the 'end' action + a return to the document.
    assert "async function endPres()" in _SRC
    assert "End the presentation for everyone?" in _SRC
    assert "action:'end'" in _SRC
    assert "location.href='__DOC_URL__'" in _SRC


def test_console_route_fills_doc_url():
    # The console route must replace __DOC_URL__ with the document view.
    assert '.replace("__DOC_URL__", url_for("document_view", doc_id=doc_id))' in _SRC


def test_end_is_a_valid_presenter_action():
    from mediahub.documents import presenter

    assert "end" in presenter.ACTIONS
