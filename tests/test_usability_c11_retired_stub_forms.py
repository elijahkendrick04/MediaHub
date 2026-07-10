"""C-11 — Sponsor Post and Session Update were removed from Create, but their
form routes stayed live and the UI kept pointing at them (drafts empty state,
old draft rows' "Generate new draft", plus Free Text existing twice via a
"legacy quick generator" link).

The forms are now retired behind one story — Free Text interprets such
prompts:
- GET /sponsor-post and /session-update redirect to the free-text landing
  with a ?seed= prompt (consumed by the landing textarea prefill, J-6);
  their POST methods are gone with the forms nothing renders any more
- the drafts empty state describes Free Text instead of the hidden types
- an old sponsor/session pack's "Generate new draft" seeds free-text
- the chat landing no longer links a duplicate "legacy quick generator"
  (it embeds the same one-shot form itself)
"""

from __future__ import annotations

import importlib
import pathlib

import pytest

ORG = "org-c11"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=ORG, display_name="Test Club"))
    app = wm.create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    assert c.post("/api/organisation/active", data={"profile_id": ORG}).status_code == 200
    return {"client": c, "wm": wm, "tmp": tmp_path}


def test_sponsor_post_get_redirects_to_seeded_free_text(env):
    r = env["client"].get("/sponsor-post", follow_redirects=False)
    assert r.status_code in (301, 302, 303, 307, 308)
    loc = r.headers["Location"]
    assert "/free-text" in loc
    assert "seed=" in loc
    assert "sponsor" in loc.lower()


def test_session_update_get_redirects_to_seeded_free_text(env):
    r = env["client"].get("/session-update", follow_redirects=False)
    assert r.status_code in (301, 302, 303, 307, 308)
    loc = r.headers["Location"]
    assert "/free-text" in loc
    assert "seed=" in loc
    assert "session" in loc.lower()


def test_retired_forms_no_longer_accept_posts(env):
    # Nothing renders a form that posts here any more; the POST method is
    # retired with the form (405, not a silent half-working generator).
    assert env["client"].post("/sponsor-post", data={}).status_code == 405
    assert env["client"].post("/session-update", data={}).status_code == 405


def test_drafts_empty_state_describes_free_text_not_hidden_types(env):
    html = env["client"].get("/drafts").get_data(as_text=True)
    assert "Sponsor Post" not in html
    assert "Session Update" not in html
    assert "Free" in html and "Text" in html


def test_old_sponsor_pack_new_draft_link_seeds_free_text(env):
    from mediahub.club_platform.stub_pack_store import save_pack

    rec = save_pack(
        "sponsor_activation",
        {"meet_name": "Autumn Gala", "sponsor_name": "Acme"},
        [
            {
                "platform": "Instagram",
                "caption": "Thanks Acme",
                "hashtags": [],
                "confidence": 0.7,
                "notes": "",
            }
        ],
        profile_id=ORG,
    )
    html = env["client"].get(f"/drafts/{rec['pack_id']}").get_data(as_text=True)
    assert "Generate new draft" in html
    # The link lands on free-text with a seed, not the retired form.
    assert "/free-text?seed=" in html
    assert "/sponsor-post" not in html


def test_chat_landing_has_single_one_shot_path(env):
    html = env["client"].get("/free-text").get_data(as_text=True)
    assert "legacy quick generator" not in html
    # The embedded one-shot form is still there.
    assert "/free-text/quick-build" in html


def test_no_stray_references_to_retired_stub_renderers():
    src = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")
    # The retired form renderers are gone, not just unlinked.
    assert '_render_stub("SponsorPostStub"' not in src
    assert '_render_stub("SessionUpdateStub"' not in src
    assert "Use the legacy quick generator" not in src
