"""D-31 — the slide remote's and presenter console's action taps must not
swallow all errors.

The remote's act() did `fetch → r.json() → if(j.state) setPos` with no try/catch
and no `j.ok===false` branch, so an offline tap, a 429 rate-limit, or a 404 did
nothing and the position never changed — the presenter couldn't tell whether the
slide advanced, the connection dropped, or they'd been rate-limited. The
console's act() was the same. Both now surface a brief inline state.

These two surfaces need a live presenter session / paired remote code to render,
so this guards the fix at the source level.
"""

from __future__ import annotations

import pathlib

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


def test_remote_act_handles_failures():
    # The remote act() catches fetch failures and non-ok/ok:false responses and
    # surfaces a state via rstat().
    assert "function rstat(m)" in _SRC
    assert "j.ok===false" in _SRC
    assert "Too many taps" in _SRC
    assert "Reconnecting" in _SRC
    assert 'id="rstat"' in _SRC


def test_console_act_handles_failures():
    assert "function cstat(m)" in _SRC
    assert "Too many attempts" in _SRC
    assert 'id="cstat"' in _SRC
    # The old fire-and-forget "await fetch(...); poll();" with no guard is gone.
    assert "async function act(a){ await fetch('__ACTION_URL__'" not in _SRC
