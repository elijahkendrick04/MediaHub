"""Tests for video.director — AI reel planning with an honest deterministic default.

The default ordering is pure maths over moment scores; the AI path is exercised
by stubbing ``media_ai.llm`` so no provider/network is touched.
"""

from __future__ import annotations

from mediahub.video import director
from mediahub.video.director import ClipBeat, ReelPlan, default_order, plan_reel


def _meta(scores_by_clip):
    """Build clips_meta with the given per-clip moment scores."""
    out = []
    for ci, scores in enumerate(scores_by_clip):
        moments = [
            {"start_ms": i * 5000, "end_ms": i * 5000 + 4000, "score": s, "kind": "energy", "reason": f"m{i}", "label": ""}
            for i, s in enumerate(scores)
        ]
        out.append({"name": f"clip{ci}", "orientation": "landscape", "moments": moments})
    return out


def test_default_order_ranks_by_score_then_caps_per_clip():
    meta = _meta([[0.9, 0.8, 0.7], [0.6]])  # clip0 has 3 moments, clip1 has 1
    order = default_order(meta, max_beats=5)
    # at most 2 from clip0 (the cap), then clip1's, then the third clip0 moment
    assert order[0] == ClipBeat(0, 0)  # highest
    assert order[1] == ClipBeat(0, 1)  # second-highest (still under cap)
    assert ClipBeat(1, 0) in order  # clip1 included for variety
    assert sum(1 for b in order if b.asset_index == 0) <= 2


def test_default_order_respects_max_beats():
    meta = _meta([[0.9, 0.5], [0.8, 0.4], [0.7, 0.3]])
    assert len(default_order(meta, max_beats=2)) == 2


def test_plan_reel_default_when_no_provider(monkeypatch):
    import mediahub.media_ai.llm as llm

    monkeypatch.setattr(llm, "is_available", lambda: False)
    plan = plan_reel(_meta([[0.9], [0.7]]))
    assert plan.source == "default"
    assert plan.order[0] == ClipBeat(0, 0)
    assert plan.look == director.DEFAULT_LOOK


def test_plan_reel_uses_ai_when_available(monkeypatch):
    import mediahub.media_ai.llm as llm

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(
        llm,
        "generate_json",
        lambda *a, **k: {
            "order": [{"clip": 1, "moment": 0}, {"clip": 0, "moment": 0}],
            "look": "warm",
            "music_mood": "triumphant",
            "hook": "Three PBs in one meet",
            "why": "lead with the medal",
        },
    )
    plan = plan_reel(_meta([[0.9], [0.7]]), brief_context="county champs")
    assert plan.source == "ai"
    assert plan.order == [ClipBeat(1, 0), ClipBeat(0, 0)]  # AI reorder honoured
    assert plan.look == "warm" and plan.music_mood == "triumphant"
    assert plan.hook == "Three PBs in one meet"


def test_plan_reel_clamps_bad_ai_output(monkeypatch):
    import mediahub.media_ai.llm as llm

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(
        llm,
        "generate_json",
        lambda *a, **k: {
            "order": [{"clip": 9, "moment": 9}, {"clip": 0, "moment": 0}],  # 9,9 invalid
            "look": "neon-cyberpunk",  # not a real look
            "hook": "x" * 200,
        },
    )
    plan = plan_reel(_meta([[0.9], [0.7]]))
    # invalid beat dropped, valid kept; unknown look → default; hook clamped
    assert ClipBeat(0, 0) in plan.order
    assert all(0 <= b.asset_index < 2 for b in plan.order)
    assert plan.look == director.DEFAULT_LOOK
    assert len(plan.hook) <= 60


def test_plan_reel_falls_back_to_default_on_ai_error(monkeypatch):
    import mediahub.media_ai.llm as llm

    def boom(*a, **k):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm, "generate_json", boom)
    plan = plan_reel(_meta([[0.9], [0.7]]))
    assert plan.source == "default"
    assert plan.order  # still usable


def test_plan_reel_no_moments_is_empty_plan():
    plan = plan_reel([{"name": "c", "moments": []}])
    assert plan.order == [] and plan.source == "default"


def test_suggest_hook_honest_without_provider(monkeypatch):
    import mediahub.media_ai.llm as llm

    monkeypatch.setattr(llm, "is_available", lambda: False)
    assert director.suggest_hook("a swim meet") == ""


def test_reel_plan_to_dict_roundtrips_shape():
    p = ReelPlan(order=[ClipBeat(0, 1)], look="film", music_mood="calm", hook="hi", source="ai")
    d = p.to_dict()
    assert d["order"] == [{"asset_index": 0, "moment_index": 1}]
    assert d["look"] == "film" and d["source"] == "ai"


# --- per-beat weight (cross-clip virality emphasis) ------------------------


def test_clamp_weight_bounds_and_garbage():
    assert director.clamp_weight(1.5) == 1.5
    assert director.clamp_weight(9.0) == director.MAX_WEIGHT
    assert director.clamp_weight(0.0) == director.MIN_WEIGHT
    assert director.clamp_weight("nope") == 1.0
    assert director.clamp_weight(None) == 1.0
    assert director.clamp_weight(float("nan")) == 1.0


def test_clip_beat_weight_omitted_at_default_present_otherwise():
    # An even (1.0) weight serialises exactly as before the feature existed, so a
    # plan that doesn't weight stays byte-identical in cache keys.
    assert director.ClipBeat(0, 0).to_dict() == {"asset_index": 0, "moment_index": 0}
    assert director.ClipBeat(0, 0, weight=1.5).to_dict() == {
        "asset_index": 0,
        "moment_index": 0,
        "weight": 1.5,
    }


def test_default_order_beats_are_evenly_weighted():
    # No AI ⇒ no virality judgement ⇒ every beat keeps its detected length.
    order = default_order(_meta([[0.9, 0.8], [0.7]]), max_beats=5)
    assert order and all(b.weight == 1.0 for b in order)


def test_plan_reel_parses_and_clamps_per_beat_weight(monkeypatch):
    import mediahub.media_ai.llm as llm

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(
        llm,
        "generate_json",
        lambda *a, **k: {
            "order": [
                {"clip": 0, "moment": 0, "weight": 1.7},  # money shot
                {"clip": 1, "moment": 0, "weight": 9.0},  # clamped to MAX
                {"clip": 0, "moment": 1},  # missing → 1.0
            ],
            "look": "punch",
        },
    )
    plan = plan_reel(_meta([[0.9, 0.5], [0.7]]))
    assert plan.source == "ai"
    weights = {(b.asset_index, b.moment_index): b.weight for b in plan.order}
    assert weights[(0, 0)] == 1.7
    assert weights[(1, 0)] == director.MAX_WEIGHT
    assert weights[(0, 1)] == 1.0
