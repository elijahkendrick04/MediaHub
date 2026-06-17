"""The design-spec contract and validator (thesis §5.4, Tier B).

The LLM art-director (a later task) emits a JSON object describing *how* a
card should be composed — which archetype, which colour roles, what to
emphasise, what mood. This module is the **contract** that sits between
that (possibly hallucinated) model output and the deterministic renderer.

It does two things and nothing else:

* :class:`DesignSpec` — the typed shape the renderer consumes.
* :func:`normalise` — coerce an arbitrary ``dict`` (a real LLM response, a
  truncated one, or pure garbage) into a *valid* ``DesignSpec`` where every
  field is either a known enum value, a supplied token-role name, or cleaned
  generated copy. Any out-of-vocabulary value falls back to a safe default,
  so a bad LLM response can never produce an illegal or illegible card.

There is **no live LLM call here** — this is the schema + validator only.
:func:`design_spec_json_schema` returns the JSON-schema dict a caller can
hand to a provider for schema-constrained decoding.

Legibility note: ``normalise`` guarantees *vocabulary validity* (no raw hex,
no invented archetype reaches the renderer). It deliberately does **not**
judge contrast/legibility between the chosen colour roles — that is the
deterministic brand-compliance gate's job (thesis §5.5, separate task),
which reuses the existing APCA/ΔE2000 maths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

# ---------------------------------------------------------------------------
# Closed vocabularies (the renderer knows how to execute each value).
#
# ``archetype`` and the four ``colour_roles`` are NOT fixed here: they are
# injected per-call via ``normalise(..., archetypes=, token_roles=)`` because
# the archetype library (Tier A) and the brand-token contract (Layer 1) are
# owned by other modules. Everything below is a renderer-internal enum.
# ---------------------------------------------------------------------------

COLOUR_ROLE_SLOTS: tuple[str, ...] = ("ground", "surface", "headline", "accent")

FOCAL_ELEMENTS: tuple[str, ...] = (
    "athlete_cutout",
    "athlete_photo",
    "team_photo",
    "action_photo",
    "big_number",
    "medal",
    "trophy",
    "logo",
    "none",
)

CROP_INTENTS: tuple[str, ...] = (
    "tight_portrait",
    "rule_of_thirds_action",
    "wide_action",
    "centered",
    "full_bleed",
    "original",
)

# Emphasis angles the deterministic ranker can surface (thesis §5.3.1 #4).
# hero_stat picks one; secondary_stats lists supporting ones.
STAT_KEYS: tuple[str, ...] = (
    "final_time",
    "pb_delta",
    "placing",
    "relay_split",
    "event",
    "split_time",
    "season_best",
    "age_group",
    "points",
)

ACCENT_TREATMENTS: tuple[str, ...] = (
    "brackets",
    "stripe",
    "badge",
    "frame",
    "minimal",
    "ribbon",
    "arrow",
    "underline",
    "diagonal_underline",
)

LOGO_LOCKUPS: tuple[str, ...] = (
    "full_horizontal",
    "full_stacked",
    "mono_light",
    "mono_dark",
    "icon",
)

MOODS: tuple[str, ...] = (
    "neutral",
    "explosive",
    "electric",
    "calm",
    "fierce",
    "celebratory",
    "stoic",
    "precise",
    "warm",
    "bold",
    "triumphant",
    "minimal",
)

MOTION_INTENTS: tuple[str, ...] = (
    "fade_in",
    "snap_in_then_settle",
    "slide_up",
    "scale_in",
    "crossfade",
    "kinetic_type",
    "parallax",
    "count_up",
    "static",
    # R1.1 motion-intent program pack — each executed by its own auto-discovered
    # file under remotion/.../sprint/intents/<name>.ts (no StoryCard.tsx switch
    # edit); the default branch of animProgram() looks them up via EXTRA_INTENTS.
    "bounce_in",
    "flip_reveal",
    "swirl",
    "reveal_from_sides",
    "cascade",
)

# Safe defaults — each MUST be a member of its vocabulary above. These are the
# values an out-of-vocabulary (hallucinated) field falls back to: every one is
# renderable without depending on an optional asset.
DEFAULT_FOCAL_ELEMENT = "big_number"
DEFAULT_CROP_INTENT = "centered"
DEFAULT_HERO_STAT = "final_time"
DEFAULT_ACCENT_TREATMENT = "minimal"
DEFAULT_LOGO_LOCKUP = "icon"
DEFAULT_MOOD = "neutral"
DEFAULT_MOTION_INTENT = "fade_in"

# Bounds on the free-text / list fields so a runaway model response can never
# break a layout or bloat a payload.
MAX_SECONDARY_STATS = 4
MAX_HOOK_LEN = 80
MAX_RATIONALE_LEN = 400


# ---------------------------------------------------------------------------
# Typed spec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColourRoles:
    """Which token *role* (never a hex) plays each compositional slot."""

    ground: str
    surface: str
    headline: str
    accent: str

    def to_dict(self) -> dict[str, str]:
        return {
            "ground": self.ground,
            "surface": self.surface,
            "headline": self.headline,
            "accent": self.accent,
        }


@dataclass(frozen=True)
class DesignSpec:
    """A validated art-direction the renderer can execute deterministically.

    Every field is a known enum value, a supplied token-role name, or cleaned
    generated copy. Construct via :func:`normalise`, not directly, so the
    vocabulary guarantees always hold.
    """

    archetype: str
    colour_roles: ColourRoles
    focal_element: str
    crop_intent: str
    hero_stat: str
    secondary_stats: tuple[str, ...]
    headline_hook: str
    accent_treatment: str
    logo_lockup: str
    mood: str
    motion_intent: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "archetype": self.archetype,
            "colour_roles": self.colour_roles.to_dict(),
            "focal_element": self.focal_element,
            "crop_intent": self.crop_intent,
            "hero_stat": self.hero_stat,
            "secondary_stats": list(self.secondary_stats),
            "headline_hook": self.headline_hook,
            "accent_treatment": self.accent_treatment,
            "logo_lockup": self.logo_lockup,
            "mood": self.mood,
            "motion_intent": self.motion_intent,
            "rationale": self.rationale,
        }


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _match_enum(value: Any, allowed: Iterable[str]) -> Optional[str]:
    """Return the canonical member of ``allowed`` matching ``value``
    (whitespace-trimmed, case-insensitive), or ``None`` if no match.

    Matching is forgiving of LLM casing/spacing ("  SPLIT_DIAGONAL_HERO ")
    but always returns the canonical spelling from ``allowed``.
    """
    if not isinstance(value, str):
        return None
    needle = value.strip().casefold()
    if not needle:
        return None
    for option in allowed:
        if option.casefold() == needle:
            return option
    return None


def _coerce_enum(value: Any, allowed: Sequence[str], default: str) -> str:
    match = _match_enum(value, allowed)
    return match if match is not None else default


def _clean_text(value: Any, *, max_len: int, oneline: bool) -> str:
    """Coerce a generated-copy field to a clean, bounded string.

    Non-strings (including ``None``, numbers, dicts) become ``""`` — generated
    copy is optional and an absent hook/rationale is legal, never illegible.
    """
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split()) if oneline else value.strip()
    return text[:max_len].strip()


def _coerce_stat_list(value: Any, *, exclude: str) -> tuple[str, ...]:
    """Keep only known stat keys, drop the hero stat, de-dupe, and cap length.

    A non-array value is treated as "no secondary stats" rather than guessed.
    """
    if not isinstance(value, (list, tuple)):
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        key = _match_enum(item, STAT_KEYS)
        if key is None or key == exclude or key in seen:
            continue
        seen.add(key)
        out.append(key)
        if len(out) >= MAX_SECONDARY_STATS:
            break
    return tuple(out)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalise(raw: dict, *, archetypes: list[str], token_roles: list[str]) -> DesignSpec:
    """Coerce a raw (possibly hallucinated) dict into a valid :class:`DesignSpec`.

    ``archetypes`` is the live archetype catalog (Tier A) and ``token_roles``
    the resolved brand colour-role names (Layer 1); both are injected because
    they are owned by other modules. Every other field is constrained to a
    closed vocabulary defined in this module.

    Out-of-vocabulary values (a hallucinated archetype, a raw ``#hex`` where a
    role name belongs, an invented mood) fall back to a documented safe
    default, so the returned spec is always renderable and brand-legal.

    A non-dict ``raw`` (a malformed response) yields an all-defaults spec.
    Empty ``archetypes``/``token_roles`` is a *caller* error (no valid value
    could exist) and raises ``ValueError``.
    """
    if not archetypes:
        raise ValueError("normalise() requires a non-empty `archetypes` vocabulary")
    if not token_roles:
        raise ValueError("normalise() requires a non-empty `token_roles` vocabulary")

    data: dict = raw if isinstance(raw, dict) else {}

    role_default = token_roles[0]
    roles_raw = data.get("colour_roles")
    roles_raw = roles_raw if isinstance(roles_raw, dict) else {}
    colour_roles = ColourRoles(
        ground=_coerce_enum(roles_raw.get("ground"), token_roles, role_default),
        surface=_coerce_enum(roles_raw.get("surface"), token_roles, role_default),
        headline=_coerce_enum(roles_raw.get("headline"), token_roles, role_default),
        accent=_coerce_enum(roles_raw.get("accent"), token_roles, role_default),
    )

    hero_stat = _coerce_enum(data.get("hero_stat"), STAT_KEYS, DEFAULT_HERO_STAT)

    return DesignSpec(
        archetype=_coerce_enum(data.get("archetype"), archetypes, archetypes[0]),
        colour_roles=colour_roles,
        focal_element=_coerce_enum(
            data.get("focal_element"), FOCAL_ELEMENTS, DEFAULT_FOCAL_ELEMENT
        ),
        crop_intent=_coerce_enum(data.get("crop_intent"), CROP_INTENTS, DEFAULT_CROP_INTENT),
        hero_stat=hero_stat,
        secondary_stats=_coerce_stat_list(data.get("secondary_stats"), exclude=hero_stat),
        headline_hook=_clean_text(data.get("headline_hook"), max_len=MAX_HOOK_LEN, oneline=True),
        accent_treatment=_coerce_enum(
            data.get("accent_treatment"), ACCENT_TREATMENTS, DEFAULT_ACCENT_TREATMENT
        ),
        logo_lockup=_coerce_enum(data.get("logo_lockup"), LOGO_LOCKUPS, DEFAULT_LOGO_LOCKUP),
        mood=_coerce_enum(data.get("mood"), MOODS, DEFAULT_MOOD),
        motion_intent=_coerce_enum(
            data.get("motion_intent"), MOTION_INTENTS, DEFAULT_MOTION_INTENT
        ),
        rationale=_clean_text(data.get("rationale"), max_len=MAX_RATIONALE_LEN, oneline=False),
    )


def design_spec_json_schema(*, archetypes: list[str], token_roles: list[str]) -> dict:
    """Return the JSON-schema dict for schema-constrained decoding.

    Mirrors :func:`normalise`: ``archetype`` is an enum over ``archetypes``,
    each ``colour_roles`` slot an enum over ``token_roles``, and every other
    field an enum over this module's closed vocabularies (or a bounded string
    for generated copy). Hand this to the provider so the model is constrained
    to legal values at decode time; ``normalise`` is still the authority for
    anything that slips through.
    """
    if not archetypes:
        raise ValueError("design_spec_json_schema() requires a non-empty `archetypes` vocabulary")
    if not token_roles:
        raise ValueError("design_spec_json_schema() requires a non-empty `token_roles` vocabulary")

    def role_schema() -> dict:
        return {"type": "string", "enum": list(token_roles)}

    def stat_schema() -> dict:
        return {"type": "string", "enum": list(STAT_KEYS)}

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "archetype": {"type": "string", "enum": list(archetypes)},
            "colour_roles": {
                "type": "object",
                "additionalProperties": False,
                "properties": {slot: role_schema() for slot in COLOUR_ROLE_SLOTS},
                "required": list(COLOUR_ROLE_SLOTS),
            },
            "focal_element": {"type": "string", "enum": list(FOCAL_ELEMENTS)},
            "crop_intent": {"type": "string", "enum": list(CROP_INTENTS)},
            "hero_stat": stat_schema(),
            "secondary_stats": {
                "type": "array",
                "items": stat_schema(),
                "maxItems": MAX_SECONDARY_STATS,
            },
            "headline_hook": {"type": "string", "maxLength": MAX_HOOK_LEN},
            "accent_treatment": {"type": "string", "enum": list(ACCENT_TREATMENTS)},
            "logo_lockup": {"type": "string", "enum": list(LOGO_LOCKUPS)},
            "mood": {"type": "string", "enum": list(MOODS)},
            "motion_intent": {"type": "string", "enum": list(MOTION_INTENTS)},
            "rationale": {"type": "string", "maxLength": MAX_RATIONALE_LEN},
        },
        "required": [
            "archetype",
            "colour_roles",
            "focal_element",
            "crop_intent",
            "hero_stat",
            "secondary_stats",
            "headline_hook",
            "accent_treatment",
            "logo_lockup",
            "mood",
            "motion_intent",
            "rationale",
        ],
    }


__all__ = [
    "DesignSpec",
    "ColourRoles",
    "normalise",
    "design_spec_json_schema",
    "COLOUR_ROLE_SLOTS",
    "FOCAL_ELEMENTS",
    "CROP_INTENTS",
    "STAT_KEYS",
    "ACCENT_TREATMENTS",
    "LOGO_LOCKUPS",
    "MOODS",
    "MOTION_INTENTS",
    "DEFAULT_FOCAL_ELEMENT",
    "DEFAULT_CROP_INTENT",
    "DEFAULT_HERO_STAT",
    "DEFAULT_ACCENT_TREATMENT",
    "DEFAULT_LOGO_LOCKUP",
    "DEFAULT_MOOD",
    "DEFAULT_MOTION_INTENT",
    "MAX_SECONDARY_STATS",
    "MAX_HOOK_LEN",
    "MAX_RATIONALE_LEN",
]
