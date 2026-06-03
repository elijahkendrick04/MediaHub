"""Tests for inline caption assist (Section 6 step 7a).

Module: the transform resolver + the 'revise, don't regenerate' requirements
brief. Endpoint: access control, empty/invalid guards, honest no-key handling,
and the happy path (all AI mocked — no real provider).
"""

from __future__ import annotations

import pytest

from mediahub.web.caption_assist import (
    PRESETS,
    assist_caption,
    build_requirements,
    resolve_instruction,
)


# ── module ──────────────────────────────────────────────────────────────────


def test_resolve_instruction():
    assert resolve_instruction("shorter") == PRESETS["shorter"]
    assert resolve_instruction("custom", "make it rhyme") == "make it rhyme"
    assert resolve_instruction("zzz", "add an emoji") == "add an emoji"  # unknown slug + free text
    assert resolve_instruction("", "") == ""
    assert resolve_instruction("custom", "") == ""


def test_build_requirements_preserves_facts_and_current():
    req = build_requirements("Alice swam a 57.10 PB!", "make it shorter")
    assert "Alice swam a 57.10 PB!" in req  # the current caption is included
    assert "shorter" in req  # the requested change
    assert "Keep every" in req and "Output ONLY" in req  # the preserve-facts + revise framing


def test_assist_caption_feeds_requirements_to_writer(monkeypatch):
    captured = {}

    def fake_gen(
        ach, brand=None, *, tone="ai", voice_profile=None, club_profile=None, requirements="", **k
    ):
        captured["requirements"] = requirements
        captured["tone"] = tone
        return "Revised caption."

    monkeypatch.setattr("mediahub.web.ai_caption.generate_caption_for_tone", fake_gen)
    out = assist_caption(
        {"swimmer_name": "Alice"}, "A long original caption", "shorter", tone="warm-club"
    )
    assert out == "Revised caption."
    assert "A long original caption" in captured["requirements"]
    assert "shorter" in captured["requirements"].lower()
    assert captured["tone"] == "warm-club"


def test_assist_caption_empty_instruction_raises():
    with pytest.raises(ValueError):
        assist_caption({}, "cap", "", custom="")


# ── endpoint ────────────────────────────────────────────────────────────────


def _fake_run():
    return {
        "run_id": "r1",
        "profile_id": "",
        "profile_display": "City SC",
        "meet": {"name": "County Champs"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "achievement": {
                        "swim_id": "s1",
                        "swimmer_name": "Alice Smith",
                        "event": "100m Freestyle",
                        "time": "57.10",
                        "headline": "Alice set a PB",
                    }
                }
            ]
        },
    }


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    return app.test_client()


def test_assist_endpoint_success(client, monkeypatch):
    monkeypatch.setattr("mediahub.web.web._load_run", lambda rid: _fake_run())
    monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
    monkeypatch.setattr(
        "mediahub.web.ai_caption.generate_caption_for_tone",
        lambda *a, **k: "Short, punchy PB! 57.10",
    )
    r = client.post(
        "/api/runs/r1/swim/s1/caption/assist",
        json={"current_caption": "Alice Smith swam a big new PB of 57.10!", "transform": "shorter"},
    )
    assert r.status_code == 200
    j = r.get_json()
    assert j["caption"] == "Short, punchy PB! 57.10"
    assert j["live"] is True and j["transform"] == "shorter"
    assert j["original"].startswith("Alice Smith")


def test_assist_endpoint_empty_caption(client, monkeypatch):
    monkeypatch.setattr("mediahub.web.web._load_run", lambda rid: _fake_run())
    r = client.post(
        "/api/runs/r1/swim/s1/caption/assist",
        json={"current_caption": "  ", "transform": "shorter"},
    )
    assert r.status_code == 400
    assert r.get_json()["error"] == "empty_caption"


def test_assist_endpoint_invalid_transform(client, monkeypatch):
    monkeypatch.setattr("mediahub.web.web._load_run", lambda rid: _fake_run())
    r = client.post(
        "/api/runs/r1/swim/s1/caption/assist",
        json={"current_caption": "A caption", "transform": "", "custom": ""},
    )
    assert r.status_code == 400
    assert r.get_json()["error"] == "invalid_transform"


def test_assist_endpoint_no_key(client, monkeypatch):
    monkeypatch.setattr("mediahub.web.web._load_run", lambda rid: _fake_run())
    monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: False)
    r = client.post(
        "/api/runs/r1/swim/s1/caption/assist",
        json={"current_caption": "A caption", "transform": "shorter"},
    )
    assert r.status_code == 200
    j = r.get_json()
    assert j["error"] == "no_key" and j["caption"] == "" and j["live"] is False


def test_assist_endpoint_run_not_found(client, monkeypatch):
    monkeypatch.setattr("mediahub.web.web._load_run", lambda rid: None)
    r = client.post(
        "/api/runs/missing/swim/s1/caption/assist",
        json={"current_caption": "x", "transform": "shorter"},
    )
    assert r.status_code == 404


def test_assist_endpoint_idor_blocked(client, monkeypatch):
    monkeypatch.setattr("mediahub.web.web._load_run", lambda rid: _fake_run())
    monkeypatch.setattr("mediahub.web.web._can_access_run", lambda *a, **k: False)
    r = client.post(
        "/api/runs/r1/swim/s1/caption/assist", json={"current_caption": "x", "transform": "shorter"}
    )
    assert r.status_code == 404
