"""Tests for the governance quota policy layer (1.23).

Policy reads counts from the default-DATA_DIR ledger, so these set DATA_DIR to a
tmp dir; the ledger reads the path lazily, so no module reload is needed for the
shared feature ledger. The dedicated imagine ledger binds its path at import, so
the one imagery test reloads it.
"""

from __future__ import annotations

import importlib

import pytest

from mediahub.governance import features, quota


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Built-in plan table ships empty; pin it so a stray future default can't
    # make these tests flaky.
    monkeypatch.setattr(quota, "_PLAN_FEATURE_LIMITS", {})
    # Clear any quota env that might leak in from the environment.
    for plan in quota.KNOWN_PLANS:
        monkeypatch.delenv(f"MEDIAHUB_QUOTA_CAPTION_{plan.upper()}", raising=False)
    monkeypatch.delenv("MEDIAHUB_QUOTA_CAPTION", raising=False)
    import mediahub.observability.feature_quota as fq

    return quota, fq


# ---- limit_for ------------------------------------------------------------


def test_limit_unlimited_by_default(fresh):
    q, _ = fresh
    assert q.limit_for("free", features.FEATURE_CAPTION) == q.UNLIMITED


def test_limit_env_feature_plan(fresh, monkeypatch):
    q, _ = fresh
    monkeypatch.setenv("MEDIAHUB_QUOTA_CAPTION_FREE", "50")
    assert q.limit_for("free", "caption") == 50
    # other plans unaffected
    assert q.limit_for("club", "caption") == q.UNLIMITED


def test_limit_env_feature_wide(fresh, monkeypatch):
    q, _ = fresh
    monkeypatch.setenv("MEDIAHUB_QUOTA_CAPTION", "100")
    assert q.limit_for("free", "caption") == 100
    assert q.limit_for("club", "caption") == 100


def test_limit_env_plan_specific_beats_wide(fresh, monkeypatch):
    q, _ = fresh
    monkeypatch.setenv("MEDIAHUB_QUOTA_CAPTION", "100")
    monkeypatch.setenv("MEDIAHUB_QUOTA_CAPTION_FREE", "10")
    assert q.limit_for("free", "caption") == 10
    assert q.limit_for("club", "caption") == 100


def test_limit_org_override_wins(fresh, monkeypatch):
    q, _ = fresh
    monkeypatch.setenv("MEDIAHUB_QUOTA_CAPTION", "100")
    assert q.limit_for("free", "caption", org_override=7) == 7
    assert q.limit_for("free", "caption", org_override=-1) == -1  # explicit unlimited


def test_limit_builtin_plan_table(fresh, monkeypatch):
    q, _ = fresh
    monkeypatch.setattr(q, "_PLAN_FEATURE_LIMITS", {"free": {"caption": 25}})
    assert q.limit_for("free", "caption") == 25
    assert q.limit_for("club", "caption") == q.UNLIMITED


# ---- check ----------------------------------------------------------------


def test_check_unmetered_counts_but_never_blocks(fresh):
    q, fq = fresh
    fq.record_use(org_id="club-a", feature="caption", ok=True)
    fq.record_use(org_id="club-a", feature="caption", ok=True)
    st = q.check("club-a", "caption", plan="free")
    assert st.enforced is False
    assert st.ok is True
    assert st.used == 2
    assert st.limit == q.UNLIMITED
    assert st.remaining == q.UNLIMITED
    assert st.warn is False


def test_check_metered_under_limit(fresh, monkeypatch):
    q, fq = fresh
    monkeypatch.setenv("MEDIAHUB_QUOTA_CAPTION", "10")
    fq.record_use(org_id="club-a", feature="caption", ok=True)
    st = q.check("club-a", "caption", plan="free")
    assert st.enforced is True
    assert st.ok is True
    assert st.used == 1
    assert st.limit == 10
    assert st.remaining == 9
    assert st.warn is False


def test_check_warns_near_limit(fresh, monkeypatch):
    q, fq = fresh
    monkeypatch.setenv("MEDIAHUB_QUOTA_CAPTION", "10")
    for _ in range(8):  # 8/10 == 80% == WARN_FRACTION
        fq.record_use(org_id="club-a", feature="caption", ok=True)
    st = q.check("club-a", "caption", plan="free")
    assert st.ok is True
    assert st.warn is True


def test_check_over_limit_not_ok(fresh, monkeypatch):
    q, fq = fresh
    monkeypatch.setenv("MEDIAHUB_QUOTA_CAPTION", "2")
    for _ in range(2):
        fq.record_use(org_id="club-a", feature="caption", ok=True)
    st = q.check("club-a", "caption", plan="free")
    assert st.ok is False
    assert st.remaining == 0


# ---- enforce --------------------------------------------------------------


def test_enforce_noop_when_unlimited(fresh):
    q, fq = fresh
    for _ in range(100):
        fq.record_use(org_id="club-a", feature="caption", ok=True)
    # No limit configured → never raises, however high usage climbs.
    q.enforce("club-a", "caption", plan="free")


def test_enforce_noop_under_limit(fresh, monkeypatch):
    q, fq = fresh
    monkeypatch.setenv("MEDIAHUB_QUOTA_CAPTION", "5")
    fq.record_use(org_id="club-a", feature="caption", ok=True)
    q.enforce("club-a", "caption", plan="free")  # 1/5 — fine


def test_enforce_raises_when_at_limit(fresh, monkeypatch):
    q, fq = fresh
    monkeypatch.setenv("MEDIAHUB_QUOTA_CAPTION", "2")
    for _ in range(2):
        fq.record_use(org_id="club-a", feature="caption", ok=True)
    with pytest.raises(q.QuotaExceeded) as ei:
        q.enforce("club-a", "caption", plan="free")
    err = ei.value
    assert err.feature == "caption"
    assert err.used == 2
    assert err.limit == 2
    assert "quota reached" in str(err).lower()


def test_enforce_noop_without_org(fresh, monkeypatch):
    q, _ = fresh
    monkeypatch.setenv("MEDIAHUB_QUOTA_CAPTION", "0")
    # Even a zero limit can't block an unattributed (no-org) call.
    q.enforce("", "caption", plan="free")


# ---- record ---------------------------------------------------------------


def test_record_writes_a_row(fresh):
    q, fq = fresh
    q.record("club-a", "caption", ok=True, provider="gemini", model="x")
    assert fq.count_for_org("club-a", feature="caption") == 1


def test_record_skips_imagine_feature(fresh):
    q, fq = fresh
    # Imagery is metered in its own ledger; the shared ledger must stay empty.
    q.record("club-a", features.FEATURE_IMAGINE, ok=True)
    assert fq.count_for_org("club-a", ok_only=False) == 0


def test_imagine_quota_reads_imagine_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import mediahub.observability.imagine_usage as iu

    importlib.reload(iu)
    iu.record_use(org_id="club-a", op="generate", ok=True)
    iu.record_use(org_id="club-a", op="edit", ok=True)
    st = quota.check("club-a", features.FEATURE_IMAGINE, plan="free")
    assert st.used == 2  # sourced from the imagine ledger, not feature_quota
