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
    # E2 (Canva gap analysis) — hand the crop to the smartcrop-style scorer:
    # multi-scale candidate scoring picks the zoom, rule-of-thirds placement is
    # the default (centred for symmetric archetypes), and a distant subject is
    # punched in. Deterministic; executed by ``saliency.smart_focus``.
    "smart",
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
    # R1.5 accent expansion pack — sizing/style variants of the base accents.
    # Each token is executed by BOTH surfaces: the still engine
    # (graphic_renderer.render._accent_decoration_html) and its motion twin
    # under remotion/.../sprint/accents/<token>.tsx (registry contract:
    # the file's exported name IS this brief token).
    "thick_stripe",
    "thin_stripe",
    "double_stripe",
    "side_rail",
    "large_brackets",
    "small_brackets",
    "bracket_frame",
    "corner_tabs",
    "offset_badge",
    # B6 (Canva gap analysis) — the frosted-glass treatment: a translucent,
    # brand-tinted panel over the photo. Executed by BOTH surfaces (still:
    # render._accent_decoration_html margin pill + the v2 modules' --mh-glass-*
    # tokens; motion: sprint/accents/glass_chip.tsx). APCA-gated in Python.
    "glass_chip",
)

# R1.10 — the photo grades the director may request. Executed in lock-step on
# both surfaces: the still applies ``render._photo_treatment_css`` and the
# motion render the matching backdrop-filter grade
# (remotion/.../sprint/layers/photo_filters.tsx). "cutout" is the clean
# default (no grade). Structural values ("no-photo", "frame") are deliberately
# NOT offered here: whether a card carries a photo is a pipeline/caller
# decision, never an art-direction whim.
#
# Canva gap analysis additions (B5/C5): "wash" is the soft brand colour-wash
# between raw photo and full duotone (partial desaturation + a bounded mix
# toward the deep brand primary — the treatment that makes mixed club
# photography read as one commissioned campaign); "sticker" traces the cutout
# silhouette with a die-cut contour in the card's on-ground ink (which also
# masks background-removal edge fringe). Both are still-authoritative; the
# motion side carries wash as a saturation grade and treats sticker as
# structural until the outline parameters are plumbed into the props.
PHOTO_TREATMENTS: tuple[str, ...] = (
    "cutout",
    "duotone",
    "halftone",
    "vignette",
    "wash",
    "sticker",
)

# E4 (Canva gap analysis) — the shaped photo-frame the director may request on
# the three windowed-photo archetypes (photo_passepartout / spotlight_disc /
# full_height_portrait_split). "rect" is the raw rectangular window (the
# default, byte-identical to the pre-lever render); the others reshape the photo
# window and pair it with an offset accent echo. Executed still-side by
# ``render._photo_frame_shape_assets`` and mirrored as static geometry in the
# motion scenes (``StoryCard.tsx`` + ``sprint/scenes``). Kept identical to
# ``graphic_renderer.photo_frame.PHOTO_FRAME_SHAPES`` by ``tests/test_photo_frame.py``.
PHOTO_FRAME_SHAPES: tuple[str, ...] = ("rect", "arch", "blob", "torn_edge")

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
    # 1.5 motion-vocabulary pack — same sprint-intents seam, but each programme
    # is *compiled* from the tokenised vocabulary (mediahub.motion.vocabulary)
    # via remotion/src/motion/compile.ts, so the movement is identical on the
    # CSS surface and in the reel. Widens the director's vocabulary (1.5).
    "rise",
    "pop",
    "drop_in",
)

# 1.9 — text-effect tokens. The slots a per-text effect can be requested on
# (mapped to the renderer's substituted text values), and the closed effect
# vocabulary. The renderer (``graphic_renderer.text_effects``) is the authority
# that executes each effect and polices it with the APCA gate; this list is kept
# identical to ``text_effects.TEXT_EFFECTS`` by ``tests/test_text_effects.py`` so
# the director can never request an effect the renderer cannot run.
TEXT_EFFECT_SLOTS: tuple[str, ...] = ("headline", "result", "kicker", "event", "meta")
TEXT_EFFECTS: tuple[str, ...] = (
    "none",
    "shadow",
    "lift",
    "hollow",
    "outline",
    "splice",
    "echo",
    "glitch",
    "neon",
    "background",
    "gradient",
    "extrude",
    "warp",
    "curve",
)
DEFAULT_TEXT_EFFECT = "none"

# D6 — per-word emphasis (the two-tone headline). The director may name ONE word
# of a slot to highlight and pick a treatment. Kept identical to
# ``text_effects.EMPHASIS_STYLES`` by ``tests/test_text_effects.py`` (the renderer
# is the authority that executes each). ``emphasis_word`` is fact-gated at apply
# time — kept only when it whole-word matches the slot's actual value — exactly
# like ``hero_stat`` is gated against the measured ``hero_stat_options``, so a
# hallucinated word simply never wraps and the card stays byte-identical.
EMPHASIS_STYLES: tuple[str, ...] = ("accent_ink", "accent_pill", "heavy")
DEFAULT_EMPHASIS_STYLE = "accent_ink"
MAX_EMPHASIS_WORD_LEN = 48

# Safe defaults — each MUST be a member of its vocabulary above. These are the
# values an out-of-vocabulary (hallucinated) field falls back to: every one is
# renderable without depending on an optional asset.
DEFAULT_FOCAL_ELEMENT = "big_number"
DEFAULT_CROP_INTENT = "centered"
DEFAULT_HERO_STAT = "final_time"
DEFAULT_ACCENT_TREATMENT = "minimal"
DEFAULT_PHOTO_TREATMENT = "cutout"
DEFAULT_PHOTO_FRAME_SHAPE = "rect"
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
    # R1.10 — the requested photo grade (PHOTO_TREATMENTS). "cutout" (the
    # default) asks for no grade, so an older spec dict without the field
    # normalises to a byte-identical card.
    photo_treatment: str = DEFAULT_PHOTO_TREATMENT
    # E4 — the shaped photo frame for the windowed archetypes (PHOTO_FRAME_SHAPES).
    # "rect" (the default) is the raw rectangular window, so an older spec dict
    # without the field normalises to a byte-identical card.
    photo_frame_shape: str = DEFAULT_PHOTO_FRAME_SHAPE
    # 1.9 — per-slot text effects as a hashable, sorted (slot, effect) tuple.
    # Only non-"none" effects on known slots survive ``normalise``; an empty
    # tuple (the default) means the card carries no effects and renders
    # byte-identically. Stored as a tuple (not a dict) so DesignSpec stays
    # frozen-hashable like its other fields.
    text_effects: tuple[tuple[str, str], ...] = ()
    # D6 — the optional accent word + its treatment (the two-tone headline). An
    # empty ``emphasis_word`` (the default) means no per-word emphasis, so an
    # older spec dict without the fields normalises to a byte-identical card.
    emphasis_word: str = ""
    emphasis_style: str = DEFAULT_EMPHASIS_STYLE

    def text_effects_map(self) -> dict[str, str]:
        """The text effects as a ``slot -> effect`` dict (renderer-facing shape)."""
        return {slot: effect for slot, effect in self.text_effects}

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
            "photo_treatment": self.photo_treatment,
            "photo_frame_shape": self.photo_frame_shape,
            "text_effects": self.text_effects_map(),
            "emphasis_word": self.emphasis_word,
            "emphasis_style": self.emphasis_style,
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


def _coerce_emphasis_word(value: Any) -> str:
    """Clean an emphasis word to a single bounded token (or ``""``).

    Vocabulary validity only: strips to the first whitespace-delimited token and
    bounds its length. The authoritative FACT gate — that the word actually
    occurs as a whole word in the slot it decorates — runs at apply time in the
    renderer (``text_effects.emphasise_value``), exactly as ``hero_stat`` is
    gated against the measured ``hero_stat_options``. So a word the card never
    contains silently produces no emphasis and the card stays byte-identical.
    """
    if not isinstance(value, str):
        return ""
    tokens = value.strip().split()
    if not tokens:
        return ""
    return tokens[0][:MAX_EMPHASIS_WORD_LEN]


def _coerce_text_effects(value: Any) -> tuple[tuple[str, str], ...]:
    """Coerce a raw ``{slot: effect}`` map into validated, sorted pairs.

    Unknown slots and unknown/"none" effects are dropped, so a hallucinated or
    partial map can only ever produce effects the renderer can run. Sorted by
    slot for a deterministic, hashable result.
    """
    if not isinstance(value, dict):
        return ()
    out: dict[str, str] = {}
    for slot, effect in value.items():
        s = _match_enum(slot, TEXT_EFFECT_SLOTS)
        e = _match_enum(effect, TEXT_EFFECTS)
        if s is None or e is None or e == "none":
            continue
        out[s] = e
    return tuple(sorted(out.items()))


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
        photo_treatment=_coerce_enum(
            data.get("photo_treatment"), PHOTO_TREATMENTS, DEFAULT_PHOTO_TREATMENT
        ),
        photo_frame_shape=_coerce_enum(
            data.get("photo_frame_shape"), PHOTO_FRAME_SHAPES, DEFAULT_PHOTO_FRAME_SHAPE
        ),
        text_effects=_coerce_text_effects(data.get("text_effects")),
        emphasis_word=_coerce_emphasis_word(data.get("emphasis_word")),
        emphasis_style=_coerce_enum(
            data.get("emphasis_style"), EMPHASIS_STYLES, DEFAULT_EMPHASIS_STYLE
        ),
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
            "photo_treatment": {"type": "string", "enum": list(PHOTO_TREATMENTS)},
            "photo_frame_shape": {"type": "string", "enum": list(PHOTO_FRAME_SHAPES)},
            "text_effects": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    slot: {"type": "string", "enum": list(TEXT_EFFECTS)}
                    for slot in TEXT_EFFECT_SLOTS
                },
            },
            # D6 — the two-tone headline. An empty ``emphasis_word`` ⇒ no
            # per-word emphasis (byte-identical); ``normalise`` fills both
            # defaults, so an older dict without them still validates.
            "emphasis_word": {"type": "string", "maxLength": MAX_EMPHASIS_WORD_LEN},
            "emphasis_style": {"type": "string", "enum": list(EMPHASIS_STYLES)},
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
            "photo_treatment",
            "photo_frame_shape",
            "text_effects",
            # D6 — required like every other spec field (normalise fills the
            # "" / accent_ink defaults, so an older dict still validates).
            "emphasis_word",
            "emphasis_style",
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
    "PHOTO_TREATMENTS",
    "PHOTO_FRAME_SHAPES",
    "LOGO_LOCKUPS",
    "MOODS",
    "MOTION_INTENTS",
    "TEXT_EFFECT_SLOTS",
    "TEXT_EFFECTS",
    "DEFAULT_TEXT_EFFECT",
    "EMPHASIS_STYLES",
    "DEFAULT_EMPHASIS_STYLE",
    "MAX_EMPHASIS_WORD_LEN",
    "DEFAULT_FOCAL_ELEMENT",
    "DEFAULT_CROP_INTENT",
    "DEFAULT_HERO_STAT",
    "DEFAULT_ACCENT_TREATMENT",
    "DEFAULT_PHOTO_TREATMENT",
    "DEFAULT_PHOTO_FRAME_SHAPE",
    "DEFAULT_LOGO_LOCKUP",
    "DEFAULT_MOOD",
    "DEFAULT_MOTION_INTENT",
    "MAX_SECONDARY_STATS",
    "MAX_HOOK_LEN",
    "MAX_RATIONALE_LEN",
]
