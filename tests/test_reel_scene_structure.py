"""SEQ-4 — video: data-driven scene structure + archetype/emphasis forwarding
+ the opt-in generative-background flag.

Covers the roadmap Appendix A SEQ-4 verification surface:
  * the reel's duration/scene budget follows the number of ranked moments
    (a one-medal weekend is a tight 7s, a five-PB weekend a 23s recap);
  * three cards keep the historic 15s, so existing cached reels stay valid;
  * an explicit ``duration_sec`` still wins (caller override);
  * the cache key varies with the card count (no cross-shape cache hits);
  * ``_card_to_props`` forwards the still's archetype + measured hero stat
    so the motion render matches the still (empty without a brief);
  * ``MEDIAHUB_GEN_BG`` is OFF by default, opt-in, and the legacy
    ``MEDIAHUB_DISABLE_AI_BG=1`` kill switch still wins — and when off, a
    real v1 render never calls the Imagen fetch even with a key present.

No Node/Remotion needed: ``_run_remotion`` is stubbed to capture its args.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from mediahub.visual import motion


BRAND = {
    "profile_id": "seq4",
    "display_name": "SEQ4 Swimming Club",
    "primary_colour": "#0E2A47",
    "secondary_colour": "#C9A227",
}


def _card(i: int) -> dict:
    return {
        "id": f"swim-seq4-{i}",
        "swim_id": f"swim-seq4-{i}",
        "achievement": {
            "swim_id": f"swim-seq4-{i}",
            "swimmer_name": f"Swimmer {i}",
            "event_name": "100m Freestyle",
            "result_time": f"1:0{i}.00",
        },
        "meet_name": "SEQ4 Invitational",
    }


# ---------------------------------------------------------------------------
# reel_duration_for — the deterministic structure maths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "n,expected",
    [(1, 8.5), (2, 12.5), (3, 16.5), (4, 20.5), (5, 24.5)],
)
def test_reel_duration_follows_ranked_moments(n, expected):
    assert motion.reel_duration_for(n) == expected


def test_reel_duration_clamps_to_route_range():
    assert motion.reel_duration_for(0) == 8.5  # never a zero-length reel
    assert motion.reel_duration_for(99) == 24.5  # capped at the 5-card max
    durations = [motion.reel_duration_for(n) for n in range(1, 6)]
    assert durations == sorted(durations)  # strictly grows with moments


def test_three_card_reel_default_total():
    """2s cover + 3×4s beats + the M17 2.5s legible outro."""
    assert motion.reel_duration_for(3) == 16.5


# ---------------------------------------------------------------------------
# render_meet_reel — duration derivation + cache-key sensitivity
# ---------------------------------------------------------------------------


def _render_reel_capture(tmp_path, monkeypatch, cards, **kwargs):
    """Run render_meet_reel with _run_remotion stubbed; return captured call."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    captured: dict = {}

    def _fake_run(
        *,
        composition_id,
        props,
        out_path,
        duration_sec=None,
        size=None,
        timeout=600,
        supersample=1.0,
    ):
        captured["composition_id"] = composition_id
        captured["props"] = props
        captured["duration_sec"] = duration_sec
        captured["size"] = size
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"0" * 2048)  # > the 1KB sanity floor
        return out

    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        result = motion.render_meet_reel(cards, BRAND, tmp_path / "out" / "reel.mp4", **kwargs)
    return captured, result


def test_reel_duration_is_data_driven_by_default(tmp_path, monkeypatch):
    one, _ = _render_reel_capture(tmp_path, monkeypatch, [_card(1)])
    assert one["duration_sec"] == 8.5
    four, _ = _render_reel_capture(tmp_path, monkeypatch, [_card(i) for i in range(4)])
    assert four["duration_sec"] == 20.5
    assert len(four["props"]["cards"]) == 4


def test_explicit_duration_still_wins(tmp_path, monkeypatch):
    cap, _ = _render_reel_capture(tmp_path, monkeypatch, [_card(1), _card(2)], duration_sec=12.5)
    assert cap["duration_sec"] == 12.5


def test_cache_key_varies_with_card_count(tmp_path, monkeypatch):
    _render_reel_capture(tmp_path, monkeypatch, [_card(1)])
    _render_reel_capture(tmp_path, monkeypatch, [_card(1), _card(2)])
    cache = motion._cache_dir()
    assert len(list(cache.glob("*.mp4"))) == 2  # different structure → new render


def test_cache_hit_skips_rerender(tmp_path, monkeypatch):
    cap1, out1 = _render_reel_capture(tmp_path, monkeypatch, [_card(1)])
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with mock.patch.object(motion, "_run_remotion") as rerun:
        out2 = motion.render_meet_reel([_card(1)], BRAND, tmp_path / "out2" / "reel.mp4")
    rerun.assert_not_called()
    assert Path(out2).read_bytes() == Path(out1).read_bytes()


# ---------------------------------------------------------------------------
# _card_to_props — archetype + measured emphasis forwarding
# ---------------------------------------------------------------------------


def test_card_props_forward_archetype_and_hero_stat():
    brief = {
        "layout_template": "big_number_dominant",
        "background_style": "clean",
        "text_layers": {"hero_stat": "−0.42s on PB"},
    }
    props = motion._card_to_props(_card(1), variation_seed=3, brief=brief)
    assert props["archetype"] == "big_number_dominant"
    assert props["heroStat"] == "−0.42s on PB"


def test_card_props_without_brief_keep_archetype_empty():
    props = motion._card_to_props(_card(1), variation_seed=3)
    assert props["archetype"] == ""
    assert props["heroStat"] == ""


def test_tsx_compositions_declare_the_forwarded_fields():
    """zod strips undeclared keys — every forwarded card prop must be declared.

    StoryCard owns the single card schema; MeetReel must IMPORT that shared
    schema (rather than re-declare its own copy) so a field added for the
    story can never be silently stripped on its reel beat.
    """
    story = (motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx").read_text()
    for field in (
        "archetype",
        "heroStat",
        "motionIntent",
        "photoPos",
        "roleGround",
        "roleSurface",
        "roleAccent",
        "roleOnGround",
    ):
        assert field in story, field
    reel = (motion.REMOTION_DIR / "src" / "compositions" / "MeetReel.tsx").read_text()
    assert (
        "cardSchema" in reel and 'from "./StoryCard"' in reel
    ), "MeetReel must reuse StoryCard's exported cardSchema"


# ---------------------------------------------------------------------------
# MEDIAHUB_GEN_BG — Tier C generative background is opt-in, default OFF
# ---------------------------------------------------------------------------


def test_gen_bg_flag_default_off(monkeypatch):
    from mediahub.graphic_renderer.render import _gen_bg_enabled

    monkeypatch.delenv("MEDIAHUB_GEN_BG", raising=False)
    monkeypatch.delenv("MEDIAHUB_DISABLE_AI_BG", raising=False)
    assert _gen_bg_enabled() is False
    monkeypatch.setenv("MEDIAHUB_GEN_BG", "1")
    assert _gen_bg_enabled() is True
    # The legacy kill switch always wins.
    monkeypatch.setenv("MEDIAHUB_DISABLE_AI_BG", "1")
    assert _gen_bg_enabled() is False


def test_v1_render_never_fetches_background_when_flag_off(tmp_path, monkeypatch):
    """Full v1 render with a 'key present': zero Imagen calls by default."""
    pytest.importorskip("playwright.sync_api")
    from mediahub.brand.kit import BrandKit
    from mediahub.creative_brief.generator import generate
    from mediahub.graphic_renderer.render import render_brief
    import mediahub.visual.ai_background as ai_bg

    monkeypatch.setenv("MEDIAHUB_GEN_V2", "0")  # v1 path (the only AI-BG surface)
    monkeypatch.delenv("MEDIAHUB_GEN_BG", raising=False)
    kit = BrandKit(profile_id="seq4", display_name="SEQ4 SC")
    brief = generate(
        {"id": "s1", "post_angle": "confirmed_official_pb", "achievement": _card(1)["achievement"]},
        None,
        kit,
        profile_id="seq4",
    )
    with (
        mock.patch.object(ai_bg, "is_available", return_value=True),
        mock.patch.object(ai_bg, "background_data_uri_for") as fetch,
    ):
        res = render_brief(
            brief,
            output_dir=tmp_path,
            size=(540, 675),
            format_name="feed_portrait",
            brand_kit=kit,
        )
    fetch.assert_not_called()
    assert Path(res.visual.file_path).exists()
