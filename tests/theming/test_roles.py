"""Tests for mediahub.theming.roles."""
from __future__ import annotations

import re

import pytest

from mediahub.theming.palette import derive_palette
from mediahub.theming.roles import derive_roles, ThemeRoles, ROLE_TONE_MAP


_TEST_SEEDS = ["#D4FF3A", "#0E2A47", "#A30D2D", "#06D6A0"]

_REQUIRED_ROLES = sorted(ROLE_TONE_MAP.keys()) + ["focus"]


class TestRoleSchemeShape:
    @pytest.mark.parametrize("seed", _TEST_SEEDS)
    def test_light_and_dark_present(self, seed):
        palette = derive_palette(seed)
        roles = derive_roles(palette)
        assert isinstance(roles, ThemeRoles)
        assert roles.light is not None
        assert roles.dark is not None

    @pytest.mark.parametrize("seed", _TEST_SEEDS)
    def test_all_roles_populated_light(self, seed):
        palette = derive_palette(seed)
        roles = derive_roles(palette)
        light_dict = roles.light.as_dict()
        for role in _REQUIRED_ROLES:
            assert role in light_dict, f"missing role {role}"
            value = light_dict[role]
            assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value), f"{role}={value!r}"

    @pytest.mark.parametrize("seed", _TEST_SEEDS)
    def test_all_roles_populated_dark(self, seed):
        palette = derive_palette(seed)
        roles = derive_roles(palette)
        dark_dict = roles.dark.as_dict()
        for role in _REQUIRED_ROLES:
            assert role in dark_dict, f"missing role {role}"
            value = dark_dict[role]
            assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value), f"{role}={value!r}"


class TestLightVsDark:
    def test_primary_differs_between_schemes(self):
        """Light primary is at tone 40, dark primary is at tone 80 —
        they MUST be different."""
        palette = derive_palette("#D4FF3A")
        roles = derive_roles(palette)
        assert roles.light.primary != roles.dark.primary

    def test_surface_differs_between_schemes(self):
        palette = derive_palette("#D4FF3A")
        roles = derive_roles(palette)
        assert roles.light.surface != roles.dark.surface

    def test_light_surface_is_lighter_than_dark_surface(self):
        from coloraide import Color
        palette = derive_palette("#D4FF3A")
        roles = derive_roles(palette)
        l_light = Color(roles.light.surface).convert("lab").coords()[0]
        l_dark = Color(roles.dark.surface).convert("lab").coords()[0]
        assert l_light > l_dark, (
            f"light surface L*={l_light:.1f} should be brighter than "
            f"dark surface L*={l_dark:.1f}"
        )

    def test_inverse_primary_swaps(self):
        """Light scheme's inverse_primary uses dark's tone (80), and vice
        versa — they should match."""
        palette = derive_palette("#D4FF3A")
        roles = derive_roles(palette)
        assert roles.light.inverse_primary == roles.dark.primary
        assert roles.dark.inverse_primary == roles.light.primary


class TestFocusAliasesPrimary:
    @pytest.mark.parametrize("seed", _TEST_SEEDS)
    def test_focus_equals_primary_in_light(self, seed):
        palette = derive_palette(seed)
        roles = derive_roles(palette)
        assert roles.light.focus == roles.light.primary

    @pytest.mark.parametrize("seed", _TEST_SEEDS)
    def test_focus_equals_primary_in_dark(self, seed):
        palette = derive_palette(seed)
        roles = derive_roles(palette)
        assert roles.dark.focus == roles.dark.primary


class TestRoleToneMap:
    def test_role_tone_map_is_complete(self):
        # Confirm the canonical roles we promised in the plan are there.
        for role in ("primary", "on_primary", "primary_container",
                     "on_primary_container", "secondary", "tertiary",
                     "error", "background", "surface", "surface_variant",
                     "on_surface", "on_surface_variant",
                     "outline", "outline_variant",
                     "inverse_primary", "inverse_surface"):
            assert role in ROLE_TONE_MAP, f"missing role {role} in ROLE_TONE_MAP"

    def test_on_pairs_invert_lightness(self):
        """Every (role, on_role) pair should have inverted tones:
        light scheme's role and on_role differ by ≥ 50 tones."""
        for role, (palette_name, l_tone, d_tone) in ROLE_TONE_MAP.items():
            if not role.startswith("on_"):
                continue
            paired_role = role[3:]   # strip "on_"
            if paired_role not in ROLE_TONE_MAP:
                continue
            _, paired_l, paired_d = ROLE_TONE_MAP[paired_role]
            assert abs(l_tone - paired_l) >= 50, (
                f"{role}/{paired_role} light: tones {l_tone} vs {paired_l}, "
                f"need ≥50 delta for MD3 contrast guarantee"
            )
            assert abs(d_tone - paired_d) >= 50, (
                f"{role}/{paired_role} dark: tones {d_tone} vs {paired_d}, "
                f"need ≥50 delta for MD3 contrast guarantee"
            )
