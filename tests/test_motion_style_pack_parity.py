"""Style-pack parity — the motion render carries the still's decorative pack.

Companion to ``test_motion_v2_parity``: the still renderer layers a style pack
(ground × texture × accent-geometry × density) over each archetype. These tests
prove the motion side mirrors it — the same pack id rides into the props, the
manifest, and the cache key, and ``StoryCard.tsx`` actually executes every lever
the catalog can emit (so a card's video matches its still's *decoration*, not
just its archetype + colours). No Node needed: TSX is checked as a source
contract, the rest is pure Python shaping.
"""

from __future__ import annotations

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import generate
from mediahub.graphic_renderer import style_packs as sp
from mediahub.visual import motion


BRAND = BrandKit(
    profile_id="p",
    display_name="Parity SC",
    primary_colour="#0E2A47",
    secondary_colour="#C9A227",
    accent_colour="#FFFFFF",
    short_name="PSC",
)


def _card(i: int = 1) -> dict:
    return {
        "id": f"swim-{i}",
        "swim_id": f"swim-{i}",
        "achievement": {
            "swim_id": f"swim-{i}",
            "swimmer_name": f"Swimmer {i}",
            "event_name": "100m Freestyle",
            "result_time": f"1:0{i}.00",
        },
    }


def _brief_dict(monkeypatch, *, seed=1, cid="swim-1") -> dict:
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    b = generate(
        {
            "id": cid,
            "post_angle": "individual_pb",
            "achievement": {
                "swimmer_name": "Eira Hughes",
                "event_name": "200m Freestyle",
                "result_time": "2:08.41",
            },
        },
        None,
        BRAND,
        profile_id="p",
        variation_seed=seed,
    )
    return b.to_dict()


def test_props_forward_the_still_style_pack(monkeypatch):
    bd = _brief_dict(monkeypatch, seed=5)
    assert bd["style_pack"], "the still should have picked a pack"
    props = motion._card_to_props(_card(1), brief=bd, brand_kit=BRAND)
    # The motion render carries the SAME pack id the still graphic used → parity.
    assert props["stylePack"] == bd["style_pack"]
    assert sp.style_pack_from_id(props["stylePack"]) is not None


def test_props_without_brief_keep_pack_empty():
    # Brief-less / legacy callers carry no pack → the bare card (pre-pack render).
    props = motion._card_to_props(_card(1))
    assert props["stylePack"] == ""


def test_manifest_records_the_style_pack(monkeypatch):
    props = motion._card_to_props(_card(1), brief=_brief_dict(monkeypatch, seed=2), brand_kit=BRAND)
    axes = motion._card_manifest_axes(props)
    assert axes["style_pack"] == props["stylePack"]


def test_cache_key_varies_with_style_pack(monkeypatch):
    base = motion._card_to_props(_card(1), brief=_brief_dict(monkeypatch, seed=2), brand_kit=BRAND)
    other = {**base, "stylePack": "vignette-dots-ring-standard"}
    same = dict(base)
    k_base = motion._content_hash({"card": base}, kind="story")
    k_other = motion._content_hash({"card": other}, kind="story")
    k_same = motion._content_hash({"card": same}, kind="story")
    assert k_base != k_other, "a different pack must bust the cache (re-render)"
    assert k_base == k_same, "the same pack must hit the same cache key"


def _lever_executed(src: str, token: str) -> bool:
    """True when the token has a real dispatch site in the TSX — a switch label
    (``case "<tok>":``) or a lookup-table key (``"<tok>": value``). Membership in
    the PACK_* Set literals alone (``"<tok>",``) does NOT count: a lever added to
    the Sets but never rendered must fail the guard."""
    import re

    escaped = re.escape(token)
    return bool(
        re.search(rf'case\s+"{escaped}"\s*:', src)
        or re.search(rf'"{escaped}"\s*:', src)
    )


def test_tsx_executes_every_style_pack_lever():
    """Drift guard: StoryCard.tsx must render the pack overlay and handle every
    lever the catalog can emit — a picked-but-ignored lever is exactly the
    parity gap this feature closes."""
    src = (motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx").read_text()
    assert "StylePackLayer" in src and "parseStylePack" in src
    assert "stylePack" in src  # the prop is consumed
    for ground in sp.GROUNDS:
        if ground == "flat":
            continue
        assert _lever_executed(src, ground), \
            f"ground {ground!r} not executed in StoryCard.tsx"
    for texture in sp.TEXTURES:
        if texture == "none":
            continue
        assert _lever_executed(src, texture), \
            f"texture {texture!r} not executed in StoryCard.tsx"
    for geo in sp.ACCENT_GEOS:
        if geo == "none":
            continue
        assert _lever_executed(src, geo), \
            f"accent geometry {geo!r} not executed in StoryCard.tsx"


def test_pack_ground_paints_beneath_scene_content_like_the_still():
    """z-order parity: the still injects the pack ground at z-index 1 (under
    archetype copy at z2–3) and texture/geometry at z6/z8 (above). The motion
    side must mount the ground layer BEFORE <Scene> and keep texture/geometry
    in the after-Scene overlay — otherwise a top_fade/vignette darkens copy on
    the video that the still leaves unshaded."""
    src = (motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx").read_text()
    assert "StylePackGroundLayer" in src
    # The ground component paints the ground; the overlay component must not.
    ground_block = src.split("const StylePackGroundLayer", 1)[1].split("const StylePackLayer", 1)[0]
    assert "packGroundGradient" in ground_block
    overlay_block = src.split("const StylePackLayer", 1)[1].split("const LogoChip", 1)[0]
    assert "packGroundGradient" not in overlay_block
    assert "packTextureImage" in overlay_block and "packAccentGeometry" in overlay_block
    # Mount order: ground → Scene → texture/geometry overlay.
    mount = src.split("<Scene ctx={ctx} />", 1)
    assert "<StylePackGroundLayer ctx={ctx} />" in mount[0]
    assert "<StylePackLayer ctx={ctx} />" in mount[1]


def test_reel_beats_inherit_packs_via_storycard():
    # The reel renders each beat through StoryCard, so the pack overlay applies
    # to reel cards too (no separate reel-side wiring needed).
    src = (motion.REMOTION_DIR / "src" / "compositions" / "MeetReel.tsx").read_text()
    assert "StoryCard" in src


def test_reel_threads_brief_so_pack_reaches_each_beat(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    bd = _brief_dict(monkeypatch, seed=3, cid="swim-2")
    captured: dict = {}

    def _fake_run(*, composition_id, props, out_path, duration_sec=None, size=None, timeout=600):
        captured["props"] = props
        from pathlib import Path

        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"0" * 2048)
        return Path(out_path)

    import tempfile
    from unittest import mock

    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        monkeypatch.setenv("DATA_DIR", tempfile.mkdtemp())
        motion.render_meet_reel(
            [_card(2)], BRAND, tempfile.mkdtemp() + "/reel.mp4", briefs=[bd]
        )
    beat = captured["props"]["cards"][0]
    assert beat["stylePack"] == bd["style_pack"]
