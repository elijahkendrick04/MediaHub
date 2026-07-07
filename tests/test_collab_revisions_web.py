"""Roadmap 1.18 build 3 — revisions & locks web routes (gate + erasure)."""

from __future__ import annotations

import importlib
import json
import sys
import time
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

PASSWORD = "twelve-chars-long"
OWNER = "owner@cluba.org"
VIEWER = "viewer@cluba.org"


def _seed_run(runs_dir: Path, run_id: str, profile_id: str):
    data = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "Alpha"},
        "cards": [{"card_id": "card-1", "id": "card-1", "swim_id": "card-1",
                   "swimmer_name": "Adult", "event": "100 Free", "headline": "PB"}],
        "recognition_report": {"n_swims_analysed": 1},
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(data))


def _write_brief(runs_dir, run_id, brief_id, card_id, headline, created):
    bdir = runs_dir / run_id / "briefs"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / f"{brief_id}.json").write_text(
        json.dumps({"id": brief_id, "content_item_id": card_id,
                    "text_layers": {"headline_line1": headline},
                    "layout_template": "hero", "created_at": created})
    )


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-alpha", display_name="Org Alpha"))
    run_id = "run-" + uuid.uuid4().hex[:8]
    runs_dir = tmp_path / "runs_v4"
    _seed_run(runs_dir, run_id, "org-alpha")
    _write_brief(runs_dir, run_id, "cb_a", "card-1", "FIRST", "2026-01-01T00:00:00Z")
    time.sleep(0.02)
    _write_brief(runs_dir, run_id, "cb_b", "card-1", "SECOND", "2026-01-02T00:00:00Z")

    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-alpha", "Alpha", "a.hy3"),
    )
    conn.commit()
    conn.close()

    from mediahub.web.auth import UserStore
    from mediahub.web import tenancy as t

    users = UserStore()
    store = t.MembershipStore()
    for email, role in ((OWNER, t.ROLE_OWNER), (VIEWER, t.ROLE_VIEWER)):
        users.create(email, PASSWORD)
        store.add(email, "org-alpha", role=role)

    app = wm.create_app()
    app.config["TESTING"] = True
    return {"app": app, "run_id": run_id}


def _act_as(app, email):
    c = app.test_client()
    c.post("/login", data={"email": email, "password": PASSWORD})
    c.post("/api/organisation/active", data={"profile_id": "org-alpha"})
    return c


def test_list_revisions(world):
    run_id = world["run_id"]
    c = _act_as(world["app"], VIEWER)  # viewing history only needs view
    r = c.get(f"/api/runs/{run_id}/card/card-1/revisions")
    assert r.status_code == 200
    j = r.get_json()
    assert [rev["brief_id"] for rev in j["revisions"]] == ["cb_a", "cb_b"]
    assert j["current_id"] == "cb_b"


def test_diff_revisions(world):
    run_id = world["run_id"]
    c = _act_as(world["app"], VIEWER)
    r = c.get(f"/api/runs/{run_id}/card/card-1/revisions/diff?a=cb_a&b=cb_b")
    assert r.status_code == 200
    fields = {d["field"] for d in r.get_json()["diff"]}
    assert "text_layers.headline_line1" in fields


def test_restore_requires_edit_capability(world):
    run_id = world["run_id"]
    # viewer can't restore
    v = _act_as(world["app"], VIEWER)
    r = v.post(f"/api/runs/{run_id}/card/card-1/revisions/restore", json={"brief_id": "cb_a"})
    assert r.status_code == 403
    # owner can
    o = _act_as(world["app"], OWNER)
    r2 = o.post(f"/api/runs/{run_id}/card/card-1/revisions/restore", json={"brief_id": "cb_a"})
    assert r2.status_code == 200, r2.get_data(as_text=True)
    # a fresh current version now exists carrying FIRST's design
    revs = o.get(f"/api/runs/{run_id}/card/card-1/revisions").get_json()["revisions"]
    assert len(revs) == 3 and revs[-1]["is_current"]


def test_locks_get_and_set_gate(world):
    run_id = world["run_id"]
    # viewer can read locks but not set them
    v = _act_as(world["app"], VIEWER)
    assert v.get(f"/api/runs/{run_id}/card/card-1/locks").status_code == 200
    r = v.post(f"/api/runs/{run_id}/card/card-1/locks", json={"element": "sponsor", "locked": True})
    assert r.status_code == 403
    # owner can lock
    o = _act_as(world["app"], OWNER)
    r2 = o.post(f"/api/runs/{run_id}/card/card-1/locks", json={"element": "sponsor", "locked": True})
    assert r2.status_code == 200
    assert "sponsor" in r2.get_json()["locked"]


def test_locks_bad_element_rejected(world):
    run_id = world["run_id"]
    o = _act_as(world["app"], OWNER)
    r = o.post(f"/api/runs/{run_id}/card/card-1/locks", json={"element": "bogus", "locked": True})
    assert r.status_code == 400


def test_locked_sponsor_drops_inspector_override(world):
    run_id = world["run_id"]
    o = _act_as(world["app"], OWNER)
    # lock the sponsor strip
    o.post(f"/api/runs/{run_id}/card/card-1/locks", json={"element": "sponsor", "locked": True})
    # try to hide the sponsor via the inspector + a normal caption edit
    r = o.post(
        f"/api/workflow/{run_id}/card-1",
        json={"action": "set_edits", "edits": {"insp.hideSponsor": "1", "warm-club_headline": "Hi"}},
    )
    assert r.status_code == 200
    import os

    from mediahub.workflow.store import WorkflowStore

    ws = WorkflowStore(Path(os.environ["RUNS_DIR"]))
    edits = (ws.load(run_id).get("card-1").edited_captions) or {}
    # the locked sponsor toggle was dropped; the unlocked caption edit landed
    assert "insp.hideSponsor" not in edits
    assert edits.get("warm-club_headline") == "Hi"


def test_erasure_cascade_drops_locks(world):
    run_id = world["run_id"]
    o = _act_as(world["app"], OWNER)
    o.post(f"/api/runs/{run_id}/card/card-1/locks", json={"element": "photo", "locked": True})
    from mediahub.collab import locks as lk
    from mediahub.privacy.erasure import run_deletion_cascade

    assert lk.locked_elements(run_id, "card-1") == {"photo"}
    report = run_deletion_cascade(run_id, "org-alpha")
    assert report.get("collab_locks", 0) == 1
    assert lk.locked_elements(run_id, "card-1") == set()
