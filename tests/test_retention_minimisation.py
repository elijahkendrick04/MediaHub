"""Retention purge + payload minimisation (compliance/retention-and-minimisation).

Pins: per-class retention windows (env default, tenant tightening-only
override), the purge cascade for aged runs/uploads/caches, security-log
ageing, and the data-minimisation boundary on LLM payloads and
notifications.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    return tmp_path


def _old_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _seed_run(data_dir: Path, run_id: str, *, age_days: int, profile_id="clubx"):
    runs = data_dir / "runs_v4"
    runs.mkdir(parents=True, exist_ok=True)
    run = {
        "run_id": run_id,
        "profile_id": profile_id,
        "finished_at": _old_iso(age_days),
        "cards": [],
        "recognition_report": {"ranked_achievements": []},
    }
    (runs / f"{run_id}.json").write_text(json.dumps(run))
    sidecar = runs / run_id / "visuals"
    sidecar.mkdir(parents=True)
    (sidecar / "card.png").write_bytes(b"png")
    (runs / f"{run_id}__workflow.json").write_text("{}")
    uploads = data_dir / "uploads_v4" / run_id
    uploads.mkdir(parents=True)
    f = uploads / "results.pdf"
    f.write_bytes(b"%PDF")
    old = time.time() - age_days * 86400
    os.utime(f, (old, old))
    os.utime(uploads, (old, old))
    return run_id


# ------------------------------------------------------------- windows


def test_global_days_env_override(monkeypatch):
    from mediahub.compliance.retention import global_days

    assert global_days("raw_uploads") == 180
    monkeypatch.setenv("MEDIAHUB_RETENTION_RAW_UPLOAD_DAYS", "30")
    assert global_days("raw_uploads") == 30
    monkeypatch.setenv("MEDIAHUB_RETENTION_RAW_UPLOAD_DAYS", "0")
    assert global_days("raw_uploads") == 0  # explicit keep-forever


def test_tenant_override_can_tighten_not_extend(data_dir):
    from mediahub.compliance.retention import effective_days
    from mediahub.web.club_profile import ClubProfile, save_profile

    profile = ClubProfile(profile_id="clubx", display_name="X")
    profile.retention_overrides = {"runs": 30}
    save_profile(profile)
    assert effective_days("runs", "clubx") == 30  # tighter wins

    profile.retention_overrides = {"runs": 99999}
    save_profile(profile)
    assert effective_days("runs", "clubx") == 730  # cannot extend past ceiling


# --------------------------------------------------------------- purge


def test_purge_deletes_aged_runs_and_keeps_fresh(data_dir):
    from mediahub.compliance.retention import run_purge

    _seed_run(data_dir, "old-run", age_days=800)
    _seed_run(data_dir, "new-run", age_days=5)

    report = run_purge()
    assert report["runs_deleted"] == ["old-run"]
    runs = data_dir / "runs_v4"
    assert not (runs / "old-run.json").exists()
    assert not (runs / "old-run").exists()
    assert not (runs / "old-run__workflow.json").exists()
    assert not (data_dir / "uploads_v4" / "old-run").exists()
    assert (runs / "new-run.json").exists()
    assert (data_dir / "uploads_v4" / "new-run").exists()


def test_purge_respects_tenant_tightened_window(data_dir):
    from mediahub.compliance.retention import run_purge
    from mediahub.web.club_profile import ClubProfile, save_profile

    profile = ClubProfile(profile_id="strict-club", display_name="S")
    profile.retention_overrides = {"runs": 10}
    save_profile(profile)
    _seed_run(data_dir, "strict-run", age_days=20, profile_id="strict-club")
    _seed_run(data_dir, "lax-run", age_days=20, profile_id="other-club")

    report = run_purge()
    assert "strict-run" in report["runs_deleted"]
    assert "lax-run" not in report["runs_deleted"]


def test_purge_raw_uploads_earlier_than_runs(data_dir):
    from mediahub.compliance.retention import run_purge

    _seed_run(data_dir, "mid-run", age_days=300)  # > 180 (uploads), < 730 (runs)
    report = run_purge()
    assert report["runs_deleted"] == []
    assert report["upload_dirs_deleted"] == ["mid-run"]
    assert (data_dir / "runs_v4" / "mid-run.json").exists()
    assert not (data_dir / "uploads_v4" / "mid-run").exists()


def test_purge_ages_out_loose_upload_files(data_dir):
    """Loose files written straight into uploads_v4 (legacy transient path)
    have no run dir or tenant hint — they age on the global raw-uploads
    window. Ported from the retired privacy.retention sweep."""
    from mediahub.compliance.retention import run_purge

    uploads = data_dir / "uploads_v4"
    uploads.mkdir(parents=True, exist_ok=True)
    stale = uploads / "stale.hy3"
    stale.write_bytes(b"x")
    old = time.time() - 300 * 86400  # > 180-day raw_uploads default
    os.utime(stale, (old, old))
    fresh = uploads / "fresh.hy3"
    fresh.write_bytes(b"x")

    report = run_purge()
    assert report["upload_files_deleted"] == 1
    assert not stale.exists()
    assert fresh.exists()


def test_purge_pb_caches_and_security_log(data_dir):
    from mediahub.compliance.retention import run_purge
    from mediahub.compliance.security_log import record_event, read_events

    cache = data_dir / "data" / "discovered" / "swimmers"
    cache.mkdir(parents=True)
    old_file = cache / "old.json"
    old_file.write_text("{}")
    stale = time.time() - 60 * 86400
    os.utime(old_file, (stale, stale))
    fresh_file = cache / "fresh.json"
    fresh_file.write_text("{}")

    record_event("login", actor="x@y.z")
    log_path = data_dir / "security_log" / "events.jsonl"
    aged = dict(json.loads(log_path.read_text().splitlines()[0]))
    aged["ts"] = _old_iso(400)
    log_path.write_text(json.dumps(aged) + "\n" + log_path.read_text())

    report = run_purge()
    assert not old_file.exists()
    assert fresh_file.exists()
    assert report["pb_cache_files_deleted"] == 1
    assert report["security_log_lines_dropped"] == 1
    # the purge itself is recorded
    assert any(e["event"] == "retention_purge" for e in read_events())


def test_zero_days_disables_purging(data_dir, monkeypatch):
    from mediahub.compliance.retention import run_purge

    monkeypatch.setenv("MEDIAHUB_RETENTION_RUN_DAYS", "0")
    monkeypatch.setenv("MEDIAHUB_RETENTION_RAW_UPLOAD_DAYS", "0")
    _seed_run(data_dir, "ancient", age_days=5000)
    report = run_purge()
    assert report["runs_deleted"] == []
    assert report["upload_dirs_deleted"] == []


def test_accountability_ledgers_never_purged(data_dir):
    """Complaints/incidents/DSR/consent ledgers are accountability records."""
    from mediahub.compliance.complaints import ComplaintsStore
    from mediahub.compliance.retention import run_purge

    ComplaintsStore().submit(name="A", contact="a@b.c", details="old complaint")
    ledger = data_dir / "compliance" / "complaints.jsonl"
    stale = time.time() - 5000 * 86400
    os.utime(ledger, (stale, stale))
    run_purge()
    assert ledger.exists()
    assert "old complaint" in ledger.read_text()


# ---------------------------------------------------------- minimisation


def test_llm_payload_strips_identifiers_and_dob_fields():
    from mediahub.web.ai_caption import _sanitise_achievement_for_prompt

    ach = {
        "swimmer_name": "Eira Hughes",
        "event": "100 Free (SC)",
        "time": "57.10",
        "age": 14,
        "asa_id": "123456",
        "dob": "2012-03-01",
        "year_of_birth": 2012,
        "raw_facts": {"time": "57.10", "dob": "2012-03-01", "asa_id": "123456", "place": 1},
    }
    out = _sanitise_achievement_for_prompt(ach)
    dumped = json.dumps(out).lower()
    assert "asa_id" not in dumped
    assert "dob" not in dumped and "year_of_birth" not in dumped
    assert "2012" not in dumped  # no DOB-level data leaves the platform
    # what the caption legitimately needs survives
    assert out["swimmer_name"] == "Eira Hughes"
    assert out["age"] == 14
    assert out["raw_facts"]["place"] == 1
    # original dict untouched
    assert "asa_id" in ach and "dob" in ach["raw_facts"]


def test_notify_payload_carries_no_athlete_names():
    """DATA_MAP flow F7 rule: notification payloads carry run ids and counts,
    never athlete personal data."""
    import inspect

    from mediahub import notify as notify_pkg

    src = inspect.getsource(notify_pkg.notify_pack_ready)
    assert "swimmer" not in src and "athlete" not in src
    # the message is built only from run_id + count
    assert "run_id" in src


def test_security_log_alert_hook_carries_no_subject(data_dir, monkeypatch):
    sent = {}

    def fake_notify(title, message, **kw):
        sent["title"] = title
        sent["message"] = message
        return 1

    import mediahub.notify

    monkeypatch.setattr(mediahub.notify, "notify", fake_notify)
    from mediahub.compliance.security_log import record_event

    record_event("dsr_erasure", subject="Eira Hughes", profile_id="clubx", actor="coach@x.y")
    assert sent, "alert hook should fire for erasure events"
    blob = (sent["title"] + sent["message"]).lower()
    assert "eira" not in blob and "coach@x.y" not in blob


# ------------------------------------------------------------- UI wiring


def test_retention_settings_route(data_dir):
    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.web import create_app

    save_profile(ClubProfile(profile_id="clubx", display_name="X"))
    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["active_profile_id"] = "clubx"

    r = client.post(
        "/organisation/consent/retention", data={"raw_uploads": "90", "runs": "365"}
    )
    assert r.status_code == 302
    from mediahub.web.club_profile import load_profile

    profile = load_profile("clubx")
    assert profile.retention_overrides == {"raw_uploads": 90, "runs": 365}

    # blank clears the override
    r = client.post("/organisation/consent/retention", data={"raw_uploads": "", "runs": "365"})
    assert r.status_code == 302
    assert load_profile("clubx").retention_overrides == {"runs": 365}


def test_retention_task_scheduled_at_boot(data_dir):
    from mediahub.web.web import create_app

    create_app()
    from mediahub.workflow.schedule import list_tasks

    tasks = [t for t in list_tasks() if t.task_type == "retention_purge"]
    assert len(tasks) == 1
    assert tasks[0].schedule_kind == "daily"
