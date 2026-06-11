"""Unit tests for the PC.6 warm-first pipeline ledger (`mediahub.commercial.pipeline`)
and the NGB application state (`mediahub.commercial.ngb`)."""

from __future__ import annotations

import pytest

from mediahub.commercial.pipeline import (
    SOURCE_COLD,
    SOURCE_REFERRAL,
    SOURCE_WARM_LOCAL,
    STATUS_WON,
    LeadStore,
    PipelineError,
    funnel_summary,
    referral_debt,
    warm_first_discipline,
)


@pytest.fixture
def store(tmp_path):
    return LeadStore(path=tmp_path / "pipeline.jsonl")


def test_create_and_update_lead(store):
    lead = store.create("Swansea SC", source=SOURCE_WARM_LOCAL, region="Swansea")
    assert lead.status == "lead"
    up = store.set_status(lead.lead_id, "contacted")
    assert up.status == "contacted"
    assert store.get(lead.lead_id).status == "contacted"


def test_referral_lead_requires_referrer(store):
    with pytest.raises(PipelineError):
        store.create("Neath SC", source=SOURCE_REFERRAL)
    lead = store.create("Neath SC", source=SOURCE_REFERRAL, referrer_club="Swansea SC")
    assert lead.referrer_club == "Swansea SC"


def test_create_rejects_bad_input(store):
    with pytest.raises(PipelineError):
        store.create("", source=SOURCE_WARM_LOCAL)
    with pytest.raises(PipelineError):
        store.create("Club", source="billboard")
    with pytest.raises(PipelineError):
        store.set_status("nope", "won")


def test_funnel_summary_counts(store):
    store.create("A", source=SOURCE_WARM_LOCAL)
    store.create("B", source=SOURCE_COLD)
    lead = store.create("C", source=SOURCE_REFERRAL, referrer_club="A")
    store.set_status(lead.lead_id, STATUS_WON)
    s = funnel_summary(store.list_all())
    assert s["total"] == 3
    assert s["by_source"][SOURCE_WARM_LOCAL] == 1
    assert s["by_source"][SOURCE_COLD] == 1
    assert s["by_status"][STATUS_WON] == 1
    assert s["by_status"]["lead"] == 2


def test_warm_first_discipline_warns_when_cold_dominates(store):
    for i in range(4):
        store.create(f"Cold {i}", source=SOURCE_COLD)
    store.create("Warm 1", source=SOURCE_WARM_LOCAL)
    d = warm_first_discipline(store.list_all())
    assert d["total"] == 5 and d["cold"] == 4
    assert d["cold_share"] == 0.8
    assert d["warn"] is True


def test_warm_first_discipline_quiet_when_warm_led(store):
    for i in range(4):
        store.create(f"Warm {i}", source=SOURCE_WARM_LOCAL)
    store.create("Cold 1", source=SOURCE_COLD)
    d = warm_first_discipline(store.list_all())
    assert d["cold_share"] == 0.2
    assert d["warn"] is False


def test_warm_first_discipline_needs_volume_before_warning(store):
    store.create("Cold 1", source=SOURCE_COLD)  # 100% cold but only 1 lead
    assert warm_first_discipline(store.list_all())["warn"] is False


def test_referral_debt_lists_won_clubs_missing_intros(store):
    a = store.create("Club A", source=SOURCE_WARM_LOCAL)
    store.set_status(a.lead_id, STATUS_WON)
    b = store.create("Club B", source=SOURCE_WARM_LOCAL)
    store.set_status(b.lead_id, STATUS_WON)
    store.set_intros(b.lead_id, ["Neath SC", "Cardiff SC"])
    c = store.create("Club C", source=SOURCE_COLD)  # not won — no debt

    debt = referral_debt(store.list_all())
    assert [d["club_name"] for d in debt] == ["Club A"]
    assert debt[0]["intros_missing"] == 2

    store.set_intros(a.lead_id, ["Bridgend SC"])
    debt = referral_debt(store.list_all())
    assert debt[0]["intros_recorded"] == 1 and debt[0]["intros_missing"] == 1


def test_ledger_is_owner_readable_only(store):
    store.create("A", source=SOURCE_WARM_LOCAL)
    assert (store.path.stat().st_mode & 0o777) == 0o600


# ---- NGB application state ------------------------------------------------


def test_ngb_state_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.commercial import ngb

    s = ngb.load_state()
    assert s["status"] == "not_applied" and s["applied_at"] == ""

    s = ngb.save_state("applied", notes="Sent via the Swim England form.")
    assert s["status"] == "applied"
    assert s["applied_at"] != ""
    applied_at = s["applied_at"]

    s = ngb.save_state("approved")
    assert s["status"] == "approved"
    assert s["applied_at"] == applied_at  # first-applied stamp is preserved

    assert ngb.load_state()["status"] == "approved"
    with pytest.raises(ValueError):
        ngb.save_state("maybe")
