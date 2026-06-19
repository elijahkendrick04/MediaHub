"""P6.2 — web surface for the copilot, memory, suggestions and ASR seam."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest import mock

import pytest

from mediahub.ai_core.llm import ToolConversation
from mediahub.creative_brief.generator import CreativeBrief


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    return app, wm, tmp_path


def _seed_run(tmp_path: Path, run_id: str = "runA") -> str:
    run_dir = tmp_path / "runs_v4" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "recognition_report": {
                    "ranked_achievements": [
                        {"id": "c1", "priority": 0.9, "achievement": {"swim_id": "c1", "swimmer_name": "Alice Lee", "event": "100 Free", "time": "57.95", "headline": "New PB"}}
                    ]
                }
            }
        )
    )
    return run_id


def _seed_brief(tmp_path: Path, run_id: str, card_id: str = "c1"):
    bdir = tmp_path / "runs_v4" / run_id / "briefs"
    bdir.mkdir(parents=True, exist_ok=True)
    brief = CreativeBrief(
        id="cb_seed", content_item_id=card_id, profile_id="club", achievement_summary="",
        objective="", primary_hook="NEW PB", confidence_label="NEW PB", tone="data-led",
        layout_template="split_diagonal_hero", inspiration_pattern_id="", image_treatment="cutout",
        text_hierarchy=[], brand_instructions="", sponsor_instructions=None, sourced_asset_ids=[],
        safety_notes=[], why_this_design="", text_layers={"headline_line1": "OLD"},
        palette={"primary": "#0E5BFF", "secondary": "#101820", "accent": "#F4D58D"},
        format_priority=["story"],
    )
    (bdir / f"{brief.id}.json").write_text(json.dumps(brief.to_dict(), default=str))


# ---------------------------------------------------------------------------
# Chat turn
# ---------------------------------------------------------------------------


def test_assistant_unknown_run_404(app_env):
    app, wm, tmp_path = app_env
    with app.test_client() as c:
        r = c.post("/api/runs/nope/card/c1/assistant", json={"message": "hi"})
    assert r.status_code == 404


def test_assistant_empty_message_400(app_env):
    app, wm, tmp_path = app_env
    run_id = _seed_run(tmp_path)
    with app.test_client() as c:
        r = c.post(f"/api/runs/{run_id}/card/c1/assistant", json={"message": "   "})
    assert r.status_code == 400 and r.get_json()["error"] == "empty_message"


def test_assistant_no_brief_409(app_env):
    app, wm, tmp_path = app_env
    run_id = _seed_run(tmp_path)  # no brief seeded
    with app.test_client() as c:
        r = c.post(f"/api/runs/{run_id}/card/c1/assistant", json={"message": "make it navy"})
    assert r.status_code == 409 and r.get_json()["error"] == "no_design"


def test_assistant_turn_applies_and_persists(app_env):
    app, wm, tmp_path = app_env
    run_id = _seed_run(tmp_path)
    _seed_brief(tmp_path, run_id)

    def fake(system, user, *, tools, on_tool_call, **kw):
        on_tool_call("propose_edit", {"ops": [{"kind": "set_headline", "text": "SEASON BEST"}]})
        return ToolConversation(text="Updated the headline.", provider="gemini")

    with mock.patch("mediahub.ai_core.ask_with_tools", fake):
        with app.test_client() as c:
            r = c.post(f"/api/runs/{run_id}/card/c1/assistant", json={"message": "headline season best"})
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j["changed"] is True
    assert any(op["kind"] == "set_headline" for op in j["applied"])
    assert j["session_id"] and j["brief_id"] and j["format"] == "story"
    # the edited brief was persisted as a new brief file
    briefs = list((tmp_path / "runs_v4" / run_id / "briefs").glob("cb_*.json"))
    assert len(briefs) == 2  # original + edited version


def test_assistant_no_provider_is_honest_200(app_env):
    app, wm, tmp_path = app_env
    run_id = _seed_run(tmp_path)
    _seed_brief(tmp_path, run_id)
    from mediahub.ai_core import ProviderNotConfigured

    def boom(*a, **k):
        raise ProviderNotConfigured("no key")

    with mock.patch("mediahub.ai_core.ask_with_tools", boom):
        with app.test_client() as c:
            r = c.post(f"/api/runs/{run_id}/card/c1/assistant", json={"message": "make it navy"})
    assert r.status_code == 200
    j = r.get_json()
    assert j["ai_available"] is False and j["changed"] is False


# ---------------------------------------------------------------------------
# Suggestions, memory, transcribe
# ---------------------------------------------------------------------------


def test_suggestions_returns_chips(app_env):
    app, wm, tmp_path = app_env
    run_id = _seed_run(tmp_path)
    with app.test_client() as c:
        r = c.get(f"/api/runs/{run_id}/card/c1/assistant/suggestions")
    assert r.status_code == 200
    assert isinstance(r.get_json()["suggestions"], list) and r.get_json()["suggestions"]


def test_memory_remember_list_delete(app_env):
    app, wm, tmp_path = app_env
    with app.test_client() as c:
        post = c.post("/api/assistant/memory", json={"text": "Never show times for 8-and-unders"})
        assert post.status_code == 200 and post.get_json()["ok"]
        item_id = post.get_json()["item"]["id"]
        lst = c.get("/api/assistant/memory")
        assert any(i["text"].startswith("Never show times") for i in lst.get_json()["items"])
        dele = c.post(f"/api/assistant/memory/{item_id}/delete", json={})
        assert dele.get_json()["ok"] is True
        empty_post = c.post("/api/assistant/memory", json={"text": "  "})
        assert empty_post.status_code == 400


def test_transcribe_honest_error_503(app_env):
    app, wm, tmp_path = app_env
    with app.test_client() as c:
        r = c.post("/api/assistant/transcribe", data=b"audio", content_type="audio/webm")
    assert r.status_code == 503 and r.get_json()["error"] == "asr_unavailable"


def test_transcribe_empty_audio_is_400_not_500(app_env, monkeypatch):
    """A configured provider with an empty upload is a client condition (400),
    not an unhandled 500. ``transcribe_audio`` raises ``ValueError('audio is
    empty')`` once a provider is set; the route must turn that into an honest
    400 rather than letting it fall through to the global 500 handler."""
    app, wm, tmp_path = app_env
    monkeypatch.setenv("MEDIAHUB_ASR_PROVIDER", "faster-whisper")
    with app.test_client() as c:
        r = c.post("/api/assistant/transcribe", data=b"", content_type="audio/webm")
    assert r.status_code == 400 and r.get_json()["error"] == "empty"
