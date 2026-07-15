"""E6 (Canva gap analysis) — saliency-centred vignette / spotlight grounds.

The two subject-framing style-pack grounds (``vignette``, ``spotlight``) recentre
their darkening ellipse on the card's resolved saliency focus, so the athlete
sits in the lit pocket rather than the fixed frame centre. Photo-less cards (and
every other ground) keep the historic fixed centre — byte-identical — so only
photo cards on those two grounds change.

Covered here:

  * ``render._parse_focus_pos`` parses the CSS object-position vocabulary;
  * ``style_packs._ground_layer`` / ``pack_overlay_html`` recentre only
    vignette/spotlight, and are byte-identical when ``focus`` is None;
  * ``motion._pack_ground_focus_prop`` attaches ``packGroundFocus`` only for a
    vignette/spotlight pack WITH a photo;
  * ``StoryCard.tsx`` threads the focus through ``packGroundGradient`` /
    ``StylePackGroundLayer`` and keeps the fixed centre when it's absent.
"""

from __future__ import annotations

from mediahub.brand.kit import BrandKit
from mediahub.graphic_renderer import render as R
from mediahub.graphic_renderer import style_packs as sp
from mediahub.visual import motion


_STD_ALPHA = 0.24


def _story_src() -> str:
    return (motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx").read_text()


# --------------------------------------------------------------------------- #
# _parse_focus_pos
# --------------------------------------------------------------------------- #


def test_parse_focus_pos_percent_and_keywords():
    assert R._parse_focus_pos("50% 30%") == (50.0, 30.0)
    assert R._parse_focus_pos("center 28%") == (50.0, 28.0)
    assert R._parse_focus_pos("left top") == (0.0, 0.0)
    assert R._parse_focus_pos("right bottom") == (100.0, 100.0)
    # Out-of-range percents clamp to [0, 100].
    assert R._parse_focus_pos("140% -20%") == (100.0, 0.0)


def test_parse_focus_pos_rejects_unparseable():
    for bad in ("", "50%", "a b c", "cover", "50% purple"):
        assert R._parse_focus_pos(bad) is None


# --------------------------------------------------------------------------- #
# _ground_layer / pack_overlay_html
# --------------------------------------------------------------------------- #


def test_ground_layer_fixed_centres_are_byte_identical_without_focus():
    # The exact historic strings — proof the lever is byte-identical when unused.
    assert sp._ground_layer("vignette", _STD_ALPHA) == (
        "radial-gradient(115% 95% at 50% 45%, rgba(0,0,0,0) 52%, rgba(0,0,0,0.24) 100%)"
    )
    assert sp._ground_layer("spotlight", _STD_ALPHA) == (
        "radial-gradient(60% 50% at 50% 38%, rgba(0,0,0,0) 0%, rgba(0,0,0,0.24) 100%)"
    )
    # Passing None explicitly is the same as omitting it.
    assert sp._ground_layer("vignette", _STD_ALPHA, None) == sp._ground_layer(
        "vignette", _STD_ALPHA
    )


def test_ground_layer_recenters_vignette_and_spotlight_on_focus():
    vig = sp._ground_layer("vignette", _STD_ALPHA, (30.0, 22.0))
    assert "at 30% 22%" in vig and "at 50% 45%" not in vig
    spot = sp._ground_layer("spotlight", _STD_ALPHA, (68.0, 40.0))
    assert "at 68% 40%" in spot and "at 50% 38%" not in spot


def test_non_subject_grounds_ignore_focus():
    # A focus never touches the other grounds — the eye-path fades stay put.
    for ground in ("top_fade", "corner_fade", "gradient_mesh", "edge_frame"):
        assert sp._ground_layer(ground, _STD_ALPHA, (10.0, 90.0)) == sp._ground_layer(
            ground, _STD_ALPHA
        )


def test_pack_overlay_html_threads_focus_only_for_subject_grounds():
    vig_pack = sp.normalise_pack(ground="vignette")
    # Photo-less (focus None) is byte-identical to the pre-E6 overlay.
    base = sp.pack_overlay_html(vig_pack, width=1080, height=1350)
    assert "at 50% 45%" in base
    # A focus recentres the ellipse on the subject.
    focused = sp.pack_overlay_html(vig_pack, width=1080, height=1350, focus=(35.0, 24.0))
    assert "at 35% 24%" in focused and "at 50% 45%" not in focused
    # A non-subject ground pack is unchanged by a focus.
    flat_pack = sp.normalise_pack(ground="top_fade")
    assert sp.pack_overlay_html(flat_pack, width=1080, height=1350, focus=(35.0, 24.0)) == (
        sp.pack_overlay_html(flat_pack, width=1080, height=1350)
    )


# --------------------------------------------------------------------------- #
# motion side
# --------------------------------------------------------------------------- #


def test_motion_pack_ground_focus_prop_attaches_only_for_subject_grounds():
    # vignette + photo → the parsed focus rides as [fx, fy].
    b = {"style_pack": "vignette-dots-none-standard"}
    assert motion._pack_ground_focus_prop(b, "40% 26%", True) == [40, 26]
    # spotlight + photo likewise.
    b2 = {"style_pack": "spotlight-none-ring-bold"}
    assert motion._pack_ground_focus_prop(b2, "55% 33%", True) == [55, 33]
    # A non-subject ground → None (no prop, byte-identical cache key).
    b3 = {"style_pack": "top_fade-grain-none-standard"}
    assert motion._pack_ground_focus_prop(b3, "40% 26%", True) is None
    # No photo → None even for vignette.
    assert motion._pack_ground_focus_prop(b, "40% 26%", False) is None
    # Unparseable focus → None (never a malformed prop).
    assert motion._pack_ground_focus_prop(b, "cover", True) is None


def test_card_props_carry_pack_ground_focus_for_a_vignette_photo_card(tmp_path, monkeypatch):
    import types

    from PIL import Image

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    src = tmp_path / "athlete.jpg"
    Image.new("RGB", (600, 800), (18, 55, 130)).save(src, "JPEG")
    asset = types.SimpleNamespace(path=str(src))
    store = types.SimpleNamespace(get=lambda aid: asset)
    monkeypatch.setattr("mediahub.media_library.store.get_store", lambda: store)

    brand = BrandKit(
        profile_id="e6",
        display_name="E6 SC",
        primary_colour="#0E2A47",
        secondary_colour="#C9A227",
        accent_colour="#FFFFFF",
        short_name="E6",
    )
    from mediahub.creative_brief.generator import generate

    achievement = {
        "swimmer_name": "Eira Hughes",
        "event_name": "200m Freestyle",
        "result_time": "2:08.41",
    }
    brief = generate(
        {"id": "swim-e6", "post_angle": "confirmed_official_pb", "achievement": achievement},
        None,
        brand,
        profile_id="e6",
    )
    d = brief.to_dict()
    d["style_pack"] = "vignette-dots-none-standard"
    d["layout_template"] = "full_bleed_photo_lower_third"
    d["sourced_asset_ids"] = ["a1"]
    card = {"id": "swim-e6", "achievement": achievement}
    props = motion._card_to_props(card, variation_seed=1, brief=d, brand_kit=brand)
    assert props["photoSrc"].startswith("data:image/jpeg;base64,")
    focus = props.get("packGroundFocus")
    assert isinstance(focus, list) and len(focus) == 2
    assert all(isinstance(v, int) and 0 <= v <= 100 for v in focus)

    # A photo-less card on the same pack attaches nothing (byte-identical).
    props_nophoto = motion._card_to_props(
        card, variation_seed=1, brief={**d, "sourced_asset_ids": []}, brand_kit=brand
    )
    assert "packGroundFocus" not in props_nophoto


# --------------------------------------------------------------------------- #
# TSX source contract
# --------------------------------------------------------------------------- #


def test_tsx_ground_layer_threads_the_focus():
    src = _story_src()
    # packGroundGradient takes the focus and uses it for the two subject grounds.
    assert "focus: readonly number[] | null" in src
    assert "hasFocus ? focus[0] : 50" in src
    assert "hasFocus ? focus[1] : 45" in src  # vignette default y
    assert "hasFocus ? focus[1] : 38" in src  # spotlight default y
    # StylePackGroundLayer passes the card's resolved focus through.
    assert "packGroundGradient(\n    pack.ground," in src
    assert "ctx.card.packGroundFocus" in src
    # The prop is on the schema.
    assert "packGroundFocus: z.array(z.number()).nullable().default(null)" in src
