"""bulk.generate — review-queued bulk generation (roadmap 1.13)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mediahub import bulk
from mediahub.bulk import store as bstore
from mediahub.bulk.generate import GenOutput, resolve_cards
from mediahub.bulk.models import ITEM_FAILED, ITEM_QUEUED, ITEM_SKIPPED
from mediahub.workflow.status import CardStatus
from mediahub.workflow.store import WorkflowStore


def _ach(swim_id, name, angle, atype):
    return {
        "achievement": {
            "swim_id": swim_id,
            "swimmer_id": "sw-" + swim_id,
            "swimmer_name": name,
            "event": "100m Freestyle",
            "headline": "Great swim",
            "type": atype,
            "raw_facts": {"time_str": "1:05.32"},
        },
        "post_angle": angle,
        "rank": 1,
        "quality_band": "strong",
    }


@pytest.fixture()
def run_env(tmp_path):
    runs = tmp_path / "runs_v4"
    runs.mkdir()
    run = {
        "run_id": "r1",
        "profile_id": "club-a",
        "meet": {"name": "Spring Open", "start_date": "2026-03-14"},
        "recognition_report": {
            "ranked_achievements": [
                _ach("s1", "Maya", "confirmed_official_pb", "pb_confirmed"),
                _ach("s2", "Sam", "medal_gold", "medal_gold"),
                _ach("s3", "Lee", "pb_improvement", "pb_confirmed"),
            ]
        },
    }
    (runs / "r1.json").write_text(json.dumps(run))
    return tmp_path, runs


def _ok_gen(ctx):
    return GenOutput(True, path=f"/tmp/cert-{ctx.card_id}.pdf")


def test_resolve_pb_only_selects_pb_cards(run_env):
    _, runs = run_env
    run = json.loads((runs / "r1.json").read_text())
    cards = resolve_cards(run, {"pb_only": True})
    names = sorted(c["achievement"]["swimmer_name"] for c in cards)
    assert names == ["Lee", "Maya"]  # the medal-only card is excluded


def test_resolve_all_when_no_query(run_env):
    _, runs = run_env
    run = json.loads((runs / "r1.json").read_text())
    assert len(resolve_cards(run, None)) == 3


def test_bulk_queues_every_card_for_review(run_env):
    tmp, runs = run_env
    job = bulk.bulk_generate(
        "club-a",
        "r1",
        "certificate",
        row_query={"pb_only": True},
        runs_dir=runs,
        jobs_dir=tmp / "bj",
        generator=_ok_gen,
    )
    assert job.n_total == 2
    assert job.n_queued == 2
    assert job.n_failed == 0
    assert job.pct == 100
    assert all(i.status == ITEM_QUEUED and i.output_path for i in job.items)

    # The review queue now holds those cards — as QUEUE, never approved.
    states = WorkflowStore(runs).load("r1")
    assert set(states) == {"s1", "s3"}
    assert all(s.status == CardStatus.QUEUE for s in states.values())


def test_bulk_never_clobbers_a_human_decision(run_env):
    tmp, runs = run_env
    ws = WorkflowStore(runs)
    ws.set_status("r1", "s1", CardStatus.APPROVED)
    job = bulk.bulk_generate(
        "club-a",
        "r1",
        "certificate",
        row_query={"pb_only": True},
        runs_dir=runs,
        jobs_dir=tmp / "bj",
        generator=_ok_gen,
    )
    # s1 is skipped (already decided); s3 queued. Approval survives.
    assert job.n_skipped == 1
    assert job.n_queued == 1
    assert ws.load("r1")["s1"].status == CardStatus.APPROVED
    skipped = [i for i in job.items if i.status == ITEM_SKIPPED][0]
    assert skipped.card_id == "s1"


def test_bulk_records_honest_render_failure(run_env):
    tmp, runs = run_env

    def bad_gen(ctx):
        return GenOutput(False, error="renderer unavailable")

    job = bulk.bulk_generate(
        "club-a",
        "r1",
        "certificate",
        row_query={"pb_only": True},
        runs_dir=runs,
        jobs_dir=tmp / "bj",
        generator=bad_gen,
    )
    assert job.n_failed == 2
    assert all("unavailable" in i.error for i in job.items)
    # The cards were still queued for review even though the artifact failed.
    assert set(WorkflowStore(runs).load("r1")) == {"s1", "s3"}


def test_cap_limits_a_job(run_env):
    tmp, runs = run_env
    job = bulk.bulk_generate(
        "club-a",
        "r1",
        "certificate",
        runs_dir=runs,
        jobs_dir=tmp / "bj",
        generator=_ok_gen,
        cap=1,
    )
    assert job.n_total == 1


def test_render_off_just_queues(run_env):
    tmp, runs = run_env
    job = bulk.bulk_generate(
        "club-a",
        "r1",
        "certificate",
        row_query={"pb_only": True},
        runs_dir=runs,
        jobs_dir=tmp / "bj",
        render=False,
    )
    assert job.n_queued == 2
    assert all(not i.output_path for i in job.items)


def test_job_persisted_and_tenant_scoped(run_env):
    tmp, runs = run_env
    jobs_dir = tmp / "bj"
    job = bulk.bulk_generate(
        "club-a",
        "r1",
        "certificate",
        row_query={"pb_only": True},
        runs_dir=runs,
        jobs_dir=jobs_dir,
        generator=_ok_gen,
    )
    # Reload as the owner.
    loaded = bstore.load_job("club-a", job.job_id, jobs_dir=jobs_dir)
    assert loaded is not None and loaded.n_queued == 2
    # Another org cannot load it, and it isn't in their list.
    assert bstore.load_job("club-b", job.job_id, jobs_dir=jobs_dir) is None
    assert bstore.list_jobs("club-b", jobs_dir=jobs_dir) == []
    assert len(bstore.list_jobs("club-a", jobs_dir=jobs_dir)) == 1


def test_plan_rejects_cross_tenant_run(run_env):
    _, runs = run_env
    with pytest.raises(PermissionError):
        bulk.plan_bulk("club-b", "r1", "certificate", runs_dir=runs)


def test_plan_missing_run_raises(run_env):
    _, runs = run_env
    with pytest.raises(ValueError):
        bulk.plan_bulk("club-a", "nope", "certificate", runs_dir=runs)


def test_real_certificate_render_contract(tmp_path, monkeypatch):
    """The shipped certificate generator (render=True, no fake) honours the
    contract: the card is queued for review, and either a real PDF is produced
    or the item fails with an honest reason — never a crash, never a fake file."""
    pytest.importorskip("playwright")
    pytest.importorskip("mediahub.graphic_renderer.print_export")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "profiles"))
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    runs = tmp_path / "runs_v4"
    runs.mkdir()

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Aqua Club"))
    run = {
        "run_id": "r1",
        "profile_id": "club-a",
        "meet": {"name": "Spring Open", "start_date": "2026-03-14"},
        "recognition_report": {
            "ranked_achievements": [
                _ach("s1", "Maya Patel", "confirmed_official_pb", "pb_confirmed")
            ]
        },
    }
    (runs / "r1.json").write_text(json.dumps(run))

    job = bulk.bulk_generate(
        "club-a",
        "r1",
        "certificate",
        row_query={"pb_only": True},
        runs_dir=runs,
        jobs_dir=tmp_path / "bj",
        render=True,
    )
    # Card queued for review regardless of the artifact outcome.
    assert "s1" in WorkflowStore(runs).load("r1")
    item = job.items[0]
    assert item.status in (ITEM_QUEUED, ITEM_FAILED)
    if item.output_path:
        pdf = Path(item.output_path)
        assert pdf.exists()
        assert pdf.read_bytes()[:5] == b"%PDF-"  # a real PDF, not a stub
    else:
        assert item.error  # honest reason when a renderer/dep is missing
