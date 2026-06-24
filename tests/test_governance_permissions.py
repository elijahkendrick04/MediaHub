"""Unit tests for governance role-based AI feature permissions (1.23)."""

from __future__ import annotations

import pytest

from mediahub.collab import permissions as caps
from mediahub.governance import features as f
from mediahub.governance import permissions as p


def test_required_capability_map():
    assert p.required_capability(f.FEATURE_CAPTION) == caps.CAP_EDIT
    assert p.required_capability(f.FEATURE_IMAGINE) == caps.CAP_EDIT
    assert p.required_capability(f.FEATURE_DESCRIBE) == caps.CAP_EDIT
    assert p.required_capability(f.FEATURE_RESEARCH) == caps.CAP_EDIT
    assert p.required_capability(f.FEATURE_BRAND) == caps.CAP_MANAGE
    assert p.required_capability(f.FEATURE_PALETTE) == caps.CAP_MANAGE
    assert p.required_capability(f.FEATURE_DNA) == caps.CAP_MANAGE


def test_unknown_feature_defaults_to_edit():
    assert p.required_capability("totally_unknown") == caps.CAP_EDIT


@pytest.mark.parametrize(
    "role,feature,expected",
    [
        ("owner", f.FEATURE_CAPTION, True),
        ("owner", f.FEATURE_BRAND, True),
        ("member", f.FEATURE_CAPTION, True),  # legacy seat = edit+approve
        ("member", f.FEATURE_BRAND, False),  # but not manage
        ("editor", f.FEATURE_CAPTION, True),
        ("editor", f.FEATURE_IMAGINE, True),
        ("editor", f.FEATURE_BRAND, False),
        ("approver", f.FEATURE_CAPTION, False),  # approve != edit
        ("reviewer", f.FEATURE_CAPTION, False),
        ("reviewer", f.FEATURE_IMAGINE, False),
        ("viewer", f.FEATURE_CAPTION, False),
        ("viewer", f.FEATURE_BRAND, False),
        ("garbage-role", f.FEATURE_CAPTION, False),  # least-privilege
    ],
)
def test_can_use_feature_matrix(role, feature, expected):
    assert p.can_use_feature(role, feature) is expected


def test_features_for_role():
    assert p.features_for_role("owner") == f.feature_keys()  # everything
    assert p.features_for_role("editor") == [
        f.FEATURE_CAPTION,
        f.FEATURE_IMAGINE,
        f.FEATURE_DESCRIBE,
        f.FEATURE_RESEARCH,
    ]
    assert p.features_for_role("viewer") == []


def test_plan_gate_default_open():
    # No feature is plan-gated by default — every plan passes.
    assert p.plan_allows(f.FEATURE_CAPTION, "free") is True
    assert p.plan_allows(f.FEATURE_IMAGINE, None) is True


def test_plan_gate_when_configured(monkeypatch):
    monkeypatch.setattr(p, "_FEATURE_MIN_PLAN", {f.FEATURE_IMAGINE: "club"})
    assert p.plan_allows(f.FEATURE_IMAGINE, "free") is False
    assert p.plan_allows(f.FEATURE_IMAGINE, "club") is True
    assert p.plan_allows(f.FEATURE_IMAGINE, "federation") is True
    # An editor on free is blocked by the plan even though the role allows it.
    assert p.can_use_feature("editor", f.FEATURE_IMAGINE, plan="free") is False
    assert p.can_use_feature("editor", f.FEATURE_IMAGINE, plan="club") is True


def test_denial_reason_role():
    msg = p.denial_reason("viewer", f.FEATURE_CAPTION)
    assert "Viewer" in msg
    assert "AI captions" in msg
    assert "editor" in msg.lower()
    # owner-only feature points at the owner, not editor access
    assert "owner" in p.denial_reason("editor", f.FEATURE_BRAND).lower()


def test_denial_reason_empty_when_allowed():
    assert p.denial_reason("owner", f.FEATURE_CAPTION) == ""


def test_denial_reason_plan(monkeypatch):
    monkeypatch.setattr(p, "_FEATURE_MIN_PLAN", {f.FEATURE_IMAGINE: "club"})
    msg = p.denial_reason("editor", f.FEATURE_IMAGINE, plan="free")
    assert "Club" in msg and "plan" in msg.lower()
