"""Shared source-scan helper for the suite (deep-review finding #15 stage 4).

Semantic data-testid assertions live in ``tests/_semantic.py``; the canonical
app/client fixtures live in ``conftest.py``. This module holds the one helper
those don't cover: the whole-web-surface source string.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["web_surface_src"]


def web_surface_src() -> str:
    """The complete web-surface source, as one string.

    Finding #15's stage 4 carved the four largest route surfaces out of
    ``web/web.py`` into ``web/routes_*.py``; source-structure tests that pin
    an idiom ("the sidecar write is atomic", "the confirm copy is present")
    should scan the whole surface, not assume the code's file. Order:
    ``web.py`` first, then the carved modules alphabetically.
    """
    web_dir = Path(__file__).resolve().parents[1] / "src" / "mediahub" / "web"
    parts = [(web_dir / "web.py").read_text(encoding="utf-8")]
    for p in sorted(web_dir.glob("routes_*.py")):
        parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts)
