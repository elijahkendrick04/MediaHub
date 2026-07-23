"""Declarative, bounded per-card motion *template* — the whole security surface.

A ``motion_template`` is a small, **flat** JSON object an operator can supply per
card (or per reel beat) that SELECTS and PARAMETERISES values MediaHub's motion
path already understands: the creative-brief art axes (motion intent, mood,
background style, accent style, typography pair, composition, photo treatment /
intensity, photo-frame shape, decoration strength, seeded blend) plus a thin
``render`` section that maps 1:1 onto knobs that are ALREADY first-class opt-in
render parameters (``format`` / ``fps`` / per-card beat ``weights`` / the
review-only ``effect_toggles``).

It is deliberately **not** an expression language, **never** ``eval`` / ``exec``,
and it can name **only** members of the closed vocabularies the renderer already
enforces. Every value is validated against the same allowlist / clamp the
existing code uses; an unknown key or out-of-vocabulary value is a hard
:class:`MotionTemplateError` (an honest error, never a silent guess, never an LLM
fix-up). This is the opposite policy to ``design_spec.normalise`` — which
*silently defaults* a hallucinated model field. A model's guess deserves a safe
default; an **operator's typo deserves a loud error**.

Architecture (why this touches zero TSX/TS/CSS): every art axis below is a key
``motion._card_to_props`` (and its helpers) already reads off the brief dict, and
the free FFmpeg engine rehydrates a ``CreativeBrief`` from that same dict — so the
template is nothing more than a **validated dict merged into the brief before
render**. An absent / empty template returns the brief object *unchanged* ⇒
byte-identical to today. It needs no composition-revision bump and does not touch
``renderer_generation()``.

v1 scope — **preview / A-B only.** The route wiring merges a template into the
brief ONLY at motion-render time (exactly like the review-only ``effect_toggles``
path); it never regenerates or re-persists the STILL. So a templated MP4 is a
*preview*, not the approved / exported artifact, and the approved card's
still↔motion parity is untouched. Structural, pack-level decisions
(archetype / layout_template / style_pack) are excluded from v1 — they reshape the
card and are a pack decision, not a per-render whim.

Security: a closed top-level schema (unknown key ⇒ raise), each field validated
against a closed allowlist sourced from the canonical registries, and an emitted
``art`` dict that can only ever set the fixed set of enum / clamped-float / bool
brief keys — none of them a path / URI / colour / role field — so ``{**brief,
**art}`` can never inject an arbitrary brief key, a file path, a data URI, or an
off-brand colour. No ``eval`` / ``exec``, no ``getattr`` on operator strings, no
LLM anywhere.
"""

from __future__ import annotations

from typing import Any, Optional

from mediahub.creative_brief.design_spec import (
    ACCENT_TREATMENTS,
    MOODS,
    MOTION_INTENTS,
    PHOTO_FRAME_SHAPES,
    PHOTO_TREATMENTS,
    UNSET_PHOTO_TREATMENT_INTENSITY,
    _match_enum,
)
from mediahub.graphic_renderer.type_pairs import PAIR_IDS

__all__ = [
    "MOTION_TEMPLATE_VERSION",
    "MotionTemplateError",
    "BACKGROUND_STYLE_KEYS",
    "COMPOSITION_KEYS",
    "validate_motion_template",
    "brief_overrides_from_template",
    "merge_into_brief",
    "render_kwargs_from_template",
]

MOTION_TEMPLATE_VERSION = 1


class MotionTemplateError(ValueError):
    """A bad operator-supplied motion template. A subclass of ``ValueError`` so
    generic ``except ValueError`` still catches it, but a distinct type the web
    route can map to an honest HTTP 400 (``bad_motion_template``)."""


# ---------------------------------------------------------------------------
# Local allowlists — the two art axes that have no exported registry tuple.
#
# Transcribed from the still renderer and guarded by a sync test
# (``tests/test_motion_template.py``) so a ground / composition added to (or
# removed from) ``graphic_renderer.render`` can never leave the template
# offering a value the renderer silently maps to its default (a quiet parity
# drift). See ``render._background_pattern_for`` and
# ``render._composition_overrides_css``.
# ---------------------------------------------------------------------------

# The exact keys of the ``builders`` dict in ``render._background_pattern_for``
# plus the gradient-mesh trigger spellings the function special-cases before the
# dict lookup. ``water`` is both a real builder key AND the fallback default, so
# selecting it is legal (byte-identical to leaving the axis unset).
BACKGROUND_STYLE_KEYS: tuple[str, ...] = (
    "checkerboard",
    "circuit",
    "clean",
    "concentric",
    "diagonal",
    "diamonds",
    "dither",
    "dots",
    "duotone",
    "geometric",
    "gradient-mesh",
    "gradient_mesh",
    "grain",
    "halftone",
    "hexmesh",
    "mesh",
    "organic-waves",
    "organic_waves",
    "radial",
    "stripes",
    "water",
)

# The branches ``render._composition_overrides_css`` handles: ``left`` / ``center``
# / ``off-center`` explicitly, plus ``right`` (its default — ``(composition or
# "right")`` returns the empty override). Selecting ``right`` is legal
# (byte-identical to leaving the axis unset).
COMPOSITION_KEYS: tuple[str, ...] = ("center", "left", "off-center", "right")


# ---------------------------------------------------------------------------
# The closed, flat top-level schema.
#
# Input is a FLAT dict mixing art + render keys (e.g.
# ``{"motion_intent": "...", "fps": 60}``); the validated output is sectioned
# into ``{"art": {...}, "render": {...}}``. Every top-level key must be one of
# these — an unknown key (a colour, a role, a seed, a file path, an arbitrary
# brief field) is a hard error, which is the security guarantee.
# ---------------------------------------------------------------------------

# key (== the brief key both surfaces read) -> the closed allowlist tuple.
_ART_ENUM_KEYS: dict[str, tuple[str, ...]] = {
    "motion_intent": MOTION_INTENTS,
    "mood": MOODS,
    "background_style": BACKGROUND_STYLE_KEYS,
    "accent_style": ACCENT_TREATMENTS,
    "typography_pair": PAIR_IDS,
    "composition": COMPOSITION_KEYS,
    "photo_treatment": PHOTO_TREATMENTS,
    "photo_frame_shape": PHOTO_FRAME_SHAPES,
}
# Clamped to the unit interval [0, 1] (the exact range the renderer enforces).
_ART_FLOAT01_KEYS: frozenset[str] = frozenset({"decoration_strength", "photo_treatment_intensity"})
# Strict booleans (operator input — no truthy-string coercion).
_ART_BOOL_KEYS: frozenset[str] = frozenset({"seeded_blend"})
# The thin render section — each maps onto an EXISTING opt-in render kwarg.
_RENDER_KEYS: frozenset[str] = frozenset({"format", "fps", "weights", "effect_toggles"})

_VERSION_KEY = "version"


def _validate_enum(key: str, value: Any, allowed: tuple[str, ...]) -> str:
    """Return the canonical member of ``allowed`` matching ``value`` (case /
    space tolerant, via the shared ``design_spec._match_enum``), else raise.

    ``_match_enum`` returns the CANONICAL spelling (never an index pick), so
    appending a member to a vocabulary can never shift an existing template's
    meaning.
    """
    match = _match_enum(value, allowed)
    if match is None:
        raise MotionTemplateError(f"{key}={value!r} is not one of {list(allowed)!r}")
    return match


def _validate_float01(key: str, value: Any) -> float:
    """Coerce a strength field to a float clamped into ``[0, 1]``.

    A non-numeric value raises. ``bool`` is rejected explicitly (it is an ``int``
    subclass and never a meaningful strength). For ``photo_treatment_intensity``
    the sentinel ``UNSET_PHOTO_TREATMENT_INTENSITY`` (-1.0, meaning "auto — size
    the grade off ``decoration_strength``") is FORBIDDEN as an input: absence is
    the only channel for "auto", so an operator can never re-express it and then
    surprise the parity contract.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MotionTemplateError(f"{key}={value!r} must be a number in [0, 1]")
    num = float(value)
    if key == "photo_treatment_intensity" and num == float(UNSET_PHOTO_TREATMENT_INTENSITY):
        raise MotionTemplateError(
            "photo_treatment_intensity cannot be the -1.0 'auto' sentinel; "
            "omit the field to get auto (size the grade off decoration_strength)"
        )
    return max(0.0, min(1.0, num))


def _validate_bool(key: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise MotionTemplateError(f"{key}={value!r} must be a boolean (true/false)")
    return value


def _validate_render_format(value: Any) -> str:
    """A named output cut from the closed ``MOTION_FORMATS`` vocabulary.

    Deliberately named-presets-only (no arbitrary ``WxH`` token): the template's
    ``render`` section speaks the closed vocabulary. Arbitrary canvases stay a
    query-string concern on the route. Raises on any unknown name.
    """
    from mediahub.visual.motion import MOTION_FORMATS

    if not isinstance(value, str) or value not in MOTION_FORMATS:
        raise MotionTemplateError(f"format={value!r} is not one of {sorted(MOTION_FORMATS)!r}")
    return value


def _validate_render_fps(value: Any) -> int:
    """A frame rate from the curated ``ALLOWED_FPS`` set. Reuses motion's own
    loud ``_validate_fps`` (which rejects bools / floats / off-set ints), wrapped
    so the failure is a :class:`MotionTemplateError` the route maps to a 400."""
    from mediahub.visual.motion import _validate_fps

    try:
        return _validate_fps(value)
    except ValueError as e:
        raise MotionTemplateError(str(e)) from e


def _validate_render_weights(value: Any) -> list[float]:
    """A per-card beat-weight list (raw, unfitted — ``normalise_reel_rhythm``
    fits it to the card count at render time). Each entry must be a real number;
    bools and non-numerics raise. An empty list raises (it asks for nothing)."""
    if not isinstance(value, (list, tuple)) or isinstance(value, (str, bytes)):
        raise MotionTemplateError(f"weights={value!r} must be a list of numbers")
    out: list[float] = []
    for w in value:
        if isinstance(w, bool) or not isinstance(w, (int, float)):
            raise MotionTemplateError(f"weights entry {w!r} must be a number")
        out.append(float(w))
    if not out:
        raise MotionTemplateError("weights must be a non-empty list of numbers")
    return out


def _validate_render_effect_toggles(value: Any) -> list[str]:
    """The decorative axes to SUPPRESS for an A/B comparison — the LIST /
    ``review_ab`` form (NOT the brief's ``{key: bool}`` dict form).

    Membership-checks each key against ``EFFECT_TOGGLE_ALLOWLIST`` ITSELF and
    RAISES on any unknown key. This is the mandatory difference from
    ``motion._validate_effect_toggles``, which silently DROPS unknown keys — a
    coerce-and-drop that would swallow an operator typo. Returns a sorted, unique
    list (so it keys the cache stably), ready to hand straight to ``review_ab``.
    """
    from mediahub.visual.motion import EFFECT_TOGGLE_ALLOWLIST

    if not isinstance(value, (list, tuple)) or isinstance(value, (str, bytes)):
        raise MotionTemplateError(f"effect_toggles={value!r} must be a list of effect keys")
    allowed = set(EFFECT_TOGGLE_ALLOWLIST)
    out: set[str] = set()
    for k in value:
        if not isinstance(k, str) or k not in allowed:
            raise MotionTemplateError(f"effect_toggles key {k!r} is not one of {sorted(allowed)!r}")
        out.add(k)
    return sorted(out)


# The render-section dispatch: each key in ``_RENDER_KEYS`` maps to its loud
# validator. Keeping it a table (rather than an elif ladder) means the closed
# ``_RENDER_KEYS`` vocabulary is the single source of truth for what the render
# section accepts.
_RENDER_VALIDATORS = {
    "format": _validate_render_format,
    "fps": _validate_render_fps,
    "weights": _validate_render_weights,
    "effect_toggles": _validate_render_effect_toggles,
}
assert set(_RENDER_VALIDATORS) == _RENDER_KEYS  # keep the table and the schema in lock-step


def validate_motion_template(raw: Any) -> Optional[dict]:
    """Validate an operator's motion template into a canonical sectioned dict.

    Returns ``None`` for a falsy / empty template, or one whose every section
    validates to empty ⇒ byte-identical to today. Otherwise a canonical
    ``{"art": {...}, "render": {...}}`` dict (each section present only when
    non-empty, keys sorted) containing ONLY the keys the operator actually set,
    each validated / clamped / canonicalised.

    Raises :class:`MotionTemplateError` on: a non-dict, an unknown top-level key,
    a wrong ``version``, an enum value not in its allowlist, a non-numeric float
    field (or the forbidden ``photo_treatment_intensity`` -1.0 sentinel), a bad
    ``fps`` / ``format``, a bad ``weights`` list, or an unknown ``effect_toggles``
    key. Every failure is loud — the opposite of ``design_spec.normalise``'s
    silent defaulting, which is correct for hallucinated model output but wrong
    for operator input.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise MotionTemplateError(f"motion template must be an object, got {type(raw).__name__}")
    if not raw:
        return None

    art: dict[str, Any] = {}
    render: dict[str, Any] = {}

    for key, value in raw.items():
        if key == _VERSION_KEY:
            # ``bool`` is an ``int`` subclass (True == 1 == VERSION); reject it.
            if isinstance(value, bool) or value != MOTION_TEMPLATE_VERSION:
                raise MotionTemplateError(
                    f"unsupported template version {value!r}; expected {MOTION_TEMPLATE_VERSION}"
                )
            continue
        if key in _ART_ENUM_KEYS:
            art[key] = _validate_enum(key, value, _ART_ENUM_KEYS[key])
        elif key in _ART_FLOAT01_KEYS:
            art[key] = _validate_float01(key, value)
        elif key in _ART_BOOL_KEYS:
            art[key] = _validate_bool(key, value)
        elif key in _RENDER_KEYS:
            render[key] = _RENDER_VALIDATORS[key](value)
        else:
            raise MotionTemplateError(f"unknown motion-template key {key!r}")

    out: dict[str, dict] = {}
    if art:
        out["art"] = dict(sorted(art.items()))
    if render:
        out["render"] = dict(sorted(render.items()))
    if not out:
        return None
    return out


def brief_overrides_from_template(t: Optional[dict]) -> dict:
    """The validated ``art`` sub-dict (the exact brief keys ``_card_to_props`` and
    its helpers read), or ``{}``. Never mutates ``t``."""
    if not t:
        return {}
    return dict(t.get("art") or {})


def merge_into_brief(brief: Optional[dict], t: Optional[dict]) -> Optional[dict]:
    """Overlay a template's validated art overrides onto a card brief.

    Returns the SAME ``brief`` object (object identity) when ``t`` is
    ``None`` / carries no art overrides ⇒ byte-identical at the render seam. When
    there ARE overrides, returns a NEW dict ``{**(brief or {}), **art}`` — only
    the keys the template set are overlaid, so every other brief field (and every
    downstream reader, both engines) is untouched. ``brief`` may be ``None``: a
    template-only card yields a minimal overrides-only dict, which
    ``_card_to_props`` already tolerates (every field is a ``b.get(...)`` with a
    safe fallback).
    """
    art = brief_overrides_from_template(t)
    if not art:
        return brief
    base = dict(brief) if isinstance(brief, dict) else {}
    base.update(art)
    return base


def render_kwargs_from_template(t: Optional[dict], *, n_cards: int = 1) -> dict:
    """Map the validated ``render`` section onto the EXISTING render kwargs.

    Emits only the keys the operator actually set, so an absent field lets the
    caller's own default stand::

        format         -> format_name (a named MOTION_FORMATS cut)
        fps            -> fps         (a curated ALLOWED_FPS rate)
        effect_toggles -> review_ab   (already-validated LIST of axes to suppress)
        weights        -> rhythm      ({"weights": [...]} through normalise_reel_rhythm)

    ``weights`` folds only when ``normalise_reel_rhythm(n_cards)`` returns
    non-``None`` (an effectively-default weight list asks for nothing and is
    dropped), so the reel's byte-identity / cache-fold behaviour is inherited
    unchanged. No new cache key is introduced here — each of these already folds
    only-when-non-default inside ``render_story_card`` / ``render_meet_reel``.
    """
    if not t:
        return {}
    render = t.get("render") or {}
    out: dict[str, Any] = {}
    if "format" in render:
        out["format_name"] = render["format"]
    if "fps" in render:
        out["fps"] = render["fps"]
    if "effect_toggles" in render:
        out["review_ab"] = list(render["effect_toggles"])
    if "weights" in render:
        from mediahub.visual.motion import normalise_reel_rhythm

        rhythm = normalise_reel_rhythm({"weights": render["weights"]}, n_cards)
        if rhythm is not None:
            out["rhythm"] = rhythm
    return out
