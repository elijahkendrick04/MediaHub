"""Generate a CreativeBrief that drives the renderer.

Inputs:
  - content_item     dict from content_pack
  - evaluation       EvaluationResult from media_requirements
  - brand_kit        BrandKit
  - voice_profile    VoiceProfile or None
  - inspiration_pat  pattern dict from mediahub.inspiration.pattern_library

Output: CreativeBrief dataclass with everything the renderer needs, plus a
human-readable "why this design" explanation.

Variation surface (Gen Engine v2)
---------------------------------
Structural variety comes from the v2 archetype library: the design-spec
director (``ai_director.ai_design_spec``) picks the archetype + emphasis +
hook for the moment when a provider is configured, and the deterministic
seeded picker (``graphic_renderer.archetypes``) is the no-LLM floor. The
brief still carries the v1 styling axes (background/accent/typography/
composition/photo treatment) for the v1 template path behind the
``MEDIAHUB_GEN_V2=0`` kill switch; an explicit ``VariationProfile`` is the
only way to set them now — the old random/menu-pick permutation engine was
removed (SEQ-3 cutover).
"""

from __future__ import annotations

import hashlib
import json as _json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mediahub.inspiration.pattern_library import best_pattern_for, patterns_for_post_angle, PATTERNS
from mediahub.media_ai import is_available as _llm_available

log = logging.getLogger(__name__)

# Human-readable phrases for the graded photo treatments (design_spec
# PHOTO_TREATMENTS minus the clean "cutout" default). Shared by the
# VariationProfile path in ``generate()`` and ``apply_design_spec`` so the
# brief's ``image_treatment`` phrase always matches its ``photo_treatment``.
_TREATMENT_PHRASES: dict[str, str] = {
    "vignette": "cutout with vignette glow",
    "duotone": "duotone-tinted cutout in brand colour",
    "halftone": "halftone-dot cutout treatment",
}

# M9 (STILLS-3): mood → server-side PhotoRecipe preset. Every brief carries a
# deliberate grade — a keyed mood maps to its look, and the neutral default
# resolves through the operator's MEDIAHUB_PHOTO_ADJUST preset (the historic
# global control keeps meaning) before falling to "natural". The renderer's
# ``recipe_for`` precedence (explicit brief value first) is unchanged; legacy
# persisted briefs without the field still fall through to the env default.
_MOOD_PHOTO_RECIPES: dict[str, str] = {
    "celebratory": "punchy",
    "explosive": "punchy",
    "electric": "punchy",
    "triumphant": "punchy",
    "stoic": "editorial",
    "precise": "editorial",
    "minimal": "editorial",
    "calm": "soft",
    "warm": "soft",
}
# E1 (Canva gap analysis): briefs without a curated mood look get the MEASURED
# auto-enhance (photo_adjust.auto_recipe — corrects only what each photo's
# statistics justify) instead of the old blind fixed "natural" nudge. Healthy
# photos pass through byte-identical; mood-keyed curated looks are unchanged.
_DEFAULT_PHOTO_RECIPE = "auto"


def _photo_recipe_for_mood(mood: str) -> str:
    keyed = _MOOD_PHOTO_RECIPES.get((mood or "").strip().lower())
    if keyed:
        return keyed
    try:
        from mediahub.graphic_renderer.photo_adjust import ENV_VAR, get_preset

        env_name = os.environ.get(ENV_VAR, "").strip().lower()
        if env_name and get_preset(env_name) is not None:
            return env_name
    except Exception:
        pass
    return _DEFAULT_PHOTO_RECIPE


# ---------------------------------------------------------------------------
# Multi-axis variation profile
# ---------------------------------------------------------------------------
#
# Every visual is characterised by a profile across these axes. The renderer
# reads them off the brief at fill-time (string-keyed; the renderer owns the
# vocabulary of patterns/decorations/typography it can paint). The old
# module-level enum tuples that drove the random/menu-pick permutation engine
# were removed with that engine (SEQ-3 cutover) — a profile is now always an
# explicit, caller-authored direction, never a random tuple.


@dataclass
class VariationProfile:
    """An explicit multi-axis direction for one visual.

    Used by caption-card flows and tests that need to pin a precise v1
    treatment (layout family, background pattern, typography, photo
    handling). Under Gen Engine v2 the archetype carries the structural
    variety; this profile remains the explicit-direction input for the
    v1 template path.
    """

    layout_family: str = ""  # e.g. "individual_hero"
    palette_role_index: int = 0  # 0..5 (which permutation)
    background_style: str = "water"  # renderer background-pattern key
    accent_style: str = "brackets"  # renderer accent-decoration key
    typography_pair: str = "anton-inter"  # renderer typography-pair key
    composition: str = "right"  # cutout placement key
    photo_treatment: str = "cutout"  # photo-processing key
    decoration_strength: float = 0.5  # 0..1, intensity of accent
    hook_phrase: str = ""  # specific hook copy (caller-supplied)
    mood: str = ""  # short mood word (caller-supplied)

    def to_dict(self) -> dict:
        return asdict(self)

    def signature(self) -> str:
        """Short string that uniquely identifies this profile combination.

        Used by the verification script to assert distinctness across N
        regenerations.
        """
        return (
            f"{self.layout_family}|{self.palette_role_index}|{self.background_style}"
            f"|{self.accent_style}|{self.typography_pair}|{self.composition}"
            f"|{self.photo_treatment}|{self.hook_phrase[:40]}"
        )


@dataclass
class CreativeBrief:
    id: str
    content_item_id: str
    profile_id: str
    achievement_summary: str
    objective: str
    primary_hook: str  # the main message/headline
    confidence_label: str  # "NEW PB" / "LIKELY PB" / "GOLD" / etc.
    tone: str  # e.g. "data_led", "hype", "warm_club"
    layout_template: str  # maps to graphic_renderer/layouts/<template>.html
    inspiration_pattern_id: str
    image_treatment: str
    text_hierarchy: list[str]
    brand_instructions: str
    sponsor_instructions: Optional[str]
    sourced_asset_ids: list[str]
    safety_notes: list[str]
    why_this_design: str
    text_layers: dict[str, str]  # actual text values keyed by layer name
    palette: dict[str, str]  # primary/secondary/accent
    format_priority: list[str]
    # --- new variation fields (additive; default-safe for legacy callers) ---
    background_style: str = "water"
    accent_style: str = "brackets"
    typography_pair: str = "anton-inter"
    composition: str = "right"
    photo_treatment: str = "cutout"
    decoration_strength: float = 0.5
    mood: str = ""  # one or two mood words
    ai_directed: bool = False  # True when AI chose the direction
    variation_signature: str = ""  # short signature for dedup/audit
    # Gen Engine v2 style pack (additive; default-safe). The decorative lever
    # bundle (ground × texture × accent-geometry × density) the renderer layers
    # over the chosen archetype — see ``graphic_renderer.style_packs``. Empty =
    # the bare pack (undecorated), so legacy/flag-off callers are byte-identical.
    style_pack: str = ""
    # --- Gen Engine v2 Tier B (additive; default-safe for legacy callers) ---
    # The measured emphasis facts this card can honestly lead with, keyed by
    # design_spec.STAT_KEYS ("pb_delta" → "−0.42s on PB"). Only facts the
    # detectors actually measured appear; the design-spec director picks among
    # them and the motion render reuses them.
    hero_stat_options: dict[str, str] = field(default_factory=dict)
    # The director's colour-role assignment (slot → token role name, e.g.
    # {"ground": "secondary"}). The renderer honours it ONLY when the
    # reassigned set clears the APCA compliance gate; empty dict = Tier A
    # brand-default roles.
    colour_role_assignment: dict[str, str] = field(default_factory=dict)
    # The director's motion language for this card (design_spec.MOTION_INTENTS,
    # e.g. "kinetic_type"). Consumed by the Remotion compositions; "" lets the
    # motion render fall back to its mood/seed-driven default programme.
    motion_intent: str = ""
    # 1.9 — per-slot text effects (slot -> effect, e.g. {"headline": "neon"}).
    # design_spec.TEXT_EFFECT_SLOTS × TEXT_EFFECTS; consumed by the still renderer
    # (graphic_renderer.text_effects), APCA-policed at apply time. Empty (the
    # default) means no effects, so every legacy card renders byte-identically.
    text_effects: dict[str, str] = field(default_factory=dict)
    # 1.10 — brand-token-recolourable library elements painted on this card. Each
    # entry is an ``elements.models.ElementPlacement`` dict (element_id + position
    # + scale + rotation + opacity); the ``sprint_hooks/elements`` hook resolves
    # and recolours them to the card's own --mh-* roles. Empty (the default) →
    # the card renders byte-identically (the additive, opt-in sprint-hook contract).
    elements: list[dict] = field(default_factory=list)
    # M9 (STILLS-3) — the server-side PhotoRecipe preset baked into this card's
    # photo pixels (``graphic_renderer.photo_adjust.PRESETS``). Set from the
    # card's mood by generate()/apply_design_spec; "" (legacy briefs) falls
    # through to the operator env default, keeping old persisted briefs stable.
    photo_adjust: str = ""
    # M10 (STILLS-4b) — the director's crop intent (design_spec.CROP_INTENTS),
    # executed deterministically by the renderer as --mh-photo-pos/scale
    # adjustments. "" (the default) keeps the pure saliency crop.
    crop_intent: str = ""
    # M8 (STILLS-2) — how the chosen archetype consumes the athlete photo:
    # "photo" (the original photograph) or "cutout" (background-removed
    # subject). Stamped from graphic_renderer.archetypes.photo_mode() when a v2
    # archetype is chosen, so the motion render can mirror the same source.
    photo_mode: str = ""
    # M11 (STILLS-5) — the director's validated secondary stats (STAT_KEY names,
    # each verified present in hero_stat_options). The data-led archetypes
    # render them as the {{STAT_CHIPS}} row; empty (the default) collapses.
    secondary_stats: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    version: int = 2

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Optional["CreativeBrief"]:
        """Rebuild a brief from its persisted ``to_dict()`` form.

        Unknown keys are dropped (older/newer shapes load cleanly); returns
        ``None`` when required fields are missing so callers can fall back.
        """
        if not isinstance(data, dict):
            return None
        try:
            from dataclasses import fields as _dc_fields

            known = {f.name for f in _dc_fields(cls)}
            return cls(**{k: v for k, v in data.items() if k in known})
        except (TypeError, ValueError):
            return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate(
    content_item: dict,
    evaluation,
    brand_kit,
    *,
    voice_profile=None,
    profile_id: str = "",
    meet_name: str = "",
    venue_name: str = "",
    sponsor: Optional[dict] = None,
    variation_seed: Optional[int] = None,
    variation_profile: Optional[VariationProfile] = None,
    use_ai_director: bool = False,
    recent_signatures: Optional[list[str]] = None,
    recent_hooks: Optional[list[str]] = None,
    allowed_families: Optional[list[str]] = None,
    photo_facts: Optional[dict] = None,
) -> CreativeBrief:
    """Build a CreativeBrief. Pure function — never reaches network unless
    LLM is available; falls back to deterministic defaults otherwise.

    ``photo_facts`` (M7 / STILLS-1): what the caller resolved about this card's
    photo BEFORE direction — ``{"has_photo": bool, "asset_type": str,
    "orientation": str, "person_photo_count": int}``. When provided, the v2
    archetype choice is photo-aware: a photo-less card picks from the type-led
    set (never a photo stage), a photo-backed card from the photo-led set, and
    the AI director's prompt carries the facts. ``None`` (every legacy caller)
    keeps the photo-blind pick byte-identical.

    ``variation_seed`` controls deterministic perturbation of the layout,
    palette role mapping, image treatment, and headline phrasing. ``None``
    (not supplied — the bulk-pack / fresh-regenerate shape) lets the v2
    archetype floor derive a stable per-card seed from the card id, rotated
    past the card's recent archetypes. An **explicit** integer — including
    ``0`` — is an exact, reproducible pick (the ``?stable`` /
    ``?variation_seed=N`` contract). For the legacy axes: ``0`` keeps the
    default look, ``1`` inverts colour roles, ``2`` swaps layout family,
    ``3`` forces a text-led / no-photo treatment.

    ``variation_profile`` (optional, preferred): a fully-specified
    ``VariationProfile`` that overrides seed-based logic. When provided
    the brief follows the profile exactly — this is the path the
    regenerate route uses to drive a fresh random or AI-chosen
    direction on every call.

    ``use_ai_director``: when True and a provider is configured, asks the
    AI to choose a creative direction (layout family, mood, hook, accent
    style) before building the brief. Falls back silently to the
    seed/profile path when the AI is unavailable.

    ``recent_signatures`` / ``recent_hooks``: short audit trails the
    caller can pass so the AI (or the random profile picker) avoids
    repeating the last few attempts for this card.
    """

    ach = content_item.get("achievement") or {}
    angle = content_item.get("post_angle") or ach.get("post_angle") or "recap_mention"

    # Pick layout
    fmt_hint = "feed_portrait"
    family_hint = evaluation.suggested_layout if evaluation else None
    pattern = best_pattern_for(angle, format_hint=fmt_hint, prefer_family=family_hint)

    # Gen Engine v2 state. The v2 design-spec director runs later (in the v2
    # hook below); the old closed-vocabulary menu-picker that used to run here
    # was removed with the enum-permutation engine (SEQ-3 cutover).
    try:
        from mediahub.graphic_renderer import archetypes as _v2_archetypes

        _v2_on = _v2_archetypes.is_enabled()
    except Exception:
        _v2_archetypes = None
        _v2_on = False

    # ---- Apply variation profile when provided ----
    if variation_profile is not None:
        # Profile wins: rotate to the AI/random-picked family if it differs.
        if variation_profile.layout_family and variation_profile.layout_family != pattern["family"]:
            target = next(
                (p for p in PATTERNS if p["family"] == variation_profile.layout_family),
                None,
            )
            if target is not None:
                pattern = target
    # ---- Variation seed: rotate pattern / image treatment if requested ----
    elif variation_seed and variation_seed != 0:
        pattern = _rotate_pattern_for_seed(pattern, angle, variation_seed)

    # ---- Hard layout constraint (caption-only / forced-photo graphics) ----
    # Applied AFTER every variation path so even the no-AI random fallback
    # can't land on a family outside the allowed set — otherwise a no_photo
    # request could pick a photo family, or a forced-photo request a text-led
    # one. Keeps the profile + pattern in lock-step.
    if allowed_families:
        if pattern.get("family") not in allowed_families:
            _target = next((p for p in PATTERNS if p["family"] == allowed_families[0]), None)
            if _target is not None:
                pattern = _target
        if (
            variation_profile is not None
            and getattr(variation_profile, "layout_family", None) not in allowed_families
        ):
            import dataclasses as _dc

            _is_text = pattern["family"] in _TEXT_LED_FAMILIES
            try:
                variation_profile = _dc.replace(
                    variation_profile,
                    layout_family=pattern["family"],
                    photo_treatment=(
                        "no-photo"
                        if _is_text
                        else (
                            "cutout"
                            if variation_profile.photo_treatment == "no-photo"
                            else variation_profile.photo_treatment
                        )
                    ),
                )
            except Exception:
                pass

    # Athlete + result vocabulary (sport-agnostic — we read whatever the
    # detectors put in the achievement dict)
    athlete = (
        ach.get("swimmer_name")
        or content_item.get("swimmer_name")
        or ach.get("athlete_name")
        or content_item.get("athlete_name")
        or ""
    )
    surname = athlete.split()[-1] if athlete else ""
    first = athlete.split()[0] if athlete else ""
    event = (
        ach.get("event_name")
        or ach.get("event")
        or content_item.get("event")
        or content_item.get("event_name")
        or ""
    )
    raw_facts = ach.get("raw_facts") or {}
    result = (
        ach.get("result_time")
        or ach.get("time")
        or ach.get("result")
        or ach.get("value")
        or raw_facts.get("time_str")
        or raw_facts.get("time")
        or raw_facts.get("result")
        or content_item.get("result_time")
        or content_item.get("time")
        or ""
    )
    place = (
        ach.get("place")
        or ach.get("position")
        or raw_facts.get("place")
        or raw_facts.get("position")
        or ""
    )

    # Achievement summary
    summary_bits = [evaluation.confidence_label if evaluation else angle]
    if athlete:
        summary_bits.append(athlete)
    if event:
        summary_bits.append(event)
    if result:
        summary_bits.append(str(result))
    summary = " · ".join(b for b in summary_bits if b)

    # Headline / hook
    label = evaluation.confidence_label if evaluation else "STRONG SWIM"
    if angle in ("medal_gold", "medal_silver", "medal_bronze", "medal_and_pb_combo"):
        primary_hook = label
    elif angle == "first_sub_barrier":
        primary_hook = label  # FIRST UNDER (paired with the result)
    else:
        primary_hook = label

    # Tone — read voice profile when possible
    tone = "data_led"
    if voice_profile and hasattr(voice_profile, "tone"):
        tone = getattr(voice_profile, "tone", None) or tone
    if angle in ("first_sub_barrier", "medal_gold", "medal_and_pb_combo"):
        tone = "hype"
    if angle in ("recap_mention", "weekend_recap", "weekend_in_numbers", "team_depth"):
        tone = "warm_club"

    # Build text layers (the renderer reads these directly)
    layers: dict[str, str] = {
        "achievement_label": label,
        "athlete_full_name": athlete,
        "athlete_first_name": first,
        "athlete_surname": surname,
        "event_name": event,
        "result_value": str(result),
        "place": str(place),
        "meet_name": meet_name or content_item.get("meet_name") or "",
        "venue_name": venue_name or "",
        "club_short": (
            getattr(brand_kit, "short_name", None) or getattr(brand_kit, "display_name", "") or ""
        ),
        "club_full": getattr(brand_kit, "display_name", "") or "",
        "sponsor_label": (sponsor or {}).get("name", "") if sponsor else "",
    }
    # Weekend-in-numbers extra fields
    if angle == "weekend_in_numbers":
        # caller can hand a `numbers` dict
        nums = content_item.get("numbers") or content_item.get("stats") or {}
        for k, v in nums.items():
            layers[f"stat_{k}"] = str(v)

    # v2 archetypes carry an optional emphasis slot ({{HERO_STAT}}) so the
    # composition can lead with a secondary fact. Honest by construction:
    # only facts the detectors actually measured are offered — absent data
    # leaves the slot empty and every archetype collapses it gracefully.
    _drop_raw = raw_facts.get("drop_seconds") or raw_facts.get("improvement_seconds")
    try:
        _drop = abs(float(_drop_raw)) if _drop_raw not in (None, "") else 0.0
    except (TypeError, ValueError):
        _drop = 0.0
    hero_stat_options: dict[str, str] = {}
    if _drop >= 0.01:
        hero_stat_options["pb_delta"] = f"−{_drop:.2f}s on PB"
    _place_line = _place_display(place)
    if _place_line:
        hero_stat_options["placing"] = _place_line
    # M11 (STILLS-5): every further emphasis fact the payload actually carries
    # — verified facts only, read straight off the detector payload, never
    # computed guesses. Each maps to a design_spec.STAT_KEY so the director's
    # hero_stat / secondary_stats picks resolve against real data.
    _more_stats = _payload_stat_options(ach, raw_facts)
    for _k, _v in _more_stats.items():
        hero_stat_options.setdefault(_k, _v)
    # M11: the measured previous PB, carried for the renderer's honest
    # before/after proportional bars (both endpoints must be real times).
    _prev_pb = str(
        raw_facts.get("prev_pb_time") or raw_facts.get("prev_pb_str") or ""
    ).strip() or _cs_display(raw_facts.get("prev_pb_cs"))
    if _prev_pb and str(result).strip():
        layers["prev_pb_time"] = _prev_pb
    # Deterministic default: lead with the PB drop when measured; else the
    # placing — except on medal angles, where the label already carries it.
    if "pb_delta" in hero_stat_options:
        layers["hero_stat"] = hero_stat_options["pb_delta"]
    elif "placing" in hero_stat_options and not _is_medal_angle(angle):
        layers["hero_stat"] = hero_stat_options["placing"]

    # Palette
    base_primary = getattr(brand_kit, "primary_colour", "#A30D2D")
    base_secondary = getattr(brand_kit, "secondary_colour", "#000000")
    base_accent = getattr(brand_kit, "accent_colour", None) or "#FFFFFF"
    # Profile-driven palette role index has priority over seed.
    if variation_profile is not None:
        palette = _apply_palette_seed(
            base_primary,
            base_secondary,
            base_accent,
            # palette_role_index is 0-based, the helper is 1-based
            # (seed=0 = identity), so add 1 for non-zero indices.
            variation_profile.palette_role_index + 1
            if variation_profile.palette_role_index > 0
            else 0,
        )
    else:
        # C6 (Canva gap analysis): gate the seed walk so it only lands on
        # colour-role permutations that clear the APCA gate — never on a
        # colourway the renderer would have to bounce. Byte-identical for kits
        # whose permutations are all legible (the common case).
        palette = _apply_palette_seed(
            base_primary, base_secondary, base_accent, variation_seed or 0, gate=True
        )

    # Brand / sponsor instructions
    brand_instr = (
        f"Use {palette['primary']} as the dominant ground colour. "
        f"Use {palette['secondary']} for surfaces and the brand corner. "
        f"Accent {palette['accent']} for chips and rim-light. "
        f"Place the club logo bottom-left in a respectful clear zone. "
        f"Display name: {layers['club_full']}."
    )
    sponsor_instr = None
    if sponsor and sponsor.get("name"):
        sponsor_instr = (
            f"Reserve a clean 12% bottom strip for the sponsor block. "
            f"Sponsor: {sponsor['name']}. Tagline: 'Performance supported by'."
        )

    # Safety notes
    safety: list[str] = []
    if evaluation:
        if evaluation.confidence_tier != "high":
            safety.append(f"hedged_language_{evaluation.confidence_tier}")
        for missing in evaluation.missing_optional:
            safety.append(f"missing_optional_{missing}")
        for asset_role, scored in (evaluation.matched or {}).items():
            top = scored[0] if scored else None
            if top and isinstance(top, dict) and top.get("asset_id") != "_brand_logo_":
                a = top.get("asset", {})
                if a.get("permission_status") in ("needs_approval", "internal_only"):
                    safety.append(f"permission_check_{asset_role}_{a.get('permission_status')}")
                if a.get("safe_for_minors") is False:
                    safety.append(f"minor_consent_pending_{asset_role}")
                if a.get("source_url"):
                    safety.append(f"web_sourced_{asset_role}")
    if athlete:
        safety.append("likeness_preserved_real_photo")

    # Sourced asset ids
    sourced: list[str] = []
    if evaluation:
        for role, scored in (evaluation.matched or {}).items():
            for s in scored[:1]:  # only the chosen one
                aid = s.get("asset_id")
                if aid and aid != "_brand_logo_":
                    sourced.append(aid)

    # Why-this-design — try LLM, otherwise deterministic
    why = _generate_why_this_design(angle, evaluation, pattern, athlete, summary)

    # Objective
    objective_map = {
        "confirmed_official_pb": "Celebrate a confirmed PB and drive athlete repostability.",
        "pb_improvement": "Celebrate a PB improvement and signal momentum.",
        "first_sub_barrier": "Celebrate breaking a milestone barrier in a way that's easy for non-swimmers to understand.",
        "medal_gold": "Recognise a gold-medal finish with on-brand, sponsor-safe layout.",
        "medal_silver": "Recognise a silver-medal finish.",
        "medal_bronze": "Recognise a bronze-medal finish.",
        "medal_and_pb_combo": "Highlight a medal-plus-PB double — combine medal hierarchy with PB drama.",
        "weekend_in_numbers": "Summarise the meet in a sponsor-safe, athlete-name-free recap.",
        "athlete_spotlight": "Profile an athlete with multiple achievements this weekend.",
        "meet_preview": "Build anticipation for an upcoming meet using venue and headliners.",
        "recap_mention": "Mention a strong performance without forcing a hero post.",
    }
    objective = objective_map.get(angle, "Recognise a notable performance.")

    # Headline phrasing — an explicit profile hook wins; otherwise the hook
    # stays the honest confidence label. (The old per-seed phrase tables were
    # removed with the enum-permutation engine — the v2 design-spec director
    # writes fresh hooks now, and the deterministic floor never invents copy.)
    if variation_profile is not None and variation_profile.hook_phrase:
        primary_hook = variation_profile.hook_phrase
        layers["achievement_label"] = primary_hook

    image_treatment = pattern.get("image_treatment", "")
    if variation_profile is not None:
        # Map profile.photo_treatment to a renderer-friendly phrase. The
        # renderer keys off the phrase to pick its filter pipeline.
        treatment_phrases = {
            **_TREATMENT_PHRASES,
            "no-photo": "no photo, text-led layout",
            "frame": "cutout boxed in accent frame",
            "cutout": image_treatment or "real cutout, contrast lift",
        }
        image_treatment = treatment_phrases.get(variation_profile.photo_treatment, image_treatment)
    elif variation_seed == 3:
        # Force text-led / no photo (legacy seed-3 contract)
        image_treatment = "no photo, text-led layout"

    # Resolve final variation axes for the brief. An explicit profile (tests,
    # caption-card flows) follows the profile exactly; otherwise the axes are
    # the stable v1 defaults — under v2 the archetype carries the structural
    # variety, and the v1 per-seed axis shuffle is gone with the
    # enum-permutation engine. Seed 3 keeps its legacy no-photo contract.
    if variation_profile is not None:
        bg_style = variation_profile.background_style
        accent_style = variation_profile.accent_style
        type_pair = variation_profile.typography_pair
        composition = variation_profile.composition
        photo_treatment = variation_profile.photo_treatment
        decoration_strength = variation_profile.decoration_strength
        mood = variation_profile.mood
    else:
        bg_style, accent_style, type_pair, composition = (
            "water",
            "brackets",
            "anton-inter",
            "right",
        )
        photo_treatment = "no-photo" if variation_seed == 3 else "cutout"
        decoration_strength = 0.5
        mood = ""
    ai_directed = False

    # ---- Caller-supplied display copy (caption-only content types) ----
    # Free Text / Session Update / Event Preview / Sponsor Post carry no
    # swim achievement to synthesise a headline + bullets from, so their
    # route hands us ready-made text via ``graphic_text``. Honour it
    # verbatim — it only feeds the text-led layouts, and the swim pipeline
    # never sets this key, so the achievement-driven path is unaffected.
    gt = content_item.get("graphic_text")
    if isinstance(gt, dict):
        if gt.get("headline_line1"):
            layers["headline_line1"] = str(gt["headline_line1"])
            # Honour an explicitly-empty second line. The stub flows set
            # their own line 2 ("THANK YOU" / "PREVIEW" / "UPDATE") or ""
            # for none — an empty string must reach the renderer as "no
            # second line", NOT fall through to its "RECAP" default
            # (which branded sponsor thank-yous as recaps).
            if "headline_line2" in gt:
                layers["headline_line2"] = str(gt.get("headline_line2") or "")
        elif gt.get("headline_line2"):
            layers["headline_line2"] = str(gt["headline_line2"])
        _gt_bullets = gt.get("bullets")
        if isinstance(_gt_bullets, list):
            _clean = [str(b).strip() for b in _gt_bullets if str(b).strip()]
            if _clean:
                layers["bullets"] = _clean[:4]
        # Caller-supplied stat tiles (label -> value) for the text-led
        # centre strip. Stub cards have no swim results, so without this
        # the renderer back-filled the strip with nonsense ("SPONSOR"
        # labelled RESULT, sentence counts labelled HIGHLIGHTS).
        _gt_stats = gt.get("stats")
        if isinstance(_gt_stats, dict):
            for _sk, _sv in list(_gt_stats.items())[:3]:
                _key = "".join(
                    ch if (ch.isalnum() or ch == "_") else "_" for ch in str(_sk).strip().lower()
                ).strip("_")
                if _key and str(_sv).strip():
                    layers[f"stat_{_key}"] = str(_sv).strip()
        if gt.get("primary_hook"):
            primary_hook = str(gt["primary_hook"])
            # Do NOT mirror the hook into ``achievement_label``: the stub
            # hooks ("SPONSOR"/"PREVIEW"/"LIVE"/"HIGHLIGHT") are routing
            # words, and the text-led renderer turns ``achievement_label``
            # into a stat-tile VALUE labelled "RESULT" — which rendered as
            # the live "SPONSOR / RESULT" tile. Only set the label when the
            # caller hands a dedicated display value for it.
            if gt.get("achievement_label"):
                layers["achievement_label"] = str(gt["achievement_label"])
            else:
                layers.pop("achievement_label", None)

    brief = CreativeBrief(
        id="cb_" + uuid.uuid4().hex[:12],
        content_item_id=str(
            content_item.get("id") or content_item.get("swim_id") or ach.get("swim_id") or ""
        ),
        profile_id=profile_id,
        achievement_summary=summary,
        objective=objective,
        primary_hook=primary_hook,
        confidence_label=label,
        tone=tone,
        layout_template=pattern["family"],
        inspiration_pattern_id=pattern["id"],
        image_treatment=image_treatment,
        text_hierarchy=list(pattern.get("text_hierarchy", [])),
        brand_instructions=brand_instr,
        sponsor_instructions=sponsor_instr,
        sourced_asset_ids=sourced,
        safety_notes=safety,
        why_this_design=why,
        text_layers=layers,
        palette=palette,
        format_priority=list(
            pattern.get("format_priority", ["feed_portrait", "story", "feed_square"])
        ),
        background_style=bg_style,
        accent_style=accent_style,
        typography_pair=type_pair,
        composition=composition,
        photo_treatment=photo_treatment,
        decoration_strength=decoration_strength,
        mood=mood,
        ai_directed=ai_directed,
        hero_stat_options=hero_stat_options,
        # M9: every card carries a deliberate grade keyed to its mood (natural
        # for the neutral default) — the dead grading stack, wired.
        photo_adjust=_photo_recipe_for_mood(mood),
    )
    # A caller that pins the multi-fact recap family (``allowed_families=
    # ["text_led_recap"]``) is asking for the v1 LIST layout: the card carries a
    # bullet list of several moments (an athlete-spotlight composite, a
    # caption-only Free Text / Event Preview / Sponsor stub) and no single hero
    # result. None of the v2 single-subject archetypes can render that list —
    # ``_fill_v2_archetype`` only fills one ``RESULT_VALUE``/``HERO_STAT`` — so
    # overriding to one drops every bullet and ships a blank card. Honour the
    # constraint and keep the v1 ``text_led_recap`` layout, which renders the
    # headline + bullet list + stat strip the caller actually supplied. Scoped
    # to that explicit constraint, so every normal card render is byte-identical.
    _layers_now = brief.text_layers or {}
    _pin_text_led_list = (
        "text_led_recap" in (allowed_families or [])
        and brief.layout_template == "text_led_recap"
        and bool(_layers_now.get("bullets"))
        and not str(_layers_now.get("result_value") or "").strip()
    )
    # Gen Engine v2: choose the v2 archetype for this card. Tier B (§5.4): when AI
    # direction is requested and a provider is configured, the design-spec director
    # picks the archetype + emphasis + hook FOR THIS MOMENT; otherwise (no provider
    # / failure) the deterministic seed-picker (Tier A) is the honest floor. v2 is
    # the default engine; MEDIAHUB_GEN_V2=0 keeps the legacy family byte-for-byte.
    try:
        if _v2_on and _v2_archetypes is not None and not _pin_text_led_list:
            _names = _v2_archetypes.list_archetypes()
            # M7 (STILLS-1): photo-aware art direction. With resolved photo
            # facts, the deterministic pick pool is the matching half of the
            # library — a photo-less card never lands on a photo stage, a
            # photo-backed card leads with one — and the director's catalog is
            # restricted to the type-led set when there is no photo (its "a
            # great photo → full-bleed" guidance must have a photo to point at).
            # photo_facts=None (legacy callers) keeps the photo-blind full pool.
            _pick_pool = None
            _director_names = _names
            if photo_facts is not None and _names:
                if photo_facts.get("has_photo"):
                    _pick_pool = sorted(_v2_archetypes.photo_archetypes())
                else:
                    _pick_pool = sorted(_v2_archetypes.type_archetypes())
                    _director_names = _pick_pool or _names
                _pick_pool = _pick_pool or None
            _spec = None
            if _names and use_ai_director:
                try:
                    from mediahub.creative_brief.ai_director import ai_design_spec

                    _spec = ai_design_spec(
                        content_item=content_item,
                        brand_kit=brand_kit,
                        archetypes=_director_names,
                        token_roles=list(_v2_archetypes.TOKEN_ROLES),
                        angle=angle,
                        recent_archetypes=[
                            s.split("|", 1)[0] for s in (recent_signatures or []) if s
                        ],
                        photo_facts=photo_facts,
                    )
                except Exception:
                    _spec = None
            if _spec is not None:
                apply_design_spec(brief, _spec)
            elif _names:
                if variation_seed is not None:
                    # Explicit seed (incl. 0, ?stable / re-render): exact pick,
                    # so the same seed always reproduces the same archetype.
                    _arch = _v2_archetypes.pick_archetype(variation_seed, _pick_pool)
                else:
                    # No seed supplied (bulk pack render / fresh regenerate):
                    # the roadmap floor — seed from the card id so a pack
                    # spreads across the library (stable per card, different
                    # across cards), rotated past this card's recently-used
                    # archetypes so regenerates vary without an LLM.
                    _card_key = str(
                        content_item.get("id")
                        or content_item.get("swim_id")
                        or ach.get("swim_id")
                        or ""
                    )
                    _arch = _v2_archetypes.pick_archetype_avoiding(
                        auto_variation_seed_for(_card_key or None),
                        (s.split("|", 1)[0] for s in (recent_signatures or []) if s),
                        _pick_pool,
                    )
                if _arch:
                    brief.layout_template = _arch
            # M8: stamp how the chosen archetype consumes the photo, so the
            # persisted brief (and the motion render) mirror the still's source.
            if brief.layout_template in _names:
                brief.photo_mode = _v2_archetypes.photo_mode(brief.layout_template)
    except Exception:  # never break brief generation for an optional feature
        log.debug("gen-v2 archetype selection skipped", exc_info=True)

    # Gen Engine v2 style pack: layer a deterministic decorative treatment over
    # the chosen archetype so a content pack reads as varied per-card designs,
    # not one repeated look. Mirrors the archetype floor's contract — an
    # explicit seed (incl. 0, the ?stable path) is an exact, reproducible pick;
    # no seed derives a stable-per-card pack that spreads across the pack and
    # walks past this card's recently-used packs. When the design-spec director
    # gave this card a mood, the pick is scoped to that mood's curated preset
    # bundle (``style_packs.mood_preset_packs``) so the decoration matches the
    # feeling, not just a seed; an empty/unknown mood (every legacy / non-AI
    # brief) falls straight through to the full-catalog pick — byte-identical.
    # v2-only and additive: under the kill switch the pack stays empty (bare).
    try:
        if _v2_on:
            from mediahub.graphic_renderer import style_packs as _sp

            _mood = (brief.mood or "").strip()
            if variation_seed is not None:
                _pack = _sp.pick_mood_pack(_mood, variation_seed)
            else:
                _recent_packs = [
                    s.split("sp:", 1)[1] for s in (recent_signatures or []) if "sp:" in s
                ]
                _pack_key = str(
                    content_item.get("id")
                    or content_item.get("swim_id")
                    or ach.get("swim_id")
                    or ""
                )
                _pack = _sp.pick_mood_pack_for_card(_mood, _pack_key or None, _recent_packs)
            brief.style_pack = _pack.id
    except Exception:
        log.debug("gen-v2 style-pack selection skipped", exc_info=True)

    # D5 (Canva gap analysis) — curated typography pairing. The old default
    # left every card on anton-inter; now the no-seed bulk path (the way
    # production packs render) draws a per-card pairing from the mood-keyed
    # subset of the curated quadruple table (``graphic_renderer.type_pairs``),
    # keyed to the same card id the archetype/pack walks hash — stable per
    # card, varied across a pack, still deterministic. Explicit-seed callers
    # (?variation_seed / ?stable re-renders) and explicit profiles keep their
    # pinned pair byte-identically, as does the v1 engine under the kill
    # switch.
    try:
        if _v2_on and variation_profile is None and variation_seed is None:
            from mediahub.graphic_renderer.type_pairs import pick_pair_for_card

            _pair_key = str(
                content_item.get("id") or content_item.get("swim_id") or ach.get("swim_id") or ""
            )
            brief.typography_pair = pick_pair_for_card(
                (brief.mood or "").strip(), _pair_key or None
            ).id
    except Exception:
        log.debug("gen-v2 typography-pair selection skipped", exc_info=True)

    # G1.8: a pack with the gradient_mesh ground triggers the real mesh engine.
    _sync_background_style_with_pack(brief)

    # Stamp a signature so callers can dedupe / audit recent renders.
    _stamp_signature(brief)
    return brief


def _stamp_signature(brief: CreativeBrief) -> None:
    """(Re)compute the dedupe/audit signature from the brief's final axes.

    The trailing ``sp:<pack-id>`` token records the v2 style pack so callers
    threading recent signatures (regenerate, bulk-pack) can walk both the
    archetype *and* the pack axis past recent renders. Old signatures without
    the token are simply ignored by the pack-avoidance parse.
    """
    brief.variation_signature = (
        f"{brief.layout_template}|{brief.palette.get('primary', '')}|"
        f"{brief.background_style}|{brief.accent_style}|"
        f"{brief.typography_pair}|{brief.composition}|"
        f"{brief.photo_treatment}|{brief.primary_hook[:40]}"
        f"|sp:{brief.style_pack}"
    )


def apply_design_spec(brief: CreativeBrief, spec) -> CreativeBrief:
    """Apply a validated ``DesignSpec`` onto a brief (Gen v2 Tier B §5.4).

    The single mapping between the director's contract and the brief, shared
    by ``generate()``'s per-card path and the candidate-pool builder so the
    two can never drift. Honest by construction: the hero-stat slot is filled
    only when the named fact was actually measured (``hero_stat_options``),
    and the colour-role assignment is recorded for the renderer's APCA-gated
    application — never painted unconditionally. When a pack was already
    selected, the decorative style pack is re-keyed to the spec mood's curated
    preset bundle (G1.28) so the decoration matches the chosen feeling. Re-stamps
    the variation signature so dedupe/audit reflects the applied direction.
    """
    brief.layout_template = spec.archetype
    if spec.headline_hook:
        brief.primary_hook = spec.headline_hook
    if spec.mood:
        brief.mood = spec.mood
        # M9: the director's mood re-keys the photo grade (celebratory →
        # punchy, stoic → editorial, …) so pixels match the chosen feeling.
        brief.photo_adjust = _photo_recipe_for_mood(spec.mood)
    if spec.rationale:
        brief.why_this_design = spec.rationale
    if spec.motion_intent:
        brief.motion_intent = spec.motion_intent
    # M10: carry the director's per-card photo judgement — the renderer
    # executes it as deterministic --mh-photo-pos/scale adjustments.
    brief.crop_intent = spec.crop_intent or ""
    # M8: record how the chosen archetype consumes the photo (photo vs cutout)
    # so the persisted brief and the motion twin mirror the still's source.
    try:
        from mediahub.graphic_renderer import archetypes as _arch_mod

        if spec.archetype in _arch_mod.list_archetypes():
            brief.photo_mode = _arch_mod.photo_mode(spec.archetype)
    except Exception:
        pass
    # R1.5 — the director's accent treatment IS the brief's accent axis. Both
    # surfaces execute every ACCENT_TREATMENTS token (still:
    # render._accent_decoration_html; motion: StoryCard's accentDecoration +
    # the sprint/accents registry), so the mapping is honest by construction.
    if spec.accent_treatment:
        brief.accent_style = spec.accent_treatment
    # R1.10 — the director's photo grade (duotone / halftone / vignette),
    # applied only onto the default photo path: a structural treatment the
    # pipeline already decided ("no-photo" text-led cards, an explicit profile
    # "frame") is never overridden by an art-direction whim. The still applies
    # the matching CSS grade (render._photo_treatment_css) and the motion
    # render the same held grade (sprint/layers/photo_filters.tsx).
    if (
        spec.photo_treatment in _TREATMENT_PHRASES
        and (brief.photo_treatment or "cutout") == "cutout"
    ):
        brief.photo_treatment = spec.photo_treatment
        brief.image_treatment = _TREATMENT_PHRASES[spec.photo_treatment]
    brief.ai_directed = True
    opts = brief.hero_stat_options or {}
    if spec.hero_stat in opts:
        brief.text_layers["hero_stat"] = opts[spec.hero_stat]
    # M11: the director's supporting facts — kept ONLY where the named fact was
    # actually measured (present in hero_stat_options), so the {{STAT_CHIPS}}
    # row can never carry an invented number.
    brief.secondary_stats = [k for k in spec.secondary_stats if k in opts]
    try:
        brief.colour_role_assignment = dict(spec.colour_roles.to_dict())
    except Exception:
        brief.colour_role_assignment = {}
    # 1.9 — carry the director's per-slot text effects onto the brief. Empty when
    # the director requested none, so an undirected card stays byte-identical.
    try:
        brief.text_effects = dict(spec.text_effects_map())
    except Exception:
        brief.text_effects = {}
    # Mood-keyed style pack (G1.28): re-key the decorative pack to the mood's
    # curated preset bundle so the decoration matches the feeling the director
    # chose. This is the same selection ``generate()``'s v2 pack block makes for
    # an AI-directed card, applied to the pre-computed-spec paths (candidate
    # pool, regenerate-variants) that set the mood *after* generate() already
    # picked. Guarded to a no-op when no pack was selected (a bare brief, or the
    # v2 kill switch left ``style_pack`` empty) or the mood has no bundle — so
    # direct callers and the legacy engine are byte-identical. The archetype is
    # folded into the key so distinct candidates for one card spread across the
    # bundle rather than sharing a single pack.
    try:
        if brief.style_pack:
            from mediahub.graphic_renderer import style_packs as _sp

            if _sp.mood_preset_packs(brief.mood):
                _key = f"{brief.content_item_id}|{brief.layout_template}"
                brief.style_pack = _sp.pick_mood_pack_for_card(brief.mood, _key).id
    except Exception:
        log.debug("gen-v2 mood style-pack re-key skipped", exc_info=True)
    # D5 — mirror of the style-pack re-key for the typography pairing: the
    # director's mood re-draws the pairing from its mood subset so the type
    # register matches the chosen feeling on the pre-computed-spec paths too.
    # Same guard (a selected pack marks the v2 engine active) and the same
    # archetype-folded key, so distinct candidates for one card spread across
    # the subset. Direct callers / the legacy engine stay byte-identical.
    try:
        if brief.style_pack and (spec.mood or "").strip():
            from mediahub.graphic_renderer.type_pairs import pick_pair_for_card

            _key = f"{brief.content_item_id}|{brief.layout_template}"
            brief.typography_pair = pick_pair_for_card(spec.mood, _key).id
    except Exception:
        log.debug("gen-v2 mood typography-pair re-key skipped", exc_info=True)
    _sync_background_style_with_pack(brief)
    _stamp_signature(brief)
    return brief


def _sync_background_style_with_pack(brief: CreativeBrief) -> None:
    """Key the G1.8 gradient-mesh ground to the card's selected style pack.

    A style pack whose *ground* lever is ``gradient_mesh`` is the reachable,
    deterministic trigger for the real mesh engine
    (``graphic_renderer.gradient_mesh`` via the ``gradient_mesh_bg`` render
    hook): the brief's ``background_style`` is set to the hook's opt-in token
    so the brand-role mesh paints the card ground, and the pack's darken-only
    pools read as atmosphere over it — one composed treatment, not two
    competing ones.

    Conservative on both edges: only the untouched default (``"water"``) is
    ever upgraded — an explicit caller/profile choice (``"clean"``, a mono
    token, ``"animated_loop"``, a mode-suffixed ``"gradient_mesh:radial"``) is
    never overridden — and only the bare token this helper set is reverted
    when a mood re-key moves the card onto a non-mesh pack.
    """
    try:
        ground = ""
        pack_id = (brief.style_pack or "").strip()
        if pack_id:
            from mediahub.graphic_renderer import style_packs as _sp

            pack = _sp.style_pack_from_id(pack_id)
            ground = pack.ground if pack is not None else ""
        current = (brief.background_style or "water").strip()
        if ground == "gradient_mesh":
            if current == "water":
                brief.background_style = "gradient_mesh"
        elif current == "gradient_mesh":
            brief.background_style = "water"
    except Exception:
        log.debug("gradient-mesh pack sync skipped", exc_info=True)


# ---------------------------------------------------------------------------
# Why-this-design — short LLM rationale; safe fallback
# ---------------------------------------------------------------------------


def _generate_why_this_design(
    angle: str, evaluation, pattern: dict, athlete: str, summary: str
) -> str:
    fb_parts: list[str] = []
    fb_parts.append(f"Pattern '{pattern['label']}' fits {angle} ({pattern['why_use_this']}).")
    if evaluation:
        if evaluation.confidence_tier != "high":
            fb_parts.append(
                f"Confidence is {evaluation.confidence_tier} — wording hedged ('{evaluation.confidence_label}')."
            )
        if evaluation.matched.get("hero_athlete"):
            fb_parts.append(f"Using a real photo of {athlete}.")
        if evaluation.missing_optional:
            fb_parts.append(
                f"Optional missing ({', '.join(evaluation.missing_optional)}) — design works without."
            )
    fb = " ".join(fb_parts)

    if not _llm_available():
        return fb

    sys = (
        "You write one short paragraph (max 60 words) explaining why a sports "
        "graphic was designed the way it was. No fluff. No bullet points. "
        "Write in the voice of an art director."
    )
    prompt = (
        f"Achievement: {summary}\n"
        f"Pattern chosen: {pattern['label']} — {pattern['why_use_this']}\n"
        f"Confidence tier: {evaluation.confidence_tier if evaluation else 'unknown'}\n"
        f"Confidence label: {evaluation.confidence_label if evaluation else 'STRONG SWIM'}\n"
        f"Has athlete photo: {bool(evaluation and evaluation.matched.get('hero_athlete'))}\n"
        f"Explain in one short paragraph why this design choice fits."
    )
    from mediahub.media_ai import generate as _gen

    try:
        out = _gen(prompt, system=sys, max_tokens=200)
    except Exception:
        # Any LLM failure (no provider, network, payload error) → safe fallback.
        return fb
    if out and "fallback" not in out.lower() and len(out) > 30:
        return out.strip()
    return fb


# ---------------------------------------------------------------------------
# Vision-based creative direction (V8.1 Issue 7 §5)
# ---------------------------------------------------------------------------

_VISION_CACHE_DIR = Path("data/cache/vision_briefs")
_VISION_TTL_SECONDS = 24 * 60 * 60  # 24h


def _vision_cache_key(asset_id: str, brand_id: str, photo_path: str) -> str:
    """Stable cache key per (asset, brand, photo content fingerprint).

    The first 64 KB of the photo is mixed in so a re-uploaded photo with
    the same name doesn't return a stale direction.
    """
    h = hashlib.sha256()
    h.update(str(asset_id).encode())
    h.update(b"|")
    h.update(str(brand_id).encode())
    try:
        with open(photo_path, "rb") as f:
            h.update(f.read(65536))
    except Exception:
        h.update(str(photo_path).encode())
    return h.hexdigest()[:24]


def _vision_cache_get(key: str) -> Optional[str]:
    p = _VISION_CACHE_DIR / f"{key}.json"
    if not p.exists():
        return None
    try:
        data = _json.loads(p.read_text("utf-8"))
        if not isinstance(data, dict):
            return None
        if time.time() - float(data.get("ts", 0)) > _VISION_TTL_SECONDS:
            return None
        v = data.get("value")
        return v if isinstance(v, str) and v.strip() else None
    except Exception:
        return None


def _vision_cache_put(key: str, value: str) -> None:
    try:
        _VISION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (_VISION_CACHE_DIR / f"{key}.json").write_text(
            _json.dumps({"ts": time.time(), "value": value}),
            encoding="utf-8",
        )
    except Exception:
        pass


def vision_creative_direction(
    photo_path,
    *,
    asset_id: str,
    brand_id: str,
    brand_kit=None,
    achievement_summary: str = "",
) -> Optional[str]:
    """Ask Claude vision for a 2-sentence creative direction string.

    Returns the direction text on success, or ``None`` if no key is
    configured / call failed / image unreadable. Callers must treat None
    as "skip vision step" — the rule-based brief continues to drive output.

    Cached per (asset_id, brand_id, photo content) for 24h to avoid
    repeated API calls on regenerate / format-trio renders.
    """
    if not _llm_available():
        return None
    photo_path = str(photo_path)
    if not Path(photo_path).is_file():
        return None

    cache_key = _vision_cache_key(asset_id or "_", brand_id or "_", photo_path)
    cached = _vision_cache_get(cache_key)
    if cached:
        return cached

    primary = getattr(brand_kit, "primary_colour", None) or "#0A2540"
    secondary = getattr(brand_kit, "secondary_colour", None) or "#101820"
    accent = getattr(brand_kit, "accent_colour", None) or "#FFFFFF"
    club_name = getattr(brand_kit, "display_name", None) or ""

    sys_prompt = (
        "You are an art director for a sports content studio. Look at the "
        "athlete photo and brand info, then write EXACTLY two short sentences "
        "of creative direction for a social-media graphic celebrating this "
        "performance. Speak about composition, mood, and how the athlete's "
        "posture / gaze / energy should drive the layout. No bullet points, "
        "no headers, no fluff, no quoting hex codes back at me."
    )
    user_prompt = (
        f"Club: {club_name}\n"
        f"Brand colours: primary {primary}, secondary {secondary}, accent {accent}.\n"
        f"Achievement: {achievement_summary or 'a strong swim performance'}.\n"
        f"Now write the two-sentence creative direction."
    )
    try:
        from mediahub.media_ai.llm import generate_vision

        out = generate_vision(
            [photo_path],
            user_prompt,
            system=sys_prompt,
            max_tokens=180,
        )
    except Exception:
        return None
    if not out or len(out.strip()) < 30:
        return None
    out = out.strip()
    if out.startswith(("- ", "• ", "#")):
        out = out.lstrip("-•# ").strip()
    _vision_cache_put(cache_key, out)
    return out


# ---------------------------------------------------------------------------
# Variation helpers (deterministic per seed)
# ---------------------------------------------------------------------------


def _rotate_pattern_for_seed(default_pattern: dict, angle: str, seed: int) -> dict:
    """Pick a different pattern based on ``seed`` — supports any positive int.

    The seed indexes into the full pattern catalog (excluding the default
    family on seed >= 2) so every distinct positive seed reliably yields a
    different visual layout family. Sport / club / brand colours never
    change — only the LAYOUT family does.

    seed == 1 -> keep the same family (palette/phrasing varies elsewhere).
    seed >= 2 -> deterministically pick one of the other families using modulo.
                 Every distinct seed in this range maps to a visible variant.
    """
    if seed == 1:
        return default_pattern

    # Seed 2 → favour the big-number-hero layout (time/result as visual hero,
    # the competitor-defining pattern from Holo/Predis/Blaze). Falls back to
    # any other pattern that fits the angle if big_number_hero isn't available.
    if seed == 2:
        big_num = next((p for p in PATTERNS if p["family"] == "big_number_hero"), None)
        if big_num and default_pattern["family"] != "big_number_hero":
            return big_num

    # Seed 3 → text-led / no-photo treatment (works without an athlete cutout).
    if seed == 3:
        text_led = next((p for p in PATTERNS if p["family"] == "text_led_recap"), None)
        wknd = next((p for p in PATTERNS if p["family"] == "weekend_numbers"), None)
        if default_pattern["family"] == "text_led_recap" and wknd:
            return wknd
        if text_led:
            return text_led

    candidates = patterns_for_post_angle(angle) or list(PATTERNS)
    others = [p for p in candidates if p["family"] != default_pattern["family"]]
    if not others:
        others = [p for p in PATTERNS if p["family"] != default_pattern["family"]]
    if not others:
        return default_pattern
    # seed indexes the full catalog of alternatives — every seed gets a
    # specific other family.
    return others[seed % len(others)]


# Six permutations of three colour roles. The club's actual brand colours
# (primary, secondary, accent — sourced from the BrandKit / logo extraction)
# are NEVER replaced. Only their ROLES rotate, so every visual still feels
# unmistakably "this club".
# Order matters: seeds 1, 2, 3 preserve the legacy V8 contract that
# test_v8_variation_seed asserts on. Seeds 4–6 are new and offer additional
# variety; seed 6 cycles back to identity so any seed > 6 reuses earlier
# permutations.
_PALETTE_PERMUTATIONS: list[tuple[int, int, int]] = [
    (1, 0, 2),  # seed 1: swap p<->s     (legacy: "inverted colour roles")
    (2, 0, 1),  # seed 2: rotate forward (legacy: p->accent, s->primary, a->secondary)
    (2, 1, 0),  # seed 3: swap p<->a     (legacy: "primary <-> accent")
    (0, 2, 1),  # seed 4: swap s<->a
    (1, 2, 0),  # seed 5: rotate left
    (0, 1, 2),  # seed 6: identity
]


def _permutation_is_legible(colors: tuple[str, str, str], perm: tuple[int, int, int]) -> bool:
    """True when a permutation's ground/accent pair clears the APCA gate both ways.

    C6 (Canva gap analysis): the permuted accent must read as a kicker on the
    permuted ground AND as a chip behind ground-coloured text — the same
    two-direction test the renderer's accent repair uses. A gate import failure
    (or a non-hex colour) is treated as legible so gating never *removes* a
    permutation the renderer could still handle.
    """
    p_idx, _s_idx, a_idx = perm
    ground, accent = colors[p_idx], colors[a_idx]
    try:
        from mediahub.quality.compliance import is_legible

        return is_legible(accent, ground) and is_legible(ground, accent)
    except Exception:
        return True


def gate_surviving_seeds(primary: str, secondary: str, accent: str) -> list[int]:
    """The 1-based seeds whose colour-role permutation clears the APCA gate (C6).

    Deterministic and order-preserving over ``_PALETTE_PERMUTATIONS``. Used to
    remap the seed walk onto only the legible permutations, so a seed never lands
    on a colourway the gate would bounce. Empty only if EVERY permutation fails
    (a pathological all-illegible kit) — the caller then keeps the raw seed.
    """
    colors = (primary, secondary, accent)
    return [
        i + 1
        for i, perm in enumerate(_PALETTE_PERMUTATIONS)
        if _permutation_is_legible(colors, perm)
    ]


def _apply_palette_seed(
    primary: str, secondary: str, accent: str, seed: int, *, gate: bool = False
) -> dict[str, str]:
    """Permute role assignments based on the seed.

    The actual hex values come from the club's BrandKit and are NEVER
    swapped for unrelated colours — only the role each colour plays
    (primary fill / secondary band / accent flash) varies. There are
    six total permutations; the seed picks one via modulo so any positive
    integer maps to a consistent visual permutation.

    seed == 0 -> identity (legacy default).

    ``gate=True`` (C6) remaps the seed onto only the gate-surviving permutations
    (:func:`gate_surviving_seeds`) so a seed can never select an illegible
    colourway. When every permutation survives — the common case, and every
    single-/two-colour legible kit — the survivor list is the full list and the
    mapping is byte-identical to the ungated walk, preserving the legacy seed
    contract; only a kit with a genuinely illegible permutation is remapped.
    """
    if seed <= 0:
        return {"primary": primary, "secondary": secondary, "accent": accent}
    if gate:
        survivors = gate_surviving_seeds(primary, secondary, accent)
        if survivors:
            seed = survivors[(seed - 1) % len(survivors)]
    colors = (primary, secondary, accent)
    p_idx, s_idx, a_idx = _PALETTE_PERMUTATIONS[(seed - 1) % len(_PALETTE_PERMUTATIONS)]
    return {
        "primary": colors[p_idx],
        "secondary": colors[s_idx],
        "accent": colors[a_idx],
    }


def auto_variation_seed_for(card_id: str | None) -> int:
    """Pick a deterministic non-zero seed for a card from its id.

    Same card → same seed (so re-renders look identical to the user when
    they reload the page). Different cards → different seeds (so visuals
    in one content pack visibly differ from one another).

    Returns 1..N where N covers the largest variation table; callers can
    pass the returned value straight to the seed-aware helpers above.
    """
    if not card_id:
        # Fall back to a time-based randomish positive seed.
        import time as _time

        return int(_time.time() * 1000) % 997 + 1
    import hashlib as _hl

    h = int(_hl.sha256(card_id.encode("utf-8")).hexdigest()[:8], 16)
    # Keep the result well above zero so seed==0 (legacy "no variation")
    # is reserved for callers who explicitly want the default.
    return (h % 997) + 1


# ---------------------------------------------------------------------------
# Family sets shared by the photo/no-photo gates
# ---------------------------------------------------------------------------

# Text-led families need no athlete photo — the renderer fills the canvas with
# type. Kept as one constant so every photo/no-photo gate agrees on the set.
_TEXT_LED_FAMILIES: frozenset[str] = frozenset({"text_led_recap", "weekend_numbers", "stat_line"})


def _cs_display(cs) -> str:
    """Centiseconds → display time ("1:02.34"), or "" for absent/junk input."""
    try:
        total = int(cs)
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    mins, rem = divmod(total, 6000)
    secs, frac = divmod(rem, 100)
    return f"{mins}:{secs:02d}.{frac:02d}" if mins else f"{secs}.{frac:02d}"


def _payload_stat_options(ach: dict, raw_facts: dict) -> dict[str, str]:
    """Measured emphasis facts beyond pb_delta/placing (M11 / STILLS-5).

    Reads only what the detector payload actually carries — the established
    raw-facts keys the brand/caption surfaces already consume — and returns
    ``STAT_KEY → display line`` entries. Absent facts are absent keys; nothing
    is computed beyond formatting.
    """
    out: dict[str, str] = {}

    def _fact(*keys: str) -> str:
        for k in keys:
            v = raw_facts.get(k)
            if v in (None, ""):
                v = ach.get(k)
            if v not in (None, ""):
                return str(v).strip()
        return ""

    split = _fact("split_time", "split")
    if split:
        out["split_time"] = f"split {split}"
    relay_split = _fact("relay_split")
    if relay_split:
        out["relay_split"] = f"relay split {relay_split}"
    season_best = _fact("season_best", "season_best_time")
    if season_best:
        out["season_best"] = f"season best {season_best}"
    age_group = _fact("age_group")
    if age_group and age_group.lower() not in ("open", "none"):
        out["age_group"] = f"age group {age_group}"
    points = _fact("points", "fina_points")
    if points:
        out["points"] = f"{points} pts"
    return out


def _is_medal_angle(angle: str) -> bool:
    a = (angle or "").lower()
    return a.startswith("medal") or a in {
        "gold_medal",
        "silver_medal",
        "bronze_medal",
        "podium_finish",
    }


def _place_display(place) -> str:
    """Human display for a placing fact — ``1`` / ``"1st"`` / ``"1."`` → ``"1st place"``.

    Returns ``""`` for empty input; a non-numeric value that already reads as
    an ordinal gets the " place" suffix, anything else passes through as-is
    (never invent a placing that wasn't detected).
    """
    s = str(place or "").strip().rstrip(".")
    if not s:
        return ""
    if s.isdigit():
        n = int(s)
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix} place"
    return f"{s} place" if s.lower().endswith(("st", "nd", "rd", "th")) else s


__all__ = [
    "generate",
    "apply_design_spec",
    "CreativeBrief",
    "VariationProfile",
    "vision_creative_direction",
    "auto_variation_seed_for",
]
