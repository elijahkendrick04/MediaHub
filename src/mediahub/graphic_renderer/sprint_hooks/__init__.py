"""Sprint render-hook registry — auto-discovered post-render HTML transforms.

The still-graphic analogue of the motion ``sprint/`` registries. Generator-sprint
capabilities (roadmap ``G1.*``) that work by injecting CSS / an overlay into the
final card HTML — gradient-mesh backgrounds, depth-of-field blur, icon/badge
overlays, mono mode, animated-still loops, the inspection overlay — register as
their **own module** in this package, with NO edits to ``render.py``. Each new
file is picked up automatically (``pkgutil``), so two parallel sessions never edit
the same file.

Drop-in contract — each module in this package defines:

    ORDER: int = 50          # lower runs earlier; ties break on module name
    def apply(html: str, ctx: "RenderHookCtx") -> str: ...

``apply`` receives the fully-assembled card HTML (after templating, grain and
watermark) and returns the transformed HTML; it MUST be deterministic and may
opt out by returning ``html`` unchanged (e.g. when ``ctx.brief`` doesn't request
the effect). With no hook modules present (today) ``apply_render_hooks`` is a
no-op and renders are byte-identical to before the seam landed.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class RenderHookCtx:
    """Read-only context handed to every render hook."""

    brief: Any  # CreativeBrief — typed loosely to avoid an import cycle
    width: int
    height: int
    family: str  # the chosen layout/archetype id
    format_name: str  # feed_square / feed_portrait / story / …
    is_v2: bool  # True for a Gen-v2 archetype


def _discover() -> list[tuple[int, str, Callable[[str, RenderHookCtx], str]]]:
    """Find every sibling module exposing ``apply``; ordered by (ORDER, name)."""
    found: list[tuple[int, str, Callable[[str, RenderHookCtx], str]]] = []
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{__name__}.{info.name}")
        fn = getattr(mod, "apply", None)
        if callable(fn):
            order = int(getattr(mod, "ORDER", 50))
            found.append((order, info.name, fn))
    found.sort(key=lambda t: (t[0], t[1]))
    return found


def apply_render_hooks(html: str, ctx: RenderHookCtx) -> str:
    """Run every registered render hook over ``html`` in order.

    A hook that raises is skipped (its effect is dropped) rather than failing the
    whole render — one sprint feature can never break the card pipeline.
    """
    for _order, _name, fn in _discover():
        try:
            result = fn(html, ctx)
            if isinstance(result, str):
                html = result
        except Exception:  # noqa: BLE001 — isolation: a bad hook is skipped, not fatal
            continue
    return html


__all__ = ["RenderHookCtx", "apply_render_hooks"]
