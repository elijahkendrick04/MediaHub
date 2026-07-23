"""The design-spec art director (Gen Engine v2, Tier B §5.4–5.5).

Wraps the provider-agnostic ``ai_core`` interface to ask Gemini/Claude for a
structured **DesignSpec**: which v2 archetype, colour-role assignment, focal
element, hero stat, hook, mood and motion intent best fit ONE achievement.
``ai_design_spec`` returns a single validated spec; ``ai_design_specs``
returns a mutually-distinct pool in one call (the candidate-pool builder's
input). Every model response is run through ``design_spec.normalise``, so a
hallucinated value can never produce an illegal or illegible card.

When no provider is configured both functions return ``None`` and never
crash — the caller falls back to the deterministic Tier A archetype picker
(``graphic_renderer.archetypes``), the honest no-LLM floor.

The old closed-vocabulary menu-picker (``ai_creative_direction[s]``), which
had the model pick from fixed enum lists, was removed at the SEQ-3 cutover —
the design-spec director is the only LLM direction surface now.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

log = logging.getLogger(__name__)


# ai_core is imported lazily inside each director call so this module stays
# importable in environments where the provider SDKs aren't installed
# (e.g. minimal CI without the anthropic SDK).


def _safe_get(obj: Any, *keys: str, default: Any = None) -> Any:
    """Walk a dotted path through dicts/objects safely."""
    cur = obj
    for k in keys:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            cur = getattr(cur, k, None)
    return cur if cur is not None else default


def _logo_inventory(brand_kit) -> str:
    """The uploaded-logo inventory for the brand kit's profile, if any.

    The art director picks a ``logo_lockup`` but was previously blind to which
    logo variants actually exist. Surface the brand-context builder's
    ``include_logos=True`` inventory (names + availability), loaded from the
    kit's owning ClubProfile, so the model chooses a lockup that maps to a
    real asset. The director is deliberately the only consumer: caption/text
    generators keep the default logo-free context so logo filenames can never
    leak into copy (guarded by test_caption_no_logo_leak). Best-effort: any
    load/import failure yields ""; the director never crashes on brand
    context.
    """
    profile_id = _safe_get(brand_kit, "profile_id", default="") or ""
    if not profile_id:
        return ""
    try:
        from mediahub.web.club_profile import load_profile

        # The single source of the include_logos=True inventory prose
        # (humanised names + dark-vs-mono guidance).
        from mediahub.brand.context import _logos_prose

        profile = load_profile(profile_id)
        if profile is None:
            return ""
        return (_logos_prose(profile) or "").strip()
    except Exception as e:  # pragma: no cover - defensive; never break the director
        log.debug("_logo_inventory: %s", e)
        return ""


def _brand_context(brand_kit) -> str:
    """One-paragraph brand context for the system prompt."""
    if brand_kit is None:
        return ""
    name = _safe_get(brand_kit, "display_name", default="") or ""
    primary = _safe_get(brand_kit, "primary_colour", default="") or ""
    secondary = _safe_get(brand_kit, "secondary_colour", default="") or ""
    accent = _safe_get(brand_kit, "accent_colour", default="") or ""
    bits = []
    if name:
        bits.append(f"Club: {name}.")
    cols = [c for c in (primary, secondary, accent) if c]
    if cols:
        bits.append(
            "Brand palette (DO NOT change the hex values, only their visual role): "
            + ", ".join(cols)
            + "."
        )
    logos = _logo_inventory(brand_kit)
    if logos:
        bits.append(logos)
    return " ".join(bits)


def _achievement_summary(content_item: dict) -> str:
    ach = (content_item or {}).get("achievement") or content_item or {}
    swimmer = ach.get("swimmer_name") or ach.get("athlete_name") or ""
    event = ach.get("event_name") or ach.get("event") or ""
    result = (
        ach.get("result_time")
        or ach.get("time")
        or ach.get("result")
        or (ach.get("raw_facts") or {}).get("time_str")
        or ""
    )
    place = ach.get("place") or ach.get("position") or ""
    angle = ach.get("post_angle") or content_item.get("post_angle") or ""
    bits = []
    if swimmer:
        bits.append(swimmer)
    if event:
        bits.append(event)
    if result:
        bits.append(str(result))
    if place:
        bits.append(f"{place} place")
    if angle:
        bits.append(f"(angle: {angle})")
    return " — ".join(bits) if bits else "a strong swim"


def _parse_strict_json(text: str) -> Optional[dict]:
    """Extract the first JSON object from ``text``.

    Models occasionally wrap JSON in ```json fences``` despite the
    prompt; this peels them and tolerates trailing text.
    """
    if not text:
        return None
    s = text.strip()
    # Strip code fences.
    if s.startswith("```"):
        # Drop the opening ``` and optional language tag.
        s = s.split("\n", 1)[1] if "\n" in s else s.lstrip("`")
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    # Find the outermost {...} block.
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(s[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _parse_strict_json_array(text: str) -> Optional[list]:
    """Extract the first JSON array of objects from ``text``.

    Mirror of ``_parse_strict_json`` for the batch-direction call: peels
    optional ```json fences``` and tolerates prose around the array.
    """
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s.lstrip("`")
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    start = s.find("[")
    end = s.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        arr = json.loads(s[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(arr, list):
        return None
    return [d for d in arr if isinstance(d, dict)]


# ---------------------------------------------------------------------------
# Gen Engine v2 — Tier B §5.4: the design-spec director
# ---------------------------------------------------------------------------

# One-line "when to use" guidance per v2 archetype, injected into the prompt so
# the model picks the composition that fits THIS moment rather than an arbitrary
# seed. Keyed by the archetype name (file stem under layouts/v2/). FALLBACK
# only: the live catalog line comes from each archetype's authored
# <name>.notes.md (see _archetype_catalog_line); this dict covers the rare
# case of an archetype whose notes are missing/unreadable.
_ARCHETYPE_GUIDE: dict[str, str] = {
    "split_diagonal_hero": "photo-led, dynamic; a strong action or portrait moment.",
    "big_number_dominant": "the time/score IS the story; works with no photo.",
    "full_bleed_photo_lower_third": "a great full-frame photo; broadcast lower-third.",
    "editorial_numbers_grid": "data-rich recap; several stats; no photo needed.",
    "minimal_type_poster": "bold, restrained, type-only; a clean PB with no photo.",
    "centered_medal_spotlight": "a medal/podium/celebratory moment; symmetric.",
}


def _archetype_catalog_line(name: str) -> str:
    """The director's briefing line for one archetype.

    Primary source is the archetype's authored ``<name>.notes.md`` (PAR-7 —
    the catalog the notes exist to feed), surfaced via
    ``archetypes.director_note``. The static ``_ARCHETYPE_GUIDE`` line is the
    fallback when the notes are unavailable, so new archetypes brief the
    director the moment they ship notes — no dict to keep in sync.
    """
    try:
        from mediahub.graphic_renderer.archetypes import director_note

        note = director_note(name)
    except Exception:
        note = ""
    return note or _ARCHETYPE_GUIDE.get(name, "a distinct layout.")


def _design_spec_system_prompt(archetypes: list[str], token_roles: list[str]) -> str:
    catalog = "\n".join(f"  - {a}: {_archetype_catalog_line(a)}" for a in archetypes)
    return (
        "You are the art director for a sports club's social graphic. Choose the "
        "single best composition for ONE achievement and return STRICT JSON only "
        "(no prose, no markdown).\n\n"
        "Pick from these archetypes:\n" + catalog + "\n\n"
        "Return this exact shape:\n"
        "{\n"
        '  "archetype": <one archetype name from the list>,\n'
        '  "colour_roles": {"ground": <role>, "surface": <role>, "headline": <role>, "accent": <role>},\n'
        '  "focal_element": "athlete_cutout|athlete_photo|big_number|medal|logo|none",\n'
        '  "crop_intent": "smart|tight_portrait|rule_of_thirds_action|centered|full_bleed|original",\n'
        '  "hero_stat": "final_time|pb_delta|placing|relay_split|event|points",\n'
        '  "secondary_stats": [<stat>, ...],\n'
        '  "headline_hook": <<=80 chars, no emoji; ground it in THIS result '
        "(a name, time, event or placing); avoid generic sports hype "
        '("what a performance", "on fire", "smashing it") and AI cliché '
        '("delve","elevate")>,\n'
        '  "accent_treatment": "brackets|stripe|badge|frame|minimal|ribbon|underline|'
        "diagonal_underline|thick_stripe|thin_stripe|double_stripe|side_rail|"
        "large_brackets|small_brackets|bracket_frame|corner_tabs|offset_badge|"
        'glass_chip",  # glass_chip = frosted-glass data chips over a photo (photo-led cards)\n'
        '  "photo_treatment": "cutout|duotone|halftone|vignette|wash|sticker|'
        'mosaic|motion_tile|roughen_edges",\n'
        '  "photo_treatment_intensity": <-1 for auto (size the grade off the '
        "card's decoration strength), else 0..1 for how strong the photo grade "
        "reads>,\n"
        '  "logo_lockup": "full_horizontal|full_stacked|mono_light|mono_dark|icon",\n'
        '  "mood": "explosive|electric|calm|fierce|celebratory|stoic|precise|bold|triumphant|minimal",\n'
        '  "motion_intent": "fade_in|snap_in_then_settle|slide_up|scale_in|kinetic_type|count_up|static|bounce_in|flip_reveal|swirl|reveal_from_sides|cascade|rise|pop|drop_in|text_scramble",\n'
        '  "text_effects": {"headline|result|kicker|event|meta": "none|shadow|lift|hollow|outline|splice|echo|glitch|neon|background|gradient|extrude|warp|curve"} (optional flourish — usually {} ),\n'
        '  "emphasis_word": <optional: ONE word already present in a slot to two-tone-highlight, else "">,\n'
        '  "emphasis_style": "accent_ink|accent_pill|heavy",\n'
        '  "rationale": <one sentence: why this composition fits THIS result>\n'
        "}\n\n"
        "colour_roles values must be one of: " + ", ".join(token_roles) + ".\n"
        "text_effects is an optional flourish: leave it {} for most cards, and at "
        "most add ONE slot when the moment is genuinely big. Craft guide: "
        "hollow/splice suit the heavy display faces only; background is the "
        "highlight pill that keeps copy legible over a photo; echo adds speed "
        "behind a result numeral; lift is the quiet photo-card shadow; glitch/neon "
        "are loud electric moods; warp/curve are geometry, best on short kickers. "
        "curve arcs text on a baseline: keep it gentle for a headline, but a large "
        "curve wraps a SHORT all-caps string (a club name, one word) toward a "
        "varsity-crest circle — only ever short all-caps, never a long line. "
        "The renderer auto-downgrades any effect that would hurt legibility, so "
        "never reach for one to force drama.\n"
        "emphasis_word is the two-tone headline: name ONE word that already "
        "appears in your headline_hook (or a slot's text) to lift in the accent "
        "(accent_ink), behind a highlight pill (accent_pill), or in a heavier cut "
        '(heavy). Leave it "" for most cards; the renderer only highlights the '
        "word when it genuinely appears and reads legibly, else it stays plain.\n"
        "photo_treatment craft: wash unifies mismatched/phone photography into "
        "one campaign look; sticker gives a cutout the die-cut poster edge "
        "(cutout archetypes only); duotone is the full two-ink brand grade. "
        "mosaic/motion_tile/roughen_edges are editorial stylize looks (a blocky "
        "posterise, a tiled photo replicate, a roughened silhouette) — reach for "
        "them sparingly, only when a graphic, treated feel genuinely suits the "
        "moment. photo_treatment_intensity tunes how strong any grade reads: use "
        "-1 (auto) for most cards to size it off the card's decoration strength, "
        "and 0..1 only when you want to dial a specific grade up or down.\n"
        "Choose the archetype that fits the moment (a medal → spotlight; a standout "
        "time with no photo → big_number or minimal poster; a great photo → "
        "full-bleed or diagonal). Lead with the most newsworthy hero_stat. Pick "
        "motion_intent count_up when the time or number itself is the story. Reach "
        "for the livelier languages only when the moment earns it: bounce_in or "
        "swirl for a celebratory win, flip_reveal or reveal_from_sides for a single "
        "standout stat, cascade when several facts share the card. rise is a calm "
        "lift for understated results, pop a confident scale punch, drop_in a "
        "decisive arrival from above. text_scramble decodes the result string "
        "with a typewriter/scramble effect that lands on the exact value — reach "
        "for it when a headline time or number is the whole story.\n"
        "accent_treatment is the margin accent the card carries on the still AND "
        "its motion render: the sizing variants (thick/thin/double stripe, "
        "large/small brackets, bracket_frame, corner_tabs, offset_badge, "
        "side_rail) scale the accent to the moment — minimal means none.\n"
        "photo_treatment is normally cutout (clean). Reach for duotone or "
        "halftone only when an editorial, monochrome grade suits the mood, and "
        "vignette to pull focus onto the athlete — never to disguise a weak "
        "photo, and never on a card without one.\n"
        "crop_intent smart hands framing to the smartcrop scorer: it picks the "
        "zoom, places the subject on a rule-of-thirds line, and punches in on a "
        "distant subject — a strong default when you want editorial framing but "
        "have no specific crop in mind."
    )


def _photo_context(photo_facts: Optional[dict]) -> str:
    """One prompt line stating what photography this card really has (M7).

    The director's archetype guidance ("a great photo → full-bleed") is only
    honest when it knows whether a photo exists. Facts are resolved by the
    caller from the media library BEFORE direction — never guessed here.
    Returns "" when the caller resolved nothing (legacy paths).
    """
    if not isinstance(photo_facts, dict):
        return ""
    if not photo_facts.get("has_photo"):
        return "PHOTO: none available — pick a type-led composition; never a photo-led stage."
    bits = []
    asset_type = str(photo_facts.get("asset_type") or "").strip()
    orientation = str(photo_facts.get("orientation") or "").strip()
    if orientation and orientation != "unknown":
        bits.append(orientation)
    bits.append(asset_type.replace("_", " ") if asset_type else "athlete photo")
    line = f"PHOTO: a real {' '.join(bits)} of the subject is available"
    try:
        count = int(photo_facts.get("person_photo_count") or 0)
    except (TypeError, ValueError):
        count = 0
    if count > 1:
        line += f" ({count} person photos in the library)"
    return line + " — lead with it where the composition earns it."


def _design_spec_user_prompt(
    summary: str,
    brand_ctx: str,
    angle: str,
    recent_archetypes: list[str],
    photo_facts: Optional[dict] = None,
) -> str:
    parts = [f"ACHIEVEMENT:\n{summary}", f"BRAND:\n{brand_ctx}"]
    photo_line = _photo_context(photo_facts)
    if photo_line:
        parts.append(photo_line)
    if angle:
        parts.append(f"ANGLE: {angle}")
    if recent_archetypes:
        parts.append(
            "RECENTLY USED archetypes (prefer a different composition for variety): "
            + ", ".join(recent_archetypes[:6])
        )
    return "\n\n".join(parts)


def ai_design_spec(
    *,
    content_item: dict,
    brand_kit,
    archetypes: list[str],
    token_roles: list[str],
    angle: str = "",
    recent_archetypes: Optional[list[str]] = None,
    photo_facts: Optional[dict] = None,
):
    """Ask the AI for a v2 ``DesignSpec`` — which archetype + emphasis + hook best
    fit THIS achievement (Tier B §5.4).

    Returns a validated :class:`creative_brief.design_spec.DesignSpec`, or ``None``
    when no provider is configured / the call fails / the response can't be parsed.
    The caller then uses the deterministic archetype picker (Tier A) as the honest
    floor — never a fabricated card. The (possibly hallucinated) model JSON is run
    through ``design_spec.normalise``, so the returned spec is always renderable and
    brand-legal even if the model ignores the schema.
    """
    if not archetypes or not token_roles:
        return None
    try:
        from mediahub.ai_core import ask, ProviderNotConfigured, ProviderError
        from mediahub.creative_brief.design_spec import normalise
    except Exception as e:
        log.debug("ai_design_spec: import failed: %s", e)
        return None

    sys = _design_spec_system_prompt(list(archetypes), list(token_roles))
    user = _design_spec_user_prompt(
        _achievement_summary(content_item),
        _brand_context(brand_kit),
        angle,
        recent_archetypes or [],
        photo_facts,
    )
    try:
        out = ask(sys, user, max_tokens=500)
    except ProviderNotConfigured:
        log.info("ai_design_spec: no provider — caller falls back to the Tier A picker")
        return None
    except ProviderError as e:
        log.warning("ai_design_spec: provider error: %s", str(e)[:300])
        return None
    except Exception as e:
        log.warning("ai_design_spec: unexpected error: %s", str(e)[:300])
        return None
    if not out:
        log.warning("ai_design_spec: provider returned empty output")
        return None
    raw = _parse_strict_json(out)
    if raw is None:
        log.warning("ai_design_spec: could not parse JSON (len=%d)", len(out or ""))
        return None
    try:
        spec = normalise(raw, archetypes=list(archetypes), token_roles=list(token_roles))
    except Exception as e:
        log.warning("ai_design_spec: normalise failed: %s", e)
        return None
    log.debug(
        "ai_design_spec: archetype=%s hero_stat=%s mood=%s",
        spec.archetype,
        spec.hero_stat,
        spec.mood,
    )
    return spec


def ai_design_specs(
    *,
    content_item: dict,
    brand_kit,
    archetypes: list[str],
    token_roles: list[str],
    angle: str = "",
    recent_archetypes: Optional[list[str]] = None,
    count: int = 5,
    photo_facts: Optional[dict] = None,
):
    """One call → ``count`` mutually-distinct validated DesignSpecs (Tier B §5.5).

    The candidate-pool builder asks for the whole pool in a single response so
    the model sees — and is held to — the distinctness rule (the same lesson as
    the old batch menu-picker learned: N parallel identical prompts return the
    same "best" answer N times). Every object is run through ``design_spec.normalise``
    so each returned spec is renderable and brand-legal regardless of what the
    model emitted; client-side dedupe drops repeated archetypes.

    Returns a list of specs (possibly shorter than ``count`` if the model
    under-delivers — the caller fills the gap with the deterministic Tier A
    picker), or ``None`` when no provider is configured / the call fails.
    """
    if not archetypes or not token_roles:
        return None
    try:
        from mediahub.ai_core import ask, ProviderNotConfigured, ProviderError
        from mediahub.creative_brief.design_spec import normalise
    except Exception as e:
        log.debug("ai_design_specs: import failed: %s", e)
        return None

    count = max(2, min(int(count or 5), 6))
    sys = (
        _design_spec_system_prompt(list(archetypes), list(token_roles))
        + "\n\nPOOL MODE: return a JSON ARRAY of exactly "
        + str(count)
        + " spec objects (schema above). Hard pool rules:\n"
        + "- Every object must use a DIFFERENT archetype.\n"
        + "- Vary the emphasis: do not give "
        + str(count)
        + " variations of one idea — different hero_stat / focal_element / "
        + "mood across the pool.\n"
        + "- Output the JSON array ONLY."
    )
    user = _design_spec_user_prompt(
        _achievement_summary(content_item),
        _brand_context(brand_kit),
        angle,
        recent_archetypes or [],
        photo_facts,
    )
    try:
        out = ask(sys, user, max_tokens=350 * count)
    except ProviderNotConfigured:
        log.info("ai_design_specs: no provider — caller falls back to the Tier A picker")
        return None
    except ProviderError as e:
        log.warning("ai_design_specs: provider error: %s", str(e)[:300])
        return None
    except Exception as e:
        log.warning("ai_design_specs: unexpected error: %s", str(e)[:300])
        return None
    if not out:
        log.warning("ai_design_specs: provider returned empty output")
        return None
    arr = _parse_strict_json_array(out)
    if not arr:
        log.warning("ai_design_specs: could not parse JSON array (len=%d)", len(out or ""))
        return None

    specs = []
    seen_archetypes: set[str] = set()
    for raw in arr[: count + 2]:
        try:
            spec = normalise(raw, archetypes=list(archetypes), token_roles=list(token_roles))
        except Exception as e:
            log.warning("ai_design_specs: normalise failed: %s", e)
            continue
        if spec.archetype in seen_archetypes:
            continue
        seen_archetypes.add(spec.archetype)
        specs.append(spec)
        if len(specs) >= count:
            break
    log.info(
        "ai_design_specs: pool returned %d/%d usable specs: %s",
        len(specs),
        count,
        [(s.archetype, s.hero_stat) for s in specs],
    )
    return specs or None


__all__ = [
    "ai_design_spec",
    "ai_design_specs",
]
