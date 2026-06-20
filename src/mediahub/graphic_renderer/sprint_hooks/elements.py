"""sprint_hooks/elements.py — paint brief-selected library elements onto a card.

Roadmap 1.10. The element library (``mediahub.elements``) is a curated set of
brand-token-recolourable SVGs — sport pictograms, stat/time chips, ribbons,
dividers, frames, texture panels. A brief can carry an ``elements`` list of
placements (id + position + scale + rotation + opacity); this hook resolves each
element, recolours it to the *exact* ``--mh-*`` roles the card painted, and lays
it out at the requested spot.

Contract (every sprint hook honours it): a brief with no ``elements`` is returned
**byte-identical** — the decorative layer is purely additive and opt-in.
Deterministic: same placements + same brand roles → same markup.
"""

from __future__ import annotations

from . import RenderHookCtx

# Above the style-pack ground/texture (~50) and card content, but below the
# achievement badges (icon_overlay, 70) so a medal/PB badge always reads on top.
ORDER = 58

# Paint band: above card content, below the icon-overlay badges (z 80) and the
# demo watermark (z 9999).
_ELEMENTS_Z = 60


def _placements(brief):
    raw = getattr(brief, "elements", None)
    if not raw or not isinstance(raw, (list, tuple)):
        return []
    try:
        from mediahub.elements.models import ElementPlacement
    except Exception:
        return []
    out = []
    for item in raw:
        if isinstance(item, ElementPlacement):
            out.append(item)
            continue
        p = ElementPlacement.from_dict(item) if isinstance(item, dict) else None
        if p is not None:
            out.append(p)
    return out


def apply(html: str, ctx: RenderHookCtx) -> str:
    brief = ctx.brief
    if brief is None or ctx.width <= 0 or ctx.height <= 0:
        return html

    placements = _placements(brief)
    if not placements:
        return html  # opt out → byte-identical

    try:
        from mediahub.elements import catalog as _catalog
        from mediahub.elements import recolour as _recolour
        from mediahub.elements import render as _render
    except Exception:
        return html  # library unavailable → leave the card untouched

    profile_id = getattr(brief, "profile_id", "") or None
    role_vars = _recolour.role_vars_for_brief(brief)

    cells: list[str] = []
    for idx, placement in enumerate(placements):
        element = _catalog.get_element(placement.element_id, profile_id)
        if element is None:
            continue
        # APCA gate: a text-carrying element must stay legible in the card's
        # resolved roles, else it's dropped (better no chip than an illegible one
        # — the deterministic-engine legibility rule, reusing quality.compliance).
        if not _recolour.element_is_legible(element, role_vars):
            continue
        uid = _render._uid_for(f"{element.id}.{idx}", role_vars)
        markup = _render.render_element_markup(element, role_vars, uid=uid, profile_id=profile_id)
        if not markup:
            continue
        box_css = _render.placement_box_css(
            placement, width=ctx.width, height=ctx.height, z_index=_ELEMENTS_Z
        )
        cells.append(
            f'<div class="mh-element" data-element="{element.id}" style="{box_css}">{markup}</div>'
        )

    if not cells:
        return html  # nothing resolved → byte-identical

    overlay = (
        f'<div class="mh-elements-overlay" '
        f'style="position:fixed;inset:0;z-index:{_ELEMENTS_Z};pointer-events:none">'
        + "".join(cells)
        + "</div>"
    )
    if "</body>" in html:
        return html.replace("</body>", overlay + "</body>", 1)
    return html + overlay


__all__ = ["apply", "ORDER"]
