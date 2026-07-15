"""Medal chrome — deterministic specular ramps + bevels (Canva gap analysis F9).

Canva medal/trophy templates use metallic chrome — a multi-stop specular
gradient, gradient-clipped numerals, bevelled panels — so a *gold* card visibly
outranks a *silver* one; MediaHub painted medal tier as one flat accent hex. This
module closes that with a **deterministic** 7-stop specular ramp derived from the
existing medal tint (fixed lighten/darken offsets — same tint always yields the
same ramp), plus the bevel shadow the chip carries.

Hard bounds kept:
* **Brand-locked.** The ramp is pure maths on the medal tint the engine already
  resolved (the fixed metallic tiers are the one sanctioned decorative palette);
  no new hue is invented. The bevel is neutral white/black alphas (a light
  effect, not colour) — the same latitude the elevation shadows use.
* **APCA-gated by the caller.** The caller checks the ramp's darkest stop against
  the ground and downgrades to the flat tint when it fails (see ``render``).
* **Byte-identical when absent.** A non-medal card never emits the ramp var or
  the chrome CSS, so its render is unchanged.
* **Deterministic.** Same tint → same ramp bytes; mirrored as static CSS in the
  medal motion scene for still↔motion parity.
"""

from __future__ import annotations


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    h = (value or "").lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _darken(value: str, amount: float) -> str:
    r, g, b = _hex_to_rgb(value)
    return _rgb_to_hex((r * (1 - amount), g * (1 - amount), b * (1 - amount)))


def _lighten(value: str, amount: float) -> str:
    r, g, b = _hex_to_rgb(value)
    return _rgb_to_hex((r + (255 - r) * amount, g + (255 - g) * amount, b + (255 - b) * amount))


# The 7 fixed (position%, transform) stops of the specular ramp: a shadowed
# edge, a bright specular band off-centre — the light-dark-light read the eye
# recognises as polished metal. Order is fixed → deterministic ramp. The edge
# darken is kept moderate (0.34) so the ramp's *darkest* stop still clears the
# APCA gate against a typical dark club ground (the common gold-on-navy case) —
# the metal reads without the gradient-clipped numeral going illegible.
_RAMP: tuple[tuple[int, str, float], ...] = (
    (0, "darken", 0.34),
    (18, "darken", 0.16),
    (36, "base", 0.0),
    (50, "lighten", 0.42),
    (64, "base", 0.0),
    (82, "darken", 0.20),
    (100, "darken", 0.34),
)


def medal_ramp_stops(tint_hex: str) -> list[str]:
    """The 7 hex stops of the specular ramp derived from ``tint_hex`` (dark→…→dark)."""
    out: list[str] = []
    for _pos, op, amt in _RAMP:
        if op == "darken":
            out.append(_darken(tint_hex, amt))
        elif op == "lighten":
            out.append(_lighten(tint_hex, amt))
        else:
            out.append(_rgb_to_hex(_hex_to_rgb(tint_hex)))
    return out


def medal_ramp_css(tint_hex: str, *, angle: int = 135) -> str:
    """The ``linear-gradient(...)`` value for the specular ramp (135deg default).

    The angle matches the elevation system's implied light (top-left), so the
    metal's highlight and the card's shadows agree on one light source.
    """
    stops = medal_ramp_stops(tint_hex)
    parts = [f"{hexv} {pos}%" for (pos, _op, _amt), hexv in zip(_RAMP, stops)]
    return f"linear-gradient({int(angle)}deg, " + ", ".join(parts) + ")"


def darkest_ramp_stop(tint_hex: str) -> str:
    """The darkest stop of the ramp — the worst-case colour for the APCA gate."""
    return _darken(tint_hex, 0.34)


# The bevel: an inset top highlight + inset bottom shadow (the light-from-above
# illusion) plus a 1px white-alpha rim. Neutral alphas only (a light effect, not
# a colour) — the same latitude the elevation shadows use.
MEDAL_BEVEL_SHADOW = "inset 0 1px 0 rgba(255,255,255,0.28), inset 0 -2px 4px rgba(0,0,0,0.5)"
MEDAL_CHIP_BORDER = "1px solid rgba(255,255,255,0.28)"


def medal_numeral_css(selector: str) -> str:
    """Gradient-clipped numeral CSS for ``selector`` (the big-numeral archetypes).

    Paints the numeral with the ramp clipped to the glyphs. Consumes
    ``--mh-medal-ramp`` (emitted only when the gate passed), so it is inert when
    the var is absent — but the caller only injects this string for medal cards.
    """
    return (
        f"\n/* --- F9 medal chrome: gradient-clipped numeral --- */\n"
        f"{selector} {{ background: var(--mh-medal-ramp);"
        f" -webkit-background-clip: text; background-clip: text;"
        f" -webkit-text-fill-color: transparent; color: transparent; }}\n"
    )


def medal_chip_css(selector: str) -> str:
    """Bevelled ramp-filled chip CSS for ``selector`` (the result-chip archetypes)."""
    return (
        f"\n/* --- F9 medal chrome: bevelled ramp chip --- */\n"
        f"{selector} {{ background: var(--mh-medal-ramp);"
        f" box-shadow: {MEDAL_BEVEL_SHADOW}; border: {MEDAL_CHIP_BORDER}; }}\n"
    )


__all__ = [
    "medal_ramp_stops",
    "medal_ramp_css",
    "darkest_ramp_stop",
    "MEDAL_BEVEL_SHADOW",
    "MEDAL_CHIP_BORDER",
    "medal_numeral_css",
    "medal_chip_css",
]
