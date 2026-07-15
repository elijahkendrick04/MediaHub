"""Grayscale / mono accessibility render mode (roadmap G1.19).

A post-render hook that turns a finished card into a **deterministic black-and-white**
render with an intelligent **colour-role remap** — not a naive ``filter: grayscale()``.

Why a remap and not just desaturation: two brand colours of *similar* luminance but
different hue (a red and a green, say) collapse to the **same** grey under plain
desaturation, destroying the contrast a card relies on (the result chip vanishes into
its ground, the hero numeral muddies into the body text). So this hook does two things,
in order:

1. **Role remap** — it reads the ``--mh-*`` role tokens the renderer actually painted
   (``--mh-primary`` ground, ``--mh-surface`` panel, ``--mh-accent`` hero/chip,
   ``--mh-on-*`` ink, ``--mh-outline`` hairline) and rewrites them to a neutral-grey
   ramp that **preserves the hierarchy**: ground and accent are pushed to opposite
   luminance extremes (near-black ground ↔ pure-white accent for a dark card), so the
   accent still reads as text on the ground *and* forms a clean inverted chip
   (``background: var(--mh-accent)`` with ``color: var(--mh-primary)`` text), exactly
   the two uses the v2 layouts make of it. The ramp clears the same APCA legibility gate
   (``quality.compliance.check_roles``) the colour render is held to — by construction,
   because the extremes give maximal contrast.

2. **Global desaturation** — it injects ``html { filter: grayscale(1) }`` so everything
   the role tokens *don't* drive (athlete photos, logos, medal tints, style-pack SVG
   overlays, any earlier sprint hook's output, and v1 ``.canvas`` grounds that predate
   the role tokens) is also truly B/W. This is the belt-and-braces that makes the card
   genuinely accessible / mono-print ready, not just brand-token grey.

Opt-in (the render is **byte-identical** to before unless mono is requested):

* ``brief.render_mode`` / ``brief.background_style`` ∈ a mono token set
  (``mono`` / ``monochrome`` / ``grayscale`` / ``greyscale`` / ``b&w`` / ``black_and_white``);
* a mono phrase anywhere in the free-text ``brief.mood`` / ``brief.style_pack``;
* the operator-wide ``MEDIAHUB_MONO_MODE`` env flag (a global accessibility / mono-print
  switch — set ``1``/``true``/``on`` and every render ships in accessible B/W with no
  code change).

All triggers are read via ``getattr`` / the environment, so this capability is a pure
**new-file drop** — it never edits the brief dataclass or ``render.py`` (roadmap G1.19 is
🟢 ISOLATED). The hook is deterministic and self-isolating: any failure returns the HTML
unchanged, so mono mode can never break the card pipeline.
"""

from __future__ import annotations

import os
import re

from . import RenderHookCtx

# Runs LATE: after gradient-mesh backgrounds, icon/badge overlays and any other
# colour-emitting sprint hook, so the global desaturation also flattens *their*
# output to B/W. The role-token declarations it rewrites are injected by
# ``render.py`` before any hook runs, so they are always present to read.
ORDER = 90

# ---------------------------------------------------------------------------
# Opt-in detection
# ---------------------------------------------------------------------------

# Exact tokens accepted in the structured ``render_mode`` / ``background_style``
# fields (spaces normalised to underscores before the lookup).
_MONO_TOKENS = frozenset(
    {
        "mono",
        "monochrome",
        "grayscale",
        "greyscale",
        "gray_scale",
        "grey_scale",
        "bw",
        "b&w",
        "b/w",
        "black_and_white",
        "black-and-white",
        "blackandwhite",
    }
)

# A mono phrase in the free-text mood / style-pack channel. Word-bounded so a
# club mood of "monochrome editorial" trips it but an unrelated word never does.
# Searched against a blob whose id separators (``_`` ``-`` ``/``) are normalised
# to spaces first, so "mono_press" and "b/w" both reach these alternatives.
_MONO_PHRASE = re.compile(
    r"\b(mono|monochrome|gray\s*scale|grey\s*scale|black\s+and\s+white|b\s*[&/]?\s*w)\b"
)


def _attr(obj, name: str, default: str = "") -> object:
    """Read ``name`` from a brief that may be a dataclass *or* a plain dict."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def mono_requested(brief) -> bool:
    """True when this brief (or the operator env) asks for the mono render mode."""
    # Read the literal name inline so the env-inventory grep (docs/ENV_INVENTORY.md)
    # registers MEDIAHUB_MONO_MODE as a var the source reads.
    if _truthy(os.environ.get("MEDIAHUB_MONO_MODE", "")):
        return True
    if brief is None:
        return False
    for field in ("render_mode", "background_style"):
        value = _attr(brief, field, "")
        if isinstance(value, str) and value.strip().lower().replace(" ", "_") in _MONO_TOKENS:
            return True
    # Free-text channel: normalise id separators (``_`` / ``-`` / ``/``) to spaces
    # so an underscored style-pack id ("mono_press") still word-boundary matches,
    # while a bare substring ("monumental") stays correctly ignored.
    blob = " ".join(str(_attr(brief, f, "") or "") for f in ("mood", "style_pack")).lower()
    blob = re.sub(r"[_/-]+", " ", blob)
    return bool(blob.strip() and _MONO_PHRASE.search(blob))


# ---------------------------------------------------------------------------
# Mono colour-role ramp
# ---------------------------------------------------------------------------

# Two neutral-grey ramps, picked by ground polarity. Each keeps the brand
# hierarchy: ``accent`` is the brightest (dark theme) / darkest (light theme)
# token so the hero result and the inverted chip pop, ``ink`` is strong but a
# touch below it, and ``ground``/``surface`` take the two ground tones (the
# lighter of the original pair keeps the lighter tone, so panels still separate).
_DARK_RAMP = {
    "ground_hi": "#1A1A1A",
    "ground_lo": "#0B0B0B",
    "ink": "#F4F4F4",
    "accent": "#FFFFFF",
    "secondary": "#B4B4B4",
    "outline": "rgba(255,255,255,0.30)",
}
_LIGHT_RAMP = {
    "ground_hi": "#F5F5F5",
    "ground_lo": "#E2E2E2",
    "ink": "#161616",
    "accent": "#000000",
    "secondary": "#4D4D4D",
    "outline": "rgba(0,0,0,0.30)",
}


# A neutral grey specular ramp (light-dark-light) — the mono stand-in for the
# F9 medal chrome, carrying no brand hue.
_MONO_MEDAL_RAMP = (
    "linear-gradient(135deg, #6E6E6E 0%, #9A9A9A 18%, #B4B4B4 36%, "
    "#E6E6E6 50%, #B4B4B4 64%, #8A8A8A 82%, #6E6E6E 100%)"
)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    h = value.lstrip("#")
    if len(h) == 3:
        h = "".join(ch + ch for ch in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _relative_luminance(value: str) -> float:
    """WCAG relative luminance of a ``#hex`` — used only to order the two grounds."""

    def _ch(c: int) -> float:
        v = c / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = _hex_to_rgb(value)
    return 0.2126 * _ch(r) + 0.7152 * _ch(g) + 0.0722 * _ch(b)


def _is_dark_ground(ground_hex: str) -> bool:
    """True when the ground wants light ink (dark-theme mono ramp).

    Reuses the engine's APCA-based ``polarity_of`` when importable — the same
    measure the colour render uses to pick ink — and falls back to a WCAG
    luminance split so the hook stays self-contained.
    """
    try:
        from mediahub.theming.contrast import polarity_of

        return polarity_of(ground_hex) == "light_on_dark"
    except Exception:
        return _relative_luminance(ground_hex) < 0.45


def mono_role_vars(ground_hex: str, surface_hex: str) -> dict[str, str]:
    """The mono ``--mh-*`` replacements for a card whose ground/surface are given.

    Deterministic and legibility-safe by construction: accent and ground sit at
    opposite luminance extremes, so every scored APCA pair (name-on-ground,
    accent-on-ground, chip-text-on-accent, text-on-surface) clears its gate.
    """
    ramp = _DARK_RAMP if _is_dark_ground(ground_hex) else _LIGHT_RAMP
    # Keep whichever ground was lighter as the lighter mono tone, so the surface
    # panel still reads as a distinct step from the main ground.
    try:
        surface_darker = _relative_luminance(surface_hex) <= _relative_luminance(ground_hex)
    except Exception:
        surface_darker = True
    ground = ramp["ground_hi"] if surface_darker else ramp["ground_lo"]
    surface = ramp["ground_lo"] if surface_darker else ramp["ground_hi"]
    return {
        "--mh-primary": ground,
        "--mh-surface": surface,
        "--mh-on-primary": ramp["ink"],
        "--mh-on-surface": ramp["ink"],
        "--mh-accent": ramp["accent"],
        "--mh-secondary": ramp["secondary"],
        "--mh-outline": ramp["outline"],
    }


# ---------------------------------------------------------------------------
# HTML transforms
# ---------------------------------------------------------------------------


# Read a painted ground/surface hex. The lookbehind keeps ``--mh-primary`` from
# matching inside ``--mh-on-primary``; the form is a *declaration* (``name:#hex``),
# never a ``var(--mh-primary)`` usage (no colon follows those).
def _find_role_hex(html: str, role: str) -> str:
    m = re.search(rf"(?<![\w-])--mh-{role}\s*:\s*(#[0-9A-Fa-f]{{3,6}})\b", html)
    return m.group(1) if m else ""


# Every colour role declaration, matched as ``--mh-<role>: <value>`` up to the
# terminating ``;`` / ``}``. ``var(--mh-*)`` usages are never matched (no colon).
_ROLE_DECL_RE = re.compile(
    r"(?<![\w-])(--mh-(?:on-primary|on-surface|outline|secondary|primary|surface|accent))"
    r"\s*:\s*[^;}]+"
)

# The DERIVED colour tokens (Canva gap analysis B/C waves) embed brand-derived
# hexes in their values — the B3 ground micro-gradient literally carries
# lit/shaded stops of the brand primary — so a mono card must rewrite them too
# or the brand colour leaks straight past the role remap.
_DERIVED_DECL_RE = re.compile(
    r"(?<![\w-])(--mh-(?:ground-gradient|surface-2|lift|ink-secondary|secondary-vis|shadow-rgb"
    # F9 medal chrome: the specular ramp vars embed the medal-tint hexes, so a
    # mono card must rewrite them to a neutral grey specular or the gold/silver
    # leaks past the role remap (the global grayscale would desaturate the pixels
    # anyway, but rewriting keeps the token itself brand-free — the B3 precedent).
    r"|medal-numeral-ramp|medal-ramp"
    r"))"
    r"\s*:\s*[^;}]+"
)


def _rewrite_role_decls(html: str, ramp: dict[str, str]) -> str:
    def _sub(m: "re.Match[str]") -> str:
        name = m.group(1)
        repl = ramp.get(name)
        return f"{name}:{repl}" if repl is not None else m.group(0)

    html = _ROLE_DECL_RE.sub(_sub, html)
    derived = {
        # A flat mono ground stands in for the micro-gradient (a colour is a
        # valid background value, so the var() consumers are unaffected).
        "--mh-ground-gradient": ramp.get("--mh-primary", "#111111"),
        "--mh-surface-2": ramp.get("--mh-surface", "#181818"),
        "--mh-lift": ramp.get("--mh-surface", "#181818"),
        "--mh-ink-secondary": ramp.get("--mh-secondary", "#B4B4B4"),
        "--mh-secondary-vis": ramp.get("--mh-secondary", "#B4B4B4"),
        "--mh-shadow-rgb": "10,10,10",
        # A neutral grey specular so a medal card still reads as polished metal
        # in mono, with no brand hue in the token.
        "--mh-medal-ramp": _MONO_MEDAL_RAMP,
        "--mh-medal-numeral-ramp": _MONO_MEDAL_RAMP,
    }

    def _sub_derived(m: "re.Match[str]") -> str:
        return f"{m.group(1)}:{derived[m.group(1)]}"

    return _DERIVED_DECL_RE.sub(_sub_derived, html)


def _mono_contrast() -> float:
    """Optional operator contrast trim for the B/W photo pass (default 1.0)."""
    raw = os.environ.get("MEDIAHUB_MONO_CONTRAST", "").strip()
    if not raw:
        return 1.0
    try:
        return max(0.5, min(2.0, float(raw)))
    except ValueError:
        return 1.0


def _inject_desaturation(html: str, contrast: float) -> str:
    """Add the page-level grayscale filter once (idempotent)."""
    if 'id="mh-mono-mode"' in html:
        return html
    filt = "grayscale(1)" if contrast == 1.0 else f"grayscale(1) contrast({contrast:g})"
    style = f'<style id="mh-mono-mode">:root{{--mh-mono:1;}}html{{filter:{filt};}}</style>'
    if "</head>" in html:
        return html.replace("</head>", style + "</head>", 1)
    if "</body>" in html:
        return html.replace("</body>", style + "</body>", 1)
    return html + style


def apply(html: str, ctx: RenderHookCtx) -> str:
    """Render-hook entry point — see the module docstring.

    Opts out (returns ``html`` unchanged) unless mono is requested, so flag-off
    renders stay byte-identical. Self-isolating: any failure returns the input.
    """
    try:
        if not isinstance(html, str) or not html:
            return html
        if not mono_requested(getattr(ctx, "brief", None)):
            return html
        # 1) role remap — only when the v2 role tokens are present to read.
        ground = _find_role_hex(html, "primary")
        if ground:
            surface = _find_role_hex(html, "surface") or ground
            html = _rewrite_role_decls(html, mono_role_vars(ground, surface))
        # 2) global desaturation — guarantees photos/logos/overlays/v1 grounds B/W.
        return _inject_desaturation(html, _mono_contrast())
    except Exception:  # noqa: BLE001 — a sprint hook must never break a render
        return html


__all__ = ["ORDER", "apply", "mono_requested", "mono_role_vars"]
