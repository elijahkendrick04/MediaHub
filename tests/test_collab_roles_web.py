"""Roadmap 1.18 build 1 — role gates on the review/approval routes (web level).

A bound workspace with one seat of each role. The single-card and bulk workflow
routes must refuse a status change (sign-off) to a seat without the approve
capability, and refuse a caption edit to a seat without the edit capability —
while the legacy ``member`` seat and the owner keep doing both, so nothing
changes for workspaces that pre-date 1.18. Also pins the last-owner demotion
guard on the members admin route.
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
MEMBER = "member@cluba.org"
EDITOR = "editor@cluba.org"
APPROVER = "approver@cluba.org"
REVIEWER = "reviewer@cluba.org"
VIEWER = "viewer@cluba.org"


def _seed_run(runs_dir: Path, run_id: str, profile_id: str):
    data = {
        "run_id": run_id,
        "profile_id": profile_id,
        "profile_display": profile_id,
        "meet": {"name": "Alpha Invitational"},
        "cards": [
            {
                "card_id": "card-1",
                "id": "card-1",
                "swim_id": "swim-1",
                "swimmer_name": "Adult Swimmer",
                "event": "100m freestyle",
                "headline": "A PB",
            }
        ],
        "trust": {"score": 0.9},
        "recognition_report": {"n_swims_analysed": 1},
        "parse_warnings": [],
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(data))


@pytest.fixture
def roles_world(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.delenv("MEDIAHUB_DEV_KEY", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-alpha", display_name="Org Alpha"))

    run_id = "run-alpha-" + uuid.uuid4().hex[:8]
    _seed_run(tmp_path / "runs_v4", run_id, "org-alpha")
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-alpha", "Alpha Invitational", "alpha.hy3"),
    )
    conn.commit()
    conn.close()

    from mediahub.web.auth import UserStore
    from mediahub.web import tenancy as t

    users = UserStore()
    store = t.MembershipStore()
    for email, role in (
        (OWNER, t.ROLE_OWNER),
        (MEMBER, t.ROLE_MEMBER),
        (EDITOR, t.ROLE_EDITOR),
        (APPROVER, t.ROLE_APPROVER),
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
    r = c.post("/login", data={"email": email, "password": PASSWORD})
    assert r.status_code in (302, 303), r.status_code
    r = c.post("/api/organisation/active", data={"profile_id": "org-alpha"})
    assert r.status_code in (200, 302, 303), r.status_code
    return c


def _approve(c, run_id):
    return c.post(
        f"/api/workflow/{run_id}/card-1",
        json={"action": "set_status", "status": "approved"},
    )


def _edit(c, run_id):
    return c.post(
        f"/api/workflow/{run_id}/card-1",
        json={"action": "set_edits", "edits": {"warm-club_headline": "Edited!"}},
    )


@pytest.mark.parametrize("email", [OWNER, MEMBER, APPROVER])
def test_approve_capable_seats_can_approve(roles_world, email):
    c = _act_as(roles_world["app"], email)
    r = _approve(c, roles_world["run_id"])
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body.get("ok") is True
    assert body.get("status") == "approved"


@pytest.mark.parametrize("email", [EDITOR, REVIEWER, VIEWER])
def test_non_approver_seats_are_refused_approval(roles_world, email):
    c = _act_as(roles_world["app"], email)
    r = _approve(c, roles_world["run_id"])
    assert r.status_code == 403, r.get_data(as_text=True)
    assert r.get_json().get("error") == "forbidden"


@pytest.mark.parametrize("email", [OWNER, MEMBER, EDITOR])
def test_edit_capable_seats_can_edit(roles_world, email):
    c = _act_as(roles_world["app"], email)
    r = _edit(c, roles_world["run_id"])
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json().get("ok") is True


@pytest.mark.parametrize("email", [APPROVER, REVIEWER, VIEWER])
def test_non_editor_seats_are_refused_edit(roles_world, email):
    c = _act_as(roles_world["app"], email)
    r = _edit(c, roles_world["run_id"])
    assert r.status_code == 403, r.get_data(as_text=True)
    assert r.get_json().get("error") == "forbidden"


def test_bulk_status_refused_for_viewer(roles_world):
    c = _act_as(roles_world["app"], VIEWER)
    r = c.post(
        f"/api/runs/{roles_world['run_id']}/cards/bulk-status",
        json={"status": "approved", "ids": ["card-1"]},
    )
    assert r.status_code == 403, r.get_data(as_text=True)
    assert r.get_json().get("error") == "forbidden"


def test_bulk_status_allowed_for_owner(roles_world):
    c = _act_as(roles_world["app"], OWNER)
    r = c.post(
        f"/api/runs/{roles_world['run_id']}/cards/bulk-status",
        json={"status": "approved", "ids": ["card-1"]},
    )
    assert r.status_code == 200, r.get_data(as_text=True)


def test_members_page_offers_the_new_roles(roles_world):
    c = _act_as(roles_world["app"], OWNER)
    body = c.get("/organisation/members").get_data(as_text=True)
    for role_label in ("Editor", "Approver", "Reviewer", "Viewer"):
        assert role_label in body


def test_cannot_demote_last_owner(roles_world):
    c = _act_as(roles_world["app"], OWNER)
    # Demote the only owner to editor — must be refused server-side.
    r = c.post(
        "/organisation/members",
        data={"action": "add", "email": OWNER, "role": "editor"},
        follow_redirects=True,
    )
    body = r.get_data(as_text=True)
    assert "last owner" in body.lower()
    from mediahub.web import tenancy as t

    assert t.MembershipStore().is_active_owner(OWNER, "org-alpha")
