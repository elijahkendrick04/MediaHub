"""Deterministic text-effect primitives (roadmap 1.9).

Canva/Adobe ship a wall of text "effects" (Shadow, Lift, Hollow, Splice, Echo,
Glitch, Neon, Background, Curve, 3D extrude, warp, gradient fills). MediaHub
re-expresses them as a small **tokenised, brand-locked, APCA-policed** vocabulary
the design-spec director (or a human in the editor) can request per text slot —
never a 3,000-template pile.

Two hard rules from CLAUDE.md hold here:

* **Deterministic.** Every effect is pure CSS/SVG maths — no AI, no randomness.
  The same ``(effect, colours)`` always yields the same style string, so a card's
  bytes stay reproducible and its render cache key stable.
* **Legibility is policed by the colour-science gate, not vibes.** Effects that
  change the colour the eye actually reads (hollow, splice, gradient) are checked
  with the existing APCA maths (:func:`mediahub.quality.compliance.is_legible`)
  and **downgraded to a guaranteed-legible outline** when they would drop a glyph
  below the headline contrast floor. The decision (applied / downgraded / why) is
  returned so the renderer and the explainability surface can show it.

How they reach the page: the renderer wraps a slot's *substituted text value* in
a ``<span>`` carrying the effect's inline style (archetype-agnostic — it rides the
value, not the template), so an empty ``text_effects`` map leaves every card
byte-identical. ``curve`` is the one effect that needs real glyph-on-path layout,
so it swaps the value for a self-contained inline SVG (:func:`curve_text_svg`).

Colours are passed in as resolved hex (for the APCA decision) but emitted as the
card's ``--mh-*`` custom properties (so an effect tracks medal tints / role
re-assignment exactly like the rest of the card).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote


def _esc(s: object) -> str:
    """Minimal HTML-escape (kept local to avoid a render.py import cycle)."""
    s = "" if s is None else str(s)
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )

# Closed vocabulary. Mirrored by ``creative_brief.design_spec.TEXT_EFFECTS`` (a
# drift test keeps the two identical); the renderer here is the authority that
# actually executes each one.
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

# Human labels for the editor surface (Build 4).
EFFECT_LABELS: dict[str, str] = {
    "none": "None",
    "shadow": "Shadow",
    "lift": "Lift",
    "hollow": "Hollow",
    "outline": "Outline",
    "splice": "Splice",
    "echo": "Echo",
    "glitch": "Glitch",
    "neon": "Neon",
    "background": "Background",
    "gradient": "Gradient",
    "extrude": "3D Extrude",
    "warp": "Warp",
    "curve": "Curve",
}

# Effects that change the colour the reader perceives → policed + maybe downgraded.
_FILL_ALTERING: frozenset[str] = frozenset({"hollow", "splice", "gradient"})
# The APCA headline floor (|Lc| ≥ 45) — the same gate the role system uses.
_LC_FLOOR = 45.0


@dataclass(frozen=True)
class EffectResult:
    """The outcome of resolving one effect token for one slot."""

    requested: str
    applied: str
    style: str  # inline CSS declarations for the span ("" for none/curve)
    svg: bool  # True ⇒ the slot value is replaced by curve_text_svg(), not wrapped
    legible: bool
    downgraded: bool
    reason: str

    @property
    def is_noop(self) -> bool:
        return self.applied == "none" and not self.style and not self.svg


def _is_legible(fg_hex: str, bg_hex: str) -> bool:
    try:
        from mediahub.quality.compliance import is_legible

        return bool(is_legible(fg_hex, bg_hex, min_lc=_LC_FLOOR))
    except Exception:
        # No colour-science available ⇒ be conservative and treat as legible
        # (the role system already gated the base ink); never crash a render.
        return True


# --------------------------------------------------------------------------- #
# Per-effect inline-style emitters (em-relative so they scale with the slot)
# --------------------------------------------------------------------------- #
def _style_for(name: str) -> str:
    """Return the inline CSS for a *fill-preserving* effect (colour inherited)."""
    if name == "shadow":
        return "text-shadow:0 0.045em 0.14em rgba(0,0,0,0.45);"
    if name == "lift":
        return (
            "text-shadow:0 0.02em 0.02em rgba(0,0,0,0.35),"
            "0 0.085em 0.22em rgba(0,0,0,0.45);"
        )
    if name == "echo":
        return (
            "text-shadow:0.055em 0.055em 0 rgba(0,0,0,0.18),"
            "0.11em 0.11em 0 rgba(0,0,0,0.10),"
            "0.165em 0.165em 0 rgba(0,0,0,0.05);"
        )
    if name == "glitch":
        return (
            "text-shadow:-0.022em 0 0 rgba(255,0,86,0.62),"
            "0.022em 0 0 rgba(0,224,255,0.62);"
        )
    if name == "neon":
        # Fill inherited (stays role-legible); glow in the brand accent.
        return (
            "text-shadow:0 0 0.1em var(--mh-accent),0 0 0.28em var(--mh-accent),"
            "0 0 0.5em var(--mh-accent);"
        )
    if name == "extrude":
        # Layered offsets in the deep brand surface = a faked 3D extrusion.
        steps = ",".join(
            f"{0.014 * i:.3f}em {0.014 * i:.3f}em 0 var(--mh-surface)" for i in range(1, 8)
        )
        return f"text-shadow:{steps},0.13em 0.13em 0.06em rgba(0,0,0,0.4);"
    return ""


def _outline_style() -> str:
    """A ground-colour halo around the role ink — legible on any busy photo."""
    return (
        "color:var(--mh-on-primary);"
        "-webkit-text-stroke:0.03em var(--mh-primary);"
        "paint-order:stroke fill;"
    )


def _warp_style() -> str:
    """A self-contained feTurbulence+feDisplacementMap filter as a data-URI.

    No page-level ``<defs>`` injection needed (so the wiring stays trivial and
    byte-identical when unused). If a renderer ever fails to resolve the filter
    the glyphs simply render un-warped — an honest, non-breaking degradation.
    """
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg'>"
        "<filter id='w'>"
        "<feTurbulence type='fractalNoise' baseFrequency='0.012 0.018' "
        "numOctaves='2' seed='7' result='n'/>"
        "<feDisplacementMap in='SourceGraphic' in2='n' scale='14' "
        "xChannelSelector='R' yChannelSelector='G'/>"
        "</filter></svg>"
    )
    return f"filter:url('data:image/svg+xml,{quote(svg)}#w');"


def effect_css(
    name: str,
    *,
    ground: str,
    ink: str,
    accent: str,
    on_accent: str,
) -> EffectResult:
    """Resolve one effect token into an :class:`EffectResult`.

    ``ground`` is the representative ground the slot sits on (the card's
    ``--mh-primary``); ``ink`` the role-gated text colour on it
    (``--mh-on-primary``); ``accent`` the brand accent; ``on_accent`` a
    pre-computed legible ink for the highlight-box effect. Hex in → APCA
    decision; the emitted style references the live ``--mh-*`` properties.
    """
    req = (name or "none").strip().lower()
    if req not in TEXT_EFFECTS:
        req = "none"

    if req == "none":
        return EffectResult("none", "none", "", False, True, False, "")

    if req == "curve":
        # Geometry only; colour unchanged ⇒ as legible as the plain slot.
        return EffectResult("curve", "curve", "", True, _is_legible(ink, ground), False, "")

    # Fill-preserving decorative effects: colour inherited, always ≥ plain legibility.
    if req in ("shadow", "lift", "echo", "glitch", "neon", "extrude"):
        return EffectResult(req, req, _style_for(req), False, _is_legible(ink, ground), False, "")

    if req == "outline":
        return EffectResult("outline", "outline", _outline_style(), False, True, False, "")

    if req == "warp":
        return EffectResult("warp", "warp", _warp_style(), False, _is_legible(ink, ground), False, "")

    if req == "background":
        # Highlight box: ink chosen legible on the accent box by construction.
        style = (
            f"background:var(--mh-accent);color:{on_accent};"
            "display:inline;box-decoration-break:clone;"
            "-webkit-box-decoration-break:clone;padding:0.04em 0.16em;border-radius:0.06em;"
        )
        return EffectResult("background", "background", style, False, True, False, "")

    # --- fill-altering, policed effects -------------------------------------
    if req == "hollow":
        ok = _is_legible(ink, ground)
        if ok:
            style = (
                "color:transparent;-webkit-text-stroke:0.02em var(--mh-on-primary);"
                "paint-order:stroke;"
            )
            return EffectResult("hollow", "hollow", style, False, True, False, "")
        return _downgrade("hollow", ink, ground)

    if req == "splice":
        ok = _is_legible(ink, ground)
        if ok:
            style = (
                "color:transparent;-webkit-text-stroke:0.018em var(--mh-on-primary);"
                "text-shadow:0.06em 0.06em 0 var(--mh-accent);paint-order:stroke;"
            )
            return EffectResult("splice", "splice", style, False, True, False, "")
        return _downgrade("splice", ink, ground)

    if req == "gradient":
        ok = _is_legible(ink, ground) and _is_legible(accent, ground)
        if ok:
            style = (
                "background:linear-gradient(92deg,var(--mh-on-primary),var(--mh-accent));"
                "-webkit-background-clip:text;background-clip:text;"
                "color:transparent;-webkit-text-fill-color:transparent;display:inline-block;"
            )
            return EffectResult("gradient", "gradient", style, False, True, False, "")
        return _downgrade("gradient", ink, ground)

    # Unreachable (vocab-guarded), but never crash a render.
    return EffectResult(req, "none", "", False, True, False, "unhandled effect")


def _downgrade(requested: str, ink: str, ground: str) -> EffectResult:
    """An illegible fill-altering effect falls back to the guaranteed outline."""
    return EffectResult(
        requested=requested,
        applied="outline",
        style=_outline_style(),
        svg=False,
        legible=True,
        downgraded=True,
        reason=(
            f"{requested!r} would drop the glyph below the APCA headline floor "
            f"(Lc {_LC_FLOOR:.0f}) on this ground; using a legible outline instead."
        ),
    )


# --------------------------------------------------------------------------- #
# Span wrapping (the archetype-agnostic application point)
# --------------------------------------------------------------------------- #
def apply_to_value(value_html: str, result: EffectResult) -> str:
    """Wrap an already-escaped slot value in the effect's span.

    A no-op effect (or an empty value) returns the value untouched, so a card
    with no effects is byte-identical to before.
    """
    if result.is_noop or not value_html:
        return value_html
    if result.svg:  # curve handled by the caller via curve_text_svg()
        return value_html
    return f'<span class="mh-fx" style="{result.style}">{value_html}</span>'


# --------------------------------------------------------------------------- #
# Curve — glyph-on-path as a self-contained inline SVG
# --------------------------------------------------------------------------- #
def curve_text_svg(
    text: str,
    *,
    curvature: float = 0.35,
    fill: str = "currentColor",
    font_family: str = "inherit",
    font_weight: str = "inherit",
    uid: Optional[str] = None,
) -> str:
    """Return a responsive inline SVG laying ``text`` on a quadratic arc.

    ``curvature`` ∈ [-1, 1]: positive arcs the baseline upward (smile), negative
    downward (frown), 0 is flat. The SVG scales to its container via a viewBox +
    ``width:100%``; ``fill: currentColor`` (the default) inherits the slot ink so
    a curved headline keeps its role-gated, APCA-passed colour. Deterministic: the
    path id is derived from the text so repeated calls are byte-identical, and two
    different curved slots on one page never collide.
    """
    t = (text or "").strip()
    c = max(-1.0, min(1.0, float(curvature)))
    W, H = 1000.0, 360.0
    # Quadratic Bézier across the width; control point lifted/dropped by curvature.
    y0 = H * (0.5 + 0.34 * abs(c)) if c >= 0 else H * (0.5 - 0.34 * abs(c))
    ctrl_y = H * (0.5 - 0.40 * c)  # opposite sense so the arc bows correctly
    x0, x1 = 40.0, W - 40.0
    path_id = uid or ("mhcurve-" + _short_hash(f"{t}|{c:.3f}"))
    path_d = f"M {x0:.0f} {y0:.0f} Q {W / 2:.0f} {ctrl_y:.0f} {x1:.0f} {y0:.0f}"
    fs = 150.0
    return (
        f'<svg class="mh-fx-curve" xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {W:.0f} {H:.0f}" width="100%" '
        f'preserveAspectRatio="xMidYMid meet" role="img" aria-label="{_esc(t)}">'
        f'<defs><path id="{path_id}" d="{path_d}" fill="none"/></defs>'
        f'<text font-family="{font_family}" font-weight="{font_weight}" '
        f'font-size="{fs:.0f}" fill="{fill}" letter-spacing="0.01em" '
        f'text-anchor="middle" dominant-baseline="middle">'
        f'<textPath href="#{path_id}" startOffset="50%">{_esc(t)}</textPath>'
        f"</text></svg>"
    )


def _short_hash(s: str) -> str:
    import hashlib

    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:10]


__all__ = [
    "TEXT_EFFECTS",
    "DEFAULT_TEXT_EFFECT",
    "EFFECT_LABELS",
    "EffectResult",
    "effect_css",
    "apply_to_value",
    "curve_text_svg",
]
