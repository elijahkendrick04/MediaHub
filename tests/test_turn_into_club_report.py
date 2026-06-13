"""Tests for the two Turn-Into additions from the awesome-generative-ai-apps
integration review: the long-form ``club_report`` artefact (Blogger-CMS-style
website report) and the email-ready envelope (subject + preheader) on
``parent_newsletter`` (Mail-Wise-style).

Deterministic-mode tests never call an LLM; AI-path tests mock the provider
layer, so everything here is offline.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest


def _meet_summary() -> dict:
    return {
        "name": "Spring Open 2026",
        "start_date": "2026-04-10",
        "end_date": "2026-04-11",
        "course": "LC",
        "venue": "Demo Pool",
        "profile_display": "Test Club",
    }


def _ranked() -> list[dict]:
    return [
        {
            "achievement": {
                "swimmer_name": "Alice Lee",
                "swimmer_id": "s1",
                "event": "100m Freestyle",
                "time": "57.95",
                "headline": "New PB in 100 Free",
                "type": "pb_confirmed",
                "raw_facts": {"time_str": "57.95"},
            },
            "priority": 0.92,
        },
        {
            "achievement": {
                "swimmer_name": "Bob Khan",
                "swimmer_id": "s2",
                "event": "200m Backstroke",
                "time": "2:08.10",
                "headline": "Silver medal",
                "type": "medal_silver",
                "raw_facts": {"place": 2},
            },
            "priority": 0.80,
        },
    ]


# --- club_report: deterministic mode ----------------------------------------


def test_deterministic_report_is_grounded_in_results():
    from mediahub.turn_into.templates import build_club_report

    art = build_club_report(_meet_summary(), _ranked(), None, None, None, deterministic=True)
    assert art["type"] == "club_report"
    body = art["captions"]["default"]
    assert "Spring Open 2026" in body
    assert "Alice Lee" in body and "57.95" in body
    assert "Bob Khan" in body
    # HTML mirror for paste-into-website use.
    assert art["html"].startswith('<article class="mh-club-report">')
    assert "Spring Open 2026" in art["html"]
    # Explainability notes carry the grounding count.
    assert any("Grounded in 2 ranked results" in n for n in art["notes"])


def test_deterministic_report_with_no_achievements_still_builds():
    from mediahub.turn_into.templates import build_club_report

    art = build_club_report(_meet_summary(), [], None, None, None, deterministic=True)
    body = art["captions"]["default"]
    assert "Spring Open 2026" in body
    assert any("Grounded in 0 ranked results" in n for n in art["notes"])


# --- club_report: AI path ----------------------------------------------------


def test_ai_report_goes_through_longform_generate():
    from mediahub.turn_into.templates import build_club_report

    seen: dict = {}

    def fake_generate(prompt, *, system=None, max_tokens=1024, **kw):
        seen["prompt"] = prompt
        seen["system"] = system or ""
        seen["max_tokens"] = max_tokens
        return "First para about the gala.\n\nSecond para with detail."

    with mock.patch("mediahub.media_ai.llm.generate", side_effect=fake_generate):
        art = build_club_report(
            _meet_summary(), _ranked(), None, None, None, deterministic=False
        )

    assert art["captions"]["default"].startswith("First para about the gala.")
    # The brief fed to the model carries the verified facts, not vibes.
    assert "Alice Lee" in seen["prompt"] and "57.95" in seen["prompt"]
    assert "must not go beyond them" in seen["prompt"]
    # Long-form needs real token headroom (the caption primitive is 400-capped).
    assert seen["max_tokens"] >= 1000
    assert "Never invent a swimmer" in seen["system"]
    # Paragraphs become escaped <p> blocks.
    assert art["html"].count("<p>") == 2


def test_ai_report_falls_back_when_provider_unavailable():
    from mediahub.media_ai.llm import ClaudeUnavailableError
    from mediahub.turn_into.templates import build_club_report

    with mock.patch(
        "mediahub.media_ai.llm.generate",
        side_effect=ClaudeUnavailableError("no key"),
    ):
        art = build_club_report(
            _meet_summary(), _ranked(), None, None, None, deterministic=False
        )
    # Package convention: the pack never crashes — deterministic copy ships.
    assert "Spring Open 2026" in art["captions"]["default"]
    assert "Alice Lee" in art["captions"]["default"]


# --- parent_newsletter: email envelope ---------------------------------------


def test_newsletter_envelope_deterministic_fallbacks():
    from mediahub.turn_into.templates import build_parent_newsletter

    art = build_parent_newsletter(
        _meet_summary(), _ranked(), None, None, None, deterministic=True
    )
    caps = art["captions"]
    assert "subject" in caps and "preheader" in caps
    assert 0 < len(caps["subject"]) <= 60
    assert 0 < len(caps["preheader"]) <= 100
    assert "Spring Open 2026" in caps["subject"]
    # Plain text + html section behaviour is unchanged.
    assert caps["default"] == caps["plain_text"]
    assert art["html"].startswith('<section class="mh-newsletter">')


def test_newsletter_envelope_uses_ai_subject_when_available():
    from mediahub.turn_into.templates import build_parent_newsletter

    with mock.patch(
        "mediahub.web.ai_caption.call_claude",
        side_effect=lambda system, user, max_tokens=400, **kw: "Body text from AI.",
    ), mock.patch(
        "mediahub.media_ai.llm.generate_json",
        return_value={"subject": "PBs galore at Spring Open", "preheader": "Two podiums and more inside."},
    ):
        art = build_parent_newsletter(
            _meet_summary(), _ranked(), None, None, None, deterministic=False
        )
    assert art["captions"]["subject"] == "PBs galore at Spring Open"
    assert art["captions"]["preheader"] == "Two podiums and more inside."


def test_newsletter_envelope_survives_subject_call_failure():
    from mediahub.media_ai.llm import ClaudeUnavailableError
    from mediahub.turn_into.templates import build_parent_newsletter

    with mock.patch(
        "mediahub.web.ai_caption.call_claude",
        side_effect=lambda system, user, max_tokens=400, **kw: "Body text from AI.",
    ), mock.patch(
        "mediahub.media_ai.llm.generate_json",
        side_effect=ClaudeUnavailableError("no key"),
    ):
        art = build_parent_newsletter(
            _meet_summary(), _ranked(), None, None, None, deterministic=False
        )
    # Envelope falls back deterministically; the AI body is kept.
    assert "Spring Open 2026" in art["captions"]["subject"]
    assert art["captions"]["default"].startswith("Body text from AI.")


# --- pack + web view ----------------------------------------------------------


def test_pack_view_renders_club_report_artefact():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        os.environ["DATA_DIR"] = tmp
        os.environ["RUNS_DIR"] = tmp + "/runs_v4"
        os.environ["UPLOADS_DIR"] = tmp + "/uploads_v4"
        Path(tmp + "/runs_v4").mkdir(parents=True, exist_ok=True)
        import importlib

        import mediahub.web.web as wm

        importlib.reload(wm)
        app = wm.create_app()
        app.config["TESTING"] = True

        run = {
            "run_id": "run-cr",
            "meet": _meet_summary(),
            "recognition_report": {"ranked_achievements": _ranked()},
        }
        Path(tmp + "/runs_v4/run-cr.json").write_text(json.dumps(run))

        client = app.test_client()
        r = client.post("/api/runs/run-cr/turn-into", json={"deterministic": True})
        assert r.status_code == 200, r.get_data(as_text=True)[:300]
        data = r.get_json()
        assert "club_report" not in (data.get("skipped") or [])

        body = client.get(data["pack_url"]).get_data(as_text=True)
        assert "Club website report" in body
        # The email envelope renders as editable caption blocks.
        assert "Subject" in body and "Preheader" in body


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
