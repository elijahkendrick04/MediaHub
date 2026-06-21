"""charts.palette — resolve a chart's colours from the brand's role vars.

A chart paints in the org's own brand colours, exactly like every other surface:
the ground, the ink, the gridlines and the series ramp all derive from the same
resolved ``--mh-*`` role set the cards, motion and elements read
(``graphic_renderer.render.resolved_role_vars_for_brief`` / ``_mh_role_vars``).
This guarantees a chart is on-brand and — where it carries labels — APCA-legible.

Deterministic: same role vars → same colours. No LLM, no randomness; this is
presentation maths, not a judgement call (the *choice* of chart is the AI's job,
in :mod:`charts.recommend`; the colours are not).
"""

from __future__ import annotations

from typing import Optional

# Conservative neutral fallback if a role var is absent (keeps a chart renderable
# even with no brand kit). Matches elements.recolour so surfaces stay consistent.
_ROLE_FALLBACK: dict[str, str] = {
    "--mh-primary": "#0A2540",
    "--mh-secondary": "#1B3D5C",
    "--mh-surface": "#051433",
    "--mh-accent": "#FFB81C",
    "--mh-on-primary": "#FFFFFF",
    "--mh-on-surface": "#FFFFFF",
    "--mh-outline": "rgba(255,255,255,0.20)",
}

# Medal tints — the one sanctioned off-palette set (the renderer already paints
# medal-tinted accents). Used by pie/medal-table charts only.
MEDAL_COLOURS: dict[str, str] = {
    "gold": "#F2C14E",
    "silver": "#C9D1D9",
    "bronze": "#C8803C",
}


def role_vars_from_palette(palette: Optional[dict] = None, brand_kit=None) -> dict[str, str]:
    """The resolved ``--mh-*`` set for a bare palette / brand kit (no card brief).

    Delegates to the renderer's single source of truth so a chart's colours match
    the cards exactly. Imported lazily to avoid an import cycle with
    ``graphic_renderer``. Falls back to a neutral set if the renderer is unavailable.
    """
    try:
        from mediahub.graphic_renderer.render import _mh_role_vars

        rv = _mh_role_vars(dict(palette or {}), brand_kit)
        if isinstance(rv, dict) and rv:
            return {**_ROLE_FALLBACK, **rv}
    except Exception:
        pass
    out = dict(_ROLE_FALLBACK)
    for k in ("primary", "secondary", "accent"):
        v = (palette or {}).get(k)
        if isinstance(v, str) and v.strip():
            out[f"--mh-{k}"] = v.strip()
    return out


def role(role_vars: dict[str, str], name: str) -> str:
    """Read one ``--mh-*`` role with a robust fallback."""
    key = name if name.startswith("--mh-") else f"--mh-{name}"
    return role_vars.get(key) or _ROLE_FALLBACK.get(key, "#FFFFFF")


class ChartColours:
    """The resolved colour set a chart paints with, derived once from role vars."""

    def __init__(self, role_vars: dict[str, str]):
        rv = {**_ROLE_FALLBACK, **(role_vars or {})}
        self.role_vars = rv
        # Paint on the deep brand surface; ink + gridlines read off it.
        self.ground = rv["--mh-surface"]
        self.ink = _legible_ink(rv["--mh-on-surface"], rv["--mh-on-primary"], self.ground)
        self.muted = _mix(self.ink, self.ground, 0.55)  # axis labels / meta
        self.grid = _mix(self.ink, self.ground, 0.82)  # hairline gridlines
        self.accent = rv["--mh-accent"]
        self.secondary = rv["--mh-secondary"]
        self.primary = rv["--mh-primary"]
        # Ink that reads on a bar/slice painted in the accent (data labels inside).
        self.on_accent = _legible_ink(rv["--mh-primary"], rv["--mh-on-primary"], self.accent)

    def series_colour(self, role_name: str, index: int) -> str:
        """The fill for a series given its declared role and ordinal position."""
        name = (role_name or "auto").lower()
        if name in MEDAL_COLOURS:
            return MEDAL_COLOURS[name]
        direct = {
            "accent": self.accent,
            "secondary": self.secondary,
            "primary": self.primary,
            "on_surface": self.ink,
        }
        if name in direct:
            return direct[name]
        return self.ramp(index)

    def ramp(self, index: int) -> str:
        """A deterministic multi-series ramp from the brand roles (cycles)."""
        base = [
            self.accent,
            self.secondary,
            _mix(self.accent, self.ground, 0.35),
            _mix(self.secondary, self.ink, 0.25),
            _mix(self.accent, self.ink, 0.30),
        ]
        return base[index % len(base)]

    def category_colour(self, label: str, index: int) -> str:
        """Pick a per-category colour, honouring medal labels (gold/silver/bronze)."""
        low = (label or "").strip().lower()
        for medal, hexv in MEDAL_COLOURS.items():
            if medal in low:
                return hexv
        return self.ramp(index)


# --------------------------------------------------------------------------- #
# colour maths (deterministic; small, dependency-free hex blending)
# --------------------------------------------------------------------------- #
def _legible_ink(preferred: str, alt: str, bg: str) -> str:
    """Pick whichever ink (preferred or its alt) reads better on ``bg`` via APCA."""
    try:
        from mediahub.quality.compliance import is_legible

        if is_legible(preferred, bg):
            return preferred
        if is_legible(alt, bg):
            return alt
    except Exception:
        pass
    # Last resort: pick by simple luminance so labels are never invisible.
    return "#FFFFFF" if _luminance(bg) < 0.5 else "#0B0B0B"


def _mix(a: str, b: str, t: float) -> str:
    """Linear blend of two hex colours; t=0 → a, t=1 → b. rgba ``b`` is ignored."""
    ar, ag, ab = _to_rgb(a)
    br, bg, bb = _to_rgb(b)
    t = max(0.0, min(1.0, t))
    r = round(ar + (br - ar) * t)
    g = round(ag + (bg - ag) * t)
    bl = round(ab + (bb - ab) * t)
    return f"#{r:02X}{g:02X}{bl:02X}"


def _to_rgb(hex_or_rgba: str) -> tuple[int, int, int]:
    s = (hex_or_rgba or "").strip()
    if s.startswith("rgba") or s.startswith("rgb"):
        nums = "".join(ch if (ch.isdigit() or ch in ".,") else " " for ch in s.split("(", 1)[-1])
        parts = [p for p in nums.replace(",", " ").split() if p]
        try:
            return (int(float(parts[0])), int(float(parts[1])), int(float(parts[2])))
        except (IndexError, ValueError):
            return (128, 128, 128)
    s = s.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return (128, 128, 128)
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return (128, 128, 128)


def _luminance(hex_colour: str) -> float:
    r, g, b = _to_rgb(hex_colour)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


__all__ = [
    "ChartColours",
    "role_vars_from_palette",
    "role",
    "MEDAL_COLOURS",
]
