"""elements.gradients — brand-palette gradient presets (roadmap 1.10).

Deterministic linear/radial CSS gradients interpolated from the resolved brand
role colours. No invented hues: every stop is one of the brand's own roles, so a
gradient background is automatically on-brand. (Canva/Express let you paint any
gradient; MediaHub keeps it brand-locked — the point of the product.)

These are *presets*, not free-form pickers — a curated, named set the director
or a human can apply. Prompt-driven "make me a sunset gradient" is intentionally
out of scope: it would mean inventing off-brand colours.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import recolour as _recolour


@dataclass(frozen=True)
class GradientPreset:
    id: str
    name: str
    kind: str  # "linear" | "radial"
    stops: tuple[str, ...]  # role var keys, e.g. ("--mh-primary","--mh-surface")
    angle: int = 160  # linear angle in degrees
    shape: str = "circle at 30% 25%"  # radial shape/position


# The curated preset set. Stops are role-var keys resolved at apply time.
PRESETS: tuple[GradientPreset, ...] = (
    GradientPreset(
        "grad.brand_descent", "Brand descent", "linear", ("--mh-primary", "--mh-surface"), angle=160
    ),
    GradientPreset(
        "grad.accent_rise",
        "Accent rise",
        "linear",
        ("--mh-surface", "--mh-primary", "--mh-accent"),
        angle=120,
    ),
    GradientPreset(
        "grad.duotone", "Brand duotone", "linear", ("--mh-primary", "--mh-secondary"), angle=145
    ),
    GradientPreset(
        "grad.spotlight",
        "Accent spotlight",
        "radial",
        ("--mh-accent", "--mh-primary"),
        shape="circle at 30% 28%",
    ),
    GradientPreset(
        "grad.deep_pool",
        "Deep pool",
        "radial",
        ("--mh-surface", "--mh-primary"),
        shape="ellipse at 50% 0%",
    ),
    GradientPreset(
        "grad.podium",
        "Podium glow",
        "linear",
        ("--mh-primary", "--mh-surface", "--mh-secondary"),
        angle=200,
    ),
)

_BY_ID = {p.id: p for p in PRESETS}


def list_presets() -> list[GradientPreset]:
    return list(PRESETS)


def get_preset(preset_id: str) -> Optional[GradientPreset]:
    return _BY_ID.get(preset_id)


def gradient_css(preset: GradientPreset, role_vars: dict[str, str]) -> str:
    """A ready-to-use CSS ``background`` value for ``preset`` in these colours."""
    cols = [_hex(role_vars, key) for key in preset.stops]
    if len(cols) < 2:
        cols = cols + cols[-1:] if cols else ["#0A2540", "#051433"]
    stop_str = ", ".join(cols)
    if preset.kind == "radial":
        return f"radial-gradient({preset.shape}, {stop_str})"
    return f"linear-gradient({preset.angle}deg, {stop_str})"


def gradient_css_for_palette(
    preset_id: str, *, palette: Optional[dict] = None, brand_kit=None
) -> Optional[str]:
    preset = get_preset(preset_id)
    if preset is None:
        return None
    role_vars = _recolour.role_vars_from_palette(palette, brand_kit)
    return gradient_css(preset, role_vars)


def _hex(role_vars: dict[str, str], key: str) -> str:
    return role_vars.get(key) or _recolour._ROLE_FALLBACK.get(key, "#0A2540")


__all__ = [
    "GradientPreset",
    "PRESETS",
    "list_presets",
    "get_preset",
    "gradient_css",
    "gradient_css_for_palette",
]
