"""SEQ-0 — the generation DesignTokens contract + lockup selection.

Verifies the contract the design-spec director consumes:
  * every renderer role token resolves with hex + brightness + when_to_use
    + APCA evidence, and matches what the v2 renderer actually paints;
  * the flat BrandKit fields stay authoritative (back-compat aliases);
  * logo lockups are typed by form/theme and derived only from real assets;
  * the lockup selector is deterministic and safe-by-default;
  * the voice profile carries examples (capped), the ban-list, emoji policy;
  * the MEDIAHUB_GEN_V2 flag read exists with an explicit kill switch.

No LLM, no network — the contract is deterministic by design.
"""

from __future__ import annotations

import pytest

from mediahub.brand.design_tokens import resolve_design_tokens
from mediahub.brand.kit import BrandKit
from mediahub.graphic_renderer.archetypes import TOKEN_ROLES
from mediahub.theming.logo_chip import select_logo_lockup


NAVY_GOLD = BrandKit(
    profile_id="seq0-club",
    display_name="SEQ0 Swimming Club",
    primary_colour="#0E2A47",
    secondary_colour="#C9A227",
)


def test_roles_cover_token_vocabulary_with_guidance():
    tokens = resolve_design_tokens("seq0-club", brand_kit=NAVY_GOLD)
    roles = tokens["roles"]
    assert set(roles) == set(TOKEN_ROLES)
    for name, role in roles.items():
        assert role["hex"].startswith("#"), name
        assert role["brightness"] in ("light", "dark"), name
        assert len(role["when_to_use"]) > 20, name
        assert role["apca_vs_ground"] >= 0.0, name
    # Known colours: a navy ground is dark, its on-colour light.
    assert roles["primary"]["brightness"] == "dark"
    assert roles["on_primary"]["brightness"] == "light"


def test_roles_match_what_the_renderer_paints():
    """One pipeline, no drift: contract hexes == the renderer's --mh-* vars."""
    from mediahub.graphic_renderer.render import _mh_role_vars

    tokens = resolve_design_tokens("seq0-club", brand_kit=NAVY_GOLD)
    mh = _mh_role_vars(
        {"primary": NAVY_GOLD.primary_colour, "secondary": NAVY_GOLD.secondary_colour},
        NAVY_GOLD,
    )
    for role in TOKEN_ROLES:
        assert tokens["roles"][role]["hex"] == mh["--mh-" + role.replace("_", "-")]


def test_flat_aliases_stay_authoritative():
    tokens = resolve_design_tokens("seq0-club", brand_kit=NAVY_GOLD)
    assert tokens["flat"]["primary_colour"] == "#0E2A47"
    assert tokens["flat"]["secondary_colour"] == "#C9A227"
    assert tokens["flat"]["accent_colour"] is None


def test_old_persisted_profile_shape_still_resolves():
    """A kit loaded from an old profile dict (unknown keys ignored) resolves."""
    kit = BrandKit.from_dict(
        {
            "profile_id": "legacy",
            "display_name": "Legacy Club",
            "primary_colour": "#A30D2D",
            "secondary_colour": "#000000",
            "some_future_key": {"ignored": True},
        }
    )
    tokens = resolve_design_tokens("legacy", brand_kit=kit)
    assert tokens["roles"]["primary"]["hex"] == "#A30D2D"
    assert tokens["display_name"] == "Legacy Club"


def test_unknown_profile_resolves_generic_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    tokens = resolve_design_tokens("does-not-exist-anywhere")
    assert set(tokens["roles"]) == set(TOKEN_ROLES)
    assert tokens["logo_lockups"] == []
    assert tokens["voice"]["examples"] == []


def test_type_pairing_is_typed():
    tokens = resolve_design_tokens("seq0-club", brand_kit=NAVY_GOLD)
    t = tokens["type"]
    assert t["pairing"] == "anton-inter"
    assert t["headline_family"] == "Anton"
    assert t["body_family"] == "Inter"
    assert t["numeral_family"] == "JetBrains Mono"


def test_voice_profile_examples_capped_and_banlist_present(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.caption_examples import append_example

    for i in range(8):
        append_example("seq0-voice", f"Approved caption number {i} — great swim!")
    tokens = resolve_design_tokens("seq0-voice", brand_kit=NAVY_GOLD)
    voice = tokens["voice"]
    assert 0 < len(voice["examples"]) <= 5
    assert any("delve" in p for p in voice["banned_phrases"])
    assert voice["emoji_policy"] == "sparing"
    assert isinstance(voice["tone"], str) and voice["tone"]


def test_inline_svg_mark_becomes_icon_lockup():
    kit = BrandKit(
        profile_id="seq0-svg",
        display_name="SVG Club",
        primary_colour="#0E2A47",
        secondary_colour="#C9A227",
        logo_svg='<svg xmlns="http://www.w3.org/2000/svg"><rect fill="#F5F2E8"/></svg>',
    )
    tokens = resolve_design_tokens("seq0-svg", brand_kit=kit)
    lockups = tokens["logo_lockups"]
    assert len(lockups) == 1
    assert lockups[0]["form"] == "icon"
    assert lockups[0]["source"] == "brand_kit_svg"
    # A cream mark is a light-theme mark (suits dark grounds).
    assert lockups[0]["theme"] == "light"
    assert lockups[0]["dominant_hex"] == "#F5F2E8"


def test_library_logos_typed_by_form_and_theme(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.club_profile import ClubProfile, save_profile

    profile = ClubProfile(profile_id="seq0-lib", display_name="Lib Club")
    profile.brand_logos = [
        {
            "logo_id": "aaa111",
            "label": "Horizontal wordmark",
            "original_filename": "club-horizontal.png",
            "ai_dominant_colours": ["#f7f7f7"],
        },
        {
            "logo_id": "bbb222",
            "label": "Stacked crest",
            "original_filename": "crest-stacked.svg",
            "ai_dominant_colours": ["#101820"],
        },
        {
            "logo_id": "ccc333",
            "label": "",
            "original_filename": "badge.png",
            "ai_dominant_colours": [],
        },
    ]
    save_profile(profile)

    tokens = resolve_design_tokens("seq0-lib")
    by_id = {lk.get("logo_id"): lk for lk in tokens["logo_lockups"]}
    assert by_id["aaa111"]["form"] == "full_horizontal"
    assert by_id["aaa111"]["theme"] == "light"
    assert by_id["bbb222"]["form"] == "full_stacked"
    assert by_id["bbb222"]["theme"] == "dark"
    assert by_id["ccc333"]["form"] == "icon"
    assert by_id["ccc333"]["theme"] == "unknown"


# ---------------------------------------------------------------------------
# select_logo_lockup — the deterministic per-background selection
# ---------------------------------------------------------------------------

LIGHT_MARK = {"form": "icon", "theme": "light", "dominant_hex": "#F7F7F7"}
DARK_MARK = {"form": "icon", "theme": "dark", "dominant_hex": "#101820"}
UNKNOWN_MARK = {"form": "full_horizontal", "theme": "unknown", "dominant_hex": None}


def test_selector_picks_contrasting_mark_bare():
    choice = select_logo_lockup([LIGHT_MARK, DARK_MARK], "#0E2A47")
    assert choice is not None
    assert choice.lockup is LIGHT_MARK  # light mark on a navy ground
    assert choice.mode == "bare"
    on_light = select_logo_lockup([LIGHT_MARK, DARK_MARK], "#F5F2E8")
    assert on_light.lockup is DARK_MARK
    assert on_light.mode == "bare"


def test_selector_is_deterministic():
    runs = [select_logo_lockup([LIGHT_MARK, DARK_MARK, UNKNOWN_MARK], "#0E2A47") for _ in range(5)]
    assert len({id(r.lockup) for r in runs}) == 1
    assert len({r.mode for r in runs}) == 1


def test_selector_unknown_dominant_defaults_to_chip():
    choice = select_logo_lockup([UNKNOWN_MARK], "#0E2A47")
    assert choice.mode == "chip"
    assert choice.chip_color  # a real chip colour is supplied
    assert "could not parse" in choice.decision.reasoning


def test_selector_honours_preferred_form_when_available():
    pool = [LIGHT_MARK, {**DARK_MARK, "form": "mono"}]
    choice = select_logo_lockup(pool, "#F5F2E8", prefer_form="mono_dark")
    assert choice.lockup["form"] == "mono"
    # No candidate of the asked form → fall back to the full pool.
    fallback = select_logo_lockup([LIGHT_MARK], "#0E2A47", prefer_form="full_stacked")
    assert fallback is not None and fallback.lockup is LIGHT_MARK


def test_selector_empty_pool_returns_none():
    assert select_logo_lockup([], "#0E2A47") is None


# ---------------------------------------------------------------------------
# Feature-flag read (kill switch)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value,expected", [("0", False), ("false", False), ("1", True), ("", True)])
def test_gen_v2_flag_kill_switch(monkeypatch, value, expected):
    from mediahub.graphic_renderer import archetypes

    monkeypatch.setenv("MEDIAHUB_GEN_V2", value)
    assert archetypes.is_enabled() is expected
