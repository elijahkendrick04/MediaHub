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
def wall_world(app, web_module, tmp_path):
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

    conn = web_module._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        ("run-a-1", "org-a", "Spring Gala 2026", "gala.hy3"),
    )
    conn.commit()
    conn.close()
    return {"app": app, "wm": web_module, "tmp": tmp_path}


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


def test_corrupt_run_json_fails_closed(wall_world):
    """A run whose JSON snapshot is missing or corrupt cannot have its athletes'
    consent verified, so the wall must fail closed: none of that run's cards
    appear on the page/feeds and the card PNG route 404s — while the public page
    itself still renders 200. Before the fix, a corrupt snapshot resolved every
    card to an empty name and slipped past the consent gate with the real
    rendered graphic."""
    from mediahub.web.club_profile import load_profile
    from mediahub.web.public_wall import wall_cards, wall_image_path
    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    runs_dir = wall_world["tmp"] / "runs_v4"
    vdir = runs_dir / "run-corrupt" / "visuals" / "brief-c"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "visual.json").write_text(json.dumps({"content_item_id": "swim-c", "id": "brief-c"}))
    (vdir / "feed_portrait.png").write_bytes(b"\x89PNG fake")
    (runs_dir / "run-corrupt.json").write_text("{ not valid json ")  # corrupt snapshot
    WorkflowStore(runs_dir).set_status("run-corrupt", "swim-c", CardStatus.APPROVED)

    conn = wall_world["wm"]._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        ("run-corrupt", "org-a", "Corrupt Meet", "c.hy3"),
    )
    conn.commit()
    conn.close()

    prof = load_profile("org-a")
    assert "swim-c" not in {c["card_id"] for c in wall_cards(prof)}
    assert wall_image_path(prof, "run-corrupt", "swim-c") is None

    c = wall_world["app"].test_client()
    assert c.get("/wall/token-org-a-secret/card/run-corrupt/swim-c.png").status_code == 404
    assert c.get("/wall/token-org-a-secret").status_code == 200  # page still renders


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


def test_hostile_brand_colour_cannot_inject_css(wall_world):
    """A non-hex brand_primary (e.g. set via a raw form POST that bypasses the
    type=color widget) must not break out of the wall page's <style> block. It
    is gated to a hex colour and falls back to the default, so the injected CSS
    rule never reaches the public page or its embed."""
    from mediahub.web.club_profile import load_profile, save_profile

    payload = '#000;}body{background:url(//evil)}h1:after{content:"x"}header{'
    prof = load_profile("org-a")
    prof.brand_primary = payload
    save_profile(prof)

    c = wall_world["app"].test_client()
    for path in ("/wall/token-org-a-secret", "/wall/token-org-a-secret/embed"):
        html = c.get(path).get_data(as_text=True)
        assert "}body{" not in html  # no CSS rule break-out
        assert "url(//evil)" not in html  # no injected beacon
        assert "border-bottom:3px solid #0A2540" in html  # fell back to the safe default


def test_powered_by_badge_opens_in_new_context(wall_world):
    """The 'Powered by MediaHub' badge must carry target=_blank + rel noopener
    noreferrer so that, inside an embedded (iframed) wall, clicking it does not
    navigate the club's own iframe to MediaHub's signup page (in-frame takeover)."""
    c = wall_world["app"].test_client()
    for path in ("/wall/token-org-a-secret", "/wall/token-org-a-secret/embed"):
        html = c.get(path).get_data(as_text=True)
        assert 'class="powered"' in html
        assert 'target="_blank"' in html
        assert 'rel="noopener noreferrer"' in html


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


# ---- RUNS_DIR override (regression) ----------------------------------------


def test_wall_honours_runs_dir_override_distinct_from_data_dir(tmp_path, monkeypatch):
    """The wall must read runs from RUNS_DIR when it points OUTSIDE
    DATA_DIR/runs_v4 — render.yaml sets RUNS_DIR and .env.example documents it,
    and every sibling helper (web.py RUNS_DIR, content_pack.builder,
    compliance.retention, autonomy.app_env) honours it. Before the fix
    public_wall hardcoded DATA_DIR/runs_v4, so a deployment with a distinct
    RUNS_DIR served an empty wall while cards were approved and rendered.
    """
    data_dir = tmp_path / "data"
    runs_dir = tmp_path / "elsewhere_runs"  # deliberately != data_dir/runs_v4
    data_dir.mkdir(parents=True)
    runs_dir.mkdir(parents=True)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, load_profile, save_profile
    from mediahub.web.public_wall import _runs_dir, wall_cards, wall_image_path

    # public_wall now resolves to the SAME place web.py does.
    assert str(_runs_dir()) == str(wm.RUNS_DIR) == str(runs_dir)

    save_profile(
        ClubProfile(
            profile_id="org-a",
            display_name="Org A SC",
            public_wall_enabled=True,
            public_wall_token="tok-a",
        )
    )
    _seed_run(runs_dir, "run-a-1", "org-a")

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

    cards = wall_cards(load_profile("org-a"))
    assert {c["card_id"] for c in cards} == {"swim-1"}  # found in the custom RUNS_DIR
    assert wall_image_path(load_profile("org-a"), "run-a-1", "swim-1") is not None

    client = app.test_client()
    assert client.get("/wall/tok-a").status_code == 200
    assert client.get("/wall/tok-a/card/run-a-1/swim-1.png").status_code == 200


# ---- output-injection safety across every public surface (regression) ------


def test_hostile_names_are_neutralised_on_every_surface(wall_world):
    """A hostile swimmer/meet/club name must not break out on ANY public exit:
    the HTML page, the RSS feed (well-formed XML, no raw script), or the JSON
    feed (served as application/json). Locks the escaping so a future edit to
    _wall_page_html / the RSS builder can't reintroduce stored XSS.
    """
    import xml.dom.minidom as minidom

    from mediahub.web.club_profile import load_profile, save_profile

    payload = "<script>alert(1)</script>\"><img src=x onerror=alert(2)>&'"
    prof = load_profile("org-a")
    prof.display_name = payload
    prof.public_wall_initials_only = False
    save_profile(prof)

    runs = wall_world["tmp"] / "runs_v4"
    data = json.loads((runs / "run-a-1.json").read_text())
    data["meet"] = {"name": payload}
    data["recognition_report"]["ranked_achievements"][0]["achievement"]["swimmer_name"] = payload
    (runs / "run-a-1.json").write_text(json.dumps(data))

    c = wall_world["app"].test_client()

    html = c.get("/wall/token-org-a-secret").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html  # neutralised as text

    rss = c.get("/wall/token-org-a-secret/feed.rss")
    body = rss.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in body
    minidom.parseString(body)  # raises if the RSS is not well-formed XML

    j = c.get("/wall/token-org-a-secret/feed.json")
    assert j.headers["Content-Type"].startswith("application/json")
    assert j.get_json()["items"]  # parses cleanly; consumers escape text fields
