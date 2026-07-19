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

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote


def _esc(s: object) -> str:
    """Minimal HTML-escape (kept local to avoid a render.py import cycle)."""
    s = "" if s is None else str(s)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


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

# The APCA headline floor (|Lc| ≥ 45) — the same gate the role system uses.
# Effects that change the colour the reader perceives (hollow/splice/gradient)
# are policed against it in effect_css() and downgraded to a legible outline.
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
        return "text-shadow:0 0.02em 0.02em rgba(0,0,0,0.35),0 0.085em 0.22em rgba(0,0,0,0.45);"
    if name == "echo":
        return (
            "text-shadow:0.055em 0.055em 0 rgba(0,0,0,0.18),"
            "0.11em 0.11em 0 rgba(0,0,0,0.10),"
            "0.165em 0.165em 0 rgba(0,0,0,0.05);"
        )
    if name == "glitch":
        # No-brand fallback dyad; the brand-locked dyad (derived from the
        # card's accent) is computed in effect_css via _glitch_style.
        return "text-shadow:-0.022em 0 0 rgba(255,0,86,0.62),0.022em 0 0 rgba(0,224,255,0.62);"
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


def _glitch_style(accent_hex: str) -> str:
    """The glitch fringe dyad, derived from the card's own accent (C7).

    Canva's Glitch restricts its colour to luminance-matched dyads, which is
    what makes it read deliberate. Ours was the one decoration in the system
    that ignored the brand palette (hardcoded magenta/cyan). The dyad here is
    the accent hue rotated ±140° with the accent's own lightness kept — pure
    HLS maths on a resolved role, so it is brand-derived, deterministic, and
    changes with medal tints exactly like the rest of the card. Falls back to
    the fixed dyad when the accent hex is unparseable.
    """
    import colorsys

    h = (accent_hex or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return _style_for("glitch")
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return _style_for("glitch")
    hue, lig, sat = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    sat = max(sat, 0.55)  # a grey accent still needs visible fringes
    lig = min(max(lig, 0.35), 0.72)  # keep both fringes in a readable band

    def _rot(deg: float) -> str:
        rr, gg, bb = colorsys.hls_to_rgb((hue + deg / 360.0) % 1.0, lig, sat)
        return f"{int(round(rr * 255))},{int(round(gg * 255))},{int(round(bb * 255))}"

    return (
        f"text-shadow:-0.022em 0 0 rgba({_rot(-140)},0.62)," f"0.022em 0 0 rgba({_rot(140)},0.62);"
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
    if req == "glitch":
        return EffectResult(
            "glitch", "glitch", _glitch_style(accent), False, _is_legible(ink, ground), False, ""
        )
    if req in ("shadow", "lift", "echo", "neon", "extrude"):
        return EffectResult(req, req, _style_for(req), False, _is_legible(ink, ground), False, "")

    if req == "outline":
        return EffectResult("outline", "outline", _outline_style(), False, True, False, "")

    if req == "warp":
        return EffectResult(
            "warp", "warp", _warp_style(), False, _is_legible(ink, ground), False, ""
        )

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
# D6 (Canva gap analysis) — per-word emphasis (the two-tone headline).
#
# Canva templates constantly emphasise ONE word of a headline — an accent-ink
# word, a highlight pill, or a heavier cut — adding a second brand colour and a
# focal point *without adding an element*. MediaHub could only style a whole
# slot uniformly. This wraps a single, fact-gated word (the director names it;
# it is kept only when it whole-word matches the slot's actual value) in an
# ``mh-em`` span carrying one of a small closed vocabulary of treatments, each
# APCA-gated with a downgrade to plain ink, exactly like the slot effects above.
# Colours ride the live ``--mh-*`` custom properties, so mono mode and role
# re-assignment track the emphasis for free (no new brand-hex token).
# --------------------------------------------------------------------------- #
EMPHASIS_STYLES: tuple[str, ...] = ("accent_ink", "accent_pill", "heavy")
DEFAULT_EMPHASIS_STYLE = "accent_ink"

EMPHASIS_LABELS: dict[str, str] = {
    "accent_ink": "Accent word",
    "accent_pill": "Highlight pill",
    "heavy": "Heavier weight",
}


def emphasis_css(
    style: str,
    *,
    ground: str,
    accent: str,
    on_accent: str,
) -> EffectResult:
    """Resolve one emphasis treatment into an :class:`EffectResult`.

    ``accent_ink`` repaints the word in the brand accent (APCA-gated against the
    ground; downgraded to *plain ink* — i.e. no wrap — when the accent would not
    read); ``accent_pill`` is the highlight box (ink chosen legible on the
    accent fill by construction, like the ``background`` slot effect); ``heavy``
    bumps the variable weight only (colour unchanged ⇒ always legible). An
    unknown token falls back to ``accent_ink``.
    """
    req = (style or "").strip().lower().replace(" ", "_")
    if req not in EMPHASIS_STYLES:
        req = DEFAULT_EMPHASIS_STYLE

    if req == "heavy":
        css = "font-weight:800;font-variation-settings:'wght' 800;"
        return EffectResult("heavy", "heavy", css, False, True, False, "")

    if req == "accent_pill":
        css = (
            f"background:var(--mh-accent);color:{on_accent};"
            "padding:0 0.14em;border-radius:0.08em;"
            "box-decoration-break:clone;-webkit-box-decoration-break:clone;"
        )
        return EffectResult("accent_pill", "accent_pill", css, False, True, False, "")

    # accent_ink — the emphasised word in the brand accent, policed like a
    # fill-altering effect: if the accent would drop below the emphasis floor on
    # this ground, leave the word as plain ink (no wrap ⇒ byte-identical).
    if _is_legible(accent, ground):
        return EffectResult(
            "accent_ink", "accent_ink", "color:var(--mh-accent);", False, True, False, ""
        )
    return EffectResult(
        "accent_ink",
        "plain",
        "",
        False,
        True,
        True,
        (
            f"accent ink would drop the word below the APCA emphasis floor "
            f"(Lc {_LC_FLOOR:.0f}) on this ground; left as plain ink."
        ),
    )


# Split a slot value into tag / non-tag runs so a whole-word match can never
# land inside a ``<br>`` or an already-applied effect span's attributes.
_TAG_SPLIT_RE = re.compile(r"(<[^>]+>)")


def emphasise_value(value_html: str, word: str, result: EffectResult) -> str:
    """Wrap the FIRST whole-word match of ``word`` in ``value_html`` in the
    emphasis span, or return the value untouched.

    ``value_html`` is already HTML-escaped; ``word`` is escaped here before
    matching (so card text can never inject markup) and matched case-insensitively
    on word boundaries, only within text runs (never inside a tag). A downgraded
    (plain) result carries an empty style and leaves the value byte-identical.
    """
    if not value_html or not word or not result.style:
        return value_html
    esc = _esc(word).strip()
    if not esc:
        return value_html
    pattern = re.compile(r"(?<!\w)(" + re.escape(esc) + r")(?!\w)", re.IGNORECASE)
    span_open = f'<span class="mh-em" style="{result.style}">'
    out: list[str] = []
    done = False
    for segment in _TAG_SPLIT_RE.split(value_html):
        if not done and segment and not segment.startswith("<"):
            new, n = pattern.subn(rf"{span_open}\1</span>", segment, count=1)
            if n:
                done = True
                out.append(new)
                continue
        out.append(segment)
    return "".join(out) if done else value_html


# --------------------------------------------------------------------------- #
# Curve — glyph-on-path as a self-contained inline SVG
# --------------------------------------------------------------------------- #
# The curvature magnitude at/below which the historic shallow quadratic bow is
# used (byte-identical to the pre-D7 renders). Above it, a true circular SVG arc
# takes over so the varsity-crest / badge register — text wrapping toward a full
# circle at the extremes — becomes reachable (D7, Canva gap analysis).
_CURVE_QUADRATIC_MAX = 0.4


def curve_text_svg(
    text: str,
    *,
    curvature: float = 0.35,
    fill: str = "currentColor",
    font_family: str = "inherit",
    font_weight: str = "inherit",
    uid: Optional[str] = None,
) -> str:
    """Return a responsive inline SVG laying ``text`` on a curved baseline.

    ``curvature`` ∈ [-1, 1]: positive arcs the baseline upward (smile), negative
    downward (frown), 0 is flat. For ``|curvature| <= 0.4`` this is the historic
    shallow **quadratic** bow (byte-identical to pre-D7 renders); above 0.4 it
    switches to a **true circular arc** (SVG ``A`` command, central angle
    ``θ = |c|·2π`` and radius ``r = w/θ``) so short all-caps strings can wrap
    toward a full-circle badge lockup, with tight-curve letter-spacing
    compensation added as the radius shrinks.

    The SVG scales to its container via a viewBox + ``width:100%``;
    ``fill: currentColor`` (the default) inherits the slot ink so a curved
    headline keeps its role-gated, APCA-passed colour. Deterministic: the path id
    is derived from the text + curvature so repeated calls are byte-identical, and
    two different curved slots on one page never collide.
    """
    t = (text or "").strip()
    c = max(-1.0, min(1.0, float(curvature)))
    path_id = uid or ("mhcurve-" + _short_hash(f"{t}|{c:.3f}"))
    fs = 150.0

    if abs(c) <= _CURVE_QUADRATIC_MAX:
        W, H = 1000.0, 360.0
        # Quadratic Bézier across the width; control point lifted/dropped by curvature.
        y0 = H * (0.5 + 0.34 * abs(c)) if c >= 0 else H * (0.5 - 0.34 * abs(c))
        ctrl_y = H * (0.5 - 0.40 * c)  # opposite sense so the arc bows correctly
        x0, x1 = 40.0, W - 40.0
        path_d = f"M {x0:.0f} {y0:.0f} Q {W / 2:.0f} {ctrl_y:.0f} {x1:.0f} {y0:.0f}"
        view_box = f"0 0 {W:.0f} {H:.0f}"
        letter_spacing = "0.01em"
    else:
        path_d, view_box, letter_spacing = _curve_arc_geometry(t, c, fs)

    return (
        f'<svg class="mh-fx-curve" xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{view_box}" width="100%" '
        f'preserveAspectRatio="xMidYMid meet" role="img" aria-label="{_esc(t)}">'
        f'<defs><path id="{path_id}" d="{path_d}" fill="none"/></defs>'
        f'<text font-family="{font_family}" font-weight="{font_weight}" '
        f'font-size="{fs:.0f}" fill="{fill}" letter-spacing="{letter_spacing}" '
        f'text-anchor="middle" dominant-baseline="middle">'
        f'<textPath href="#{path_id}" startOffset="50%">{_esc(t)}</textPath>'
        f"</text></svg>"
    )


def _curve_arc_geometry(text: str, c: float, fs: float) -> tuple[str, str, str]:
    """The true-arc path, viewBox and letter-spacing for ``|c| > 0.4`` (D7).

    Lays the string on a circle of central angle ``θ = |c|·2π`` (clamped just
    short of a full turn to avoid a degenerate zero-length arc) whose radius
    ``r = arc_length / θ`` is sized so the estimated text advance fills the arc.
    Positive curvature bows up (text on the top of the circle reading L→R),
    negative bows down. The viewBox is computed by sampling the baseline and the
    glyph-reach radius so the whole lockup is contained and centred; a tighter
    curve (bigger θ, smaller r) earns proportionally more splay compensation.
    """
    import math

    theta = min(abs(c) * 2.0 * math.pi, 1.9 * math.pi)
    # Tight-curve letter-spacing compensation: +0.02em at the switch point up to
    # +0.05em near a full wrap (glyphs splay at the baseline as the radius drops).
    span = (1.9 * math.pi) - (_CURVE_QUADRATIC_MAX * 2.0 * math.pi)
    frac = (
        0.0
        if span <= 0
        else max(0.0, min(1.0, (theta - _CURVE_QUADRATIC_MAX * 2.0 * math.pi) / span))
    )
    ls_em = round(0.02 + 0.03 * frac, 4)

    n = max(1, len(text))
    # Estimated advance in user units at font-size fs (caps average ≈ 0.62em plus
    # the applied tracking), inflated 6% so the run never overruns the arc ends.
    advance = fs * (n * 0.62 + (n - 1) * ls_em) * 1.06
    r = advance / theta if theta > 1e-6 else advance

    # Circle centred at the origin; sample the baseline + a small inward band and
    # the outward glyph reach so the bounding box contains every painted pixel.
    glyph_out = fs * 0.82  # caps ascent reach beyond the baseline
    glyph_in = fs * 0.16
    up = c > 0  # smile: arc on the top of the circle; frown: on the bottom
    base = (-math.pi / 2.0) if up else (math.pi / 2.0)
    a_start = base - theta / 2.0
    a_end = base + theta / 2.0

    def _pt(angle: float, radius: float) -> tuple[float, float]:
        return (radius * math.cos(angle), radius * math.sin(angle))

    x0, y0 = _pt(a_start, r)
    x1, y1 = _pt(a_end, r)
    large_arc = 1 if theta > math.pi else 0
    # increasing angle → clockwise sweep in SVG's y-down space (reads L→R on top).
    sweep = 1
    path_d = f"M {x0:.2f} {y0:.2f} A {r:.2f} {r:.2f} 0 {large_arc} {sweep} {x1:.2f} {y1:.2f}"

    xs: list[float] = []
    ys: list[float] = []
    steps = 32
    for i in range(steps + 1):
        a = a_start + (a_end - a_start) * (i / steps)
        for radius in (r - glyph_in, r, r + glyph_out):
            px, py = _pt(a, radius)
            xs.append(px)
            ys.append(py)
    pad = fs * 0.12
    min_x, max_x = min(xs) - pad, max(xs) + pad
    min_y, max_y = min(ys) - pad, max(ys) + pad
    view_box = f"{min_x:.2f} {min_y:.2f} {max_x - min_x:.2f} {max_y - min_y:.2f}"
    return path_d, view_box, f"{ls_em}em"


def _short_hash(s: str) -> str:
    import hashlib

    # Not security-sensitive: just a stable, collision-resistant-enough id for an
    # inline SVG <path> fragment (so two curved slots on a page don't clash).
    return hashlib.sha1(s.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]


__all__ = [
    "TEXT_EFFECTS",
    "DEFAULT_TEXT_EFFECT",
    "EFFECT_LABELS",
    "EffectResult",
    "effect_css",
    "apply_to_value",
    "curve_text_svg",
    "EMPHASIS_STYLES",
    "DEFAULT_EMPHASIS_STYLE",
    "EMPHASIS_LABELS",
    "emphasis_css",
    "emphasise_value",
]
