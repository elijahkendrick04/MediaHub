"""Roadmap 1.18 build 4 — share-link management + public review surface (web).

Owner mints an expiring, scoped link; a no-account visitor opens it, sees only
the scoped (consent-cleared, rendered) card, and — if the link allows — comments.
Revoke and expiry kill access; the erasure cascade drops shares.
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
VIEWER = "viewer@cluba.org"


def _seed_run(runs_dir: Path, run_id: str, profile_id: str):
    data = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "Alpha Invitational"},
        "cards": [{"card_id": "card-1", "id": "card-1", "swim_id": "card-1"}],
        "recognition_report": {
            "n_swims_analysed": 1,
            "ranked_achievements": [
                {
                    "rank": 1,
                    "id": "card-1",
                    "achievement": {
                        "swim_id": "card-1",
                        "swimmer_name": "Adult Swimmer",
                        "event": "100 Free",
                        "headline": "A new PB",
                    },
                }
            ],
        },
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(data))


def _stage_visual(runs_dir: Path, run_id: str, card_id: str):
    """A minimal rendered-visual sidecar so the public surface has a card to show."""
    vdir = runs_dir / run_id / "visuals" / "cb_demo"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "visual.json").write_text(json.dumps({"content_item_id": card_id, "id": "vis1"}))
    (vdir / "story.png").write_bytes(b"\x89PNG\r\n\x1a\n fake png bytes")


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
    _stage_visual(runs_dir, run_id, "card-1")

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


def _create_share(app, run_id, perm="view", card_id="card-1"):
    o = _act_as(app, OWNER)
    r = o.post(f"/api/runs/{run_id}/shares", json={"card_id": card_id, "perm": perm, "ttl_days": 7})
    assert r.status_code == 201, r.get_data(as_text=True)
    return r.get_json()["share"]


def test_create_share_requires_manage(world):
    run_id = world["run_id"]
    # viewer can't mint a share
    v = _act_as(world["app"], VIEWER)
    r = v.post(f"/api/runs/{run_id}/shares", json={"perm": "view"})
    assert r.status_code == 403
    # owner can
    share = _create_share(world["app"], run_id)
    assert share["token"] and "/share/" in share["url"]


def test_public_page_view_only(world):
    run_id = world["run_id"]
    share = _create_share(world["app"], run_id, perm="view")
    token = share["token"]
    anon = world["app"].test_client()  # no login
    r = anon.get(f"/share/{token}")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "for review" in body.lower()
    # view-only → no comment form
    assert "Send comment" not in body


def test_public_page_comment_perm_shows_form(world):
    run_id = world["run_id"]
    share = _create_share(world["app"], run_id, perm="comment")
    anon = world["app"].test_client()
    body = anon.get(f"/share/{share['token']}").get_data(as_text=True)
    assert "Send comment" in body


def test_public_comment_posts_and_notifies(world):
    run_id = world["run_id"]
    share = _create_share(world["app"], run_id, perm="comment")
    anon = world["app"].test_client()
    r = anon.post(
        f"/share/{share['token']}/comment",
        data={"card_id": "card-1", "name": "A Parent", "body": "The name is spelled right"},
    )
    assert r.status_code in (302, 303)
    from mediahub.collab import threads as th

    comments = th.list_for_card(run_id, "card-1")
    assert any("spelled right" in c.body for c in comments)
    # the club gets an org-wide inbox nudge
    from mediahub.notify import inbox as _inbox

    assert any(n["title"] == "New review comment" for n in _inbox.list_for("org-alpha"))


def test_view_only_link_refuses_comment(world):
    run_id = world["run_id"]
    share = _create_share(world["app"], run_id, perm="view")
    anon = world["app"].test_client()
    r = anon.post(
        f"/share/{share['token']}/comment", data={"card_id": "card-1", "body": "hi"}
    )
    assert r.status_code == 404  # view-only links have no comment route access


def test_revoked_link_dies(world):
    run_id = world["run_id"]
    share = _create_share(world["app"], run_id, perm="view")
    token = share["token"]
    o = _act_as(world["app"], OWNER)
    assert o.post(f"/api/runs/{run_id}/shares/{token}/revoke", json={}).status_code == 200
    anon = world["app"].test_client()
    assert anon.get(f"/share/{token}").status_code == 404
    assert anon.get(f"/share/{token}/card/card-1.png").status_code == 404


def test_unknown_token_404(world):
    anon = world["app"].test_client()
    assert anon.get("/share/not-a-real-token").status_code == 404


def test_public_card_image_served(world):
    run_id = world["run_id"]
    share = _create_share(world["app"], run_id, perm="view")
    anon = world["app"].test_client()
    r = anon.get(f"/share/{share['token']}/card/card-1.png")
    assert r.status_code == 200
    assert r.mimetype == "image/png"


def test_card_scoped_link_only_serves_its_card(world):
    run_id = world["run_id"]
    share = _create_share(world["app"], run_id, perm="view", card_id="card-1")
    anon = world["app"].test_client()
    # a different card id on a card-scoped link is refused
    assert anon.get(f"/share/{share['token']}/card/other-card.png").status_code == 404


def test_internal_comments_and_tasks_never_render_on_share_page(world):
    """The public share page shows only external-safe entries: comments posted
    via the share link itself (no account email). Internal committee comments
    and tasks — always author_email-attributed — must not leak to an
    unauthenticated link holder."""
    run_id = world["run_id"]
    from mediahub.collab import threads as th

    th.add_comment(
        run_id,
        "card-1",
        "check surname, parent complained",
        author_email=OWNER,
        author_name=OWNER,
        kind="comment",
    )
    th.add_comment(
        run_id,
        "card-1",
        "task: confirm the lane-4 name",
        author_email=OWNER,
        author_name=OWNER,
        kind="task",
    )
    share = _create_share(world["app"], run_id, perm="comment")
    anon = world["app"].test_client()
    # An external reviewer's own share-posted comment IS visible.
    anon.post(
        f"/share/{share['token']}/comment",
        data={"card_id": "card-1", "name": "A Parent", "body": "Looks great to me"},
    )
    body = anon.get(f"/share/{share['token']}").get_data(as_text=True)
    assert "parent complained" not in body
    assert "lane-4" not in body
    assert OWNER not in body
    assert "Looks great to me" in body


def test_erasure_cascade_drops_shares(world):
    run_id = world["run_id"]
    _create_share(world["app"], run_id)
    from mediahub.collab import share_tokens as st
    from mediahub.privacy.erasure import run_deletion_cascade

    assert len(st.list_for_run(run_id)) == 1
    report = run_deletion_cascade(run_id, "org-alpha")
    assert report.get("collab_shares", 0) == 1
    assert st.list_for_run(run_id) == []
