"""G-13 — the audience autoplay must advance on the session's configured
cadence, not a hardcoded 6s.

The presenter session stores ``autoplay_seconds`` (default 8.0) and publishes it
in ``public_state``, but the audience view's ``startAuto`` looped on a literal
``6000`` ms and never read it — so a foyer/kiosk loop ran faster than configured.
The audience view now drives the interval from ``state.autoplay_seconds`` and
restarts the timer if the operator retimes the deck live.

The audience view needs a live presenter session to render, so this guards the
fix at the source level plus a unit check that ``autoplay_seconds`` is published.
"""

from __future__ import annotations

import importlib
import pathlib

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


def test_audience_autoplay_reads_configured_seconds():
    # The interval is a variable seeded from the polled state, not a literal 6000.
    assert "apMs=8000" in _SRC
    assert "Number(s.autoplay_seconds)||8" in _SRC
    assert "setInterval(function(){ apIdx=(apIdx+1)%TOTAL; show(apIdx,ver); }, apMs)" in _SRC


def test_old_hardcoded_6000_interval_gone():
    # The exact old hardcoded-cadence startAuto is gone.
    assert (
        "setInterval(function(){ apIdx=(apIdx+1)%TOTAL; show(apIdx,ver); }, 6000)" not in _SRC
    )


def test_autoplay_seconds_is_published_in_public_state():
    from mediahub.documents import presenter

    importlib.reload(presenter)
    s = presenter.PresenterSession(
        session_id="s1", doc_id="d1", owner="club-1", total_slides=3
    )
    assert "autoplay_seconds" in s.public_state()
    assert s.public_state()["autoplay_seconds"] == 8.0
