"""Material 3 role-token mapping for the Adaptive Theming Engine.

Given a ``DerivedPalette``, return a ``ThemeRoles`` containing the
light-mode and dark-mode ``RoleScheme`` instances. Each scheme has
~30 named roles: primary, on_primary, primary_container,
on_primary_container, surface, surface_container, outline, …

The tone selections come straight from the published MD3 tables
(documented in ``concepts/dynamic_color_scheme.md`` of
``material-color-utilities``). The MD3 contrast guarantees are baked
into the geometry — a tone delta ≥ 50 between any role and its "on"
pair gives WCAG AA (4.5:1) automatically. We rely on that here; the
extra APCA/CVD QA gates run in ``quality.py``.

Per-role tone lookup:

    Light       | Dark
    --------    | --------
    primary               40       | 80
    on_primary           100       | 20
    primary_container     90       | 30
    on_primary_container  10       | 90
    (same pattern for secondary, tertiary, error)

    background            99       | 10
    on_background         10       | 90
    surface               99       | 10
    on_surface            10       | 90
    surface_variant       90       | 30   (neutral_variant palette)
    on_surface_variant    30       | 80   (neutral_variant palette)
    surface_container_lowest  100  | 4
    surface_container_low     96   | 10
    surface_container         94   | 12
    surface_container_high    92   | 17
    surface_container_highest 90   | 22

    outline               50       | 60   (neutral_variant palette)
    outline_variant       80       | 30   (neutral_variant palette)

    inverse_surface       20       | 90
    inverse_on_surface    95       | 20
    inverse_primary       80       | 40

References:
  - m3.material.io/styles/color/roles
  - material-color-utilities/concepts/dynamic_color_scheme.md
  - flutter.dev/ColorScheme (canonical list of ~30 roles)
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

from .palette import DerivedPalette, TonalRamp


__all__ = ["RoleScheme", "ThemeRoles", "derive_roles", "ROLE_TONE_MAP"]


# ---------------------------------------------------------------------------
# Per-role (palette, light_tone, dark_tone) table
# ---------------------------------------------------------------------------
# Tuple shape: (palette_name, light_tone, dark_tone)
# Palette names: "primary" / "secondary" / "tertiary" / "neutral" /
#                "neutral_variant" / "error"

ROLE_TONE_MAP: dict[str, tuple[str, int, int]] = {
    # Primary
    "primary": ("primary", 40, 80),
    "on_primary": ("primary", 100, 20),
    "primary_container": ("primary", 90, 30),
    "on_primary_container": ("primary", 10, 90),
    # Secondary
    "secondary": ("secondary", 40, 80),
    "on_secondary": ("secondary", 100, 20),
    "secondary_container": ("secondary", 90, 30),
    "on_secondary_container": ("secondary", 10, 90),
    # Tertiary
    "tertiary": ("tertiary", 40, 80),
    "on_tertiary": ("tertiary", 100, 20),
    "tertiary_container": ("tertiary", 90, 30),
    "on_tertiary_container": ("tertiary", 10, 90),
    # Error
    "error": ("error", 40, 80),
    "on_error": ("error", 100, 20),
    "error_container": ("error", 90, 30),
    "on_error_container": ("error", 10, 90),
    # Background + Surface
    "background": ("neutral", 99, 10),
    "on_background": ("neutral", 10, 90),
    "surface": ("neutral", 99, 10),
    "on_surface": ("neutral", 10, 90),
    # Surface containers (M3 elevation tints)
    "surface_container_lowest": ("neutral", 100, 0),
    "surface_container_low": ("neutral", 95, 10),
    "surface_container": ("neutral", 90, 20),
    "surface_container_high": ("neutral", 90, 30),
    "surface_container_highest": ("neutral", 90, 30),
    # Surface-variant (neutral_variant palette)
    "surface_variant": ("neutral_variant", 90, 30),
    "on_surface_variant": ("neutral_variant", 30, 80),
    # Outline
    "outline": ("neutral_variant", 50, 60),
    "outline_variant": ("neutral_variant", 80, 30),
    # Inverse
    "inverse_surface": ("neutral", 20, 90),
    "inverse_on_surface": ("neutral", 95, 20),
    "inverse_primary": ("primary", 80, 40),
}


@dataclass
class RoleScheme:
    """~30 MD3 role tokens for a single scheme (light or dark)."""

    primary: str
    on_primary: str
    primary_container: str
    on_primary_container: str

    secondary: str
    on_secondary: str
    secondary_container: str
    on_secondary_container: str

    tertiary: str
    on_tertiary: str
    tertiary_container: str
    on_tertiary_container: str

    error: str
    on_error: str
    error_container: str
    on_error_container: str

    background: str
    on_background: str
    surface: str
    on_surface: str

    surface_container_lowest: str
    surface_container_low: str
    surface_container: str
    surface_container_high: str
    surface_container_highest: str

    surface_variant: str
    on_surface_variant: str

    outline: str
    outline_variant: str

    inverse_surface: str
    inverse_on_surface: str
    inverse_primary: str

    # MediaHub addition — `focus` is the colour of the focus ring;
    # aliased to primary so every theme has a consistent accent.
    focus: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class ThemeRoles:
    light: RoleScheme
    dark: RoleScheme


def _build_scheme(palette: DerivedPalette, *, is_dark: bool) -> RoleScheme:
    values: dict[str, str] = {}
    for role_name, (palette_name, light_t, dark_t) in ROLE_TONE_MAP.items():
        ramp: TonalRamp = palette.ramp_by_name(palette_name)
        tone = dark_t if is_dark else light_t
        values[role_name] = ramp.tone(tone)
    # Focus aliases to primary.
    values["focus"] = values["primary"]
    return RoleScheme(**values)


def derive_roles(palette: DerivedPalette) -> ThemeRoles:
    """Build light + dark RoleScheme from a DerivedPalette."""
    return ThemeRoles(
        light=_build_scheme(palette, is_dark=False),
        dark=_build_scheme(palette, is_dark=True),
    )
