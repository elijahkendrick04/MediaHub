"""Guard: web.py lane accents follow the club brand via color-mix(var(--lane)).

PR 778 converted lane tints to ``color-mix(in oklab, var(--lane) N%, transparent)``
so accents follow the club brand instead of staying yellow. Three hardcoded
``rgba(212,255,58,...)`` literals survived that sweep (plan-calendar event chip
and the media-library shared banner); this pins that none creep back in.
"""

from __future__ import annotations

from pathlib import Path

WEB_PY = Path(__file__).resolve().parents[1] / "src" / "mediahub" / "web" / "web.py"


def test_no_hardcoded_lane_yellow_left():
    src = WEB_PY.read_text(encoding="utf-8").replace(" ", "")
    assert "rgba(212,255,58" not in src
