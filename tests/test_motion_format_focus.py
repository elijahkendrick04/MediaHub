"""R1.7 — format-aware photo focal points for motion.

The reel/story renderer now resolves the saliency ``photoPos`` per output cut
(story 9:16 / portrait 4:5 / square 1:1 / landscape 16:9) instead of always
using the 9:16 story crop. A subject framed for the tall story can otherwise
sit off-centre once the same photo is rendered in the wide landscape; computing
the focus for each cut's real aspect ratio keeps it in frame everywhere.

These tests are pure-Python: the saliency maths is deterministic and the
Remotion render is stubbed (``_run_remotion`` mocked), so no Node is needed.
The photo-path resolver is mocked to a synthetic off-centre-subject image so
the focus is exercised end-to-end without the media-library store.

Critically, the ``story`` default must stay byte-identical to the pre-format
behaviour (``focus_position(p, "9:16")``) so existing cached renders never
churn.
"""

from __future__ import annotations

import math
from pathlib import Path
from unittest import mock

import numpy as np
import pytest
from PIL import Image

from mediahub.brand.kit import BrandKit
from mediahub.graphic_renderer import saliency
from mediahub.visual import motion


BRAND = BrandKit(
    profile_id="r17",
    display_name="Focus SC",
    primary_colour="#0E2A47",
    secondary_colour="#C9A227",
    accent_colour="#FFFFFF",
    short_name="FSC",
)


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


def _corner_subject(tmp_path: Path, name: str = "subj.png") -> Path:
    """A 1000×1000 frame with a textured subject pinned to the top-left.

    Square source + off-centre subject is the case that separates the cuts:
    the 9:16 story crop slides horizontally (focus tracks X), the 16:9
    landscape crop slides vertically (focus tracks Y), so the two object-
    positions are provably different.
    """
    img = Image.new("RGB", (1000, 1000), (8, 8, 8))
    rng = np.random.default_rng(0)
    block = Image.fromarray(rng.integers(0, 256, size=(240, 240, 3), dtype=np.uint8), "RGB")
    img.paste(block, (60, 60))
    p = tmp_path / name
    img.save(p)
    return p


@pytest.fixture(scope="module")
def corner_subject(tmp_path_factory) -> Path:
    """The corner-subject frame, generated ONCE for the whole module.

    Every test drives the *same* deterministic (seeded RNG) off-centre-subject
    image, so its saliency focus is identical whether the image is built once or
    thirteen times. Generating it (numpy RNG fill + PNG encode) a single time —
    instead of per test via ``_corner_subject(tmp_path)`` — removes the module's
    main redundant cost without touching a single assertion: tests that need
    their own ``tmp_path`` for ``DATA_DIR`` / output paths still take it, they
    just share this one input photo.
    """
    d = tmp_path_factory.mktemp("corner_subject")
    return _corner_subject(d)


@pytest.fixture(autouse=True, scope="module")
def _no_bg_remover():
    """Report no background remover for this module — the real per-test cost sink.

    These tests exercise per-format photo *focus* (``photoPos``), not cutout
    synthesis. Left un-stubbed, the first ``_card_to_props`` that resolves a
    cutout calls ``get_bg_remover()``, which tries to fetch the u2net ONNX model
    over the network — many seconds of 403 retry/back-off in a sandbox with no
    cached model — before falling back to a passthrough alpha the matte gate
    then rejects (so the resolved cutout is ``""`` anyway). Reporting no remover
    reaches that identical ``""`` cutout with zero network cost, so every
    ``photoPos`` / ``photoSrc`` assertion is byte-identical while the module
    stops paying for a model download it never tests. The saliency maths itself
    is already cheap and its one input image is shared via ``corner_subject`` —
    the download attempt, not the maths, was the recompute (#133).
    """
    with mock.patch("mediahub.media_ai.providers.get_bg_remover", return_value=None):
        yield


def _card(i: int = 1) -> dict:
    return {
        "id": f"c{i}",
        "swimmer_name": f"Swimmer {i}",
        "event": "100 Free",
        "result_time": "00:54.32",
        "type": "NEW PB",
    }


def _brief() -> dict:
    # Non-empty, not "no-photo" → the photo path resolver (mocked) is consulted.
    return {"sourced_asset_ids": ["asset-1"], "photo_treatment": "full-bleed"}


def _pct(pos: str) -> tuple[float, float]:
    x, y = pos.split()
    return float(x.rstrip("%")), float(y.rstrip("%"))


# --------------------------------------------------------------------------- #
# Drift guard: saliency ratios ↔ renderer pixel sizes
# --------------------------------------------------------------------------- #


def test_format_ratios_match_motion_pixel_sizes():
    """``saliency.FORMAT_RATIOS`` is the ratio-only view of the renderer's
    ``MOTION_FORMATS`` pixel sizes. They live in two modules (saliency can't
    import the renderer without a cycle), so this guards them against drift —
    every motion cut must have a ratio entry that matches its real aspect."""
    assert set(saliency.FORMAT_RATIOS) == set(motion.MOTION_FORMATS)
    for fmt, (w, h) in motion.MOTION_FORMATS.items():
        rw, rh = (float(v) for v in saliency.FORMAT_RATIOS[fmt].split(":"))
        assert math.isclose(rw / rh, w / h, rel_tol=1e-9), fmt


# --------------------------------------------------------------------------- #
# _photo_focus_for_brief — format-aware
# --------------------------------------------------------------------------- #


def test_photo_focus_for_brief_is_format_aware(corner_subject):
    p = corner_subject
    with mock.patch.object(motion, "_photo_asset_path_for_brief", return_value=p):
        b = _brief()
        story = motion._photo_focus_for_brief(b, "story")
        landscape = motion._photo_focus_for_brief(b, "landscape")
        # Each cut keeps the top-left subject in frame along its free axis.
        sx, sy = _pct(story)
        lx, ly = _pct(landscape)
        assert sx < 50 and abs(sy - 50) < 1
        assert abs(lx - 50) < 1 and ly < 50
        assert story != landscape


def test_photo_focus_default_is_story_and_byte_identical_to_legacy(corner_subject):
    p = corner_subject
    with mock.patch.object(motion, "_photo_asset_path_for_brief", return_value=p):
        b = _brief()
        # No format arg defaults to the story cut …
        assert motion._photo_focus_for_brief(b) == motion._photo_focus_for_brief(b, "story")
        # … which is exactly the pre-R1.7 hardcoded 9:16 focus.
        assert motion._photo_focus_for_brief(b) == saliency.focus_position(str(p), "9:16")


def test_photo_focus_for_brief_unknown_format_falls_back_to_story(corner_subject):
    p = corner_subject
    with mock.patch.object(motion, "_photo_asset_path_for_brief", return_value=p):
        b = _brief()
        assert motion._photo_focus_for_brief(b, "feed_square") == motion._photo_focus_for_brief(
            b, "story"
        )


def test_photo_focus_for_brief_no_photo_is_empty_for_every_format():
    # No brief / no-photo treatment → "" regardless of cut (TSX neutral default).
    for fmt in ("story", "portrait", "square", "landscape"):
        assert motion._photo_focus_for_brief(None, fmt) == ""
        assert motion._photo_focus_for_brief({"photo_treatment": "no-photo"}, fmt) == ""


def test_photo_focus_for_brief_swallows_saliency_errors(corner_subject):
    p = corner_subject
    with (
        mock.patch.object(motion, "_photo_asset_path_for_brief", return_value=p),
        mock.patch(
            "mediahub.graphic_renderer.saliency.focus_position_for_format",
            side_effect=RuntimeError("boom"),
        ),
    ):
        # A focus failure must never break a render — it degrades to "".
        assert motion._photo_focus_for_brief(_brief(), "landscape") == ""


# --------------------------------------------------------------------------- #
# _card_to_props — photoPos carries the per-format focus
# --------------------------------------------------------------------------- #


def test_card_to_props_photo_pos_varies_by_format(corner_subject):
    p = corner_subject
    with mock.patch.object(motion, "_photo_asset_path_for_brief", return_value=p):
        b = _brief()
        positions = {
            fmt: motion._card_to_props(_card(1), brief=b, format_name=fmt)["photoPos"]
            for fmt in ("story", "portrait", "square", "landscape")
        }
        # Story and landscape steer along different axes → distinct strings.
        assert positions["story"] != positions["landscape"]
        # The default (no format_name) matches the story cut.
        assert motion._card_to_props(_card(1), brief=b)["photoPos"] == positions["story"]


def test_card_to_props_default_format_preserves_legacy_photo_pos(corner_subject):
    p = corner_subject
    with mock.patch.object(motion, "_photo_asset_path_for_brief", return_value=p):
        props = motion._card_to_props(_card(1), brief=_brief())
        assert props["photoPos"] == saliency.focus_position(str(p), "9:16")


def test_card_to_props_no_photo_keeps_photo_pos_empty():
    props = motion._card_to_props(
        _card(1), brief={"photo_treatment": "no-photo"}, format_name="square"
    )
    assert props["photoPos"] == ""


# --------------------------------------------------------------------------- #
# Integration — format flows render_story_card / render_meet_reel → props
# --------------------------------------------------------------------------- #


def _capture_story(tmp_path, monkeypatch, fmt: str, photo: Path) -> dict:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    captured: dict = {}

    def _fake_run(*, composition_id, props, out_path, duration_sec=None, size=None, timeout=600):
        captured["props"] = props
        captured["size"] = size
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"0" * 2048)
        return out

    with (
        mock.patch.object(motion, "_photo_asset_path_for_brief", return_value=photo),
        mock.patch.object(motion, "_run_remotion", side_effect=_fake_run),
    ):
        motion.render_story_card(
            _card(1), BRAND, tmp_path / "out" / f"{fmt}.mp4", brief=_brief(), format_name=fmt
        )
    return captured


def test_render_story_card_plumbs_format_into_photo_pos(tmp_path, monkeypatch, corner_subject):
    p = corner_subject
    story = _capture_story(tmp_path, monkeypatch, "story", p)
    landscape = _capture_story(tmp_path, monkeypatch, "landscape", p)

    assert story["size"] == motion.MOTION_FORMATS["story"]
    assert landscape["size"] == motion.MOTION_FORMATS["landscape"]

    sp = story["props"]["card"]["photoPos"]
    lp = landscape["props"]["card"]["photoPos"]
    assert sp == saliency.focus_position_for_format(str(p), "story")
    assert lp == saliency.focus_position_for_format(str(p), "landscape")
    assert sp != lp


def test_render_meet_reel_plumbs_format_into_each_card(tmp_path, monkeypatch, corner_subject):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    p = corner_subject
    captured: dict = {}

    def _fake_run(*, composition_id, props, out_path, duration_sec=None, size=None, timeout=600):
        captured["props"] = props
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"0" * 2048)
        return out

    with (
        mock.patch.object(motion, "_photo_asset_path_for_brief", return_value=p),
        mock.patch.object(motion, "_run_remotion", side_effect=_fake_run),
    ):
        motion.render_meet_reel(
            [_card(1), _card(2)],
            BRAND,
            tmp_path / "reel.mp4",
            briefs=[_brief(), _brief()],
            format_name="landscape",
        )

    cards = captured["props"]["cards"]
    assert cards, "reel rendered no card beats"
    expected = saliency.focus_position_for_format(str(p), "landscape")
    for beat in cards:
        assert beat["photoPos"] == expected


def test_format_specific_cards_get_distinct_cache_keys(corner_subject):
    """The per-format photoPos rides in the card payload, so the four cuts of a
    photo-bearing card hash to four different cache keys — no cut clobbers
    another's cached MP4. (Size already differs; this confirms photoPos doesn't
    accidentally collapse the focus back to one value.)"""
    p = corner_subject
    with mock.patch.object(motion, "_photo_asset_path_for_brief", return_value=p):
        b = _brief()
        positions = {
            fmt: motion._card_to_props(_card(1), brief=b, format_name=fmt)["photoPos"]
            for fmt in motion.MOTION_FORMATS
        }
    # square is the degenerate "whole image" centre; story/portrait/landscape differ.
    assert len({positions["story"], positions["portrait"], positions["landscape"]}) == 3


# --------------------------------------------------------------------------- #
# Explainability — the manifest records the resolved focus
# --------------------------------------------------------------------------- #


def test_manifest_axes_record_photo_focus(corner_subject):
    p = corner_subject
    with mock.patch.object(motion, "_photo_asset_path_for_brief", return_value=p):
        props = motion._card_to_props(_card(1), brief=_brief(), format_name="landscape")
    axes = motion._card_manifest_axes(props)
    assert axes["photo_focus"] == props["photoPos"]
    assert axes["photo_focus"] == saliency.focus_position_for_format(str(p), "landscape")
    assert axes["has_photo"] is True


# --------------------------------------------------------------------------- #
# _apply_format_photo_focus — per-cut re-resolution shared by both reel paths
# --------------------------------------------------------------------------- #
# The reel assembler (R1.15) embeds photos + resolves roles ONCE with the
# story-focus base and reuses that across every cut; R1.7 re-steers only the
# cheap photoPos per cut at the render chokepoint. These cover that helper.


def _reel_base(p: Path, n: int = 2):
    """The format-independent (story-focus) card props + matching briefs the
    reel assembler produces, with the photo path resolver mocked to ``p``."""
    briefs = [_brief() for _ in range(n)]
    with mock.patch.object(motion, "_photo_asset_path_for_brief", return_value=p):
        cards = [motion._card_to_props(_card(i), brief=briefs[i]) for i in range(n)]
    return cards, briefs


def test_apply_format_photo_focus_story_is_identity(corner_subject):
    p = corner_subject
    cards, briefs = _reel_base(p)
    # The story cut returns the very same list object — no work, byte-identical
    # cache key, embedded photoSrc/cutoutSrc bytes untouched.
    assert motion._apply_format_photo_focus(cards, briefs, "story") is cards


def test_apply_format_photo_focus_resolves_per_cut(corner_subject):
    p = corner_subject
    cards, briefs = _reel_base(p)
    with mock.patch.object(motion, "_photo_asset_path_for_brief", return_value=p):
        out = motion._apply_format_photo_focus(cards, briefs, "landscape")
    expected = saliency.focus_position_for_format(str(p), "landscape")
    assert [c["photoPos"] for c in out] == [expected, expected]
    # Story base differed → the cards were re-resolved for the landscape cut …
    assert out[0]["photoPos"] != cards[0]["photoPos"]
    # … but the expensive embedded photo bytes ride through unchanged.
    assert out[0]["photoSrc"] == cards[0]["photoSrc"]


def test_apply_format_photo_focus_does_not_mutate_input(corner_subject):
    p = corner_subject
    cards, briefs = _reel_base(p)
    before = [c["photoPos"] for c in cards]
    with mock.patch.object(motion, "_photo_asset_path_for_brief", return_value=p):
        motion._apply_format_photo_focus(cards, briefs, "landscape")
    assert [c["photoPos"] for c in cards] == before  # originals untouched


def test_apply_format_photo_focus_leaves_photoless_cards():
    # No photo → "" in the base and "" for every cut; the card object is reused.
    nb = {"photo_treatment": "no-photo"}
    cards = [motion._card_to_props(_card(1), brief=nb)]
    out = motion._apply_format_photo_focus(cards, [nb], "square")
    assert out[0]["photoPos"] == ""
    assert out[0] is cards[0]  # unchanged → not copied
