"""P6.3 — per-org quota ledger + enforcement.

Mirrors the llm_usage test pattern: set DATA_DIR → reload the ledger module so
it points at a fresh tmp DB.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import mediahub.observability.imagine_usage as iu

    importlib.reload(iu)
    return iu


def test_record_and_count(ledger):
    assert ledger.count_for_org("club-a") == 0
    rid = ledger.record_use(org_id="club-a", op="generate", ok=True, provider="gemini")
    assert rid > 0
    assert ledger.count_for_org("club-a") == 1
    # A different org is isolated.
    assert ledger.count_for_org("club-b") == 0


def test_failed_calls_not_counted_by_default(ledger):
    ledger.record_use(org_id="club-a", op="generate", ok=False, provider="gemini")
    assert ledger.count_for_org("club-a") == 0  # ok_only default
    assert ledger.count_for_org("club-a", ok_only=False) == 1


def test_blank_org_or_op_records_nothing(ledger):
    assert ledger.record_use(org_id="", op="generate", ok=True) == 0
    assert ledger.record_use(org_id="club-a", op="", ok=True) == 0


def test_usage_breakdown_by_op(ledger):
    for op in ("generate", "generate", "remove"):
        ledger.record_use(org_id="club-a", op=op, ok=True)
    usage = ledger.usage_for_org("club-a")
    assert usage["total"] == 3
    assert usage["by_op"]["generate"] == 2
    assert usage["by_op"]["remove"] == 1


def test_window_excludes_old_rows(ledger):
    old = "2000-01-01T00:00:00+00:00"
    ledger.record_use(org_id="club-a", op="generate", ok=True, ts=old)
    assert ledger.count_for_org("club-a", window_hours=24) == 0


# --- facade quota policy ----------------------------------------------------


@pytest.fixture
def imagine_with_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MEDIAHUB_IMAGINE_QUOTA_MONTHLY", raising=False)
    import mediahub.observability.imagine_usage as iu

    importlib.reload(iu)
    import mediahub.media_ai.imagine as im

    return im, iu


def test_check_quota_default_limit(imagine_with_ledger):
    im, iu = imagine_with_ledger
    assert im.monthly_quota() == im.DEFAULT_MONTHLY_QUOTA
    st = im.check_quota("club-a")
    assert st.ok is True
    assert st.limit == im.DEFAULT_MONTHLY_QUOTA
    assert st.used == 0
    assert st.remaining == im.DEFAULT_MONTHLY_QUOTA


def test_check_quota_env_override(imagine_with_ledger, monkeypatch):
    im, iu = imagine_with_ledger
    monkeypatch.setenv("MEDIAHUB_IMAGINE_QUOTA_MONTHLY", "2")
    assert im.monthly_quota() == 2
    iu.record_use(org_id="club-a", op="generate", ok=True)
    iu.record_use(org_id="club-a", op="generate", ok=True)
    st = im.check_quota("club-a")
    assert st.used == 2
    assert st.ok is False
    assert st.remaining == 0


def test_unlimited_quota(imagine_with_ledger, monkeypatch):
    im, iu = imagine_with_ledger
    monkeypatch.setenv("MEDIAHUB_IMAGINE_QUOTA_MONTHLY", "-1")
    st = im.check_quota("club-a")
    assert st.unlimited is True
    assert st.ok is True


def test_enforce_quota_raises_when_over(imagine_with_ledger, monkeypatch):
    im, iu = imagine_with_ledger
    monkeypatch.setenv("MEDIAHUB_IMAGINE_QUOTA_MONTHLY", "1")
    iu.record_use(org_id="club-a", op="generate", ok=True)
    with pytest.raises(im.QuotaExceeded):
        im._enforce_quota("club-a", "generate")


def test_generate_records_usage_and_enforces(imagine_with_ledger, monkeypatch):
    im, iu = imagine_with_ledger
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("MEDIAHUB_IMAGINE_QUOTA_MONTHLY", "1")
    import io

    from PIL import Image
    import mediahub.media_ai.imagine_providers.gemini_imagine as g

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (0, 0, 0)).save(buf, format="PNG")
    monkeypatch.setattr(g, "imagen_predict", lambda *a, **k: [buf.getvalue()])

    # First call succeeds and is metered.
    im.generate("a backdrop", org_id="club-a")
    assert iu.count_for_org("club-a") == 1
    # Second call is over the limit of 1 → honest QuotaExceeded, not metered.
    with pytest.raises(im.QuotaExceeded):
        im.generate("another", org_id="club-a")
    assert iu.count_for_org("club-a") == 1
