"""Tests for mediahub.quality.variant_metrics (§8C distinctiveness metrics).

All deterministic and offline: archetype diversity over specs, perceptual
spread over locally-generated PNGs, and worst-case caption n-gram overlap.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest
from PIL import Image

from mediahub.quality import (
    archetype_diversity,
    caption_repetition,
    perceptual_spread,
)
from mediahub.quality.variant_metrics import _archetype_label, _word_ngrams


# --------------------------------------------------------------------------- #
# archetype_diversity
# --------------------------------------------------------------------------- #

@dataclass
class _Brief:
    layout_family: str = ""
    archetype: str = ""


def test_archetype_diversity_empty_is_zero():
    assert archetype_diversity([]) == 0.0


def test_archetype_diversity_single_candidate():
    assert archetype_diversity([{"archetype": "split_diagonal_hero"}]) == 1.0


def test_archetype_diversity_all_same():
    specs = [{"archetype": "big_number_dominant"}] * 4
    assert archetype_diversity(specs) == 0.25


def test_archetype_diversity_all_distinct():
    specs = [{"archetype": a} for a in ("a", "b", "c", "d", "e")]
    assert archetype_diversity(specs) == 1.0


def test_archetype_diversity_partial():
    specs = [{"archetype": "a"}, {"archetype": "b"}, {"archetype": "a"}]
    assert archetype_diversity(specs) == pytest.approx(2 / 3)


def test_archetype_diversity_meets_8c_pool_target():
    # §8C: a 5-candidate pool for one card should span >= 4 archetypes (>= 0.8).
    specs = [{"archetype": a} for a in ("hero", "grid", "magazine", "minimal", "hero")]
    assert archetype_diversity(specs) >= 0.8


def test_archetype_diversity_meets_8c_pack_target():
    # §8C: a pack of 10 cards should use >= 6 distinct archetypes (>= 0.6).
    families = ["a", "b", "c", "d", "e", "f", "a", "b", "c", "d"]
    specs = [{"archetype": f} for f in families]
    assert archetype_diversity(specs) >= 0.6


def test_archetype_diversity_today_is_low():
    # The "samey" status quo: 5 candidates, only the modal skeleton + one other.
    specs = [{"archetype": a} for a in ("hero", "hero", "hero", "hero", "big_number")]
    assert archetype_diversity(specs) <= 0.4


def test_archetype_diversity_layout_family_fallback():
    specs = [{"layout_family": "individual_hero"}, {"layout_family": "big_number_hero"}]
    assert archetype_diversity(specs) == 1.0


def test_archetype_diversity_object_attribute():
    specs = [_Brief(layout_family="individual_hero"), _Brief(archetype="ticker_strip")]
    assert archetype_diversity(specs) == 1.0


def test_archetype_diversity_plain_strings():
    assert archetype_diversity(["a", "b", "a"]) == pytest.approx(2 / 3)


def test_archetype_diversity_normalises_case_and_space():
    specs = [{"archetype": "Hero"}, {"archetype": " hero "}]
    assert archetype_diversity(specs) == 0.5


def test_archetype_diversity_missing_label_counts_as_candidate():
    # A blank archetype is still a candidate (denominator) but adds no diversity.
    specs = [{"archetype": "a"}, {}]
    assert archetype_diversity(specs) == 0.5


def test_archetype_diversity_all_blank_is_zero():
    assert archetype_diversity([{}, {}, {}]) == 0.0


def test_archetype_label_prefers_archetype_over_family():
    assert _archetype_label({"archetype": "x", "layout_family": "y"}) == "x"
    assert _archetype_label(_Brief(layout_family="y")) == "y"
    assert _archetype_label(None) == ""


# --------------------------------------------------------------------------- #
# perceptual_spread
# --------------------------------------------------------------------------- #

def _write(path, img) -> str:
    img.save(path)
    return str(path)


def _flat(shade: int) -> Image.Image:
    return Image.new("RGB", (96, 96), (shade, shade, shade))


def _left_right() -> Image.Image:
    im = Image.new("L", (96, 96), 0)
    im.paste(255, (0, 0, 48, 96))
    return im.convert("RGB")


def _top_bottom() -> Image.Image:
    im = Image.new("L", (96, 96), 0)
    im.paste(255, (0, 0, 96, 48))
    return im.convert("RGB")


def _center_box() -> Image.Image:
    im = Image.new("L", (96, 96), 0)
    im.paste(255, (24, 24, 72, 72))
    return im.convert("RGB")


def test_perceptual_spread_empty_is_zero():
    assert perceptual_spread([]) == 0.0


def test_perceptual_spread_single_is_zero(tmp_path):
    p = _write(tmp_path / "a.png", _flat(128))
    assert perceptual_spread([p]) == 0.0


def test_perceptual_spread_identical_is_zero(tmp_path):
    a = _write(tmp_path / "a.png", _left_right())
    b = _write(tmp_path / "b.png", _left_right())
    assert perceptual_spread([a, b]) == 0.0


def test_perceptual_spread_structural_difference_positive(tmp_path):
    a = _write(tmp_path / "lr.png", _left_right())
    b = _write(tmp_path / "box.png", _center_box())
    assert perceptual_spread([a, b]) > 0.0


def test_perceptual_spread_ignores_flat_recolour(tmp_path):
    # Two flat cards of different brand colours are structurally identical, so a
    # cosmetic recolour must not register as spread (thesis §2.2).
    a = _write(tmp_path / "dark.png", _flat(40))
    b = _write(tmp_path / "light.png", _flat(200))
    assert perceptual_spread([a, b]) == 0.0


def test_perceptual_spread_bounded_and_symmetric(tmp_path):
    a = _write(tmp_path / "lr.png", _left_right())
    b = _write(tmp_path / "tb.png", _top_bottom())
    c = _write(tmp_path / "box.png", _center_box())
    s1 = perceptual_spread([a, b, c])
    s2 = perceptual_spread([c, b, a])
    assert 0.0 <= s1 <= 1.0
    assert s1 == pytest.approx(s2)


def test_perceptual_spread_more_varied_scores_higher(tmp_path):
    lr = _write(tmp_path / "lr.png", _left_right())
    lr2 = _write(tmp_path / "lr2.png", _left_right())
    tb = _write(tmp_path / "tb.png", _top_bottom())
    box = _write(tmp_path / "box.png", _center_box())
    same = perceptual_spread([lr, lr2])      # identical structure
    varied = perceptual_spread([lr, tb, box])  # three different structures
    assert same == 0.0
    assert varied > same


def test_perceptual_spread_accepts_path_objects(tmp_path):
    a = tmp_path / "lr.png"
    _left_right().save(a)
    b = tmp_path / "box.png"
    _center_box().save(b)
    assert perceptual_spread([a, b]) > 0.0  # Path objects, not str


def test_perceptual_spread_missing_file_raises(tmp_path):
    a = _write(tmp_path / "a.png", _left_right())
    with pytest.raises(FileNotFoundError):
        perceptual_spread([a, str(tmp_path / "does_not_exist.png")])


# --------------------------------------------------------------------------- #
# caption_repetition
# --------------------------------------------------------------------------- #

def test_caption_repetition_empty_is_zero():
    assert caption_repetition([]) == 0.0


def test_caption_repetition_single_is_zero():
    assert caption_repetition(["a personal best for hannah today"]) == 0.0


def test_caption_repetition_identical_is_one():
    c = "another superb personal best from the city squad tonight"
    assert caption_repetition([c, c]) == 1.0


def test_caption_repetition_case_insensitive():
    a = "Personal Best For Hannah Today!"
    b = "personal best for hannah today"
    assert caption_repetition([a, b]) == 1.0


def test_caption_repetition_disjoint_is_zero():
    a = "hannah smashed her freestyle record today"
    b = "the relay squad qualified for nationals"
    assert caption_repetition([a, b]) == 0.0


def test_caption_repetition_partial_between_zero_and_one():
    a = "another personal best for hannah today"
    b = "another personal best for jordan today"
    val = caption_repetition([a, b])
    assert 0.0 < val < 1.0
    assert val == pytest.approx(2 / 6)


def test_caption_repetition_returns_worst_pair():
    a = "a totally unique sentence about swimming quickly"
    b = "another personal best for hannah today again"
    c = "another personal best for hannah today again"  # identical to b
    assert caption_repetition([a, b, c]) == 1.0


def test_caption_repetition_short_caption_fallback():
    assert caption_repetition(["big win", "big win"]) == 1.0
    assert caption_repetition(["big win", "huge loss"]) == 0.0


def test_caption_repetition_punctuation_ignored():
    assert caption_repetition(["personal best!!!", "personal best"]) == 1.0


def test_caption_repetition_n_param_changes_result():
    a = "the fast brown swimmer wins gold"
    b = "the fast green swimmer wins silver"
    assert caption_repetition([a, b], n=3) == 0.0   # no shared trigram
    assert caption_repetition([a, b], n=2) > 0.0    # shares "the fast", "swimmer wins"


def test_caption_repetition_bounded():
    caps = ["one two three four", "two three four five", "five six seven eight"]
    val = caption_repetition(caps, n=2)
    assert 0.0 <= val <= 1.0


def test_caption_repetition_invalid_n_raises():
    with pytest.raises(ValueError):
        caption_repetition(["a b c", "d e f"], n=0)


def test_word_ngrams_short_fallback():
    assert _word_ngrams("big win", 3) == {("big", "win")}
    assert _word_ngrams("", 3) == set()
    assert _word_ngrams("a b c d", 3) == {("a", "b", "c"), ("b", "c", "d")}
