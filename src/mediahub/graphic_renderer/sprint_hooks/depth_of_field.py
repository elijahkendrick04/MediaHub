"""Depth-of-field background-blur photo treatment — roadmap **G1.21**.

A sprint render-hook drop (see ``sprint_hooks/README.md``): when a card's brief
opts into the depth-of-field treatment, soften the *photographic background*
layers and keep the *athlete subject* sharp, so the cutout reads as the plane of
focus — the still-graphic analogue of a wide-aperture lens. "Focus the athlete,
soften the background."

Why a pure CSS-filter transform (no injected ``<div>``):
    The card's ``.canvas`` declares ``isolation: isolate`` (its own stacking
    context) and the shared CSS is inlined into every card, so a body-level
    overlay could not interleave *between* the background (``z-index: 1``) and
    the subject (``z-index: 5``). A ``<style>`` block, by contrast, restyles the
    real layers wherever they already sit. We therefore blur the existing
    background photo / AI-background layers and add separation to the existing
    cutout — no DOM surgery, no stacking-context surprises.

Honesty & isolation guarantees:
    * **Opt-in only.** The brief requests it by setting ``photo_treatment`` (or
      ``background_style``) to a depth-of-field token (``depth_of_field`` /
      ``dof`` / ``background_blur`` / …), or by carrying a **bokeh-ground style
      pack** while its photo grade is the untouched default (the deterministic
      pack pick is the reachable emitter — same bridge shape as G1.8's
      gradient-mesh ground). Every other brief returns the HTML untouched, so
      all existing renders stay byte-identical.
    * **Real photos only.** The blur acts on layers that exist solely when a
      real image was supplied (``.bg-photo``, a non-empty ``--ai-bg`` URI) and
      the focus pop on the real athlete cutout — no pixels are generated.
    * **Deterministic.** Blur radius is a pure function of the canvas size and
      the brief's ``decoration_strength``; no randomness, clock or I/O.
    * **Import-safe.** Stdlib-only, no third-party imports, so the registry's
      import-time discovery (``sprint_hooks._discover``) can never fail on it.
"""

from __future__ import annotations

from . import RenderHookCtx

# Run after background-establishing hooks (e.g. a gradient-mesh background at
# ORDER 20) but before any foreground overlay (icons/badges), so the blur lands
# on the settled background while the sharp subject still paints on top.
ORDER = 40

# Brief tokens that request the treatment. Compared after normalisation
# (lowercased; spaces and hyphens → underscores), so "Depth Of Field",
# "depth-of-field" and "dof" all match.
_DOF_TOKENS = frozenset(
    {
        "depth_of_field",
        "dof",
        "background_blur",
        "blur_background",
        "blurred_background",
        "bokeh",
    }
)

# Marker id on the injected style block — makes the transform idempotent (a
# second pass is a no-op) and easy to assert on in tests.
_MARKER = "mh-dof"


def _norm(value: object) -> str:
    """Lower-case and underscore-normalise a brief token for matching."""
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _brief_attr(brief: object, name: str, default: object = None) -> object:
    """Read the raw ``name`` off a brief that may be a dataclass/object or dict."""
    val = getattr(brief, name, None)
    if val is None and isinstance(brief, dict):
        val = brief.get(name)
    return default if val is None else val


def _brief_value(brief: object, name: str) -> str:
    """Read ``name`` as a normalised token (dataclass/object or dict brief)."""
    return _norm(_brief_attr(brief, name))


def _pack_ground(brief: object) -> str:
    """The *ground* lever of the brief's selected style pack ('' when none)."""
    pack_id = str(_brief_attr(brief, "style_pack", "") or "").strip()
    if not pack_id:
        return ""
    try:
        from .. import style_packs as _sp  # same-package; lazy keeps import stdlib-only

        pack = _sp.style_pack_from_id(pack_id)
        return pack.ground if pack is not None else ""
    except Exception:
        return ""


def _wants_dof(brief: object) -> bool:
    """True when the brief opts into the depth-of-field treatment.

    Two deterministic emitters:

    * an explicit ``photo_treatment`` / ``background_style`` dof token, or
    * a **bokeh-ground style pack** — the pack's defocused-pools atmosphere is
      the treatment's own look, so the deterministically-picked pack keys the
      real blur engine (the same bridge shape as the G1.8 gradient-mesh ground
      → ``gradient_mesh_bg`` hook). Conservative edge: only the untouched
      default photo grade is bridged — an explicit duotone/halftone/vignette
      choice is never compounded with a blur.
    """
    if brief is None:
        return False
    if (
        _brief_value(brief, "photo_treatment") in _DOF_TOKENS
        or _brief_value(brief, "background_style") in _DOF_TOKENS
    ):
        return True
    if _pack_ground(brief) == "bokeh":
        return _brief_value(brief, "photo_treatment") in ("", "cutout")
    return False


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def _blur_radius_px(ctx: RenderHookCtx) -> int:
    """Deterministic blur radius, scaled to the canvas and ``decoration_strength``.

    Anchored on the shorter canvas edge so the *perceptual* softness is constant
    across formats (story 1080×1920, square 1080×1080, …). ``decoration_strength``
    (0..1, default 0.5) nudges it within a tasteful band: a stoic club gets a
    lighter blur, a celebratory card a stronger one — never frosted glass.
    """
    short_edge = max(1, min(int(ctx.width or 0), int(ctx.height or 0)))
    try:
        raw_strength = float(_brief_attr(ctx.brief, "decoration_strength", 0.5))
    except (TypeError, ValueError):
        raw_strength = 0.5
    strength = _clamp(raw_strength, 0.0, 1.0)
    factor = 0.8 + 0.4 * strength  # 0.8 … 1.2 around the 1.0 default at 0.5
    raw = short_edge * 0.018 * factor
    return int(_clamp(round(raw), 12, 30))


def _scale_pct(blur_px: int) -> int:
    """Over-scale (in %) for the blurred layers so blur edge-bleed stays off-frame.

    A Gaussian blur of N px softens ~3N px inward from each edge, exposing the
    layer's transparent border. Scaling the (``inset: 0``) layer up from centre
    pushes that bleed out of frame. Kept in a tight 6–12% band.
    """
    return int(_clamp(round(blur_px / 2.5), 6, 12))


def _dof_css(ctx: RenderHookCtx) -> str:
    """Build the deterministic depth-of-field style block."""
    blur = _blur_radius_px(ctx)
    scale = 1.0 + _scale_pct(blur) / 100.0
    return (
        f'<style id="{_MARKER}">'
        "/* G1.21 depth-of-field: soften the photographic background, focus the subject */"
        # Soften the background photo + AI-background layers. brightness/contrast
        # trims push the out-of-focus plane back (a real lens darkens the bokeh);
        # the scale hides blur edge-bleed.
        ".bg-photo,.bg-ai{"
        f"filter:blur({blur}px) saturate(1.06) brightness(0.90) contrast(0.97) !important;"
        f"transform:scale({scale:.3f}) !important;"
        "transform-origin:center center !important;"
        "}"
        # Keep the athlete cutout crisp and lift it off the soft background: a
        # gentle tonal pop plus a layered separation shadow read as "in focus".
        ".athlete-cutout{"
        "filter:contrast(1.05) saturate(1.06) "
        "drop-shadow(0 26px 46px rgba(0,0,0,0.50)) "
        "drop-shadow(0 8px 16px rgba(0,0,0,0.42)) !important;"
        "}"
        "</style>"
    )


def apply(html: str, ctx: RenderHookCtx) -> str:
    """Inject the depth-of-field style block when the brief opts in.

    Returns ``html`` unchanged for every brief that does not request the
    treatment (byte-identical), when it has already been applied (idempotent),
    or when there is no photographic layer for it to act on.
    """
    if not isinstance(html, str) or not _wants_dof(ctx.brief):
        return html
    if _MARKER in html:  # idempotent: never double-blur on a second pass
        return html
    # Nothing photographic to soften/focus → honestly no-op rather than emit
    # dead CSS. The cutout <img> and bg-photo <div> are only present with a real
    # image; the AI background is gated on a non-empty data/file URI in --ai-bg.
    if not (
        '<img class="athlete-cutout"' in html
        or '<div class="bg-photo"' in html
        or _has_real_ai_bg(html)
    ):
        return html

    style = _dof_css(ctx)
    if "</body>" in html:
        return html.replace("</body>", style + "</body>", 1)
    return html + style


def _has_real_ai_bg(html: str) -> bool:
    """True when ``--ai-bg`` carries a real image URI rather than an empty url()."""
    marker = "--ai-bg: url('"
    idx = html.find(marker)
    if idx == -1:
        return False
    start = idx + len(marker)
    end = html.find("'", start)
    if end == -1:
        return False
    return len(html[start:end].strip()) > 0
