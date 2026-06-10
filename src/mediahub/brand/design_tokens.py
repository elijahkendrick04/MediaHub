"""Generation DesignTokens contract (Gen Engine v2, SEQ-0 — thesis §5.3).

The Adaptive Theming Engine already owns colour *derivation* (DTCG
``derived_palette``, MD3 roles, APCA/ΔE gates). This module is the thin,
additive layer on top that the **generation** surfaces consume: one dict per
profile that bundles

* the resolved ``--mh-*`` colour **roles** the v2 renderer actually paints,
  each with a ``brightness`` tag, a ``when_to_use`` sentence an LLM can read,
  and the APCA evidence number backing it;
* the club's **logo lockups** typed by ``form`` (icon / full_horizontal /
  full_stacked / mono) and ``theme`` (light / dark mark), derived honestly
  from what the club actually uploaded — never invented;
* a typed **type pairing** (headline / body / numeral families);
* a structured **voice** profile (approved caption examples, the AI-tell
  ban-list, emoji policy) that the caption store populates over time.

The flat ``BrandKit.primary_colour`` / ``secondary_colour`` / ``accent_colour``
fields stay authoritative and are mirrored under ``flat`` — this contract is
additive, nothing existing changes shape.

Resolution reuses the renderer's own role mapper (``render._mh_role_vars``)
so the contract always describes exactly what a v2 card will paint; there is
no second colour pipeline to drift.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

log = logging.getLogger(__name__)

# The role vocabulary is owned by the archetype registry (single source of
# truth shared with the design-spec director); imported lazily in
# resolve_design_tokens so this module stays import-light.

# Fallback AI-tell ban-list, used only if the caption module (which owns the
# canonical list) cannot be imported in a minimal environment.
_FALLBACK_BANNED = (
    "delve",
    "elevate",
    "in the world of",
    "game-changer",
    "unleash",
)

# Static role guidance. The hex + APCA numbers are computed per profile; these
# sentences tell the design-spec director what each role is FOR.
_ROLE_GUIDE: dict[str, str] = {
    "primary": (
        "The brand ground — the full-bleed canvas fill most archetypes paint "
        "behind the composition. Headline text on it uses on_primary."
    ),
    "secondary": (
        "Supporting brand colour for rules, secondary panels and duotones. "
        "Not contrast-guaranteed as text on the ground — use accent for that."
    ),
    "surface": (
        "A deep brand-tinted panel ground for editorial archetypes and stat "
        "panels. Text on it uses on_surface."
    ),
    "accent": (
        "Kickers, result chips, underlines and decorative accents. "
        "APCA-gated against the ground, so it is the safe choice for any "
        "small emphasis element that must read."
    ),
    "on_primary": "Text and icons painted directly on the primary ground.",
    "on_surface": "Text and icons painted on the surface panel colour.",
}

# Lockup form vocabulary — kept in lock-step with
# creative_brief.design_spec.LOGO_LOCKUPS (mono_light/mono_dark collapse to a
# ``mono`` form + a ``theme``).
_FORMS = ("icon", "full_horizontal", "full_stacked", "mono")

_HEX_IN_TEXT = re.compile(r"#[0-9A-Fa-f]{6}\b")


def _infer_form(meta: dict) -> str:
    """Best-effort lockup form from the operator's own label/filename.

    Deterministic keyword match; anything unrecognised is an ``icon`` (the
    safe, always-renderable form). Never guesses beyond the words present.
    """
    text = " ".join(
        str(meta.get(k) or "") for k in ("label", "original_filename", "ai_description")
    ).lower()
    if any(w in text for w in ("horizontal", "wide", "landscape", "wordmark")):
        return "full_horizontal"
    if any(w in text for w in ("stacked", "vertical", "portrait lockup")):
        return "full_stacked"
    if any(w in text for w in ("mono", "monochrome", "one colour", "one-color", "single colour")):
        return "mono"
    return "icon"


def _mark_theme(dominant_hex: Optional[str]) -> str:
    """``light`` / ``dark`` appearance of the mark itself, or ``unknown``.

    A *light* mark suits dark grounds and vice versa; the selector in
    ``theming.logo_chip`` uses this (plus the APCA/ΔE gates) to pick.
    """
    if not dominant_hex:
        return "unknown"
    try:
        from mediahub.graphic_renderer.render import _rel_luminance

        return "light" if _rel_luminance(dominant_hex) > 0.42 else "dark"
    except Exception:
        return "unknown"


def _svg_dominant_hex(logo_svg: Optional[str]) -> Optional[str]:
    """First 6-digit hex literal in an inline SVG, if any. Best-effort only —
    absence is honest (``theme: unknown``), never a guessed colour."""
    if not logo_svg or not isinstance(logo_svg, str):
        return None
    m = _HEX_IN_TEXT.search(logo_svg)
    return m.group(0) if m else None


def _logo_lockups(brand_kit, profile) -> list[dict]:
    """Every lockup the club actually has, typed by form + theme.

    Sources, in order: the inline ``BrandKit.logo_svg`` (the mark the renderer
    uses today) and the profile's uploaded logo library (``brand_logos`` metas,
    which carry the vision pass's ``ai_dominant_colours``).
    """
    lockups: list[dict] = []
    svg = getattr(brand_kit, "logo_svg", None)
    if svg:
        dom = _svg_dominant_hex(svg)
        lockups.append(
            {
                "form": "icon",
                "theme": _mark_theme(dom),
                "source": "brand_kit_svg",
                "dominant_hex": dom,
                "label": "inline brand mark",
            }
        )
    for meta in getattr(profile, "brand_logos", None) or []:
        if not isinstance(meta, dict):
            continue
        colours = meta.get("ai_dominant_colours") or []
        dom = colours[0] if colours and isinstance(colours[0], str) else None
        lockups.append(
            {
                "form": _infer_form(meta),
                "theme": _mark_theme(dom),
                "source": "logo_library",
                "logo_id": meta.get("logo_id"),
                "dominant_hex": dom,
                "label": (meta.get("label") or meta.get("original_filename") or "")[:80],
            }
        )
    return lockups


def _voice_profile(profile_id: str, tone: str) -> dict:
    """Structured voice profile for the director + caption prompts.

    ``examples`` come from the club's approved-caption store (capped at 5,
    same cap the few-shot injection uses); the ban-list is the canonical
    AI-tell list from the caption module. Both degrade to honest empties —
    a club with no history simply has no examples yet.
    """
    examples: list[str] = []
    try:
        from mediahub.web.caption_examples import load_examples

        examples = list(load_examples(profile_id))[:5]
    except Exception:
        examples = []
    try:
        from mediahub.web.ai_caption import AI_TELL_BAN_LIST

        banned = sorted(AI_TELL_BAN_LIST)
    except Exception:
        banned = list(_FALLBACK_BANNED)
    return {
        "tone": tone,
        "examples": examples,
        "banned_phrases": banned,
        "emoji_policy": "sparing",
    }


def _type_pairing(pairing_id: str = "anton-inter") -> dict:
    """Typed font pairing. Families mirror the renderer's @font-face stacks
    (self-hosted — see layouts/_shared.css); the numeral face is the fixed
    result-chip font every layout shares."""
    headline = {
        "anton-inter": "Anton",
        "bebas-grotesk": "Bebas Neue",
        "druk-inter": "Anton",
        "bowlby-inter": "Bowlby One",
        "archivo-inter": "Anton",
        "oswald-inter": "Anton",
    }.get((pairing_id or "").lower(), "Anton")
    body = "Space Grotesk" if pairing_id == "bebas-grotesk" else "Inter"
    return {
        "pairing": pairing_id or "anton-inter",
        "headline_family": headline,
        "body_family": body,
        "numeral_family": "JetBrains Mono",
    }


def resolve_design_tokens(profile_id: str, *, brand_kit=None) -> dict:
    """The full generation DesignTokens contract for one profile.

    Pass ``brand_kit`` to resolve a run-scoped kit that never hit the profile
    store (the per-run upload flow); otherwise the profile's saved kit loads.
    Deterministic, no LLM, no network — safe to call per render.
    """
    profile = None
    tone = "warm-club"
    if brand_kit is None:
        try:
            from mediahub.brand.store import load_brand

            brand_kit, tone_enum, _templates = load_brand(profile_id)
            tone = getattr(tone_enum, "value", str(tone_enum))
        except Exception:
            from mediahub.brand.kit import BrandKit

            brand_kit = BrandKit.generic_default()
    try:
        from mediahub.web.club_profile import load_profile

        profile = load_profile(profile_id)
    except Exception:
        profile = None

    # Resolve the exact role hexes the v2 renderer paints (one pipeline, no
    # drift) and the APCA evidence the compliance gate scores them by.
    from mediahub.graphic_renderer.render import _mh_role_vars, _rel_luminance
    from mediahub.graphic_renderer.archetypes import TOKEN_ROLES
    from mediahub.theming.contrast import apca

    palette = {
        "primary": getattr(brand_kit, "primary_colour", None) or "#0A2540",
        "secondary": getattr(brand_kit, "secondary_colour", None) or "#000000",
        "accent": getattr(brand_kit, "accent_colour", None) or "",
    }
    mh = _mh_role_vars(palette, brand_kit)
    ground = mh["--mh-primary"]

    roles: dict[str, dict[str, Any]] = {}
    for role in TOKEN_ROLES:
        hex_value = mh.get("--mh-" + role.replace("_", "-"), "")
        if not (isinstance(hex_value, str) and hex_value.startswith("#")):
            continue
        try:
            brightness = "light" if _rel_luminance(hex_value) > 0.42 else "dark"
        except Exception:
            brightness = "dark"
        try:
            lc = round(abs(apca(hex_value, ground)), 1)
        except Exception:
            lc = 0.0
        roles[role] = {
            "hex": hex_value,
            "brightness": brightness,
            "when_to_use": _ROLE_GUIDE.get(role, "A resolved brand colour role."),
            "apca_vs_ground": lc,
        }

    return {
        "version": 1,
        "profile_id": profile_id,
        "display_name": getattr(brand_kit, "display_name", "") or profile_id,
        # Back-compat aliases: the flat BrandKit fields stay authoritative.
        "flat": {
            "primary_colour": getattr(brand_kit, "primary_colour", None),
            "secondary_colour": getattr(brand_kit, "secondary_colour", None),
            "accent_colour": getattr(brand_kit, "accent_colour", None),
        },
        "roles": roles,
        "logo_lockups": _logo_lockups(brand_kit, profile),
        "type": _type_pairing(),
        "voice": _voice_profile(profile_id, tone),
    }


__all__ = ["resolve_design_tokens"]
