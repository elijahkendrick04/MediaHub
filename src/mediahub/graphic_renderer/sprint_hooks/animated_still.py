"""Animated-still render hook (roadmap G1.29).

Injects a subtle, seamlessly-looping animated SVG layer into the finished card
HTML so a *live* preview of the card breathes — the still-graphic analogue of a
motion beat. The heavy maths (loop catalogue, palette, seed, the matching APNG/
GIF exporter) live in :mod:`mediahub.graphic_renderer.animated_still`; this hook
is just the HTML-injection seam.

**Opt-in only.** The effect is added only when ``ctx.brief`` asks for it
(``animate_still`` truthy, ``background_style == "animated_loop"``, or an explicit
in-vocabulary ``animated_loop``). For every other render this hook returns the
HTML unchanged, so renders stay byte-identical — the registry invariant.

The injected layer is paused at its neutral 0% keyframe, so the static screenshot
the renderer captures is deterministic and visually unchanged; the exporter is
what turns the card into a moving APNG/GIF.
"""

from __future__ import annotations

from typing import Any

from . import RenderHookCtx

# Runs early: this is an atmospheric background-class layer, so it should sit
# under any later overlay hooks (icons/badges). Ties break on module name.
ORDER = 20


def _wants_animation(brief: Any) -> bool:
    """True only when this brief explicitly asked for an animated still."""
    if bool(getattr(brief, "animate_still", False)):
        return True
    if str(getattr(brief, "background_style", "") or "").strip().lower() == "animated_loop":
        return True
    loop = getattr(brief, "animated_loop", None)
    return isinstance(loop, str) and bool(loop.strip())


def apply(html: str, ctx: RenderHookCtx) -> str:
    if not _wants_animation(ctx.brief):
        return html  # opt out → byte-identical render

    # Imported lazily so the hook stays importable (and the registry stays a
    # no-op for opted-out renders) even if the heavy renderer/deps are absent.
    from mediahub.graphic_renderer.animated_still import build_animation_css, plan_from_brief

    plan = plan_from_brief(ctx.brief)
    fragment = build_animation_css(plan, ctx.width, ctx.height)
    if "</body>" in html:
        return html.replace("</body>", fragment + "</body>", 1)
    return html + fragment
