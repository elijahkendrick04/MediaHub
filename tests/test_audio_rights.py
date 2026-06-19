"""Tests for audio/rights.py — licence ledger + fingerprinting (roadmap 1.8).

Most tests run without FFmpeg (file-byte hashing + the SQLite ledger). The
fingerprint method is asserted to be one of the known tiers rather than pinned,
so the suite passes whether or not FFmpeg/fpcalc are present.
"""

from __future__ import annotations

import pytest

from mediahub.audio import rights
from mediahub.audio.library import Licence, load_library
from mediahub.audio.rights import RightsLedger, RightsRecord


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))


def _sample(tmp_path, data=b"hello-audio", name="clip.wav"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_content_hash_deterministic(tmp_path):
    p = _sample(tmp_path)
    assert rights.content_hash(p) == rights.content_hash(p)
    q = _sample(tmp_path, data=b"different", name="q.wav")
    assert rights.content_hash(p) != rights.content_hash(q)


def test_fingerprint_method_is_known_and_stable(tmp_path):
    p = _sample(tmp_path)
    fp1 = rights.fingerprint(p)
    fp2 = rights.fingerprint(p)
    assert fp1.value == fp2.value
    assert fp1.method in {"chromaprint", "pcm", "filebytes"}


def test_ledger_record_get_list_delete(tmp_path):
    led = RightsLedger()
    rec = RightsRecord(
        asset_id="a1",
        profile_id="clubA",
        filename="clip.wav",
        fingerprint="fp123",
        licence=Licence(name="CC0 1.0", spdx="CC0-1.0", commercial_ok=True),
        platforms=("instagram", "tiktok"),
        attested_by="me",
    )
    led.record(rec)
    got = led.get("a1")
    assert got is not None
    assert got.licence.spdx == "CC0-1.0"
    assert got.platforms == ("instagram", "tiktok")
    assert got.attested_at  # stamped on record
    assert [r.asset_id for r in led.list_for_profile("clubA")] == ["a1"]
    assert led.find_by_fingerprint("fp123")[0].asset_id == "a1"
    assert led.delete("a1") is True
    assert led.get("a1") is None


def test_platforms_filtered_to_known_set(tmp_path):
    led = RightsLedger()
    led.record(
        RightsRecord(
            asset_id="a2",
            profile_id="clubB",
            platforms=("instagram", "bogus", "tiktok"),
        )
    )
    got = led.get("a2")
    assert "bogus" not in got.platforms
    assert set(got.platforms) == {"instagram", "tiktok"}


def test_attest_and_duplicate_detection(tmp_path):
    p = _sample(tmp_path)
    led = RightsLedger()
    check1 = rights.check_upload(p, ledger=led)
    assert check1.is_duplicate is False
    rec = rights.attest_upload(
        p,
        asset_id="up1",
        profile_id="clubA",
        licence=Licence(name="CC0 1.0", spdx="CC0-1.0"),
        attested_by="me",
        ledger=led,
    )
    assert rec.fingerprint  # recorded
    check2 = rights.check_upload(p, ledger=led)
    assert check2.is_duplicate is True
    assert [m.asset_id for m in check2.matches] == ["up1"]


def test_record_for_bundled_track(tmp_path):
    led = RightsLedger()
    track = load_library(include_operator=False).all()[0]
    rec = rights.record_for_track(track, ledger=led)
    assert rec.asset_id == track.id
    assert led.get(track.id).licence.spdx == "CC0-1.0"


def test_safe_for_platform_helper():
    ok = Licence(commercial_ok=True)
    no = Licence(commercial_ok=False)
    assert rights.safe_for_platform(ok, "instagram") is True
    assert rights.safe_for_platform(no, "instagram") is False
    rec = RightsRecord(asset_id="x", licence=no, platforms=("instagram",))
    assert rec.safe_for("instagram") is False  # non-commercial blocks
    rec2 = RightsRecord(asset_id="y", licence=ok, platforms=("instagram",))
    assert rec2.safe_for("instagram") is True
    assert rec2.safe_for("tiktok") is False  # not in platform set
