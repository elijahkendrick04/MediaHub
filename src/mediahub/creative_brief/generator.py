"""Generate a CreativeBrief that drives the renderer.

Inputs:
  - content_item     dict from content_pack
  - evaluation       EvaluationResult from media_requirements
  - brand_kit        BrandKit
  - voice_profile    VoiceProfile or None
  - inspiration_pat  pattern dict from mediahub.inspiration.pattern_library

Output: CreativeBrief dataclass with everything the renderer needs, plus a
human-readable "why this design" explanation.

Variation surface
-----------------
The brief carries an eight-axis ``VariationProfile`` so two renders of the
same card can look meaningfully different (different layout family,
background pattern, decoration style, typography pair, headline hook,
palette role, composition, photo treatment). The profile is chosen by:

1. The AI creative director when a provider is configured
   (``creative_brief.ai_director``), or
2. A deterministic seed for the legacy six-permutation contract
   (seeds 1-6 keep the original test contract), or
3. A fresh random profile per call when the caller requests one (the
   regenerate route uses this so clicking "Regenerate" actually produces
   something new every time).
"""

from __future__ import annotations

import hashlib
import json as _json
import random as _random
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mediahub.inspiration.pattern_library import best_pattern_for, patterns_for_post_angle, PATTERNS
from mediahub.media_ai import is_available as _llm_available


# ---------------------------------------------------------------------------
# Multi-axis variation profile
# ---------------------------------------------------------------------------
#
# Every visual is characterised by a profile across these axes. The
# renderer reads them off the brief at fill-time. Adding a new axis here
# is a deliberate change because the renderer needs to honour it.

# Background pattern keys honoured by graphic_renderer.render.
# "water" is the legacy default (subtle ripple SVG). The rest are new
# pattern data URIs added alongside this overhaul.
BACKGROUND_STYLES: tuple[str, ...] = (
    "water",  # subtle horizontal ripples (legacy)
    "halftone",  # repeating dot grid (sport-magazine feel)
    "diagonal",  # angled stripes (energy/motion)
    "radial",  # radial gradient burst (hero spotlight)
    "geometric",  # blocky triangle/chevron field (editorial)
    "clean",  # no pattern, gradient only (minimal)
    "stripes",  # vertical stripes (broadcast graphic)
    "dots",  # offset dot grid (newsprint)
    "duotone",  # two-tone diagonal split (modern poster)
    "grain",  # heavy film grain only (analogue)
)

# Accent decoration keys. The renderer paints these on top of the
# composition; they layer the brand's accent colour into a recognisable
# visual signature without altering layout structure.
ACCENT_STYLES: tuple[str, ...] = (
    "brackets",  # corner brackets top-left + bottom-right
    "stripe",  # horizontal accent stripe across mid-section
    "badge",  # round accent badge near result chip
    "frame",  # thin frame around the whole canvas
    "minimal",  # no accent geometry, accent in type only
    "ribbon",  # diagonal ribbon across one corner
    "arrow",  # arrow/chevron pointing at the result
    "underline",  # bold underline beneath headline
)

# Typography pair keys. The first font drives headline/numeral, the
# second drives body/labels. Adding a key requires the @font-face block
# to actually have the font available (see _shared.css).
TYPOGRAPHY_PAIRS: tuple[str, ...] = (
    "anton-inter",  # legacy default (condensed display + clean body)
    "bebas-grotesk",  # broadcast headline + modern body
    "druk-inter",  # ultra-heavy editorial + clean body
    "bowlby-inter",  # rounded chunky display + clean body
    "archivo-inter",  # athletic geometric + clean body
    "oswald-inter",  # tall condensed + clean body
)

# Composition placement keys. Drives where the athlete cutout sits in the
# canvas and how the text balances against it.
COMPOSITIONS: tuple[str, ...] = (
    "right",  # cutout right, text left (legacy)
    "left",  # cutout left, text right (mirror)
    "center",  # cutout centred, text stacked above/below
    "off-center",  # slight offset for dynamic asymmetry
)

# Photo treatment keys. Drives how the athlete cutout is processed by
# the renderer before paste-in.
PHOTO_TREATMENTS: tuple[str, ...] = (
    "cutout",  # clean alpha cutout (legacy)
    "vignette",  # cutout with soft vignette glow
    "duotone",  # cutout tinted with brand colour
    "frame",  # cutout boxed in a thin accent frame
    "halftone",  # cutout rendered as halftone dots
    "no-photo",  # text-led, no athlete image
)


@dataclass
class VariationProfile:
    """Multi-axis variation profile for visual diversity.

    Each axis is independent. Two renders of the same achievement with
    different profiles will produce visibly different graphics even when
    the underlying data is identical. The profile is what makes
    "regenerate" actually do something.
    """

    layout_family: str = ""  # e.g. "individual_hero"
    palette_role_index: int = 0  # 0..5 (which permutation)
    background_style: str = "water"  # see BACKGROUND_STYLES
    accent_style: str = "brackets"  # see ACCENT_STYLES
    typography_pair: str = "anton-inter"  # see TYPOGRAPHY_PAIRS
    composition: str = "right"  # see COMPOSITIONS
    photo_treatment: str = "cutout"  # see PHOTO_TREATMENTS
    decoration_strength: float = 0.5  # 0..1, intensity of accent
    hook_phrase: str = ""  # specific hook copy (AI-supplied)
    mood: str = ""  # short mood word (AI-supplied)

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
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    version: int = 2

    def to_dict(self) -> dict:
        return asdict(self)


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
    variation_seed: int = 0,
    variation_profile: Optional[VariationProfile] = None,
    use_ai_director: bool = False,
    recent_signatures: Optional[list[str]] = None,
    recent_hooks: Optional[list[str]] = None,
    allowed_families: Optional[list[str]] = None,
) -> CreativeBrief:
    """Build a CreativeBrief. Pure function — never reaches network unless
    LLM is available; falls back to deterministic defaults otherwise.

    ``variation_seed`` controls deterministic perturbation of the layout,
    palette role mapping, image treatment, and headline phrasing. ``0``
    keeps the default behaviour. ``1`` keeps the same family but inverts
    colour roles. ``2`` swaps to a different layout family. ``3`` forces a
    text-led / no-photo treatment.

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

    # ---- AI creative direction (optional, preferred when configured) ----
    # When ``use_ai_director`` is True we always try the AI first, even
    # if the caller pre-populated ``variation_profile`` with a random
    # fallback (web.py does this so we still have variety when Gemini
    # is unavailable). The AI direction WINS when it returns a result;
    # the pre-populated profile only kicks in when the AI call returns
    # nothing — a configured Gemini key would never have been honoured
    # otherwise, which silently downgraded production to random-only
    # variation.
    ai_direction: Optional[dict] = None
    if use_ai_director:
        try:
            from mediahub.creative_brief.ai_director import ai_creative_direction

            ai_direction = ai_creative_direction(
                content_item=content_item,
                brand_kit=brand_kit,
                angle=angle,
                default_family=pattern["family"],
                recent_signatures=recent_signatures or [],
                recent_hooks=recent_hooks or [],
                allowed_families=allowed_families,
            )
        except Exception:
            ai_direction = None
        if ai_direction:
            # Promote the AI direction into a VariationProfile so the rest
            # of the function only has one code path to follow.
            variation_profile = _profile_from_ai_direction(
                ai_direction,
                default_family=pattern["family"],
                allowed_families=allowed_families,
            )

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
        palette = _apply_palette_seed(base_primary, base_secondary, base_accent, variation_seed)

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

    # Headline phrasing — profile.hook_phrase wins, then seed-table fallback.
    if variation_profile is not None and variation_profile.hook_phrase:
        primary_hook = variation_profile.hook_phrase
        layers["achievement_label"] = primary_hook
    elif variation_seed:
        primary_hook = _phrase_for_seed(primary_hook, label, angle, variation_seed)
        layers["achievement_label"] = primary_hook

    image_treatment = pattern.get("image_treatment", "")
    if variation_profile is not None:
        # Map profile.photo_treatment to a renderer-friendly phrase. The
        # renderer keys off the phrase to pick its filter pipeline.
        treatment_phrases = {
            "no-photo": "no photo, text-led layout",
            "vignette": "cutout with vignette glow",
            "duotone": "duotone-tinted cutout in brand colour",
            "frame": "cutout boxed in accent frame",
            "halftone": "halftone-dot cutout treatment",
            "cutout": image_treatment or "real cutout, contrast lift",
        }
        image_treatment = treatment_phrases.get(variation_profile.photo_treatment, image_treatment)
    elif variation_seed == 3:
        # Force text-led / no photo (legacy seed-3 contract)
        image_treatment = "no photo, text-led layout"

    # Resolve final variation axes for the brief
    if variation_profile is not None:
        bg_style = variation_profile.background_style
        accent_style = variation_profile.accent_style
        type_pair = variation_profile.typography_pair
        composition = variation_profile.composition
        photo_treatment = variation_profile.photo_treatment
        decoration_strength = variation_profile.decoration_strength
        mood = variation_profile.mood
        ai_directed = bool(ai_direction)
    else:
        # Legacy seed-only path — derive the new axes deterministically
        # from the seed so even legacy callers get *some* variety.
        bg_style, accent_style, type_pair, composition, photo_treatment, decoration_strength = (
            _legacy_axes_from_seed(variation_seed)
        )
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
    )
    # Stamp a signature so callers can dedupe / audit recent renders.
    sig = (
        f"{brief.layout_template}|{brief.palette.get('primary','')}|"
        f"{brief.background_style}|{brief.accent_style}|"
        f"{brief.typography_pair}|{brief.composition}|"
        f"{brief.photo_treatment}|{brief.primary_hook[:40]}"
    )
    brief.variation_signature = sig
    return brief


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


def _apply_palette_seed(primary: str, secondary: str, accent: str, seed: int) -> dict[str, str]:
    """Permute role assignments based on the seed.

    The actual hex values come from the club's BrandKit and are NEVER
    swapped for unrelated colours — only the role each colour plays
    (primary fill / secondary band / accent flash) varies. There are
    six total permutations; the seed picks one via modulo so any positive
    integer maps to a consistent visual permutation.

    seed == 0 -> identity (legacy default).
    """
    if seed <= 0:
        return {"primary": primary, "secondary": secondary, "accent": accent}
    colors = (primary, secondary, accent)
    p_idx, s_idx, a_idx = _PALETTE_PERMUTATIONS[(seed - 1) % len(_PALETTE_PERMUTATIONS)]
    return {
        "primary": colors[p_idx],
        "secondary": colors[s_idx],
        "accent": colors[a_idx],
    }


# Six phrase tables so any positive integer seed maps to a hook variant.
_PHRASE_TABLES: list[dict[str, str]] = [
    # Table 1 — "personal best" tone
    {
        "NEW PB": "PERSONAL BEST",
        "LIKELY PB": "LIKELY PERSONAL BEST",
        "GOLD": "FIRST PLACE",
        "SILVER": "SECOND PLACE",
        "BRONZE": "THIRD PLACE",
        "STRONG SWIM": "BIG SWIM",
    },
    # Table 2 — "best ever" tone
    {
        "NEW PB": "BEST EVER",
        "LIKELY PB": "BEST EVER (PROVISIONAL)",
        "GOLD": "GOLD MEDAL",
        "SILVER": "SILVER MEDAL",
        "BRONZE": "BRONZE MEDAL",
        "STRONG SWIM": "STANDOUT SWIM",
    },
    # Table 3 — "alert" tone
    {
        "NEW PB": "PB ALERT",
        "LIKELY PB": "PB CONTENDER",
        "GOLD": "TOP OF THE PODIUM",
        "SILVER": "PODIUM FINISH",
        "BRONZE": "PODIUM FINISH",
        "STRONG SWIM": "NOTABLE PERFORMANCE",
    },
    # Table 4 — "career best" / "milestone" tone
    {
        "NEW PB": "CAREER BEST",
        "LIKELY PB": "CAREER BEST (TBC)",
        "GOLD": "CHAMPION",
        "SILVER": "RUNNER-UP",
        "BRONZE": "BRONZE FOR THE BOOKS",
        "STRONG SWIM": "MAJOR SWIM",
    },
    # Table 5 — short / Stories-friendly tone
    {
        "NEW PB": "NEW PB",
        "LIKELY PB": "PB INCOMING",
        "GOLD": "GOLD",
        "SILVER": "SILVER",
        "BRONZE": "BRONZE",
        "STRONG SWIM": "STRONG ONE",
    },
    # Table 6 — celebratory tone
    {
        "NEW PB": "LIFETIME BEST",
        "LIKELY PB": "LIFETIME BEST (PENDING)",
        "GOLD": "FIRST ACROSS THE WALL",
        "SILVER": "RIGHT BEHIND IT",
        "BRONZE": "ON THE PODIUM",
        "STRONG SWIM": "WHAT A SWIM",
    },
]


def _phrase_for_seed(default_hook: str, label: str, angle: str, seed: int) -> str:
    """Tweak the headline phrasing deterministically.

    Supports any positive integer seed — picks one of six phrase tables
    via modulo. Falls back to the default hook if the label isn't in the
    chosen table (e.g. for one-off custom labels).
    """
    if seed <= 0:
        return default_hook
    label = (label or default_hook or "").upper()
    table = _PHRASE_TABLES[(seed - 1) % len(_PHRASE_TABLES)]
    return table.get(label, default_hook)


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
# Random / AI-driven variation profile picker
# ---------------------------------------------------------------------------

# Families safe to pick from for a generic achievement card. Restricted to
# templates that exist in graphic_renderer/layouts/ and that work without
# a sponsor or athlete photo dependency. The ai_director can recommend
# any of these without needing extra data.
# Text-led families need no athlete photo — the renderer fills the canvas with
# type. Kept as one constant so every photo/no-photo gate agrees on the set.
_TEXT_LED_FAMILIES: frozenset[str] = frozenset(
    {"text_led_recap", "weekend_numbers", "stat_line"}
)

_GENERIC_FAMILIES: tuple[str, ...] = (
    "individual_hero",
    "big_number_hero",
    "text_led_recap",
    "weekend_numbers",
    "athlete_spotlight",
    "story_card",
    "stat_line",
)

# Medal-aware families. Used when the achievement is a medal so the
# composition reads "podium" rather than "PB".
_MEDAL_FAMILIES: tuple[str, ...] = (
    "medal_card",
    "individual_hero",
    "big_number_hero",
    "story_card",
)


def _is_medal_angle(angle: str) -> bool:
    a = (angle or "").lower()
    return a.startswith("medal") or a in {
        "gold_medal",
        "silver_medal",
        "bronze_medal",
        "podium_finish",
    }


def random_variation_profile(
    angle: str = "",
    *,
    rng: Optional[_random.Random] = None,
    avoid_signatures: Optional[list[str]] = None,
) -> VariationProfile:
    """Build a fresh random ``VariationProfile`` across all axes.

    Used by the regenerate route so every click produces a visually
    distinct graphic without depending on AI availability. When
    ``avoid_signatures`` is provided the picker will try up to 12 random
    profiles to find one whose signature isn't in the avoid list — good
    enough for the small recent-history pool the route persists.
    """
    rng = rng or _random.SystemRandom()
    families = _MEDAL_FAMILIES if _is_medal_angle(angle) else _GENERIC_FAMILIES

    def _pick() -> VariationProfile:
        family = rng.choice(families)
        is_text_led = family in _TEXT_LED_FAMILIES
        # When the family is text-led, no athlete photo can be in play.
        photo = "no-photo" if is_text_led else rng.choice(PHOTO_TREATMENTS)
        # Text-led layouts rely on the BRAND PRIMARY being dark for the
        # white-on-primary type to be legible. Restrict role rotations
        # that would push the (often-light) accent into primary so the
        # text never disappears against a yellow / cream background.
        # Permutations 0, 1, 3 keep the original primary or secondary
        # as the dominant fill; 2, 4, 5 promote the accent.
        if is_text_led:
            palette_role = rng.choice((0, 1, 3))
        else:
            palette_role = rng.randint(0, 5)
        return VariationProfile(
            layout_family=family,
            palette_role_index=palette_role,
            background_style=rng.choice(BACKGROUND_STYLES),
            accent_style=rng.choice(ACCENT_STYLES),
            typography_pair=rng.choice(TYPOGRAPHY_PAIRS),
            composition=rng.choice(COMPOSITIONS),
            photo_treatment=photo,
            decoration_strength=round(rng.uniform(0.2, 1.0), 2),
            hook_phrase="",  # left blank → seed-table fallback fills it
            mood=rng.choice(_RANDOM_MOOD_WORDS),
        )

    avoid = set(avoid_signatures or [])
    profile = _pick()
    if avoid:
        for _ in range(12):
            if profile.signature() not in avoid:
                break
            profile = _pick()
    return profile


# Mood words a random profile can pick. Used by the renderer to subtly
# bias the background style intensity and the accent treatment when the
# AI isn't in the loop.
_RANDOM_MOOD_WORDS: tuple[str, ...] = (
    "electric",
    "calm",
    "fierce",
    "celebratory",
    "stoic",
    "explosive",
    "precise",
    "warm",
    "underdog",
    "champion",
    "milestone",
    "bold",
    "minimal",
    "editorial",
    "broadcast",
)


def _legacy_axes_from_seed(seed: int) -> tuple[str, str, str, str, str, float]:
    """Map an integer seed to the new multi-axis variation values.

    Lets legacy callers that only pass ``variation_seed`` still benefit
    from the new background/accent/typography variation — without
    breaking the existing seed-0..3 test contract (those return the
    legacy defaults so the test PNG bytes still differ in their existing
    way).

    Returns: (bg_style, accent_style, type_pair, composition, photo_treatment, deco_strength)
    """
    if seed is None or seed <= 0:
        return ("water", "brackets", "anton-inter", "right", "cutout", 0.5)
    rng = _random.Random(seed)
    return (
        rng.choice(BACKGROUND_STYLES),
        rng.choice(ACCENT_STYLES),
        rng.choice(TYPOGRAPHY_PAIRS),
        rng.choice(COMPOSITIONS),
        # Seed 3 forces no-photo per legacy contract.
        "no-photo" if seed == 3 else rng.choice(PHOTO_TREATMENTS),
        round(rng.uniform(0.3, 0.9), 2),
    )


def _profile_from_ai_direction(
    direction: dict,
    *,
    default_family: str,
    allowed_families: Optional[list[str]] = None,
) -> VariationProfile:
    """Convert the AI director's structured output into a VariationProfile.

    The director returns a JSON object describing the creative
    direction; this maps it into the in-memory profile, normalising
    unknown values to safe defaults so a hallucinated key never
    breaks the renderer.

    ``allowed_families`` hard-constrains the layout (caption-only graphics
    must stay text-led); when the chosen family is text-led the photo
    treatment is forced to no-photo so the render never expects a cutout
    that doesn't exist.
    """

    def _norm(key: str, allowed: tuple[str, ...], default: str) -> str:
        v = str(direction.get(key, "") or "").strip().lower()
        return v if v in allowed else default

    family = str(direction.get("layout_family", "") or default_family).strip().lower()
    if not family or family not in {p["family"] for p in PATTERNS}:
        family = default_family
    if allowed_families and family not in allowed_families:
        family = allowed_families[0]
    photo_override = "no-photo" if family in _TEXT_LED_FAMILIES else None

    try:
        deco = float(direction.get("decoration_strength", 0.5))
        deco = max(0.0, min(1.0, deco))
    except (TypeError, ValueError):
        deco = 0.5

    try:
        prole = int(direction.get("palette_role_index", 0))
        prole = max(0, min(5, prole))
    except (TypeError, ValueError):
        prole = 0

    return VariationProfile(
        layout_family=family,
        palette_role_index=prole,
        background_style=_norm("background_style", BACKGROUND_STYLES, "water"),
        accent_style=_norm("accent_style", ACCENT_STYLES, "brackets"),
        typography_pair=_norm("typography_pair", TYPOGRAPHY_PAIRS, "anton-inter"),
        composition=_norm("composition", COMPOSITIONS, "right"),
        photo_treatment=photo_override or _norm("photo_treatment", PHOTO_TREATMENTS, "cutout"),
        decoration_strength=deco,
        hook_phrase=str(direction.get("hook_phrase", "") or "").strip()[:80],
        mood=str(direction.get("mood", "") or "").strip()[:40],
    )


__all__ = [
    "generate",
    "CreativeBrief",
    "VariationProfile",
    "vision_creative_direction",
    "auto_variation_seed_for",
    "random_variation_profile",
    "BACKGROUND_STYLES",
    "ACCENT_STYLES",
    "TYPOGRAPHY_PAIRS",
    "COMPOSITIONS",
    "PHOTO_TREATMENTS",
]
