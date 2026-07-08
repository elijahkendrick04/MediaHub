"""D-18 — a downloaded (unpublished) newsletter must not silently drop images.

Card images were resolved to public URLs only when a newsletter was published;
downloading an unpublished draft left every card ``src`` empty and the renderer
omitted the ``<img>`` — so "Download email HTML" → paste into Mailchimp produced
an email with all result-card images missing, while the preview iframe (which
passes ?preview=1) showed them fine. The download now embeds each card image as
an inline ``data:`` URI, falling back to an honest placeholder, never a blank.
"""

from __future__ import annotations

import importlib
import json
from datetime import date

import pytest


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    for sub in ("runs_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    return app, tmp_path


def _login(client, pid="club-a"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=pid, display_name="Club A"))
    with client.session_transaction() as s:
        s["active_profile_id"] = pid


def _seed_approved_run(tmp_path, run_id="r1", profile_id="club-a"):
    rd = tmp_path / "runs_v4"
    rd.mkdir(parents=True, exist_ok=True)
    run = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "County Champs", "date": date.today().isoformat()},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "achievement": {
                        "type": "pb_confirmed",
                        "swimmer_name": "Ada Lovelace",
                        "event": "100m Free",
                        "swim_id": "a1",
                    },
                    "priority": 0.9,
                    "rank": 1,
                }
            ]
        },
        "cards": [],
    }
    (rd / f"{run_id}.json").write_text(json.dumps(run))
    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    WorkflowStore(rd).set_status(run_id, "a1", CardStatus.APPROVED)


def _seed_visual(tmp_path, run_id, card_id, brief):
    vdir = tmp_path / "runs_v4" / run_id / "visuals" / brief
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "visual.json").write_text(json.dumps({"content_item_id": card_id, "id": brief}))
    (vdir / "feed_portrait.png").write_bytes(b"\x89PNG fake-bytes")


def _new_card_ref_newsletter(client, card_refs):
    nid = client.post(
        "/api/newsletters/generate",
        json={"format": "blank", "range": "this_season", "with_ai": False},
    ).get_json()["newsletter_id"]
    from mediahub.email_design import store as ns

    data = ns.load_newsletter("club-a", nid).to_dict()
    data["sections"] = [
        {
            "blocks": [
                {"kind": "card", "props": {"title": "T", "body": "b", "card_ref": ref}}
                for ref in card_refs
            ]
        }
    ]
    client.post(f"/api/newsletters/{nid}/save", json={"spec": data})
    return nid


def test_unpublished_download_embeds_rendered_card_image(app_env):
    app, tmp = app_env
    c = app.test_client()
    _login(c)
    _seed_approved_run(tmp)
    _seed_visual(tmp, "r1", "a1", "brief-a")
    nid = _new_card_ref_newsletter(c, ["r1/a1"])

    rd = c.get(f"/api/newsletters/{nid}/html?dl=1")
    assert rd.status_code == 200
    body = rd.get_data(as_text=True)
    # The image is embedded inline, not dropped — a real raster data URI.
    assert "data:image/png;base64," in body


def test_unpublished_download_of_unrendered_card_shows_placeholder_not_blank(app_env):
    app, tmp = app_env
    c = app.test_client()
    _login(c)
    _seed_approved_run(tmp)  # approved, but NO visual rendered on disk
    nid = _new_card_ref_newsletter(c, ["r1/a1"])

    body = c.get(f"/api/newsletters/{nid}/html?dl=1").get_data(as_text=True)
    # Honest placeholder (an SVG data URI), never a silent missing image.
    assert "data:image/svg+xml;base64," in body
