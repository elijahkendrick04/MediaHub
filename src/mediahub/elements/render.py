"""elements.render — turn a library Element into recoloured, on-brand SVG markup.

The renderer never rasterises here: an element is inline SVG that drops straight
into the card HTML (rendered to PNG by the same Playwright pass as everything
else — exactly how ``sprint_hooks/icon_overlay`` injects its badges) and into
the browse-tab thumbnails (browsers render SVG natively). One code path, fully
deterministic, brand-locked.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from . import catalog as _catalog
from . import recolour as _recolour
from .models import Element, ElementPlacement


def render_element_markup(
    element: Element,
    role_vars: dict[str, str],
    *,
    uid: Optional[str] = None,
    profile_id: Optional[str] = None,
    fill_box: bool = True,
) -> Optional[str]:
    """Recoloured inline ``<svg>`` for ``element`` (or ``None`` if its file is missing)."""
    svg = _catalog.load_svg(element, profile_id)
    if not svg:
        return None
    token = uid or _uid_for(element.id, role_vars)
    out = _recolour.recolour_svg(svg, role_vars, uid=token)
    if fill_box and "<svg " in out:
        # size to its container, like icon_overlay does
        out = out.replace("<svg ", '<svg style="width:100%;height:100%;display:block" ', 1)
    return out


def render_for_brief(
    element: Element,
    brief,
    *,
    brand_kit=None,
    uid: Optional[str] = None,
    profile_id: Optional[str] = None,
) -> Optional[str]:
    """Recolour an element to the colours the *card* painted."""
    role_vars = _recolour.role_vars_for_brief(brief, brand_kit)
    return render_element_markup(element, role_vars, uid=uid, profile_id=profile_id)


def render_for_palette(
    element: Element,
    *,
    palette: Optional[dict] = None,
    brand_kit=None,
    uid: Optional[str] = None,
    profile_id: Optional[str] = None,
) -> Optional[str]:
    """Recolour an element to a bare palette/brand kit (browse-tab thumbnails)."""
    role_vars = _recolour.role_vars_from_palette(palette, brand_kit)
    return render_element_markup(element, role_vars, uid=uid, profile_id=profile_id)


def placement_box_css(
    placement: ElementPlacement,
    *,
    width: int,
    height: int,
    z_index: int,
) -> str:
    """Absolute-position CSS for a placement, sized off the card's short edge."""
    short = max(1, min(width, height))
    box = max(8, round(short * max(0.02, placement.scale)))
    # centre the box on the (x, y) fraction of the card
    left = round(placement.x * width - box / 2)
    top = round(placement.y * height - box / 2)
    transform = ""
    if abs(placement.rotation) > 0.01:
        transform = f"transform:rotate({placement.rotation:.2f}deg);"
    opacity = ""
    if placement.opacity < 0.999:
        opacity = f"opacity:{max(0.0, min(1.0, placement.opacity)):.3f};"
    return (
        f"position:absolute;left:{left}px;top:{top}px;"
        f"width:{box}px;height:{box}px;z-index:{z_index};"
        f"pointer-events:none;{transform}{opacity}"
    )


def _uid_for(element_id: str, role_vars: dict[str, str]) -> str:
    """A stable, content-derived uid so repeated renders are byte-identical."""
    accent = role_vars.get("--mh-accent", "")
    ground = role_vars.get("--mh-primary", "")
    h = hashlib.blake2b(
        f"{element_id}|{accent}|{ground}".encode("utf-8"), digest_size=5
    ).hexdigest()
    return f"e{h}"


__all__ = [
    "render_element_markup",
    "render_for_brief",
    "render_for_palette",
    "placement_box_css",
]
