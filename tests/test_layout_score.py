"""F6 — measured layout scoring (the pure, browserless energy maths).

These tests pin the deterministic scorer in
``graphic_renderer/layout_score.py`` without a browser: candidate enumeration,
the per-term energy maths, the hard text-collision gate, the humble
"only switch on a real improvement" selection, and the opt-in / degrade-safe
contracts. The Playwright end-to-end path (composing + measuring real cards) is
covered in ``test_layout_score_render.py``.
"""

from __future__ import annotations

import re

import pytest

from mediahub.graphic_renderer import layout_score as ls


# --------------------------------------------------------------------------- #
# Opt-in gate + candidate-count parsing
# --------------------------------------------------------------------------- #


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_LAYOUT_SCORE", raising=False)
    assert ls.enabled() is False


@pytest.mark.parametrize("val,expected", [("1", True), ("true", True), ("on", True), ("yes", True)])
def test_enabled_truthy_values(monkeypatch, val, expected):
    monkeypatch.setenv("MEDIAHUB_LAYOUT_SCORE", val)
    assert ls.enabled() is expected


@pytest.mark.parametrize("val", ["", "0", "false", "off", "no", "garbage"])
def test_disabled_falsey_values(monkeypatch, val):
    monkeypatch.setenv("MEDIAHUB_LAYOUT_SCORE", val)
    assert ls.enabled() is False


def test_candidate_count_default(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_LAYOUT_SCORE_K", raising=False)
    assert ls.candidate_count() == ls._DEFAULT_K


def test_candidate_count_clamped(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_LAYOUT_SCORE_K", "99")
    assert ls.candidate_count() == ls._MAX_K
    monkeypatch.setenv("MEDIAHUB_LAYOUT_SCORE_K", "1")
    assert ls.candidate_count() == ls._MIN_K
    monkeypatch.setenv("MEDIAHUB_LAYOUT_SCORE_K", "notanint")
    assert ls.candidate_count() == ls._DEFAULT_K


# --------------------------------------------------------------------------- #
# Candidate enumeration
# --------------------------------------------------------------------------- #


class _Brief:
    def __init__(self, style_pack="", mood=""):
        self.style_pack = style_pack
        self.mood = mood


def test_candidates_empty_without_pack():
    assert ls.candidate_pack_ids(_Brief(style_pack="")) == []


def test_candidates_current_is_first_and_deduped():
    from mediahub.graphic_renderer import style_packs as sp

    current = sp.list_style_packs()[5].id
    cands = ls.candidate_pack_ids(_Brief(style_pack=current), k=4)
    assert cands[0] == current, "the director's current pack must be candidate #0"
    assert len(cands) == len(set(cands)) == 4, "no duplicates; exactly k candidates"


def test_candidates_respect_k():
    from mediahub.graphic_renderer import style_packs as sp

    current = sp.list_style_packs()[0].id
    assert len(ls.candidate_pack_ids(_Brief(style_pack=current), k=2)) == 2
    assert len(ls.candidate_pack_ids(_Brief(style_pack=current), k=6)) == 6


def test_candidates_skip_recent_but_keep_current():
    from mediahub.graphic_renderer import style_packs as sp

    ids = [p.id for p in sp.list_style_packs()]
    current = ids[0]
    nxt = ids[1]
    cands = ls.candidate_pack_ids(_Brief(style_pack=current), k=4, recent=[nxt])
    assert cands[0] == current, "current stays even if it were recent"
    assert nxt not in cands[1:], "a recent pack is skipped in the tail"


def test_candidates_walk_the_mood_bundle_when_mood_set():
    from mediahub.graphic_renderer import style_packs as sp

    mood = "explosive"
    bundle = [m.strip().lower() for m in sp.mood_preset_ids(mood)]
    assert bundle, "precondition: the mood has a curated bundle"
    current = bundle[0]
    cands = ls.candidate_pack_ids(_Brief(style_pack=current, mood=mood), k=8)
    # Every candidate is drawn from the mood bundle — F6 never overrides the
    # director's *feeling* with an off-mood but tidier pack.
    assert set(cands) <= set(bundle), f"{cands} escaped the mood bundle {bundle}"
    assert cands[0] == current


def test_candidates_anchor_unknown_current_at_zero():
    cands = ls.candidate_pack_ids(_Brief(style_pack="not-a-real-pack-id"), k=3)
    assert cands[0] == "not-a-real-pack-id"


def test_candidates_are_ground_diverse():
    # The catalog is sorted quiet→busy, so ADJACENT packs share a ground; the
    # strided walk must sample across the pool so the scorer chooses among
    # genuinely different treatments, not four density variants of one look.
    from mediahub.graphic_renderer import style_packs as sp

    packs = sp.list_style_packs()
    for idx in (50, len(packs) // 2, (3 * len(packs)) // 4):
        walk = ls.candidate_pack_ids(_Brief(style_pack=packs[idx].id), k=4)
        grounds = {pid.split("-")[0] for pid in walk}
        assert len(grounds) >= 2, f"walk from {packs[idx].id} is not ground-diverse: {walk}"


# --------------------------------------------------------------------------- #
# Geometry fixtures + the measurement JS contract
# --------------------------------------------------------------------------- #


def _text(x, y, w, h, *, text="RIVERSIDE", font=64, weight=800, bg=False, eff=1.0):
    return {
        "kind": "text",
        "x": x,
        "y": y,
        "w": w,
        "h": h,
        "text": text,
        "fontPx": font,
        "weight": weight,
        "bgFill": bg,
        "eff": eff,
    }


def _photo(x, y, w, h, ox=0.5, oy=0.5):
    return {"kind": "photo", "x": x, "y": y, "w": w, "h": h, "ox": ox, "oy": oy}


def _mark(x, y, w, h):
    return {"kind": "mark", "x": x, "y": y, "w": w, "h": h, "gradient": False, "fill": True}


def _clean_geom():
    return {
        "W": 1080,
        "H": 1350,
        "boxes": [
            _text(80, 120, 600, 130, text="EIRA HUGHES", font=96),
            _text(80, 300, 420, 40, text="100M FREESTYLE", font=28, weight=600),
            _text(80, 1120, 320, 90, text="ONE MINUTE", font=64),
            _photo(0, 0, 1080, 1350, ox=0.5, oy=0.35),
            _mark(920, 60, 90, 90),
        ],
    }


def test_measure_js_is_a_real_sweep():
    assert isinstance(ls.MEASURE_JS, str) and ls.MEASURE_JS.strip()
    assert "getBoundingClientRect" in ls.MEASURE_JS
    assert "querySelectorAll" in ls.MEASURE_JS
    assert "objectPosition" in ls.MEASURE_JS, "the saliency term needs the photo focus"


# --------------------------------------------------------------------------- #
# Hard collision gate
# --------------------------------------------------------------------------- #


def test_text_text_overlap_is_disqualified():
    geom = {
        "W": 1080,
        "H": 1350,
        "boxes": [
            _text(80, 120, 600, 130, text="EIRA HUGHES"),
            _text(90, 130, 600, 130, text="OVERLAPPING"),
        ],
    }
    rec = ls.score_geometry(geom)
    assert rec["disqualified"] is True
    assert rec["total"] == 0.0
    assert "overlap" in rec["reason"]


def test_degenerate_canvas_is_disqualified_not_raised():
    # A malformed measurement (no canvas) must be skipped, never raise — so one
    # bad candidate can't sink the whole scoring pass.
    for bad in ({"W": 0, "H": 0, "boxes": []}, {"boxes": [_text(0, 0, 10, 10)]}):
        rec = ls.score_geometry(bad)
        assert rec["disqualified"] is True
        assert rec["total"] == 0.0


def test_text_over_photo_is_not_a_collision():
    # Text sitting on a full-bleed photo is normal, not a break.
    geom = {
        "W": 1080,
        "H": 1350,
        "boxes": [_photo(0, 0, 1080, 1350), _text(80, 600, 600, 130, text="EIRA HUGHES")],
    }
    rec = ls.score_geometry(geom)
    assert rec["disqualified"] is False


def test_short_fragments_do_not_trigger_collision():
    # A monospaced result splits into fragments (2:18 / . / 07); overlapping
    # 1-2 char fragments must not read as a collision.
    geom = {
        "W": 1080,
        "H": 1350,
        "boxes": [
            _text(80, 120, 60, 60, text="2:18", font=64),
            _text(120, 120, 20, 60, text=".", font=64),
        ],
    }
    assert ls.score_geometry(geom)["disqualified"] is False


# --------------------------------------------------------------------------- #
# Individual energy terms (clear monotonic cases)
# --------------------------------------------------------------------------- #


def test_clean_card_scores_and_is_deterministic():
    g = _clean_geom()
    rec = ls.score_geometry(g, archetype="individual_hero")
    assert rec["disqualified"] is False
    assert 0.0 <= rec["total"] <= 1.0
    for k, v in rec["terms"].items():
        assert 0.0 <= v <= 1.0, f"term {k} out of [0,1]: {v}"
    # Deterministic: identical input → identical record.
    assert ls.score_geometry(g, archetype="individual_hero") == rec


def test_whitespace_band_rewards_breathing_room():
    W, H = 1080, 1350
    lo, hi = ls._DEFAULT_WHITESPACE_BAND
    # A single tiny text box — almost all whitespace, ABOVE the band's upper edge.
    sparse = [_text(80, 120, 200, 40, text="RSC")]
    # Marks tiling most of the canvas — little whitespace, BELOW the band.
    dense = [_mark(0, 0, 1080, 900), _mark(0, 900, 900, 400)]
    # Content covering ~30% of the canvas → whitespace ~0.70, comfortably INSIDE
    # the default band, so it should score a perfect 1.0.
    balanced = [_mark(80, 200, 920, 400), _text(80, 120, 500, 130, text="EIRA HUGHES")]
    s_sparse = ls._whitespace_score(sparse, W, H, "individual_hero")
    s_dense = ls._whitespace_score(dense, W, H, "individual_hero")
    s_bal = ls._whitespace_score(balanced, W, H, "individual_hero")
    # Sanity: the balanced fixture really is in-band.
    ws_bal = 1.0 - ls._coverage_fraction(balanced, W, H)
    assert lo <= ws_bal <= hi, f"fixture off-band: whitespace {ws_bal:.3f} not in ({lo},{hi})"
    assert s_bal == 1.0
    assert s_bal > s_sparse and s_bal > s_dense


def test_balance_prefers_centre_or_thirds_over_drift():
    W, H = 1080, 1350
    centred = [_text(440, 620, 200, 110, text="EIRA")]  # near dead-centre
    drift = [_text(40, 40, 120, 60, text="EIRA")]  # jammed in a corner
    assert ls._balance_score(centred, W, H) > ls._balance_score(drift, W, H)


def test_alignment_rewards_shared_left_edge():
    W = 1080
    aligned = [
        _text(80, 120, 500, 120, text="EIRA HUGHES"),
        _text(80, 300, 300, 40, text="FREESTYLE"),
        _text(80, 1120, 320, 90, text="ONE MIN"),
    ]
    ragged = [
        _text(80, 120, 500, 120, text="EIRA HUGHES"),
        _text(237, 300, 300, 40, text="FREESTYLE"),
        _text(511, 1120, 320, 90, text="ONE MIN"),
    ]
    assert ls._alignment_score(aligned, W) > ls._alignment_score(ragged, W)


def test_clearance_penalises_a_badge_on_a_word():
    W, H = 1080, 1350
    word = _text(80, 120, 600, 130, text="EIRA HUGHES")
    clear = [word, _mark(950, 60, 80, 80)]  # badge in the corner
    on_word = [word, _mark(120, 140, 90, 90)]  # small badge dead on the headline
    assert ls._clearance_score(clear, W, H) > ls._clearance_score(on_word, W, H)


def test_saliency_neutral_without_photo_and_rewards_in_frame():
    W, H = 1080, 1350
    assert ls._saliency_score([_text(80, 120, 400, 60)], W, H) == 0.5
    in_frame = [_photo(0, 0, 1080, 1350, ox=0.5, oy=0.4)]
    edge = [_photo(0, 0, 1080, 1350, ox=0.98, oy=0.98)]
    assert ls._saliency_score(in_frame, W, H) > ls._saliency_score(edge, W, H)


def test_saliency_penalises_focus_under_a_word():
    W, H = 1080, 1350
    focus_clear = [_photo(0, 0, 1080, 1350, ox=0.5, oy=0.3), _text(80, 1100, 400, 90, text="ONE")]
    focus_buried = [
        _photo(0, 0, 1080, 1350, ox=0.5, oy=0.5),
        _text(0, 620, 1080, 130, text="HEADLINE"),  # sits over the focus point
    ]
    assert ls._saliency_score(focus_clear, W, H) > ls._saliency_score(focus_buried, W, H)


# --------------------------------------------------------------------------- #
# Selection (choose) — humble, degrade-safe
# --------------------------------------------------------------------------- #


def _drifting_geom():
    # Same content as clean, but the text is jammed into a corner (worse balance).
    return {
        "W": 1080,
        "H": 1350,
        "boxes": [
            _text(20, 20, 400, 120, text="EIRA HUGHES", font=96),
            _text(20, 150, 300, 40, text="100M FREESTYLE", font=28, weight=600),
            _photo(0, 0, 1080, 1350, ox=0.5, oy=0.35),
        ],
    }


def test_choose_keeps_current_on_tie():
    g = _clean_geom()
    rec = ls.choose([("cur", g), ("sib", g)], archetype="individual_hero", current_id="cur")
    assert rec["winner"] == "cur"
    assert rec["changed"] is False


def test_choose_keeps_current_when_sibling_collides():
    collide = {
        "W": 1080,
        "H": 1350,
        "boxes": [
            _text(80, 120, 600, 130, text="EIRA HUGHES"),
            _text(90, 130, 600, 130, text="OVERLAP"),
        ],
    }
    rec = ls.choose(
        [("cur", _clean_geom()), ("sib", collide)], archetype="individual_hero", current_id="cur"
    )
    assert rec["winner"] == "cur" and rec["changed"] is False


def test_choose_switches_when_sibling_is_clearly_better():
    rec = ls.choose(
        [("cur", _drifting_geom()), ("sib", _clean_geom())],
        archetype="individual_hero",
        current_id="cur",
    )
    assert rec["winner"] == "sib"
    assert rec["changed"] is True


def test_choose_switches_off_a_colliding_current():
    collide = {
        "W": 1080,
        "H": 1350,
        "boxes": [
            _text(80, 120, 600, 130, text="EIRA HUGHES"),
            _text(90, 130, 600, 130, text="OVERLAP"),
        ],
    }
    rec = ls.choose(
        [("cur", collide), ("sib", _clean_geom())], archetype="individual_hero", current_id="cur"
    )
    assert rec["winner"] == "sib" and rec["changed"] is True


def test_choose_degrades_to_current_when_all_disqualified():
    collide = {
        "W": 1080,
        "H": 1350,
        "boxes": [
            _text(80, 120, 600, 130, text="EIRA HUGHES"),
            _text(90, 130, 600, 130, text="OVERLAP"),
        ],
    }
    rec = ls.choose(
        [("cur", collide), ("sib", collide)], archetype="individual_hero", current_id="cur"
    )
    assert rec["winner"] == "cur" and rec["changed"] is False


def test_choose_handles_failed_measurement_as_disqualified():
    rec = ls.choose(
        [("cur", _clean_geom()), ("sib", None)], archetype="individual_hero", current_id="cur"
    )
    assert rec["winner"] == "cur"
    # The failed candidate is recorded but never chosen.
    assert any(c["pack"] == "sib" and c["disqualified"] for c in rec["candidates"])


def test_choose_empty_is_a_noop():
    rec = ls.choose([], current_id="cur")
    assert rec["winner"] == "cur" and rec["changed"] is False


def test_choose_is_deterministic():
    cands = [("cur", _drifting_geom()), ("sib", _clean_geom())]
    a = ls.choose(cands, archetype="individual_hero", current_id="cur")
    b = ls.choose(cands, archetype="individual_hero", current_id="cur")
    assert a == b
