"""UI 1.8 — timestamp-anchored reel review comments: HTTP routes + wiring.

Frame.io-style markers pinned to a moment on a generated reel (or story card)
in the content-builder review surface, stored per run/target in SQLite and
shown as overlays on the video scrubber. These tests drive the Flask routes
end-to-end (mirroring test_reel_job_async.py's app fixture):

  GET/POST /api/runs/<run_id>/reel/comments
  POST     /api/runs/<run_id>/reel/comments/<comment_id>   (action in body)

Covered: create/list/order, resolve/reopen/edit/delete, run-scoped mutation,
validation errors, tenant isolation, run-not-found, the CSRF content-type
exemption the front-end relies on, run-deletion cleanup, and that the comment
UI helpers actually ship in the page JS.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    save_profile(ClubProfile(profile_id="beta", display_name="Beta SC"))

    for rid, owner in (("r1", "alpha"), ("r2", "alpha")):
        run = {
            "run_id": rid,
            "profile_id": owner,
            "meet_name": "Test Open",
            "meet": {"name": "Test Open"},
            "recognition_report": {"ranked_achievements": []},
        }
        (wm.RUNS_DIR / f"{rid}.json").write_text(json.dumps(run), encoding="utf-8")
    return app, wm, tmp_path


def _as(client, pid):
    client.post("/api/organisation/active", data={"profile_id": pid})


def _add(client, run="r1", **body):
    body.setdefault("target", "reel")
    body.setdefault("t_ms", 1000)
    body.setdefault("body", "a note")
    return client.post(f"/api/runs/{run}/reel/comments", json=body)


# ---------------------------------------------------------------------------
# Create + list
# ---------------------------------------------------------------------------


class TestCreateAndList:
    def test_empty_list_initially(self, app_env):
        app, *_ = app_env
        with app.test_client() as c:
            _as(c, "alpha")
            r = c.get("/api/runs/r1/reel/comments")
            assert r.status_code == 200
            j = r.get_json()
            assert j["ok"] is True
            assert j["comments"] == []

    def test_add_returns_201_and_echoes_comment(self, app_env):
        app, *_ = app_env
        with app.test_client() as c:
            _as(c, "alpha")
            r = _add(c, t_ms=3200, body="Trim the intro", author="Coach")
            assert r.status_code == 201
            com = r.get_json()["comment"]
            assert com["id"]
            assert com["t_ms"] == 3200
            assert com["body"] == "Trim the intro"
            assert com["author"] == "Coach"
            assert com["resolved"] is False

    def test_added_comment_is_listed_ordered_by_time(self, app_env):
        app, *_ = app_env
        with app.test_client() as c:
            _as(c, "alpha")
            _add(c, t_ms=5000, body="third")
            _add(c, t_ms=1000, body="first")
            _add(c, t_ms=3000, body="second")
            j = c.get("/api/runs/r1/reel/comments").get_json()
            assert [x["body"] for x in j["comments"]] == ["first", "second", "third"]

    def test_target_filter(self, app_env):
        app, *_ = app_env
        with app.test_client() as c:
            _as(c, "alpha")
            _add(c, target="reel", body="reel note")
            _add(c, target="card:swim-9", body="card note")
            reel = c.get("/api/runs/r1/reel/comments?target=reel").get_json()["comments"]
            card = c.get(
                "/api/runs/r1/reel/comments?target=card:swim-9"
            ).get_json()["comments"]
            assert [x["body"] for x in reel] == ["reel note"]
            assert [x["body"] for x in card] == ["card note"]

    def test_resolved_filter(self, app_env):
        app, *_ = app_env
        with app.test_client() as c:
            _as(c, "alpha")
            keep = _add(c, body="open").get_json()["comment"]
            done = _add(c, body="closing").get_json()["comment"]
            c.post(f"/api/runs/r1/reel/comments/{done['id']}", json={"action": "resolve"})
            shown = c.get("/api/runs/r1/reel/comments?resolved=0").get_json()["comments"]
            assert [x["id"] for x in shown] == [keep["id"]]


# ---------------------------------------------------------------------------
# Mutate: resolve / reopen / edit / delete
# ---------------------------------------------------------------------------


class TestMutate:
    def test_resolve_then_reopen(self, app_env):
        app, *_ = app_env
        with app.test_client() as c:
            _as(c, "alpha")
            cid = _add(c).get_json()["comment"]["id"]
            r = c.post(f"/api/runs/r1/reel/comments/{cid}", json={"action": "resolve"})
            assert r.status_code == 200 and r.get_json()["comment"]["resolved"] is True
            r = c.post(f"/api/runs/r1/reel/comments/{cid}", json={"action": "reopen"})
            assert r.get_json()["comment"]["resolved"] is False

    def test_edit_body(self, app_env):
        app, *_ = app_env
        with app.test_client() as c:
            _as(c, "alpha")
            cid = _add(c, body="old").get_json()["comment"]["id"]
            r = c.post(
                f"/api/runs/r1/reel/comments/{cid}", json={"action": "edit", "body": "new"}
            )
            assert r.status_code == 200 and r.get_json()["comment"]["body"] == "new"

    def test_edit_empty_body_is_400(self, app_env):
        app, *_ = app_env
        with app.test_client() as c:
            _as(c, "alpha")
            cid = _add(c).get_json()["comment"]["id"]
            r = c.post(
                f"/api/runs/r1/reel/comments/{cid}", json={"action": "edit", "body": "  "}
            )
            assert r.status_code == 400

    def test_delete(self, app_env):
        app, *_ = app_env
        with app.test_client() as c:
            _as(c, "alpha")
            cid = _add(c).get_json()["comment"]["id"]
            r = c.post(f"/api/runs/r1/reel/comments/{cid}", json={"action": "delete"})
            assert r.status_code == 200 and r.get_json()["deleted"] == cid
            assert c.get("/api/runs/r1/reel/comments").get_json()["comments"] == []
            # second delete is a clean 404
            r = c.post(f"/api/runs/r1/reel/comments/{cid}", json={"action": "delete"})
            assert r.status_code == 404

    def test_unknown_action_is_400(self, app_env):
        app, *_ = app_env
        with app.test_client() as c:
            _as(c, "alpha")
            cid = _add(c).get_json()["comment"]["id"]
            r = c.post(f"/api/runs/r1/reel/comments/{cid}", json={"action": "frobnicate"})
            assert r.status_code == 400

    def test_mutate_missing_comment_is_404(self, app_env):
        app, *_ = app_env
        with app.test_client() as c:
            _as(c, "alpha")
            r = c.post("/api/runs/r1/reel/comments/deadbeef", json={"action": "resolve"})
            assert r.status_code == 404

    def test_comment_id_scoped_to_its_run(self, app_env):
        """A comment created under r1 cannot be touched via r2's URL."""
        app, *_ = app_env
        with app.test_client() as c:
            _as(c, "alpha")
            cid = _add(c, run="r1").get_json()["comment"]["id"]
            # r2 is also owned by alpha (access ok) but the id isn't r2's.
            r = c.post(f"/api/runs/r2/reel/comments/{cid}", json={"action": "delete"})
            assert r.status_code == 404
            # still present under r1
            j = c.get("/api/runs/r1/reel/comments").get_json()
            assert [x["id"] for x in j["comments"]] == [cid]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_empty_body_is_400(self, app_env):
        app, *_ = app_env
        with app.test_client() as c:
            _as(c, "alpha")
            assert _add(c, body="   ").status_code == 400

    def test_negative_time_is_400(self, app_env):
        app, *_ = app_env
        with app.test_client() as c:
            _as(c, "alpha")
            assert _add(c, t_ms=-5).status_code == 400

    def test_non_numeric_time_is_400(self, app_env):
        app, *_ = app_env
        with app.test_client() as c:
            _as(c, "alpha")
            assert _add(c, t_ms="banana").status_code == 400


# ---------------------------------------------------------------------------
# Access control + run existence
# ---------------------------------------------------------------------------


class TestAccess:
    def test_foreign_org_cannot_read(self, app_env):
        app, *_ = app_env
        with app.test_client() as c:
            _as(c, "alpha")
            _add(c, body="secret")
        with app.test_client() as other:
            _as(other, "beta")
            assert other.get("/api/runs/r1/reel/comments").status_code == 404

    def test_foreign_org_cannot_write(self, app_env):
        app, *_ = app_env
        with app.test_client() as other:
            _as(other, "beta")
            assert _add(other, run="r1").status_code == 404

    def test_foreign_org_cannot_mutate(self, app_env):
        app, *_ = app_env
        with app.test_client() as c:
            _as(c, "alpha")
            cid = _add(c).get_json()["comment"]["id"]
        with app.test_client() as other:
            _as(other, "beta")
            r = other.post(f"/api/runs/r1/reel/comments/{cid}", json={"action": "delete"})
            assert r.status_code == 404
        # still there for the owner
        with app.test_client() as c:
            _as(c, "alpha")
            assert len(c.get("/api/runs/r1/reel/comments").get_json()["comments"]) == 1

    def test_unknown_run_is_404(self, app_env):
        app, *_ = app_env
        with app.test_client() as c:
            _as(c, "alpha")
            assert c.get("/api/runs/nope/reel/comments").status_code == 404
            assert _add(c, run="nope").status_code == 404


# ---------------------------------------------------------------------------
# CSRF: the front-end relies on JSON POSTs being exempt by content-type
# ---------------------------------------------------------------------------


class TestCsrf:
    def test_json_post_works_under_enforced_csrf(self, app_env):
        app, *_ = app_env
        with app.test_client() as c:
            _as(c, "alpha")  # set org while CSRF is still relaxed
            app.config["ENFORCE_CSRF"] = True
            try:
                # JSON content-type -> exempt -> succeeds without a token.
                assert _add(c, body="json ok").status_code == 201
                # A form post carries no token and is refused.
                r = c.post("/api/runs/r1/reel/comments", data={"body": "x", "t_ms": 1})
                assert r.status_code == 403
            finally:
                app.config["ENFORCE_CSRF"] = False


# ---------------------------------------------------------------------------
# Run-deletion cleanup + page wiring
# ---------------------------------------------------------------------------


class TestCleanupAndWiring:
    def test_run_deletion_cascade_purges_comments(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            _as(c, "alpha")
            _add(c, body="one")
            _add(c, target="card:x", body="two")

        from mediahub.privacy.erasure import run_deletion_cascade
        from mediahub.workflow import review_comments as rc

        assert rc.count_comments("r1") == 2
        report = run_deletion_cascade("r1")
        assert report["review_comments"] == 2
        assert rc.count_comments("r1") == 0

    def test_delete_run_helper_purges_comments(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            _as(c, "alpha")
            _add(c, body="bye")
        from mediahub.workflow import review_comments as rc

        assert rc.count_comments("r1") == 1
        wm._delete_run("r1")
        assert rc.count_comments("r1") == 0

    def test_page_js_ships_the_comment_helpers(self, app_env):
        app, wm, _ = app_env
        js = wm._card_creative_js()
        for needle in ("mhReelComments", "mhRenderReel", "mhRenderReelCommentsOnly"):
            assert needle in js, needle
        # The composer posts JSON (CSRF-exempt) and never injects user text as HTML.
        assert "application/json" in js
        assert "textContent" in js

    def test_content_builder_renders_reel_comment_surface(self, app_env):
        """The full content builder (an approved card) ships the reel panel,
        the comment helpers, and the on-load restore script — exercising the
        f-string brace-escaping in the live page, not just the JS helper."""
        app, wm, _ = app_env
        run = {
            "run_id": "r1",
            "profile_id": "alpha",
            "meet_name": "Test Open",
            "meet": {"name": "Test Open"},
            "recognition_report": {
                "ranked_achievements": [
                    {
                        "id": "swim-1",
                        "rank": 1,
                        "priority": 0.9,
                        "achievement": {
                            "swim_id": "swim-1",
                            "swimmer_name": "Eira Hughes",
                            "event": "100m Freestyle",
                            "time": "59.80",
                        },
                    }
                ]
            },
            "cards": [{"id": "swim-1", "swimmer_name": "Eira Hughes"}],
        }
        (wm.RUNS_DIR / "r1.json").write_text(json.dumps(run), encoding="utf-8")

        from mediahub.workflow import WorkflowStore
        from mediahub.workflow.status import CardStatus

        WorkflowStore(wm.RUNS_DIR).set_status("r1", "swim-1", CardStatus.APPROVED)

        with app.test_client() as c:
            _as(c, "alpha")
            resp = c.get("/pack/r1")
            assert resp.status_code == 200
            html = resp.get_data(as_text=True)
        assert 'id="reel-panel"' in html
        assert "mhReelComments" in html
        assert "mhRenderReelCommentsOnly" in html
        assert "/comments?target=reel" in html  # the on-load restore probe
