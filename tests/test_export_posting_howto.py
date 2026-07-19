"""After approval, the Content builder's export disclosure offered nothing but
bare ZIP download buttons — no explanation of what the ZIP contains or how to
turn it into an Instagram/Facebook/Twitter post (audit finding c892a9c59486).

MediaHub never auto-publishes (see CLAUDE.md "External integrations"), so the
fix is on-page instructional copy only: what's inside the ZIP and how a
volunteer manually posts it, naming the actual platforms.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _run_payload(profile_id: str) -> dict:
    return {
        "run_id": "r1",
        "profile_id": profile_id,
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
                        "swimmer_name": "Swimmer One",
                        "event": "100m Freestyle",
                        "headline": "PB set",
                        "type": "pb",
                        "confidence_label": "high",
                        "time": "59.80",
                    },
                }
            ]
        },
    }


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.media_library.store as mls
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    mls._default_store = None
    app = wm.create_app()
    app.config["TESTING"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    (wm.RUNS_DIR / "r1.json").write_text(json.dumps(_run_payload("alpha")), encoding="utf-8")
    return app, wm, tmp_path


def _approve(tmp_path, *card_ids):
    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    ws = WorkflowStore(Path(tmp_path / "runs_v4"))
    for cid in card_ids:
        ws.set_status("r1", cid, CardStatus.APPROVED)


def _seed_visual(wm, card_id: str, brief_id: str) -> None:
    vdir = wm.RUNS_DIR / "r1" / "visuals" / brief_id
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "feed_portrait.png").write_bytes(PNG)
    (vdir / "visual.json").write_text(
        json.dumps(
            {
                "id": f"vis_{brief_id}",
                "content_item_id": card_id,
                "visual_ids": {f"vis_{brief_id}": "feed_portrait"},
                "layout_template": "story_card",
                "why_this_design": "seeded design",
                "sourced_asset_ids": [],
            }
        ),
        encoding="utf-8",
    )


def _pack_page(app) -> str:
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "alpha"})
        resp = c.get("/pack/r1")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def _export_disclosure(page: str) -> str:
    assert 'id="mh-export-pack"' in page
    return page.split('id="mh-export-pack"', 1)[1].split("</details>", 1)[0]


class TestExportGivesPostingGuidance:
    def test_disclosure_explains_what_to_do_with_the_zip(self, app_env, tmp_path):
        """Visible copy (not just a hover title=) must tell the approver the
        ZIP is ready to post and name the platforms it's sized for."""
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1")
        _seed_visual(wm, "swim-1", "cb_a")
        body = _export_disclosure(_pack_page(app))

        howto = body.split('id="mh-export-howto"', 1)
        assert len(howto) == 2, "no visible how-to-post copy next to the export buttons"
        howto_html = howto[1].split(">", 1)[1].split("</", 1)[0]

        for platform in ("Instagram", "Facebook", "Twitter"):
            assert platform in howto_html, f"{platform} not mentioned in the how-to copy"
