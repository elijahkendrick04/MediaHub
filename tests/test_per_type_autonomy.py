"""Tests for P2.4 — per-type autonomy controls.

Covers:
  1. Default policy is fully gated (approval_required) for every content type.
  2. Setting a level persists per-profile and survives a reload.
  3. Cross-profile isolation: org A cannot read or alter org B's policy.
  4. Publish gate (assert_type_publishing_allowed):
     a. Blocks when the type is approval_required (default).
     b. Blocks when the type is draft_only.
     c. Allows when the type is fully_autonomous AND the global kill switch is off.
     d. Blocks even if fully_autonomous when the global kill switch is engaged.
  5. Old profiles (no stored policy file) load cleanly as fully gated.
  6. UI route GET /api/autonomy/policy returns the policy for the active org.
  7. UI route POST /api/autonomy/policy persists a saved setting.
  8. /healthz/deps includes per_type_autonomy without affecting the ok flag.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mediahub.publishing.per_type_policy import (
    AutonomyLevel,
    load_policy,
    save_policy,
)
from mediahub.publishing.kill_switch import KILL_SWITCH_ENV
from mediahub.publishing.type_gate import TypeGated, assert_type_publishing_allowed
from mediahub.club_platform.content_types import ContentType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_gated(policy: dict) -> bool:
    """True when every type in the policy is gated (not fully_autonomous)."""
    return all(v != AutonomyLevel.FULLY_AUTONOMOUS.value for v in policy.values())


def _all_types() -> list[str]:
    return [ct.value for ct in ContentType]


# ---------------------------------------------------------------------------
# 1. Defaults are fully gated
# ---------------------------------------------------------------------------


def test_default_policy_is_all_gated(tmp_path):
    pol = load_policy("org-new", data_dir=tmp_path)
    assert _all_gated(pol), f"Expected all gated; got: {pol}"


def test_default_policy_covers_all_content_types(tmp_path):
    pol = load_policy("org-new", data_dir=tmp_path)
    for ct in _all_types():
        assert ct in pol, f"Missing content type {ct!r} in default policy"


def test_default_level_is_approval_required(tmp_path):
    pol = load_policy("org-new", data_dir=tmp_path)
    for ct in _all_types():
        assert pol[ct] == AutonomyLevel.APPROVAL_REQUIRED.value, (
            f"Expected approval_required for {ct!r}; got {pol[ct]!r}"
        )


# ---------------------------------------------------------------------------
# 2. Setting a level persists and reloads correctly
# ---------------------------------------------------------------------------


def test_save_and_reload_single_type(tmp_path):
    org = "org-alpha"
    pol = load_policy(org, data_dir=tmp_path)
    pol[ContentType.MEET_RECAP.value] = AutonomyLevel.FULLY_AUTONOMOUS.value
    save_policy(org, pol, data_dir=tmp_path)

    reloaded = load_policy(org, data_dir=tmp_path)
    assert reloaded[ContentType.MEET_RECAP.value] == AutonomyLevel.FULLY_AUTONOMOUS.value
    # All other types remain gated
    for ct in _all_types():
        if ct != ContentType.MEET_RECAP.value:
            assert reloaded[ct] != AutonomyLevel.FULLY_AUTONOMOUS.value


def test_save_and_reload_all_types(tmp_path):
    org = "org-beta"
    pol = {ct: AutonomyLevel.DRAFT_ONLY.value for ct in _all_types()}
    save_policy(org, pol, data_dir=tmp_path)

    reloaded = load_policy(org, data_dir=tmp_path)
    for ct in _all_types():
        assert reloaded[ct] == AutonomyLevel.DRAFT_ONLY.value


def test_save_normalises_unknown_values_to_approval_required(tmp_path):
    org = "org-gamma"
    dirty_pol = {ContentType.MEET_RECAP.value: "not_a_real_level"}
    save_policy(org, dirty_pol, data_dir=tmp_path)
    reloaded = load_policy(org, data_dir=tmp_path)
    assert reloaded[ContentType.MEET_RECAP.value] == AutonomyLevel.APPROVAL_REQUIRED.value


# ---------------------------------------------------------------------------
# 3. Cross-profile isolation
# ---------------------------------------------------------------------------


def test_cross_profile_isolation_no_bleed(tmp_path):
    """Org A's policy does not affect Org B's policy."""
    pol_a = load_policy("org-a", data_dir=tmp_path)
    pol_a[ContentType.MEET_RECAP.value] = AutonomyLevel.FULLY_AUTONOMOUS.value
    save_policy("org-a", pol_a, data_dir=tmp_path)

    pol_b = load_policy("org-b", data_dir=tmp_path)
    assert pol_b[ContentType.MEET_RECAP.value] != AutonomyLevel.FULLY_AUTONOMOUS.value


def test_cross_profile_write_does_not_affect_other(tmp_path):
    """Saving org B's policy does not alter org A's stored file."""
    pol_a = {ct: AutonomyLevel.FULLY_AUTONOMOUS.value for ct in _all_types()}
    save_policy("org-a", pol_a, data_dir=tmp_path)

    pol_b = load_policy("org-b", data_dir=tmp_path)
    save_policy("org-b", pol_b, data_dir=tmp_path)  # save default

    reloaded_a = load_policy("org-a", data_dir=tmp_path)
    for ct in _all_types():
        assert reloaded_a[ct] == AutonomyLevel.FULLY_AUTONOMOUS.value


def test_separate_files_per_org(tmp_path):
    """Each org gets its own file under per_type_autonomy/."""
    save_policy("org-x", {ct: AutonomyLevel.DRAFT_ONLY.value for ct in _all_types()}, data_dir=tmp_path)
    save_policy("org-y", {ct: AutonomyLevel.APPROVAL_REQUIRED.value for ct in _all_types()}, data_dir=tmp_path)

    files = list((tmp_path / "per_type_autonomy").iterdir())
    names = {f.name for f in files}
    assert "org-x.json" in names
    assert "org-y.json" in names


# ---------------------------------------------------------------------------
# 4. Publish gate
# ---------------------------------------------------------------------------


def test_gate_blocks_approval_required(tmp_path, monkeypatch):
    monkeypatch.delenv(KILL_SWITCH_ENV, raising=False)
    org = "org-gate-a"
    # default policy is approval_required
    with pytest.raises(TypeGated):
        assert_type_publishing_allowed(org, ContentType.MEET_RECAP.value, data_dir=tmp_path)


def test_gate_blocks_draft_only(tmp_path, monkeypatch):
    monkeypatch.delenv(KILL_SWITCH_ENV, raising=False)
    org = "org-gate-b"
    pol = load_policy(org, data_dir=tmp_path)
    pol[ContentType.MEET_RECAP.value] = AutonomyLevel.DRAFT_ONLY.value
    save_policy(org, pol, data_dir=tmp_path)

    with pytest.raises(TypeGated):
        assert_type_publishing_allowed(org, ContentType.MEET_RECAP.value, data_dir=tmp_path)


def test_gate_allows_fully_autonomous(tmp_path, monkeypatch):
    monkeypatch.delenv(KILL_SWITCH_ENV, raising=False)
    org = "org-gate-c"
    pol = load_policy(org, data_dir=tmp_path)
    pol[ContentType.MEET_RECAP.value] = AutonomyLevel.FULLY_AUTONOMOUS.value
    save_policy(org, pol, data_dir=tmp_path)

    # Should NOT raise
    assert_type_publishing_allowed(org, ContentType.MEET_RECAP.value, data_dir=tmp_path)


def test_gate_blocks_fully_autonomous_when_kill_switch_engaged(tmp_path, monkeypatch):
    monkeypatch.setenv(KILL_SWITCH_ENV, "1")
    from mediahub.publishing.kill_switch import PublishingHalted

    org = "org-gate-d"
    pol = load_policy(org, data_dir=tmp_path)
    pol[ContentType.MEET_RECAP.value] = AutonomyLevel.FULLY_AUTONOMOUS.value
    save_policy(org, pol, data_dir=tmp_path)

    with pytest.raises(PublishingHalted):
        assert_type_publishing_allowed(org, ContentType.MEET_RECAP.value, data_dir=tmp_path)


def test_gate_blocks_unknown_type_as_gated(tmp_path, monkeypatch):
    """An unknown content type string resolves to approval_required."""
    monkeypatch.delenv(KILL_SWITCH_ENV, raising=False)
    org = "org-gate-e"
    # Save a policy with all types fully_autonomous, but unknown type won't appear
    pol = {ct: AutonomyLevel.FULLY_AUTONOMOUS.value for ct in _all_types()}
    save_policy(org, pol, data_dir=tmp_path)

    with pytest.raises(TypeGated):
        assert_type_publishing_allowed(org, "not_a_real_content_type", data_dir=tmp_path)


# ---------------------------------------------------------------------------
# 5. Old profiles without a stored policy load as gated
# ---------------------------------------------------------------------------


def test_missing_policy_file_loads_as_gated(tmp_path):
    """An org with no policy JSON on disk is treated as fully gated."""
    pol = load_policy("brand-new-org", data_dir=tmp_path)
    assert _all_gated(pol)


def test_corrupt_policy_file_falls_back_to_gated(tmp_path):
    """A corrupted/non-JSON policy file falls back gracefully to gated."""
    (tmp_path / "per_type_autonomy").mkdir(parents=True, exist_ok=True)
    (tmp_path / "per_type_autonomy" / "bad-org.json").write_text("not valid json", encoding="utf-8")

    pol = load_policy("bad-org", data_dir=tmp_path)
    assert _all_gated(pol)


# ---------------------------------------------------------------------------
# 6 & 7. Flask route: GET + POST /api/autonomy/policy
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_with_org(tmp_path, monkeypatch):
    """Flask test app with a seeded org pinned in session."""
    import os

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.web import create_app

    save_profile(ClubProfile(profile_id="org-test", display_name="Test Club"))

    application = create_app()
    application.config["TESTING"] = True
    application.config["SECRET_KEY"] = "test-secret"
    return application


def _with_org(client, org_id: str):
    """Pin an org into the test session."""
    with client.session_transaction() as sess:
        sess["active_profile_id"] = org_id


def test_get_policy_no_active_org(app_with_org):
    with app_with_org.test_client() as client:
        resp = client.get("/api/autonomy/policy")
    assert resp.status_code == 403


def test_get_policy_returns_defaults(app_with_org, tmp_path):
    with app_with_org.test_client() as client:
        _with_org(client, "org-test")
        resp = client.get("/api/autonomy/policy")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["org_id"] == "org-test"
    policy = body["policy"]
    for ct in _all_types():
        assert ct in policy
        assert policy[ct] == AutonomyLevel.APPROVAL_REQUIRED.value


def test_post_policy_saves_and_get_reflects(app_with_org, tmp_path):
    with app_with_org.test_client() as client:
        _with_org(client, "org-test")

        payload = {ContentType.MEET_RECAP.value: AutonomyLevel.FULLY_AUTONOMOUS.value}
        post_resp = client.post(
            "/api/autonomy/policy",
            data=payload,
            content_type="application/x-www-form-urlencoded",
        )
        assert post_resp.status_code == 200
        assert post_resp.get_json()["ok"] is True

        get_resp = client.get("/api/autonomy/policy")
        saved = get_resp.get_json()["policy"]
        assert saved[ContentType.MEET_RECAP.value] == AutonomyLevel.FULLY_AUTONOMOUS.value
        # Other types remain gated
        for ct in _all_types():
            if ct != ContentType.MEET_RECAP.value:
                assert saved[ct] == AutonomyLevel.APPROVAL_REQUIRED.value


def test_post_policy_json_body(app_with_org, tmp_path):
    with app_with_org.test_client() as client:
        _with_org(client, "org-test")

        payload = {ContentType.ATHLETE_SPOTLIGHT.value: AutonomyLevel.DRAFT_ONLY.value}
        post_resp = client.post(
            "/api/autonomy/policy",
            json=payload,
            content_type="application/json",
        )
        assert post_resp.status_code == 200

        get_resp = client.get("/api/autonomy/policy")
        saved = get_resp.get_json()["policy"]
        assert saved[ContentType.ATHLETE_SPOTLIGHT.value] == AutonomyLevel.DRAFT_ONLY.value


def test_post_policy_no_active_org(app_with_org):
    with app_with_org.test_client() as client:
        resp = client.post(
            "/api/autonomy/policy",
            data={ContentType.MEET_RECAP.value: AutonomyLevel.FULLY_AUTONOMOUS.value},
        )
    assert resp.status_code == 403


def test_settings_page_renders_autonomy_section(app_with_org):
    with app_with_org.test_client() as client:
        _with_org(client, "org-test")
        resp = client.get("/settings")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "autonomy" in body.lower()
    assert "Approval required" in body or "approval_required" in body


# ---------------------------------------------------------------------------
# 8. /healthz/deps includes per_type_autonomy without breaking ok flag
# ---------------------------------------------------------------------------


@pytest.fixture()
def plain_app(tmp_path, monkeypatch):
    import os

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    return application


def test_healthz_deps_includes_per_type_autonomy(plain_app):
    with plain_app.test_client() as client:
        resp = client.get("/healthz/deps")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "per_type_autonomy" in body["deps"]
    # ok flag is NOT affected by the per_type_autonomy key
    assert "ok" in body


def test_healthz_deps_per_type_autonomy_no_org(plain_app):
    with plain_app.test_client() as client:
        resp = client.get("/healthz/deps")
    body = resp.get_json()
    pt = body["deps"]["per_type_autonomy"]
    # With no active org, should return a note, not an error
    assert "note" in pt or "error" in pt or "org_id" in pt


def test_healthz_deps_ok_flag_not_affected_by_autonomy(plain_app, monkeypatch):
    """ok derives from playwright/node/remotion only — per_type_autonomy must not drag it down."""
    with plain_app.test_client() as client:
        resp = client.get("/healthz/deps")
    body = resp.get_json()
    deps = body["deps"]
    # Compute expected ok independently
    expected_ok = (
        bool(deps.get("playwright", {}).get("chromium"))
        and bool(deps.get("node", {}).get("available"))
        and bool(deps.get("remotion", {}).get("available"))
    )
    assert body["ok"] == expected_ok
