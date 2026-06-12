"""PC.10 — public achievements wall: token resolution, approved-only feed,
embed/RSS/JSON surfaces, revocation, and tenant isolation."""

from __future__ import annotations

import importlib
import json

import pytest


def _seed_run(runs_dir, run_id, profile_id, *, swimmer="Alice Smith", approved=True):
    runs_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "profile_id": profile_id,
        "meet_name": "Spring Gala 2026",
        "meet": {"name": "Spring Gala 2026"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "achievement": {
                        "swim_id": "swim-1",
                        "swimmer_name": swimmer,
                        "event": "100m Freestyle",
                        "time": "59.10",
                    }
                },
                {
                    "achievement": {
                        "swim_id": "swim-2",
                        "swimmer_name": "Bob Jones",
                        "event": "50m Backstroke",
                        "time": "31.42",
                    }
                },
            ]
        },
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(data))

    # Visual sidecars + PNGs for both cards.
    for cid, brief in (("swim-1", "brief-a"), ("swim-2", "brief-b")):
        vdir = runs_dir / run_id / "visuals" / brief
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "visual.json").write_text(json.dumps({"content_item_id": cid, "id": brief}))
        (vdir / "feed_portrait.png").write_bytes(b"\x89PNG fake")

    if approved:
        from mediahub.workflow.status import CardStatus
        from mediahub.workflow.store import WorkflowStore

        ws = WorkflowStore(runs_dir)
        ws.set_status(run_id, "swim-1", CardStatus.APPROVED)
        # swim-2 stays in QUEUE — must never appear publicly.


@pytest.fixture
def wall_world(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="org-a",
            display_name="Org A SC",
            public_wall_enabled=True,
            public_wall_token="token-org-a-secret",
        )
    )
    save_profile(
        ClubProfile(
            profile_id="org-b",
            display_name="Org B SC",
            public_wall_enabled=True,
            public_wall_token="token-org-b-secret",
        )
    )

    _seed_run(tmp_path / "runs_v4", "run-a-1", "org-a")

    app = wm.create_app()
    app.config["TESTING"] = True
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        ("run-a-1", "org-a", "Spring Gala 2026", "gala.hy3"),
    )
    conn.commit()
    conn.close()
    return {"app": app, "wm": wm, "tmp": tmp_path}


# ---- module-level helpers ------------------------------------------------


def test_initials_of():
    from mediahub.web.public_wall import initials_of

    assert initials_of("Alice Smith") == "A.S."
    assert initials_of("alice") == "A."
    assert initials_of("") == ""


def test_profile_for_token(wall_world):
    from mediahub.web.public_wall import profile_for_token

    assert profile_for_token("token-org-a-secret").profile_id == "org-a"
    assert profile_for_token("wrong") is None
    assert profile_for_token("") is None


def test_disabled_wall_does_not_resolve(wall_world):
    from mediahub.web.club_profile import load_profile, save_profile
    from mediahub.web.public_wall import profile_for_token

    prof = load_profile("org-a")
    prof.public_wall_enabled = False
    save_profile(prof)
    assert profile_for_token("token-org-a-secret") is None


def test_wall_cards_approved_only_and_initials(wall_world):
    from mediahub.web.club_profile import load_profile
    from mediahub.web.public_wall import wall_cards

    cards = wall_cards(load_profile("org-a"))
    assert len(cards) == 1  # swim-2 is queued, never public
    c = cards[0]
    assert c["card_id"] == "swim-1"
    assert "A.S." in c["title"]
    assert "Alice" not in c["title"]  # initials-only default
    assert "Alice" not in c["alt_text"]


def test_wall_cards_full_names_when_initials_off(wall_world):
    from mediahub.web.club_profile import load_profile, save_profile
    from mediahub.web.public_wall import wall_cards

    prof = load_profile("org-a")
    prof.public_wall_initials_only = False
    save_profile(prof)
    cards = wall_cards(load_profile("org-a"))
    assert "Alice Smith" in cards[0]["title"]


def test_wall_cards_respects_per_card_exclusion(wall_world):
    from mediahub.web.club_profile import load_profile, save_profile
    from mediahub.web.public_wall import wall_cards

    prof = load_profile("org-a")
    prof.public_wall_excluded_cards = ["run-a-1::swim-1"]
    save_profile(prof)
    assert wall_cards(load_profile("org-a")) == []


def test_other_org_token_sees_nothing(wall_world):
    from mediahub.web.club_profile import load_profile
    from mediahub.web.public_wall import wall_cards, wall_image_path

    prof_b = load_profile("org-b")
    assert wall_cards(prof_b) == []
    assert wall_image_path(prof_b, "run-a-1", "swim-1") is None


# ---- public routes ---------------------------------------------------------


def test_wall_page_renders(wall_world):
    c = wall_world["app"].test_client()
    r = c.get("/wall/token-org-a-secret")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "A.S." in html and "Alice" not in html
    assert "Powered by" in html and "MediaHub" in html
    assert r.headers["Cache-Control"].startswith("public")


def test_wall_embed_renders_without_header(wall_world):
    c = wall_world["app"].test_client()
    r = c.get("/wall/token-org-a-secret/embed")
    assert r.status_code == 200
    assert "<header>" not in r.get_data(as_text=True)


def test_wall_feeds(wall_world):
    c = wall_world["app"].test_client()
    j = c.get("/wall/token-org-a-secret/feed.json")
    assert j.status_code == 200
    data = j.get_json()
    assert data["club"] == "Org A SC"
    assert len(data["items"]) == 1
    assert "swim-1" in data["items"][0]["image"]

    r = c.get("/wall/token-org-a-secret/feed.rss")
    assert r.status_code == 200
    assert "rss+xml" in r.headers["Content-Type"]
    body = r.get_data(as_text=True)
    assert "<rss" in body and "<item>" in body and "Spring Gala 2026" in body


def test_wall_card_png_served_and_gated(wall_world):
    c = wall_world["app"].test_client()
    ok = c.get("/wall/token-org-a-secret/card/run-a-1/swim-1.png")
    assert ok.status_code == 200
    assert ok.headers["Content-Type"].startswith("image/png")
    # Queued card never served.
    assert c.get("/wall/token-org-a-secret/card/run-a-1/swim-2.png").status_code == 404
    # Cross-tenant: org-b's token cannot fetch org-a's card.
    assert c.get("/wall/token-org-b-secret/card/run-a-1/swim-1.png").status_code == 404


def test_bad_token_404s_everywhere(wall_world):
    c = wall_world["app"].test_client()
    for path in (
        "/wall/nope",
        "/wall/nope/embed",
        "/wall/nope/feed.json",
        "/wall/nope/feed.rss",
        "/wall/nope/card/run-a-1/swim-1.png",
    ):
        assert c.get(path).status_code == 404, path


# ---- workspace settings routes ---------------------------------------------


def _pin(client, profile_id):
    return client.post("/api/organisation/active", data={"profile_id": profile_id})


def test_enable_disable_revokes_token(wall_world):
    from mediahub.web.club_profile import load_profile, save_profile

    # Start from OFF.
    prof = load_profile("org-a")
    prof.public_wall_enabled = False
    prof.public_wall_token = ""
    save_profile(prof)

    c = wall_world["app"].test_client()
    assert _pin(c, "org-a").status_code == 200

    # Enable → a token is generated and the wall resolves.
    r = c.post("/public-wall/update", data={"action": "enable"})
    assert r.status_code == 302
    token = load_profile("org-a").public_wall_token
    assert token
    assert c.get(f"/wall/{token}").status_code == 200

    # Disable → token cleared, old URL 404s (revocation is structural).
    c.post("/public-wall/update", data={"action": "disable"})
    prof = load_profile("org-a")
    assert prof.public_wall_enabled is False
    assert prof.public_wall_token == ""
    assert c.get(f"/wall/{token}").status_code == 404


def test_settings_exclude_include_card(wall_world):
    from mediahub.web.club_profile import load_profile

    c = wall_world["app"].test_client()
    assert _pin(c, "org-a").status_code == 200
    c.post("/public-wall/update", data={"action": "exclude", "card_key": "run-a-1::swim-1"})
    assert load_profile("org-a").public_wall_excluded_cards == ["run-a-1::swim-1"]
    c.post("/public-wall/update", data={"action": "include", "card_key": "run-a-1::swim-1"})
    assert load_profile("org-a").public_wall_excluded_cards == []


def test_settings_page_requires_org(wall_world):
    c = wall_world["app"].test_client()
    r = c.get("/public-wall")
    assert r.status_code == 302  # no pinned org → setup redirect
