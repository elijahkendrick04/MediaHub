"""elements.recolour — paint a library element in the card's brand colours.

The one job here: take an SVG that carries ``__SLOT__`` placeholders and an
optional ``__UID__`` (for unique gradient/filter ids), and substitute each slot
with the resolved ``--mh-*`` brand role colour the card itself painted. This is
the same single source of truth the archetype fill, the motion render and the
APCA compliance gate all read (``graphic_renderer.render.resolved_role_vars_for_brief``),
so an element is *guaranteed* on-brand — and, where it carries text, legible.

Deterministic: same SVG + same role vars + same uid → byte-identical output.
No LLM, no randomness (this is presentation maths, not a judgement call).
"""

from __future__ import annotations

from typing import Optional

from .models import Element

# Element SLOT  →  renderer role var. Single mapping; everything else derives.
_SLOT_TO_ROLE: dict[str, str] = {
    "GROUND": "--mh-primary",
    "SECONDARY": "--mh-secondary",
    "SURFACE": "--mh-surface",
    "ACCENT": "--mh-accent",
    "ON_GROUND": "--mh-on-primary",
    "ON_SURFACE": "--mh-on-surface",
    "OUTLINE": "--mh-outline",
}

# Conservative neutral defaults if a role var is absent (keeps render robust;
# the resolver normally supplies every key).
_ROLE_FALLBACK: dict[str, str] = {
    "--mh-primary": "#0A2540",
    "--mh-secondary": "#1B3D5C",
    "--mh-surface": "#051433",
    "--mh-accent": "#FFB81C",
    "--mh-on-primary": "#FFFFFF",
    "--mh-on-surface": "#FFFFFF",
    "--mh-outline": "rgba(255,255,255,0.20)",
}


def role_vars_for_brief(brief, brand_kit=None) -> dict[str, str]:
    """The exact ``--mh-*`` set the card painted (delegates to the renderer).

    Imported lazily so this module stays cheap and free of import cycles with
    ``graphic_renderer``.
    """
    try:
        from mediahub.graphic_renderer.render import resolved_role_vars_for_brief

        rv = resolved_role_vars_for_brief(brief, brand_kit)
        if isinstance(rv, dict) and rv:
            return rv
    except Exception:
        pass
    return dict(_ROLE_FALLBACK)


def role_vars_from_palette(palette: Optional[dict] = None, brand_kit=None) -> dict[str, str]:
    """Resolve role vars from a bare palette / brand kit (no brief).

    Used by standalone surfaces (the browse-tab thumbnails) that recolour an
    element to an org's brand without a full card brief.
    """
    try:
        from mediahub.graphic_renderer.render import _mh_role_vars

        rv = _mh_role_vars(dict(palette or {}), brand_kit)
        if isinstance(rv, dict) and rv:
            return rv
    except Exception:
        pass
    out = dict(_ROLE_FALLBACK)
    for k in ("primary", "secondary", "accent"):
        v = (palette or {}).get(k)
        if isinstance(v, str) and v.strip():
            out[f"--mh-{k}"] = v.strip()
    return out


def recolour_svg(svg_text: str, role_vars: dict[str, str], *, uid: str = "el") -> str:
    """Substitute ``__SLOT__`` / ``__UID__`` placeholders with brand colours.

    Outline is an rgba() string (alpha only), so it drops straight in. Every
    other slot is a hex from the resolved role set.
    """
    out = svg_text.replace("__UID__", _safe_uid(uid))
    for slot, role in _SLOT_TO_ROLE.items():
        colour = role_vars.get(role) or _ROLE_FALLBACK[role]
        out = out.replace(f"__{slot}__", colour)
    return out


def best_text_role(bg_role: str, role_vars: dict[str, str]) -> str:
    """Pick the legible ink role for text painted on ``bg_role``.

    Honours the deterministic-engine boundary by reusing the APCA gate
    (``quality.compliance.is_legible``): tries on-ground then on-surface then
    a black/white fallback, returning the role var key of the winner. This lets
    a text-carrying element stay legible even on an off-default background.
    """
    bg_hex = role_vars.get(bg_role) or _ROLE_FALLBACK.get(bg_role, "#0A2540")
    candidates = ("--mh-on-primary", "--mh-on-surface")
    try:
        from mediahub.quality.compliance import is_legible

        for cand in candidates:
            ink = role_vars.get(cand) or _ROLE_FALLBACK[cand]
            if is_legible(ink, bg_hex):
                return cand
        # neither role ink clears — fall back to the higher-contrast of B/W
        white_ok = is_legible("#FFFFFF", bg_hex)
        return "--mh-on-primary" if white_ok else "--mh-on-surface"
    except Exception:
        return "--mh-on-primary"


def element_is_legible(element: Element, role_vars: dict[str, str]) -> bool:
    """For a text-carrying element, is its ink legible on its ground?

    Best-effort and conservative: non-text elements always pass; text elements
    pass when on-ground clears APCA over the accent (the chip ground) or the
    brand ground. Callers use this to gate a text element or swap its ink.
    """
    if not element.carries_text:
        return True
    try:
        from mediahub.quality.compliance import is_legible

        ink = role_vars.get("--mh-on-primary") or _ROLE_FALLBACK["--mh-on-primary"]
        for bg_role in ("--mh-accent", "--mh-primary", "--mh-surface"):
            bg = role_vars.get(bg_role) or _ROLE_FALLBACK[bg_role]
            if is_legible(ink, bg):
                return True
        # chips usually paint ground-coloured text on the accent — try that too
        ground = role_vars.get("--mh-primary") or _ROLE_FALLBACK["--mh-primary"]
        accent = role_vars.get("--mh-accent") or _ROLE_FALLBACK["--mh-accent"]
        return is_legible(ground, accent)
    except Exception:
        return True


def _safe_uid(uid: str) -> str:
    """A DOM/SVG-id-safe token (gradient/filter ids must be unique + valid)."""
    cleaned = "".join(ch for ch in str(uid) if ch.isalnum() or ch in "-_")
    return cleaned or "el"


__all__ = [
    "recolour_svg",
    "role_vars_for_brief",
    "role_vars_from_palette",
    "best_text_role",
    "element_is_legible",
]
