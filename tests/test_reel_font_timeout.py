"""Regression — the meet reel must not die on Remotion's default 30s
delayRender budget.

Bug (live, 2026-06-04): "Generate reel from this meet" returned
"Remotion render failed (exit 1)" with the uncleared delayRender created in
``ensureBrandFonts``. The 15s/450-frame MeetReel exceeds the default 30s
delayRender timeout on a contended single-CPU deployment (the lighter 6s
StoryCard passes), so the whole reel render exits 1.

Fix pinned here: fonts.ts holds the render with an explicit generous
timeout AND kicks ``document.fonts.load()`` per face so ``fonts.ready``
settles fast; render.js raises renderMedia's global delayRender budget to
match (well inside the Python wrapper's 600s subprocess timeout).
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_FONTS_TS = _ROOT / "src" / "mediahub" / "remotion" / "src" / "fonts.ts"
_RENDER_JS = _ROOT / "src" / "mediahub" / "remotion" / "render.js"


def test_fonts_hold_has_explicit_timeout():
    src = _FONTS_TS.read_text(encoding="utf-8")
    assert "timeoutInMilliseconds" in src, (
        "fonts.ts delayRender must carry an explicit timeout — the default "
        "30s budget kills the MeetReel on a 1-CPU box."
    )


def test_fonts_are_kicked_eagerly():
    src = _FONTS_TS.read_text(encoding="utf-8")
    assert "document.fonts.load" in src, (
        "fonts.ts must kick each face with document.fonts.load() so "
        "fonts.ready settles deterministically instead of waiting for "
        "first layout use."
    )


def test_render_media_budget_raised():
    src = _RENDER_JS.read_text(encoding="utf-8")
    assert "timeoutInMilliseconds" in src, (
        "render.js renderMedia must raise the global delayRender budget "
        "above Remotion's 30s default for the reel."
    )


def test_budget_stays_inside_python_subprocess_timeout():
    src = _RENDER_JS.read_text(encoding="utf-8")
    import re

    m = re.search(r"timeoutInMilliseconds:\s*(\d+)", src)
    assert m, "timeoutInMilliseconds must be a literal number"
    assert (
        int(m.group(1)) < 600_000
    ), "renderMedia budget must stay inside motion.py's 600s subprocess cap"
