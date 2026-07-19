"""
Regression tests for P10 — legacy/swim_content_v5/recommender.py dead-code &
unreachable-path fixes (issues F26, F29, F32).

F26: ``derive_safe_to_post`` must return the CANONICAL
     ``mediahub.recognition.schema.SafeToPost``. Previously a module-level
     ``try: from recognition.schema import SafeToPost`` always failed at
     canonical import time and bound a shadow class instead, so ``isinstance``
     against the real type was always False.
F32: the identity-suppression branch (``pb_decision`` ->
     ``SUPPRESSED_NEEDS_VERIFICATION`` -> do_not_post) and the unused
     ``ranked_factors`` / ``pb_decision`` parameters are removed — the sole
     caller (ranker.py) passes only the achievement, so the branch was dead.
F29: ``recommend_post_type`` no longer builds the dead ``meet_level`` list or
     computes the unused ``best_priority`` local. (The whole persisted
     'recommendations' blob is dead output; removing the blob itself spans
     report.py/schema.py/recognition-__init__ and is a cross-session hand-off.)
"""
import inspect
from types import SimpleNamespace

import pytest

# Importing mediahub installs the legacy alias + sys.path shims used below.
import mediahub  # noqa: F401
from swim_content_v5.recommender import derive_safe_to_post, recommend_post_type
from swim_content_v5.schema import QualityBand, PostType
from mediahub.recognition.schema import SafeToPost as CanonicalSafeToPost


def _ach(confidence=0.9, notes=None, atype="medal_gold"):
    return SimpleNamespace(
        confidence=confidence,
        uncertainty_notes=notes or [],
        type=atype,
    )


def _ranked(name, swimmer_id, band, priority, atype):
    return SimpleNamespace(
        achievement=SimpleNamespace(
            swimmer_name=name, swimmer_id=swimmer_id, type=atype
        ),
        quality_band=band,
        priority=priority,
    )


# --- F26: canonical SafeToPost resolution ----------------------------------

def test_derive_safe_to_post_returns_canonical_type():
    """The result is an instance of the canonical SafeToPost, not a shadow."""
    result = derive_safe_to_post(_ach(confidence=0.9, atype="medal_gold"))
    assert isinstance(result, CanonicalSafeToPost)
    assert type(result).__module__ == "mediahub.recognition.schema"
    assert result.to_dict() == {"level": result.level, "reason": result.reason}


def test_recommender_has_no_module_level_safetopost_shadow():
    """The broken try/except shadow class is gone from the module namespace."""
    from swim_content_v5 import recommender
    assert not hasattr(recommender, "SafeToPost"), (
        "recommender must not bind a module-level SafeToPost shadow class"
    )


# --- F32: dead identity-suppression path & unused params -------------------

def test_derive_safe_to_post_signature_has_only_achievement():
    params = list(inspect.signature(derive_safe_to_post).parameters)
    assert params == ["achievement"]


def test_derive_safe_to_post_rejects_removed_pb_decision_kwarg():
    with pytest.raises(TypeError):
        derive_safe_to_post(
            _ach(), pb_decision={"status": "SUPPRESSED_NEEDS_VERIFICATION"}
        )


def test_derive_safe_to_post_suppression_branch_removed_from_source():
    src = inspect.getsource(derive_safe_to_post)
    assert "SUPPRESSED_NEEDS_VERIFICATION" not in src
    assert "could not be verified" not in src
    assert "pb_decision" not in src
    assert "ranked_factors" not in src


def test_derive_safe_to_post_live_levels_preserved():
    # confidence < 0.4 -> do_not_post
    assert derive_safe_to_post(
        _ach(confidence=0.3, atype="medal_gold")
    ).level == "do_not_post"
    # any uncertainty note -> needs_review
    assert derive_safe_to_post(
        _ach(confidence=0.9, notes=["ambiguous name"], atype="x")
    ).level == "needs_review"
    # medium confidence (0.4 <= conf < 0.7) -> needs_review
    assert derive_safe_to_post(
        _ach(confidence=0.5, atype="medal_gold")
    ).level == "needs_review"
    # high-confidence medal_gold -> safe with per-type reason
    gold = derive_safe_to_post(_ach(confidence=0.95, atype="medal_gold"))
    assert gold.level == "safe" and "Gold medal" in gold.reason


# --- F29: dead recommend_post_type internals -------------------------------

def test_recommend_post_type_has_no_dead_locals():
    src = inspect.getsource(recommend_post_type)
    assert "meet_level:" not in src         # dead local list declaration
    assert "meet_level.append" not in src   # ... and its only writer
    assert "best_priority" not in src       # unused max() computation
    # the legitimate ctx.meet_level national override must remain
    assert 'ctx.meet_level == "national"' in src


def test_recommend_post_type_still_groups_and_recommends():
    ras = [
        _ranked("Ana", "a1", QualityBand.ELITE, 0.9, "medal_gold"),
        _ranked("Ana", "a1", QualityBand.STRONG, 0.8, "pb_confirmed"),
        _ranked("Bob", "b1", QualityBand.STRONG, 0.7, "pb_confirmed"),
        _ranked("Cy", "c1", QualityBand.NICE, 0.3, "pb_likely"),
    ]
    ctx = SimpleNamespace(meet_level="county", meet_name="Spring Open")
    recs = recommend_post_type(ras, ctx)
    by_name = {r.swimmer_or_group: r for r in recs}
    assert by_name["Ana"].suggested_post_type == PostType.MAIN_FEED
    assert by_name["Bob"].suggested_post_type == PostType.STORY
    assert by_name["Cy"].suggested_post_type == PostType.INTERNAL_NOTE
    # 3 elite/strong achievements -> a headline meet-recap is prepended
    assert recs[0].swimmer_or_group == "meet recap"


def test_recommend_post_type_national_override_preserved():
    ras = [
        _ranked("Nat", "n1", QualityBand.STRONG, 0.7, "pb_confirmed"),
        _ranked("Nat", "n1", QualityBand.STRONG, 0.6, "pb_confirmed"),
    ]
    ctx = SimpleNamespace(meet_level="national", meet_name="Nationals")
    recs = recommend_post_type(ras, ctx)
    nat = next(r for r in recs if r.swimmer_or_group == "Nat")
    assert nat.suggested_post_type == PostType.MAIN_FEED
