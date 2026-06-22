"""Roadmap 1.18 build 2 — collab comment routes, task-gate & mention notify (web).

Bound workspace; exercises the comment API end-to-end: the comment-capability
gate, @mention notifications landing in the right member's inbox, a task holding
a card's approval until resolved, reactions, author-scoped delete, and the
erasure cascade dropping a run's threads.
"""

from __future__ import annotations

import importlib
import json
import sys
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

PASSWORD = "twelve-chars-long"
OWNER = "owner@cluba.org"
REVIEWER = "reviewer@cluba.org"
VIEWER = "viewer@cluba.org"


def _seed_run(runs_dir: Path, run_id: str, profile_id: str):
    data = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "Alpha Invitational"},
        "cards": [
            {"card_id": "card-1", "id": "card-1", "swim_id": "card-1",
             "swimmer_name": "Adult Swimmer", "event": "100 Free", "headline": "PB"}
        ],
        "recognition_report": {"n_swims_analysed": 1},
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(data))


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.delenv("MEDIAHUB_DEV_KEY", raising=False)
    for d in ("runs_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-alpha", display_name="Org Alpha"))

    run_id = "run-" + uuid.uuid4().hex[:8]
    _seed_run(tmp_path / "runs_v4", run_id, "org-alpha")
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-alpha", "Alpha Invitational", "a.hy3"),
    )
    conn.commit()
    conn.close()

    from mediahub.web.auth import UserStore
    from mediahub.web import tenancy as t

    users = UserStore()
    store = t.MembershipStore()
    for email, role in (
        (OWNER, t.ROLE_OWNER),
        (REVIEWER, t.ROLE_REVIEWER),
        (VIEWER, t.ROLE_VIEWER),
    ):
        users.create(email, PASSWORD)
        store.add(email, "org-alpha", role=role)

    app = wm.create_app()
    app.config["TESTING"] = True
    return {"app": app, "wm": wm, "run_id": run_id}


def _act_as(app, email):
    c = app.test_client()
    assert c.post("/login", data={"email": email, "password": PASSWORD}).status_code in (302, 303)
    c.post("/api/organisation/active", data={"profile_id": "org-alpha"})
    return c


def _comments_url(run_id):
    return f"/api/runs/{run_id}/comments"


def test_reviewer_can_comment_viewer_cannot(world):
    run_id = world["run_id"]
    # Reviewer (has comment capability)
    c = _act_as(world["app"], REVIEWER)
    r = c.post(_comments_url(run_id), json={"card_id": "card-1", "body": "looks good"})
    assert r.status_code == 201, r.get_data(as_text=True)
    # Viewer (no comment capability) is refused
    v = _act_as(world["app"], VIEWER)
    r2 = v.post(_comments_url(run_id), json={"card_id": "card-1", "body": "hi"})
    assert r2.status_code == 403
    assert r2.get_json().get("error") == "forbidden"
    # …but a viewer can still READ the thread
    r3 = v.get(_comments_url(run_id) + "?card_id=card-1")
    assert r3.status_code == 200
    assert len(r3.get_json()["comments"]) == 1


def test_mention_notifies_target_member(world):
    run_id = world["run_id"]
    c = _act_as(world["app"], OWNER)
    r = c.post(_comments_url(run_id), json={"card_id": "card-1", "body": "ping @reviewer please check"})
    assert r.status_code == 201
    assert r.get_json()["comment"]["mentions"] == [REVIEWER]
    from mediahub.notify import inbox as _inbox

    got = _inbox.list_for("org-alpha", user_email=REVIEWER)
    assert any(n["kind"] == "mention" for n in got)
    # The owner (mentioner) didn't get a mention of themselves
    owner_inbox = _inbox.list_for("org-alpha", user_email=OWNER)
    assert not any(n["kind"] == "mention" for n in owner_inbox)


def test_open_task_blocks_then_unblocks_approval(world):
    run_id = world["run_id"]
    c = _act_as(world["app"], OWNER)
    # raise a task on the card
    rt = c.post(_comments_url(run_id), json={"card_id": "card-1", "body": "check lane 4 name", "kind": "task"})
    assert rt.status_code == 201
    task_id = rt.get_json()["comment"]["id"]
    # approval is now blocked
    ra = c.post(f"/api/workflow/{run_id}/card-1", json={"action": "set_status", "status": "approved"})
    assert ra.status_code == 403, ra.get_data(as_text=True)
    assert ra.get_json()["error"] == "tasks_open"
    # resolve the task → approval succeeds
    c.post(f"{_comments_url(run_id)}/{task_id}", json={"action": "complete"})
    ra2 = c.post(f"/api/workflow/{run_id}/card-1", json={"action": "set_status", "status": "approved"})
    assert ra2.status_code == 200, ra2.get_data(as_text=True)
    assert ra2.get_json()["status"] == "approved"


def test_task_assignment_notifies_assignee(world):
    run_id = world["run_id"]
    c = _act_as(world["app"], OWNER)
    c.post(
        _comments_url(run_id),
        json={"card_id": "card-1", "body": "verify time", "kind": "task", "assignee": REVIEWER},
    )
    from mediahub.notify import inbox as _inbox

    got = _inbox.list_for("org-alpha", user_email=REVIEWER)
    assert any(n["kind"] == "task" for n in got)


def test_reactions_toggle_via_route(world):
    run_id = world["run_id"]
    c = _act_as(world["app"], OWNER)
    cid = c.post(_comments_url(run_id), json={"card_id": "card-1", "body": "x"}).get_json()["comment"]["id"]
    r = c.post(f"{_comments_url(run_id)}/{cid}", json={"action": "react", "emoji": "👍"})
    assert r.status_code == 200 and r.get_json()["on"] is True
    assert "👍" in r.get_json()["reactions"]


def test_author_scoped_delete(world):
    run_id = world["run_id"]
    # reviewer posts
    rev = _act_as(world["app"], REVIEWER)
    cid = rev.post(_comments_url(run_id), json={"card_id": "card-1", "body": "mine"}).get_json()["comment"]["id"]
    # owner is a manager (approve/manage) → may delete anyone's
    owner = _act_as(world["app"], OWNER)
    r = owner.post(f"{_comments_url(run_id)}/{cid}", json={"action": "delete"})
    assert r.status_code == 200 and r.get_json()["deleted"] == cid


def test_erasure_cascade_drops_threads(world):
    run_id = world["run_id"]
    c = _act_as(world["app"], OWNER)
    c.post(_comments_url(run_id), json={"card_id": "card-1", "body": "to be erased"})
    from mediahub.collab import threads as th
    from mediahub.privacy.erasure import run_deletion_cascade

    assert th.count_for_card(run_id) == 1
    report = run_deletion_cascade(run_id, "org-alpha")
    assert report.get("collab_comments", 0) == 1
    assert th.count_for_card(run_id) == 0
