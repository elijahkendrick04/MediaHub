"""Ordered-dither debanding overlay render hook (render-banding-dither).

Auto-discovered post-render transform (see ``sprint_hooks/__init__``). It paints
a low-amplitude (~±1/255), static Bayer-8×8 *ordered-dither* layer over a card's
big brand fill — enough to break the 8-bit gradient banding a flat brand ground
shows on a phone screen, without introducing any hue and without moving the
field's average colour. Off by default: with every brief that did not explicitly
opt in the hook returns the HTML unchanged, so existing renders are byte-for-byte
identical (the still PNG cache stays valid).

Opt-in contract — a SEPARATE, standalone ``background_style`` token
(``"dither"``), deliberately NOT a ``:mode`` suffix. The one ``:``-suffix slot on
``background_style`` is already owned by the gradient-mesh mode
(``gradient_mesh:radial`` etc.); a ``:dither`` suffix would collide with it and
silently reparse as an invalid mesh mode. A standalone base token sidesteps that
entirely. ``render._background_pattern_for`` registers ``"dither"`` so the ground
resolves to a CLEAN fill (not the default busy water tile) for the dither to sit
over.

This is distinct from the aesthetic film-grain the v1 grain injector paints by
default: that is a stylised texture; this is a mean-preserving debanding pass.

Scope note (deliberate): the dither is a *background* overlay over the ground
fill — the big surface that actually bands. It is NOT layered above foreground
content, so it does not attempt to redither small foreground chrome such as the
medal chip's specular ramp; those are tiny surfaces where banding is not visible.
On v1 layouts it rides just above the ground (mirroring the ``.bg-noise`` layer's
stacking, below content); on v2 archetypes — which have no ``.canvas`` isolation
wrapper the grain injector could target, so they band on their flat root fill —
it rides as a top overlay so the mix-blend still composites against the root.
"""

from __future__ import annotations

from . import RenderHookCtx

# Run after the gradient-mesh hook (ORDER 20) and after the grain injector so the
# dither composites over the fully-assembled ground.
ORDER = 40

# The standalone opt-in token (parsed as the base, before any ``:`` suffix).
_TRIGGERS = frozenset({"dither"})

_ANCHOR = '<div class="bg-noise"></div>'


def apply(html: str, ctx: RenderHookCtx) -> str:
    raw = (getattr(ctx.brief, "background_style", "") or "").strip().lower()
    if not raw:
        return html
    if raw.partition(":")[0] not in _TRIGGERS:
        return html  # opt out — this brief didn't ask for the dither layer

    # Lazy import to keep discovery cheap and avoid an import cycle with render.
    from mediahub.graphic_renderer.render import _dither_pattern_data_uri

    uri = _dither_pattern_data_uri()

    if _ANCHOR in html:
        # v1: ride just above the ground, below content, inside the isolated
        # ``.canvas`` (so the mix-blend composites against the canvas fill).
        div = '<div class="bg-dither mh-dither-v1"></div>'
        html = html.replace(_ANCHOR, _ANCHOR + div, 1)
    elif ctx.is_v2:
        # v2: no ``.canvas`` isolation wrapper — a top overlay before </body>
        # blends against the archetype's flat root fill.
        div = '<div class="bg-dither mh-dither-v2"></div>'
        html = html.replace("</body>", div + "</body>", 1)
    else:
        return html  # no sensible anchor — leave the render untouched

    style = (
        '<style data-mh-dither="1">'
        ".bg-dither{position:absolute;inset:0;background-image:" + uri + ";"
        "background-size:8px 8px;background-repeat:repeat;"
        "mix-blend-mode:overlay;pointer-events:none}"
        ".bg-dither.mh-dither-v1{z-index:2}"
        ".bg-dither.mh-dither-v2{z-index:9998}"
        "</style>"
    )
    return html.replace("</body>", style + "</body>", 1)
