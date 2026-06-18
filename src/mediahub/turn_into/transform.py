"""turn_into v2 — the format transformer ("turn *this* into *that*", P6.1).

The shipped ``turn_into`` package turns one meet into a fixed set of artefacts.
This module generalises the idea into the **Magic-Switch** behaviour the
roadmap calls for: take an *approved design* (a persisted ``CreativeBrief``) and
re-target it to any catalogue :class:`FormatSpec` — a different per-channel
size, a poster, a certificate — by **re-laying-out** the content for the new
canvas rather than naively scaling pixels.

What is preserved vs. re-decided:

* **Preserved (the approved creative decisions):** the palette and any
  APCA-gated colour-role assignment, the headline / hook, the text layers and
  measured hero stats, the chosen photo, tone and confidence label. A transform
  must not silently rewrite the copy the human approved.
* **Re-decided (what the new canvas demands):** the *archetype* (composition),
  because a layout that sings at 9:16 is wrong at 16:9. That single judgement
  goes through the design-spec director (Gemini→Anthropic via ``ai_core``),
  constrained to the archetypes that suit the target aspect; when no provider
  is configured the deterministic per-aspect picker is the honest floor — never
  a fabricated layout. This is exactly the Tier B pattern ``creative_brief``
  already uses, reused here.

The transformer returns a new brief; it does not render. The web layer threads
the new brief + the format's ``size`` into the existing
``graphic_renderer.render_brief`` (which already adapts the composition to the
aspect), so there is no second rendering engine.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Optional, Union

from mediahub.club_platform.format_catalog import FormatSpec, format_for, preferred_archetypes
from mediahub.creative_brief.generator import CreativeBrief

log = logging.getLogger(__name__)


@dataclass
class TransformResult:
    """The outcome of re-targeting one design to one format."""

    brief: CreativeBrief
    format: FormatSpec
    source_archetype: str
    target_archetype: str
    rationale: str
    ai_directed: bool

    def to_dict(self) -> dict:
        return {
            "brief": self.brief.to_dict(),
            "format": self.format.to_dict(),
            "source_archetype": self.source_archetype,
            "target_archetype": self.target_archetype,
            "rationale": self.rationale,
            "ai_directed": self.ai_directed,
        }


def _coerce_brief(source: Union[CreativeBrief, dict]) -> Optional[CreativeBrief]:
    """A *copy* of the source brief (never mutate the caller's object)."""
    if isinstance(source, CreativeBrief):
        return CreativeBrief.from_dict(source.to_dict())
    if isinstance(source, dict):
        return CreativeBrief.from_dict(source)
    return None


def _synth_content_item(brief: CreativeBrief) -> dict:
    """Reconstruct a minimal content_item from the brief for the director."""
    layers = brief.text_layers or {}
    return {
        "id": brief.content_item_id,
        "swim_id": brief.content_item_id,
        "achievement": {
            "swimmer_name": layers.get("athlete_full_name") or "",
            "event": layers.get("event_name") or "",
            "time": layers.get("result_value") or "",
            "headline": brief.primary_hook or "",
        },
        "post_angle": "",
    }


def _seed_from(key: str) -> int:
    """Stable non-negative int from a key (same card → same pick)."""
    if not key:
        return 0
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16)


def _pick_from(options: list[str], seed: int, avoid: set[str]) -> Optional[str]:
    """Deterministically pick an archetype from ``options``, skipping ``avoid``.

    Walks the (order-preserved) options from a seeded offset so the same card
    always lands on the same layout for a given format, while different cards
    spread across the set. Falls back to ignoring ``avoid`` only if it would
    otherwise eliminate every option.
    """
    if not options:
        return None
    candidates = [o for o in options if o not in avoid] or list(options)
    return candidates[seed % len(candidates)]


def _live_archetypes() -> list[str]:
    try:
        from mediahub.graphic_renderer import archetypes as _a

        return list(_a.list_archetypes())
    except Exception:  # pragma: no cover - renderer always present in-repo
        return []


def _direct_archetype(
    *,
    content_item: dict,
    brand_kit,
    options: list[str],
    target_format: FormatSpec,
    avoid_recent: list[str],
) -> Optional[str]:
    """Ask the design-spec director for an aspect-appropriate archetype.

    Constrained to ``options`` (the format's suitable archetypes). Returns the
    chosen archetype name, or ``None`` when no provider is configured / the call
    fails — the caller then uses the deterministic picker.
    """
    if not options:
        return None
    try:
        from mediahub.creative_brief.ai_director import ai_design_spec
        from mediahub.graphic_renderer import archetypes as _a

        spec = ai_design_spec(
            content_item=content_item,
            brand_kit=brand_kit,
            archetypes=options,
            token_roles=list(_a.TOKEN_ROLES),
            angle=(
                f"re-target this approved design to a {target_format.title} "
                f"({target_format.width}×{target_format.height}, "
                f"{target_format.orientation}) canvas — choose the composition "
                f"that suits the new shape"
            ),
            recent_archetypes=avoid_recent,
        )
    except Exception as e:  # pragma: no cover - defensive
        log.debug("transform: director call failed: %s", e)
        return None
    if spec is None:
        return None
    # normalise() guarantees spec.archetype ∈ options (we passed options as the
    # archetype vocabulary), so it is always a suitable, renderable choice.
    return spec.archetype


def transform_design(
    *,
    source_brief: Union[CreativeBrief, dict],
    target_format: Union[FormatSpec, str],
    brand_kit=None,
    content_item: Optional[dict] = None,
    use_ai_director: bool = False,
    recent_archetypes: Optional[list[str]] = None,
    deterministic: bool = False,
) -> TransformResult:
    """Re-target an approved design to ``target_format`` (the Magic-Switch).

    Returns a :class:`TransformResult` whose ``brief`` is a *new* brief
    (the source is never mutated) carrying the approved copy/palette/photo but a
    composition re-chosen for the new canvas. ``use_ai_director`` (and a
    configured provider) routes the archetype choice through the design-spec
    director; otherwise the deterministic per-aspect picker is the floor.

    Raises ``ValueError`` for an unknown format slug or an unparseable brief.
    """
    spec = format_for(target_format) if isinstance(target_format, str) else target_format
    if not isinstance(spec, FormatSpec):
        raise ValueError(f"unknown target format: {target_format!r}")

    brief = _coerce_brief(source_brief)
    if brief is None:
        raise ValueError("source_brief is not a CreativeBrief or a valid brief dict")

    source_archetype = brief.layout_template or ""
    options = preferred_archetypes(spec, available=_live_archetypes())

    ai_directed = False
    target_archetype = source_archetype

    if options:
        # Keep the approved layout only if it already suits the new aspect;
        # otherwise re-lay-out for the canvas.
        if source_archetype in options:
            target_archetype = source_archetype
        else:
            item = content_item or _synth_content_item(brief)
            chosen = None
            if use_ai_director and not deterministic:
                chosen = _direct_archetype(
                    content_item=item,
                    brand_kit=brand_kit,
                    options=options,
                    target_format=spec,
                    avoid_recent=[source_archetype] + list(recent_archetypes or []),
                )
                ai_directed = chosen is not None
            if chosen is None:
                avoid = {source_archetype} | {a for a in (recent_archetypes or [])}
                chosen = _pick_from(options, _seed_from(brief.content_item_id), avoid)
            target_archetype = chosen or source_archetype

    # Apply the re-layout, preserving every approved creative decision.
    brief.layout_template = target_archetype
    # Lead the format priority with the target so any multi-format caller and
    # the explainability trail agree on the intended output size.
    rest = [f for f in (brief.format_priority or []) if f != spec.render_name]
    brief.format_priority = [spec.render_name] + rest
    if ai_directed:
        brief.ai_directed = True

    rationale = _build_rationale(spec, source_archetype, target_archetype)
    brief.why_this_design = rationale

    # Re-stamp the dedupe/audit signature off the new axes.
    try:
        from mediahub.creative_brief.generator import _stamp_signature

        _stamp_signature(brief)
    except Exception:  # pragma: no cover - signature is best-effort
        pass

    return TransformResult(
        brief=brief,
        format=spec,
        source_archetype=source_archetype,
        target_archetype=target_archetype,
        rationale=rationale,
        ai_directed=ai_directed,
    )


def blank_brief_for_format(
    target_format: Union[FormatSpec, str],
    brand_kit=None,
    *,
    headline: str = "",
    subhead: str = "",
    profile_id: str = "",
    content_item_id: str = "",
) -> CreativeBrief:
    """The blank-start escape hatch — a minimal on-brand brief for a format.

    Seeds palette + club name from the ``BrandKit`` and picks a deterministic
    aspect-appropriate archetype, so "start from blank" still lands on a
    branded, renderable canvas rather than an empty one. Manual element editing
    on top of this is the P6.24 pro-editor's job.
    """
    spec = format_for(target_format) if isinstance(target_format, str) else target_format
    if not isinstance(spec, FormatSpec):
        raise ValueError(f"unknown target format: {target_format!r}")

    import uuid

    options = preferred_archetypes(spec, available=_live_archetypes())
    cid = content_item_id or ("blank_" + uuid.uuid4().hex[:8])
    archetype = _pick_from(options, _seed_from(cid), set()) or (options[0] if options else "")

    primary = getattr(brand_kit, "primary_colour", None) or "#0A2540"
    secondary = getattr(brand_kit, "secondary_colour", None) or "#101820"
    accent = getattr(brand_kit, "accent_colour", None) or "#FFFFFF"
    club_full = getattr(brand_kit, "display_name", "") or ""
    club_short = getattr(brand_kit, "short_name", None) or club_full

    layers: dict[str, str] = {"club_full": club_full, "club_short": club_short}
    if headline:
        layers["headline_line1"] = headline
        layers["primary_hook"] = headline
    if subhead:
        layers["headline_line2"] = subhead

    brief = CreativeBrief(
        id="cb_" + uuid.uuid4().hex[:12],
        content_item_id=cid,
        profile_id=profile_id,
        achievement_summary="",
        objective=f"Blank {spec.title} started from brand tokens.",
        primary_hook=headline or "",
        confidence_label="",
        tone=getattr(brand_kit, "tone", "") or "warm-club",
        layout_template=archetype,
        inspiration_pattern_id="",
        image_treatment="no photo, text-led layout",
        text_hierarchy=[],
        brand_instructions=(
            f"Use {primary} as the dominant ground colour, {secondary} for surfaces, "
            f"and {accent} for accents. Club: {club_full}."
        ),
        sponsor_instructions=None,
        sourced_asset_ids=[],
        safety_notes=[],
        why_this_design=f"Blank {spec.title} seeded from {club_full or 'the club'}'s brand tokens.",
        text_layers=layers,
        palette={"primary": primary, "secondary": secondary, "accent": accent},
        format_priority=[spec.render_name],
        photo_treatment="no-photo",
    )
    try:
        from mediahub.creative_brief.generator import _stamp_signature

        _stamp_signature(brief)
    except Exception:  # pragma: no cover
        pass
    return brief


def _build_rationale(spec: FormatSpec, src: str, tgt: str) -> str:
    """One human sentence explaining the re-target, for the explainability UI."""
    where = f"{spec.title} — {spec.width}×{spec.height}px ({spec.orientation})"
    kept = "Kept the approved palette, headline and stats"
    if src and tgt and src != tgt:
        layout = (
            f"re-laid the composition from {src.replace('_', ' ')} to "
            f"{tgt.replace('_', ' ')} so it suits a {spec.orientation} canvas"
        )
    elif tgt:
        layout = f"the {tgt.replace('_', ' ')} layout already suits a {spec.orientation} canvas"
    else:
        layout = "kept the existing layout"
    return f"Re-targeted to {where}. {kept}; {layout}."


__all__ = ["TransformResult", "transform_design", "blank_brief_for_format"]
