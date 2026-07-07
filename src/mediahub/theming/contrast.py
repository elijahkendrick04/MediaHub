"""APCA + WCAG 2.x contrast for the Adaptive Theming Engine.

Two contrast models live here:

  apca(fg, bg)         — Accessible Perceptual Contrast Algorithm
                         (Andrew Somers, SAPC-APCA v0.1.9). Returns a
                         signed Lc value: positive = dark text on light
                         bg, negative = light text on dark bg. Body-text
                         threshold is |Lc| ≥ 75 (Silver level).
  wcag2_ratio(fg, bg)  — WCAG 2.x (L1+0.05)/(L2+0.05). Body-text AA
                         threshold is ratio ≥ 4.5.

Both are exposed because the explainability panel for Stage H shows
both numbers side-by-side ("APCA is the modern model; WCAG2 is the
legal standard your auditor will quote").

APCA implementation references:
  - Myndex/SAPC-APCA (Github, MIT)
  - apca-w3 (npm v0.1.9)
  - git.apcacontrast.com/documentation/APCA_in_a_Nutshell.html

The constants below come from the v0.1.9 reference. Tested against the
published reference vectors in tests/test_contrast.py.
"""

from __future__ import annotations

from typing import Literal


__all__ = [
    "apca",
    "wcag2_ratio",
    "pick_ink",
    "polarity_of",
    "brand_on_color",
    "Polarity",
]

Polarity = Literal["dark_on_light", "light_on_dark"]


# ---------------------------------------------------------------------------
# Hex parsing
# ---------------------------------------------------------------------------


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(ch + ch for ch in h)
    if len(h) >= 6:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    raise ValueError(f"not a valid hex colour: {h!r}")


# ---------------------------------------------------------------------------
# APCA — SAPC-APCA v0.1.9 reference
# ---------------------------------------------------------------------------

# APCA "Simple Mode" constants (apca-w3 v0.1.9).
# https://github.com/Myndex/SAPC-APCA/blob/master/documentation/APCAonly.98G-4g-W3-Compatible.md
_SA98G = {
    "mainTRC": 2.4,
    # sRGB coefficients (R, G, B) for relative luminance.
    "sRco": 0.2126729,
    "sGco": 0.7151522,
    "sBco": 0.0721750,
    # Black soft-clamp.
    "normBG": 0.56,
    "normTXT": 0.57,
    "revTXT": 0.62,
    "revBG": 0.65,
    # Black soft-clip parameters.
    "blkThrs": 0.022,
    "blkClmp": 1.414,
    # Scaling.
    "scaleBoW": 1.14,
    "scaleWoB": 1.14,
    # Low-contrast clip (output rounded to 0 when below this magnitude).
    # The reference's deltaYmin abs(Ybg-Ytxt) early-zero check is omitted:
    # the loClip clamp below subsumes it.
    "loBoWoffset": 0.027,
    "loWoBoffset": 0.027,
    "loClip": 0.1,
}


def _srgb_to_y(rgb: tuple[int, int, int]) -> float:
    """sRGB 0-255 → APCA "screen luminance" Y. Uses the simple-mode
    `2.4` channel exponent and the rec.709-style coefficients."""
    r, g, b = (c / 255.0 for c in rgb)
    return (
        _SA98G["sRco"] * (r ** _SA98G["mainTRC"])
        + _SA98G["sGco"] * (g ** _SA98G["mainTRC"])
        + _SA98G["sBco"] * (b ** _SA98G["mainTRC"])
    )


def _soft_clamp(y: float) -> float:
    """Black-level soft clamp from APCA spec — only affects the very-
    dark end; suppresses noise without inflating dark-mode contrast
    like WCAG 2.x's +0.05 flare term does."""
    if y < _SA98G["blkThrs"]:
        return y + (_SA98G["blkThrs"] - y) ** _SA98G["blkClmp"]
    return y


def apca(fg_hex: str, bg_hex: str) -> float:
    """Return APCA Lc as a signed float.

    Positive Lc → dark text on light background.
    Negative Lc → light text on dark background.
    |Lc| ≥ 75 is the body-text Silver threshold (≈ WCAG 2 7:1).
    |Lc| ≥ 45 is the headline / non-text Bronze threshold.

    Output is rounded to one decimal place per the apca-w3 convention.
    """
    y_txt = _soft_clamp(_srgb_to_y(_hex_to_rgb(fg_hex)))
    y_bg = _soft_clamp(_srgb_to_y(_hex_to_rgb(bg_hex)))

    # Forward (dark text on light bg) vs reverse (light text on dark bg)
    if y_bg > y_txt:
        # Forward — dark text on light bg
        sapc = (y_bg ** _SA98G["normBG"] - y_txt ** _SA98G["normTXT"]) * _SA98G["scaleBoW"]
        if sapc < _SA98G["loClip"]:
            return 0.0
        output = sapc - _SA98G["loBoWoffset"]
    else:
        # Reverse — light text on dark bg
        sapc = (y_bg ** _SA98G["revBG"] - y_txt ** _SA98G["revTXT"]) * _SA98G["scaleWoB"]
        if sapc > -_SA98G["loClip"]:
            return 0.0
        output = sapc + _SA98G["loWoBoffset"]

    return round(output * 100.0, 1)


# ---------------------------------------------------------------------------
# WCAG 2.x — the simple ratio
# ---------------------------------------------------------------------------


def _srgb_to_relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG 2.x relative luminance (L)."""

    def _ch(c: int) -> float:
        v = c / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * _ch(r) + 0.7152 * _ch(g) + 0.0722 * _ch(b)


def wcag2_ratio(fg_hex: str, bg_hex: str) -> float:
    """Return (L1 + 0.05) / (L2 + 0.05) where L1 ≥ L2 — the canonical
    WCAG 2.x contrast ratio. Always positive, always ≥ 1.0."""
    l1 = _srgb_to_relative_luminance(_hex_to_rgb(fg_hex))
    l2 = _srgb_to_relative_luminance(_hex_to_rgb(bg_hex))
    if l1 < l2:
        l1, l2 = l2, l1
    return round((l1 + 0.05) / (l2 + 0.05), 2)


# ---------------------------------------------------------------------------
# Polarity + ink picker
# ---------------------------------------------------------------------------


def polarity_of(bg_hex: str) -> Polarity:
    """Return 'dark_on_light' or 'light_on_dark' for a given surface
    colour, based on which ink yields higher |APCA Lc|."""
    lc_black = abs(apca("#000000", bg_hex))
    lc_white = abs(apca("#FFFFFF", bg_hex))
    return "dark_on_light" if lc_black >= lc_white else "light_on_dark"


def pick_ink(bg_hex: str) -> tuple[str, Polarity]:
    """Return (ink_hex, polarity) — the better of #000 / #FFF against
    a surface."""
    polarity = polarity_of(bg_hex)
    return ("#000000" if polarity == "dark_on_light" else "#FFFFFF", polarity)


def brand_on_color(
    bg_hex: str,
    *,
    dark: str = "#0A0B11",
    light: str = "#F5F2E8",
    aa: float = 4.5,
) -> str:
    """Pick a legible on-colour (text/ink) for a brand-coloured fill.

    The Adaptive Theming Engine recolours the whole UI to each club's brand,
    so a button's background becomes the brand seed — which may be light
    (the lane-yellow default) or dark (a navy / maroon club). This selector
    keeps the label readable on either, reusing the deterministic contrast
    primitives above rather than hard-coding a per-club value.

    Preference order:
      1. MediaHub's own ink pair — paper-black ``dark`` / paper-cream
         ``light`` — picking whichever clears WCAG 2.x AA (``aa``, default
         4.5:1). This keeps the house aesthetic; for the lane-yellow default
         it returns the existing near-black, so nothing changes there.
      2. If neither house ink clears AA (a rare mid-luminance seed where no
         ink can comfortably), fall back to :func:`pick_ink` — maximal pure
         #000 / #FFF — so we always emit the highest-contrast option available.

    Returns an uppercase hex string. Deterministic and pure; no I/O.
    """
    dark_ratio = wcag2_ratio(dark, bg_hex)
    light_ratio = wcag2_ratio(light, bg_hex)
    if dark_ratio >= light_ratio:
        best, best_ratio = dark, dark_ratio
    else:
        best, best_ratio = light, light_ratio
    if best_ratio >= aa:
        return best
    return pick_ink(bg_hex)[0]
