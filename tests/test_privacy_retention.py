"""UK legal baseline — retention enforcement (Privacy Notice §8).

MEDIAHUB_RETENTION_DAYS drives a daily sweep that deletes expired runs
THROUGH the run-deletion path (so the erasure cascade applies) plus stale
upload files. Unset/0 = disabled, matching the documented default.
"""

from __future__ import annotations

import json
import os
import time

import pytest


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def _age(path, days):
    old = time.time() - days * 86400
    os.utime(path, (old, old))


def _seed(data_dir):
    runs = data_dir / "runs_v4"
    runs.mkdir(parents=True, exist_ok=True)
    uploads = data_dir / "uploads_v4"
    uploads.mkdir(parents=True, exist_ok=True)
    old_run = runs / "old-run.json"
    old_run.write_text(json.dumps({"run_id": "old-run", "profile_id": "sharks"}))
    _age(old_run, 40)
    fresh_run = runs / "fresh-run.json"
    fresh_run.write_text(json.dumps({"run_id": "fresh-run", "profile_id": "sharks"}))
    sidecar = runs / "old-run__workflow.json"
    sidecar.write_text("{}")
    _age(sidecar, 40)
    old_upload = uploads / "stale.bin"
    old_upload.write_bytes(b"x")
    _age(old_upload, 40)
    fresh_upload = uploads / "fresh.bin"
    fresh_upload.write_bytes(b"x")
    return old_run, fresh_run, old_upload, fresh_upload


def test_sweep_disabled_by_default(data_dir, monkeypatch):
    monkeypatch.delenv("MEDIAHUB_RETENTION_DAYS", raising=False)
    old_run, *_ = _seed(data_dir)
    from mediahub.privacy.retention import sweep_expired

    deleted = []
    report = sweep_expired(lambda rid: deleted.append(rid) or True)
    assert report["enabled"] is False
    assert deleted == []
    assert old_run.exists()


def test_sweep_deletes_only_expired(data_dir, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RETENTION_DAYS", "30")
    old_run, fresh_run, old_upload, fresh_upload = _seed(data_dir)
    from mediahub.privacy.retention import sweep_expired

    deleted = []
    report = sweep_expired(lambda rid: deleted.append(rid) or True)
    # Only the 40-day-old run goes, via the delete_run callable (cascade
    # path); the workflow sidecar is never treated as its own run.
    assert deleted == ["old-run"]
    assert report["runs_deleted"] == 1
    assert fresh_run.exists()
    assert not old_upload.exists()
    assert fresh_upload.exists()
    assert report["uploads_deleted"] == 1


def test_sweep_tolerates_failing_delete(data_dir, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RETENTION_DAYS", "30")
    _seed(data_dir)

    def boom(rid):
        raise RuntimeError("db locked")

    from mediahub.privacy.retention import sweep_expired

    report = sweep_expired(boom)  # must not raise
    assert report["runs_deleted"] == 0


def test_retention_days_parsing(monkeypatch):
    from mediahub.privacy.retention import retention_days

    monkeypatch.delenv("MEDIAHUB_RETENTION_DAYS", raising=False)
    assert retention_days() == 0
    monkeypatch.setenv("MEDIAHUB_RETENTION_DAYS", "90")
    assert retention_days() == 90
    monkeypatch.setenv("MEDIAHUB_RETENTION_DAYS", "-5")
    assert retention_days() == 0
    monkeypatch.setenv("MEDIAHUB_RETENTION_DAYS", "junk")
    assert retention_days() == 0


def test_privacy_page_states_retention(data_dir, monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.setenv("MEDIAHUB_RETENTION_DAYS", "60")
    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    client = app.test_client()
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="sharks", display_name="Sharks"))
    with client.session_transaction() as sess:
        sess["active_profile_id"] = "sharks"
        sess["login_seen_at"] = 2**62
    html = client.get("/privacy").get_data(as_text=True)
    assert "older than 60 days are deleted daily" in html
