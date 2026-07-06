"""Roadmap 1.18 build 5 — collections web routes, Team Context, assistant-in-threads."""

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
VIEWER = "viewer@cluba.org"


def _seed_run(runs_dir: Path, run_id: str, profile_id: str):
    data = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "Alpha"},
        "cards": [{"card_id": "card-1", "id": "card-1", "swim_id": "card-1"}],
        "recognition_report": {
            "n_swims_analysed": 1,
            "ranked_achievements": [
                {"rank": 1, "id": "card-1", "achievement": {"swim_id": "card-1",
                 "swimmer_name": "Adult", "event": "100 Free", "headline": "PB"}}
            ],
        },
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(data))


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    # Ensure no AI provider is configured, so assistant-in-threads honest-errors.
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "MEDIAHUB_LLM_ENDPOINTS"):
        monkeypatch.delenv(k, raising=False)
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


def test_create_collection_requires_edit(world):
    v = _act_as(world["app"], VIEWER)
    assert v.post("/api/collections", json={"name": "X"}).status_code == 403
    o = _act_as(world["app"], OWNER)
    r = o.post("/api/collections", json={"name": "Summer League"})
    assert r.status_code == 201
    assert r.get_json()["collection"]["name"] == "Summer League"


def test_collection_lifecycle(world):
    o = _act_as(world["app"], OWNER)
    cid = o.post("/api/collections", json={"name": "C"}).get_json()["collection"]["id"]
    # add the run
    r = o.post(f"/api/collections/{cid}", json={"action": "add_item", "item_type": "run", "item_id": world["run_id"]})
    assert r.status_code == 200
    items = o.get(f"/api/collections/{cid}").get_json()["items"]
    assert any(it["item_id"] == world["run_id"] for it in items)
    # list shows count 1
    cols = o.get("/api/collections").get_json()["collections"]
    assert cols[0]["count"] == 1
    # rename + delete
    assert o.post(f"/api/collections/{cid}", json={"action": "rename", "name": "C2"}).status_code == 200
    assert o.post(f"/api/collections/{cid}", json={"action": "delete"}).status_code == 200
    assert o.get("/api/collections").get_json()["collections"] == []


def test_collections_page_renders(world):
    o = _act_as(world["app"], OWNER)
    body = o.get("/collections").get_data(as_text=True)
    assert "Collections" in body


def test_team_context_route(world):
    o = _act_as(world["app"], OWNER)
    j = o.get("/api/organisation/context").get_json()
    assert j["ok"] is True
    assert set(j["context"].keys()) == {"brand", "preferences", "recent"}
    assert j["context"]["brand"]["display_name"] == "Org Alpha"


def test_run_erasure_drops_collection_membership(world):
    run_id = world["run_id"]
    o = _act_as(world["app"], OWNER)
    cid = o.post("/api/collections", json={"name": "C"}).get_json()["collection"]["id"]
    o.post(f"/api/collections/{cid}", json={"action": "add_item", "item_type": "run", "item_id": run_id})
    from mediahub.collab import collections as col
    from mediahub.privacy.erasure import run_deletion_cascade

    report = run_deletion_cascade(run_id, "org-alpha")
    assert report.get("collab_collection_items", 0) == 1
    assert col.collections_for_item("org-alpha", "run", run_id) == []


def test_assistant_in_thread_replies_honestly_without_provider(world):
    run_id = world["run_id"]
    o = _act_as(world["app"], OWNER)
    r = o.post(
        f"/api/runs/{run_id}/comments",
        json={"card_id": "card-1", "body": "@assistant what do you think of this card?"},
    )
    assert r.status_code == 201
    from mediahub.collab import threads as th

    comments = th.list_for_card(run_id, "card-1")
    # the human comment + an assistant reply
    assistant_replies = [c for c in comments if c.author_name == "MediaHub Assistant"]
    assert len(assistant_replies) == 1
    # honest-error: no provider configured → says so, never a fabricated answer
    assert "configured" in assistant_replies[0].body.lower()
    assert assistant_replies[0].parent_id  # it's a threaded reply
