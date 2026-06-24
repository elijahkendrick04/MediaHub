"""Tests for governance request-context + the feature_scope guard (1.23)."""

from __future__ import annotations

import pytest

from mediahub.governance import context, features, quota


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(quota, "_PLAN_FEATURE_LIMITS", {})
    monkeypatch.delenv("MEDIAHUB_QUOTA_CAPTION", raising=False)
    for plan in quota.KNOWN_PLANS:
        monkeypatch.delenv(f"MEDIAHUB_QUOTA_CAPTION_{plan.upper()}", raising=False)
    context.clear_request_context()
    import mediahub.observability.feature_quota as fq

    yield context, fq
    context.clear_request_context()


# ---- the contextvar -------------------------------------------------------


def test_set_get_clear(fresh):
    ctx, _ = fresh
    assert ctx.current_org_id() is None
    ctx.set_request_context("club-a", "free")
    assert ctx.current_org_id() == "club-a"
    assert ctx.current_plan() == "free"
    ctx.clear_request_context()
    assert ctx.current_org_id() is None
    assert ctx.current_plan() is None


def test_blank_org_normalises_to_none(fresh):
    ctx, _ = fresh
    ctx.set_request_context("   ", "")
    assert ctx.current_org_id() is None
    assert ctx.current_plan() is None


def test_bind_restores_prior(fresh):
    ctx, _ = fresh
    ctx.set_request_context("club-a", "free")
    with ctx.bind("club-b", "club"):
        assert ctx.current_org_id() == "club-b"
        assert ctx.current_plan() == "club"
    assert ctx.current_org_id() == "club-a"
    assert ctx.current_plan() == "free"


# ---- feature_scope --------------------------------------------------------


def test_scope_without_org_runs_but_records_nothing(fresh):
    ctx, fq = fresh
    ran = False
    with ctx.feature_scope(features.FEATURE_CAPTION):
        ran = True
    assert ran is True
    assert fq.count_for_org("club-a", ok_only=False) == 0


def test_scope_records_success_from_context(fresh):
    ctx, fq = fresh
    ctx.set_request_context("club-a", "free")
    with ctx.feature_scope(features.FEATURE_CAPTION):
        pass
    assert fq.count_for_org("club-a", feature="caption") == 1


def test_scope_records_failure_and_reraises(fresh):
    ctx, fq = fresh
    ctx.set_request_context("club-a", "free")
    with pytest.raises(ValueError):
        with ctx.feature_scope(features.FEATURE_CAPTION):
            raise ValueError("boom")
    # Recorded, but as a failure → not counted against quota.
    assert fq.count_for_org("club-a", feature="caption") == 0
    assert fq.count_for_org("club-a", feature="caption", ok_only=False) == 1


def test_scope_annotation_written(fresh):
    ctx, fq = fresh
    ctx.set_request_context("club-a", "free")
    with ctx.feature_scope(features.FEATURE_CAPTION) as scope:
        scope.provider = "gemini"
        scope.model = "gemini-2.5"
        scope.detail = "tone=warm"
    usage = fq.usage_for_org("club-a")
    assert usage["by_feature"]["caption"] == 1


def test_scope_explicit_args_override_context(fresh):
    ctx, fq = fresh
    ctx.set_request_context("club-a", "free")
    with ctx.feature_scope(features.FEATURE_CAPTION, org_id="club-b", plan="club"):
        pass
    assert fq.count_for_org("club-a", ok_only=False) == 0
    assert fq.count_for_org("club-b", feature="caption") == 1


def test_scope_enforces_and_blocks_without_recording(fresh, monkeypatch):
    ctx, fq = fresh
    monkeypatch.setenv("MEDIAHUB_QUOTA_CAPTION", "1")
    ctx.set_request_context("club-a", "free")
    # First call is fine and consumes the single unit.
    with ctx.feature_scope(features.FEATURE_CAPTION):
        pass
    assert fq.count_for_org("club-a", feature="caption") == 1
    # Second call is over the limit → QuotaExceeded before the body, no new row.
    body_ran = False
    with pytest.raises(quota.QuotaExceeded):
        with ctx.feature_scope(features.FEATURE_CAPTION):
            body_ran = True
    assert body_ran is False
    assert fq.count_for_org("club-a", feature="caption", ok_only=False) == 1


def test_scope_enforce_false_skips_blocking(fresh, monkeypatch):
    ctx, fq = fresh
    monkeypatch.setenv("MEDIAHUB_QUOTA_CAPTION", "0")  # would block everything
    ctx.set_request_context("club-a", "free")
    with ctx.feature_scope(features.FEATURE_CAPTION, enforce=False):
        pass
    # Not blocked, and still metered.
    assert fq.count_for_org("club-a", feature="caption") == 1
