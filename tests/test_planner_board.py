"""Roadmap 1.14 — the planning board (Kanban / whiteboard).

Pins the per-org board store (add / move / delete / promote-to-draft, the column
model, ordering, tenant isolation) and the web surfaces (the board page + the
board APIs, including org-gating and that 'promote' mints a real org-owned draft).
"""

from __future__ import annotations

import pytest

from mediahub.content_engine.board import (
    COLUMNS,
    add_card,
    board_by_column,
    delete_card,
    link_pack,
    load_board,
    move_card,
)

ORG_A = "org-alpha"
ORG_B = "org-beta"


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def test_add_move_delete_and_columns(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    assert load_board(ORG_A) == []
    a = add_card(ORG_A, "Thank the volunteers", "after the gala")
    assert a is not None and a.column == "idea"
    b = add_card(ORG_A, "New kit launch")
    assert b is not None

    # Empty title is refused (honest None, not a blank card).
    assert add_card(ORG_A, "   ") is None

    # Move through the lifecycle; an unknown column is refused.
    assert move_card(ORG_A, a.id, "approved").column == "approved"
    assert move_card(ORG_A, a.id, "nonsense") is None
    assert move_card(ORG_A, "no-such-card", "idea") is None

    cols = board_by_column(load_board(ORG_A))
    assert set(cols.keys()) >= set(COLUMNS)
    assert {c.id for c in cols["approved"]} == {a.id}
    assert {c.id for c in cols["idea"]} == {b.id}

    assert delete_card(ORG_A, a.id) is True
    assert delete_card(ORG_A, a.id) is False  # already gone
    assert {c.id for c in load_board(ORG_A)} == {b.id}


def test_link_pack_advances_card(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    c = add_card(ORG_A, "Sponsor shout-out")
    linked = link_pack(ORG_A, c.id, "pack123", column="drafted")
    assert linked.pack_id == "pack123" and linked.column == "drafted"


def test_board_is_tenant_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    add_card(ORG_A, "Alpha idea")
    add_card(ORG_B, "Beta idea")
    assert {c.title for c in load_board(ORG_A)} == {"Alpha idea"}
    assert {c.title for c in load_board(ORG_B)} == {"Beta idea"}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_org(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.web import create_app

    save_profile(ClubProfile(profile_id="org-test", display_name="Test Club"))

    application = create_app()
    application.config["TESTING"] = True
    application.config["SECRET_KEY"] = "test-secret"
    return application


def _with_org(client, org_id: str):
    with client.session_transaction() as sess:
        sess["active_profile_id"] = org_id


def test_board_routes_require_org(app_with_org):
    with app_with_org.test_client() as client:
        assert client.get("/plan/board").status_code == 302
        assert client.get("/api/plan/board").status_code == 403
        assert client.post("/api/plan/board/add", json={"title": "x"}).status_code == 403


def test_board_survives_non_utf8_file(app_with_org, tmp_path):
    """Audit (QA-016 class): a non-UTF-8 board file must load empty, not 500
    /plan/board and every board API with an unhandled UnicodeDecodeError."""
    (tmp_path / "plan_board").mkdir(parents=True, exist_ok=True)
    (tmp_path / "plan_board" / "org-test.json").write_bytes(
        b'{"cards": [{"id": "c1", "title": "caf\xe9\xff", "column": "idea"}]}'
    )
    # Module-level: the corrupt board degrades to empty rather than raising.
    assert load_board("org-test") == []
    with app_with_org.test_client() as client:
        _with_org(client, "org-test")
        assert client.get("/plan/board").status_code == 200
        assert client.get("/api/plan/board").status_code == 200
        assert client.post("/api/plan/board/add", json={"title": "fresh"}).status_code == 200


def test_board_page_and_apis(app_with_org):
    with app_with_org.test_client() as client:
        _with_org(client, "org-test")

        assert client.get("/plan/board").status_code == 200

        # Add → idea column.
        r = client.post("/api/plan/board/add", json={"title": "Thank the volunteers"})
        cid = r.get_json()["card"]["id"]
        assert r.get_json()["card"]["column"] == "idea"
        # Empty title → 400.
        assert client.post("/api/plan/board/add", json={"title": ""}).status_code == 400

        # Move to approved.
        assert (
            client.post("/api/plan/board/move", json={"card_id": cid, "column": "approved"})
            .get_json()["card"]["column"]
            == "approved"
        )
        # Bad column → 400.
        assert client.post(
            "/api/plan/board/move", json={"card_id": cid, "column": "zzz"}
        ).status_code == 400

        # The page renders the card + the four columns.
        html = client.get("/plan/board").get_data(as_text=True)
        assert "Thank the volunteers" in html
        assert "Ideas" in html and "Scheduled" in html

        # Delete.
        assert client.post("/api/plan/board/delete", json={"card_id": cid}).get_json()["ok"] is True


def test_promote_mints_org_owned_draft(app_with_org):
    from mediahub.club_platform.stub_pack_store import load_pack

    with app_with_org.test_client() as client:
        _with_org(client, "org-test")
        cid = client.post(
            "/api/plan/board/add", json={"title": "Kit launch", "note": "Post about the new kit"}
        ).get_json()["card"]["id"]

        r = client.post("/api/plan/board/promote", json={"card_id": cid})
        body = r.get_json()
        assert r.status_code == 200 and body["ok"] is True
        pack_id = body["pack_id"]
        assert body["card"]["column"] == "drafted" and body["card"]["pack_id"] == pack_id

        # The promoted draft is a real, org-owned stub pack seeded from the idea.
        rec = load_pack(pack_id)
        assert rec is not None and rec["profile_id"] == "org-test"
        assert "new kit" in (rec["cards"][0]["caption"] or "").lower()

        # Promoting again is idempotent (returns the same pack).
        again = client.post("/api/plan/board/promote", json={"card_id": cid}).get_json()
        assert again["pack_id"] == pack_id and again.get("already") is True
