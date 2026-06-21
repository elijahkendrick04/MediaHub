"""Roadmap 1.14 — per-channel previews + safe zones + IG grid.

Pins the platform-spec data, the caption-fold / hashtag-cap / mention-validation
rules, the safe-zone geometry, the Instagram grid arrangement, and the web
surfaces (per-pack channel preview, grid, the live preview API) — including
org-gating and tenant isolation.
"""

from __future__ import annotations

import pytest

from mediahub.channel_preview import (
    all_platforms,
    hashtag_status,
    instagram_grid,
    platform,
    preview_card,
    truncate_caption,
    validate_handle,
)


# ---------------------------------------------------------------------------
# Specs
# ---------------------------------------------------------------------------


def test_platform_lookup_and_aliases():
    assert platform("instagram").name == "Instagram"
    assert platform("IG").slug == "instagram"  # alias + case-insensitive
    assert platform("twitter").slug == "x"
    assert platform("fb").slug == "facebook"
    assert platform("nonesuch") is None
    slugs = {p.slug for p in all_platforms()}
    assert {"instagram", "tiktok", "x", "facebook", "linkedin"} <= slugs


def test_format_aspect_labels():
    ig = platform("instagram")
    assert ig.format("feed").aspect_label() == "4:5"
    assert ig.format("story").aspect_label() == "9:16"
    assert ig.format("square").aspect_label() == "1:1"
    # Unknown format name falls back to the first format, never errors.
    assert ig.format("bogus").name == ig.formats[0].name


# ---------------------------------------------------------------------------
# Caption fold / hashtags / mentions
# ---------------------------------------------------------------------------


def test_truncate_caption_fold_and_limits():
    ig = platform("instagram")
    short = truncate_caption("Short and sweet", ig)
    assert short["truncated"] is False and short["hidden"] == ""

    long = "word " * 60  # 300 chars, > IG's 125 truncate point
    t = truncate_caption(long, ig)
    assert t["truncated"] is True
    assert len(t["shown"]) <= ig.caption_truncate
    assert t["shown"] and t["hidden"]
    # Reassembling shown+hidden preserves every non-space character.
    assert t["shown"].replace(" ", "") + t["hidden"].replace(" ", "") == long.replace(" ", "")

    # X has a hard 280-char limit: a longer caption is flagged over_limit.
    x = platform("x")
    over = truncate_caption("a" * 281, x)
    assert over["over_limit"] is True


def test_hashtag_cap():
    ig = platform("instagram")
    assert hashtag_status(["t"] * 30, ig)["within"] is True
    assert hashtag_status(["t"] * 31, ig)["within"] is False
    # Uncapped platform is always within.
    x = platform("x")
    assert hashtag_status(["t"] * 99, x)["within"] is True
    assert hashtag_status([], ig)["count"] == 0


def test_validate_handle_per_platform():
    x = platform("x")
    ig = platform("instagram")
    assert validate_handle("@swansea_swim", x)["valid"] is True
    assert validate_handle("sixteencharacter", x)["valid"] is False  # >15 for X
    assert validate_handle("swansea.swim", ig)["valid"] is True  # dot ok on IG
    assert validate_handle("bad handle", ig)["valid"] is False  # space invalid
    assert validate_handle("", ig)["valid"] is False
    assert validate_handle("swansea.swim", x)["valid"] is False  # dot invalid on X


# ---------------------------------------------------------------------------
# preview_card + safe zones + grid
# ---------------------------------------------------------------------------


def test_preview_card_safe_zone_only_on_story():
    feed = preview_card({"caption": "hi"}, "instagram", format_name="feed")
    sz = feed["format"]["safe_zone"]
    assert sz == {"top": 0.0, "right": 0.0, "bottom": 0.0, "left": 0.0}

    story = preview_card({"caption": "hi"}, "instagram", format_name="story")
    sz = story["format"]["safe_zone"]
    assert sz["top"] > 0 and sz["bottom"] > 0  # chrome bands exist on stories

    assert preview_card({"caption": "x"}, "myspace") is None  # unknown platform


def test_instagram_grid_pads_last_row():
    rows = instagram_grid([{"title": str(i)} for i in range(4)], columns=3)
    assert len(rows) == 2
    assert all(len(r) == 3 for r in rows)
    assert sum(1 for c in rows[-1] if c.get("placeholder")) == 2
    assert instagram_grid([], columns=3) == []


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
    save_profile(ClubProfile(profile_id="org-other", display_name="Other Club"))

    application = create_app()
    application.config["TESTING"] = True
    application.config["SECRET_KEY"] = "test-secret"
    return application


def _with_org(client, org_id: str):
    with client.session_transaction() as sess:
        sess["active_profile_id"] = org_id


def _seed_pack(profile_id="org-test", caption="A great day at the gala!"):
    from mediahub.club_platform import stub_pack_store as sps

    rec = sps.save_pack(
        "free_text",
        {"free_text": caption},
        [{"caption": caption, "hashtags": ["swim", "pb"]}],
        profile_id=profile_id,
    )
    return rec["pack_id"]


def test_preview_routes_require_org(app_with_org):
    with app_with_org.test_client() as client:
        assert client.post("/api/channel-preview", json={"caption": "x"}).status_code == 403
        assert client.get("/plan/preview/anything").status_code == 302
        assert client.get("/plan/grid").status_code == 302


def test_channel_preview_page_and_switching(app_with_org):
    with app_with_org.test_client() as client:
        _with_org(client, "org-test")
        pid = _seed_pack(caption="word " * 60)  # long enough to fold on IG/TikTok

        page = client.get(f"/plan/preview/{pid}?platform=instagram&format=story")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert "safe area" in html  # safe-zone overlay on story
        assert "9:16" in html
        assert "… more" in html  # caption folds
        assert "TikTok" in html  # platform tabs present

        # Switching platform works and changes the active tab target.
        assert client.get(f"/plan/preview/{pid}?platform=tiktok&format=video").status_code == 200
        # A feed format has no safe-zone band.
        feed = client.get(f"/plan/preview/{pid}?platform=instagram&format=feed").get_data(
            as_text=True
        )
        assert "4:5" in feed


def test_channel_preview_is_tenant_isolated(app_with_org):
    pid = _seed_pack(profile_id="org-other")
    with app_with_org.test_client() as client:
        _with_org(client, "org-test")  # different org
        assert client.get(f"/plan/preview/{pid}").status_code == 404


def test_grid_page_lists_org_drafts_only(app_with_org):
    from mediahub.club_platform import stub_pack_store as sps

    with app_with_org.test_client() as client:
        _with_org(client, "org-test")
        pid = _seed_pack(caption="Mine")
        sps.set_planned_date(pid, "2026-06-20")
        _seed_pack(profile_id="org-other", caption="Theirs")

        html = client.get("/plan/grid").get_data(as_text=True)
        assert "2026-06-20" in html  # the planned tile shows its date
        assert "Theirs" not in html  # other org's draft never appears


def test_api_channel_preview(app_with_org):
    with app_with_org.test_client() as client:
        _with_org(client, "org-test")
        r = client.post(
            "/api/channel-preview",
            json={"caption": "a" * 300, "platform": "x", "hashtags": ["t"]},
        )
        body = r.get_json()
        assert r.status_code == 200 and body["ok"] is True
        assert body["preview"]["caption"]["over_limit"] is True  # >280 on X
        # Unknown platform → 400.
        assert client.post(
            "/api/channel-preview", json={"caption": "x", "platform": "myspace"}
        ).status_code == 400
