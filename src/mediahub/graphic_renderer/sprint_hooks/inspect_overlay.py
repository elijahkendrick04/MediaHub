"""Render inspection-overlay hook (roadmap G1.30).

Auto-discovered sprint render hook that drops the design debug HUD +
explainability sidecar onto a finished card — see
:mod:`mediahub.graphic_renderer.inspect` for the overlay/sidecar maths.

Strictly opt-in: it returns the HTML untouched unless inspection is requested
(``MEDIAHUB_INSPECT_OVERLAY`` env truthy, or the brief carries a truthy
``inspect_overlay`` attribute). Off — the default — the render is byte-identical,
so this module is safe to ship in the always-loaded registry. It runs late
(``ORDER`` high) so it observes the fully-assembled card (grain, watermark, every
other sprint effect) and its HUD sits on top.
"""

from __future__ import annotations

from . import RenderHookCtx
from .. import inspect as _inspect

# Run after the decorative hooks so the overlay measures and sits above the
# finished card rather than an intermediate state.
ORDER = 95


def apply(html: str, ctx: RenderHookCtx) -> str:
    """Inject the inspection overlay when requested; otherwise pass ``html`` through."""
    if not _inspect.inspect_enabled(ctx):
        return html
    return _inspect.render_inspect_overlay(html, ctx)
