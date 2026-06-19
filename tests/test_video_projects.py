"""Tests for video.projects — per-profile EDL persistence + approval (1.6)."""

from __future__ import annotations

import pytest

from mediahub.video.edl import EDL, Clip
from mediahub.video.projects import VideoProject, VideoProjectStore


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return VideoProjectStore()


def _project(profile="club_a", name="Race highlight"):
    edl = EDL(clips=[Clip(source="a.mp4", in_ms=0, out_ms=6000)])
    return VideoProject(id="", profile_id=profile, name=name, edl=edl)


def test_save_assigns_id_and_timestamps(store):
    p = store.save(_project())
    assert p.id.startswith("vid_")
    assert p.created_at > 0 and p.updated_at > 0


def test_get_roundtrips_edl(store):
    p = store.save(_project())
    got = store.get(p.id)
    assert got is not None
    assert got.name == "Race highlight"
    assert len(got.edl.clips) == 1
    assert got.edl.clips[0].source == "a.mp4"


def test_list_is_profile_scoped(store):
    store.save(_project(profile="club_a", name="A1"))
    store.save(_project(profile="club_a", name="A2"))
    store.save(_project(profile="club_b", name="B1"))
    a = store.list(profile_id="club_a")
    b = store.list(profile_id="club_b")
    assert {p.name for p in a} == {"A1", "A2"}
    assert {p.name for p in b} == {"B1"}


def test_set_status_gates_approval(store):
    p = store.save(_project())
    assert p.status == "draft"
    approved = store.set_status(p.id, "approved")
    assert approved is not None and approved.status == "approved"


def test_set_status_rejects_unknown(store):
    p = store.save(_project())
    with pytest.raises(ValueError):
        store.set_status(p.id, "published")


def test_delete(store):
    p = store.save(_project())
    assert store.delete(p.id) is True
    assert store.get(p.id) is None
    assert store.delete("vid_missing") is False


def test_update_persists_edl_change(store):
    p = store.save(_project())
    p.edl.clips.append(Clip(source="b.mp4", in_ms=0, out_ms=3000))
    store.save(p)
    got = store.get(p.id)
    assert len(got.edl.clips) == 2
