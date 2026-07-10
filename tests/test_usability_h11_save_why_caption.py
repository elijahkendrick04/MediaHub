"""H-11 — "Use in next caption" result can be saved to the card; the no-key
error uses the standard honest wording (no "heuristic mode").

The audit found the Why-this-card "Use in next caption" flow rendered a
read-only panel whose only action was Copy — nothing persisted the woven
caption — and its no-key branch showed an off-brand "AI is in heuristic
mode. Contact your administrator to enable AI." instead of the standard
"AI captions are unavailable on this deployment." wording used everywhere
else.

This file pins the fix:

  * the result panel gains a "Save to card" button beside Copy, persisting
    through the SAME workflow set_edits route (and the same three tone
    headline slots) the edit drawer's Save uses, with success/failure toasts
    that name the failure reason;
  * the generated button passes the workflow save URL + card id into
    ``mhUseWhyInCaption``;
  * the phrase "heuristic mode" no longer appears anywhere user-facing —
    the no-key branch shows the server's standard message.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_WEB_SRC = (_ROOT / "src" / "mediahub" / "web" / "web.py").read_text(encoding="utf-8")


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True
    return types.SimpleNamespace(app=app, wm=wm, tmp=tmp_path)


def _save_org(world, pid="riverbend", name="Riverbend SC"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id=pid,
            display_name=name,
            brand_voice_summary="Proud, warm, community-first.",
        )
    )
    return pid


def _seed_run(world, run_id, *, profile_id):
    runs_dir = world.tmp / "runs_v4"
    runs_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "Riverbend Autumn Sprint Gala"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "rank": 1,
                    "quality_band": "elite",
                    "priority": 0.92,
                    "achievement": {
                        "swim_id": "s1",
                        "swimmer_name": "Tamsin Veldt",
                        "event": "200m IM",
                        "headline": "Tamsin Veldt takes gold in the 200m IM",
                        "type": "medal_gold",
                        "confidence": 0.91,
                        "confidence_label": "high",
                    },
                }
            ]
        },
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(data))


# --------------------------------------------------------------------------- #
# 1. The button hands the workflow save URL + card id to the JS
# --------------------------------------------------------------------------- #
class TestButtonWiring:
    def test_button_carries_save_url_and_card_id(self, world):
        with world.app.test_request_context("/"):
            btn, panel = world.wm._use_in_caption_html("runx", "s1", "cu1")
        assert "Use in next caption" in btn
        assert "/api/workflow/runx/s1" in btn
        # Signature: mhUseWhyInCaption(this, capUrl, panelId, saveUrl, cardId)
        m = re.search(r"mhUseWhyInCaption\(this, (.*)\)", btn)
        assert m and m.group(1).count(",") == 3
        assert '"s1"' in m.group(1)
        assert panel.startswith('<div id="why-cap-cu1"')

    def test_js_signature_accepts_save_args(self):
        assert (
            "window.mhUseWhyInCaption = function(btn, captionUrl, panelId, saveUrl, cardId)"
            in _WEB_SRC
        )


# --------------------------------------------------------------------------- #
# 2. Save to card — same route + slots as the drawer's Save, honest toasts
# --------------------------------------------------------------------------- #
class TestSaveToCard:
    def test_panel_js_builds_a_save_to_card_button(self):
        assert "saveBtn.textContent = 'Save to card';" in _WEB_SRC
        # It POSTs the drawer's exact persistence shape.
        assert "JSON.stringify({action: 'set_edits', edits: {" in _WEB_SRC
        assert "'Caption saved to the card'" in _WEB_SRC
        assert "'Could not save the caption — ' + m" in _WEB_SRC

    def test_workflow_route_persists_the_saved_caption(self, world):
        """The exact POST the Save-to-card button fires persists the caption
        into the card's edited_captions (so the pack build honours it)."""
        pid = _save_org(world)
        _seed_run(world, "h11run0001", profile_id=pid)
        c = world.app.test_client()
        with c.session_transaction() as sess:
            sess["active_profile_id"] = pid
        text = "Gold for Tamsin — woven from the reasoning"
        r = c.post(
            "/api/workflow/h11run0001/s1",
            json={
                "action": "set_edits",
                "edits": {
                    "warm-club_headline": text,
                    "hype_headline": text,
                    "data-led_headline": text,
                },
            },
        )
        assert r.status_code == 200
        assert r.get_json()["ok"] is True
        edits = world.wm._get_wf_store().load("h11run0001")["s1"].edited_captions
        assert edits["warm-club_headline"] == text


# --------------------------------------------------------------------------- #
# 3. No-key copy — the standard wording; "heuristic mode" gone
# --------------------------------------------------------------------------- #
class TestNoKeyCopy:
    def test_heuristic_mode_never_reaches_a_page(self, world):
        pid = _save_org(world)
        _seed_run(world, "h11run0002", profile_id=pid)
        c = world.app.test_client()
        with c.session_transaction() as sess:
            sess["active_profile_id"] = pid
        html = c.get("/review/h11run0002").get_data(as_text=True)
        assert "heuristic mode" not in html
        assert "AI is in heuristic mode" not in html

    def test_no_key_branch_uses_the_standard_wording(self):
        assert "AI is in heuristic mode" not in _WEB_SRC
        # The panel prefers the server's message and falls back to the
        # standard sentence used on every other caption surface.
        assert (
            "'AI captions are unavailable on this deployment. "
            "Contact your administrator to enable them.'" in _WEB_SRC
        )
