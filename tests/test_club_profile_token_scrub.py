"""At-rest scrub of withdrawn Buffer/scheduler tokens from persisted JSON.

``ClubProfile.from_dict`` ignores ``scheduler_access_token`` /
``buffer_access_token`` and ``to_dict`` never writes them, but profiles
saved before the feature was withdrawn still carry the third-party
secrets on disk. Loading a profile must proactively rewrite the file
without them — atomically, and fail-soft on a read-only filesystem.
"""

from __future__ import annotations

import json

import pytest

import mediahub.web.club_profile as cp


def _write_legacy_profile(profiles_dir, profile_id="legacy-club"):
    profiles_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "profile_id": profile_id,
        "display_name": "Legacy Club",
        "scheduler_access_token": "tok-sched-123",
        "buffer_access_token": "tok-buf-456",
    }
    path = profiles_dir / f"{profile_id}.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


@pytest.fixture()
def profiles_dir(tmp_path, monkeypatch):
    d = tmp_path / "club_profiles"
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(d))
    return d


def test_load_profile_scrubs_tokens_from_disk(profiles_dir):
    path = _write_legacy_profile(profiles_dir)

    prof = cp.load_profile("legacy-club")
    assert prof is not None
    assert prof.display_name == "Legacy Club"

    on_disk = json.loads(path.read_text())
    assert "scheduler_access_token" not in on_disk
    assert "buffer_access_token" not in on_disk
    assert on_disk["display_name"] == "Legacy Club"
    # No temp file left behind.
    assert not list(profiles_dir.glob("*.tmp"))


def test_list_profiles_scrubs_tokens_from_disk(profiles_dir):
    path = _write_legacy_profile(profiles_dir)

    profs = cp.list_profiles()
    assert [p.profile_id for p in profs] == ["legacy-club"]

    on_disk = json.loads(path.read_text())
    assert "scheduler_access_token" not in on_disk
    assert "buffer_access_token" not in on_disk


def test_clean_profile_is_not_rewritten(profiles_dir):
    profiles_dir.mkdir(parents=True, exist_ok=True)
    path = profiles_dir / "clean.json"
    path.write_text(json.dumps({"profile_id": "clean", "display_name": "Clean"}))
    before = path.stat().st_mtime_ns

    assert cp.load_profile("clean") is not None
    assert path.stat().st_mtime_ns == before  # untouched — no needless rewrite


def test_scrub_is_fail_soft_on_readonly_fs(profiles_dir, monkeypatch):
    path = _write_legacy_profile(profiles_dir)

    def _boom(*a, **k):  # pragma: no cover - simulated read-only FS
        raise OSError("read-only file system")

    monkeypatch.setattr(cp.os, "replace", _boom)
    prof = cp.load_profile("legacy-club")
    assert prof is not None  # load never breaks
    # File keeps the keys (rewrite failed), but the loaded profile is clean.
    assert "scheduler_access_token" in json.loads(path.read_text())


def test_legacy_secrets_json_is_scrubbed(profiles_dir, tmp_path, monkeypatch):
    import mediahub.web.secrets_store as ss

    secrets = tmp_path / "secrets.json"
    secrets.write_text(
        json.dumps(
            {
                "anthropic_api_key": "keep-me",
                "buffer_access_token": "tok-buf-789",
                "scheduler_access_token": "tok-sched-789",
            }
        )
    )
    monkeypatch.setattr(ss, "_SECRETS_PATH", secrets)
    _write_legacy_profile(profiles_dir)

    assert cp.load_profile("legacy-club") is not None

    on_disk = json.loads(secrets.read_text())
    assert "buffer_access_token" not in on_disk
    assert "scheduler_access_token" not in on_disk
    assert on_disk["anthropic_api_key"] == "keep-me"  # unrelated keys survive
