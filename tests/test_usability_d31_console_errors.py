"""D-31 — the presenter console's action taps must not swallow all errors.

The console's act() was a fire-and-forget `await fetch(...); poll();` with no
try/catch and no `!r.ok` branch, so an offline tap, a 429, or a 404 did nothing
and the position never changed — the presenter couldn't tell whether the slide
advanced, the connection dropped, or they'd been rate-limited. It now surfaces a
brief inline state.

The console needs a live presenter session to render, so this guards the fix at
the source level.
"""

from __future__ import annotations

import pathlib

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


def test_console_act_handles_failures():
    assert "function cstat(m)" in _SRC
    assert "Too many attempts" in _SRC
    assert 'id="cstat"' in _SRC
    # The old fire-and-forget "await fetch(...); poll();" with no guard is gone.
    assert "async function act(a){ await fetch('__ACTION_URL__'" not in _SRC
