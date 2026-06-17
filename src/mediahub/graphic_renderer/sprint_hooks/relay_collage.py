"""Relay-collage compositor hook (roadmap G1.2).

The auto-discovered seam that wires the multi-athlete collage engine
(``graphic_renderer.collage``) into the ``relay_collage`` archetype with **no
edit to render.py**. When a card renders that archetype, this hook resolves the
card's 2-4 people-photos, composites them into one balanced frame, and drops the
block between the ``<!--RC:STAGE-->`` markers the archetype ships — replacing the
single-photo fallback.

Strictly opt-in and isolating: it is a no-op for every other archetype, and a
no-op (leaving the single-photo fallback in place) whenever fewer than two usable
cutouts resolve. Deterministic — the collage engine seeds its placement from the
brief — so a re-render of the same card never reshuffles the squad.
"""

from __future__ import annotations

import re

from . import RenderHookCtx

# Composite the squad before any later cosmetic post-render hooks (mono mode,
# inspection overlays, …) so those see the finished stage.
ORDER = 20

_STAGE_RE = re.compile(r"<!--RC:STAGE-->.*?<!--/RC:STAGE-->", re.DOTALL)


def apply(html: str, ctx: RenderHookCtx) -> str:
    """Swap the relay_collage stage for the composited multi-subject block."""
    if ctx.family != "relay_collage":
        return html
    if "<!--RC:STAGE-->" not in html or "<!--/RC:STAGE-->" not in html:
        return html

    from mediahub.graphic_renderer.collage import collage_block_for_brief

    block = collage_block_for_brief(ctx.brief, width=ctx.width, height=ctx.height)
    if not block:
        # Fewer than two people-photos resolved — keep the archetype's
        # single-photo / painted fallback untouched.
        return html

    # Function replacement so a backslash / group-ref inside the data-URI block
    # is inserted verbatim, never interpreted by re.
    return _STAGE_RE.sub(lambda _m: block, html, count=1)
