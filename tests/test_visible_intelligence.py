"""tests/test_visible_intelligence.py — Phase 1.4 default-on explainer.

Pins the three visible-intelligence invariants that the previous test
coverage missed (per the audit):

  1. `<details open>` — the explainer renders open-by-default so the
     editorial reasoning is the first thing a user sees on a card.
  2. The "Use in next caption" button is conditional on a real run_id
     being supplied (legacy renders without it don't break).
  3. The `?include_why=1` query param on /api/runs/<id>/swim/<id>/caption
     actually injects the explainer text into the LLM system prompt as
     `_extra_instructions`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ranked_achievement(swim_id: str = "swim-1") -> dict:
    """Minimal achievement shape that survives the explainer build."""
    return {
        "rank": 1,
        "priority": 0.95,
        "factors": [
            {
                "name": "pb_magnitude_seconds",
                "value": 0.5,
                "weight": 1.0,
                "reason": "PB by 0.5s",
                "plain_summary": "Confirmed PB by 0.5 seconds.",
            }
        ],
        "achievement": {
            "swim_id": swim_id,
            "swimmer_name": "Emma Davies",
            "event": "100m Freestyle",
            "time": "58.21",
            "type": "pb_confirmed",
            "pb": True,
            "headline": "First sub-60 in the 100 free",
            "evidence": [
                {
                    "label": "result line",
                    "raw_text": "100 FR  58.21  PB",
                    "file_offset": None,
                }
            ],
        },
    }


# ---------------------------------------------------------------------------
# 1. <details open> — explainer is default-visible
# ---------------------------------------------------------------------------


class TestDetailsOpenByDefault:
    def test_renders_details_open_attribute(self):
        from mediahub.web.web import _render_why_this_card
        from flask import Flask

        # Need an app context for url_for() in the AI-error block path.
        app = Flask(__name__)
        app.add_url_rule("/settings", endpoint="settings_page", view_func=lambda: "")
        app.add_url_rule(
            "/api/runs/<run_id>/swim/<swim_id>/caption",
            endpoint="api_live_caption",
            view_func=lambda run_id, swim_id: "",
            methods=["POST"],
        )
        with app.test_request_context("/"):
            html = _render_why_this_card(_ranked_achievement(), card_uuid="t1")
        # The disclosure must open by default — single most important
        # Phase 1.4 invariant. Allow either attribute syntax (`open`
        # alone or `open=""`).
        assert "<details open" in html, (
            "explainer must default to <details open …> so reasoning " "is visible without a click"
        )


# ---------------------------------------------------------------------------
# 2. "Use in next caption" button is gated on run_id
# ---------------------------------------------------------------------------


class TestUseInCaptionButtonRender:
    def _render(self, run_id: str) -> str:
        from mediahub.web.web import _render_why_this_card
        from flask import Flask

        app = Flask(__name__)
        app.add_url_rule("/settings", endpoint="settings_page", view_func=lambda: "")
        app.add_url_rule(
            "/api/runs/<run_id>/swim/<swim_id>/caption",
            endpoint="api_live_caption",
            view_func=lambda run_id, swim_id: "",
            methods=["POST"],
        )
        # H-11: the button also carries the workflow save URL ("Save to
        # card"), so the stub app needs that route registered too.
        app.add_url_rule(
            "/api/workflow/<run_id>/<card_id>",
            endpoint="api_workflow_set",
            view_func=lambda run_id, card_id: "",
            methods=["POST"],
        )
        with app.test_request_context("/"):
            return _render_why_this_card(
                _ranked_achievement(),
                card_uuid="t2",
                run_id=run_id,
            )

    def test_button_absent_when_no_run_id(self):
        html = self._render(run_id="")
        # Neither the button label nor the JS handler reference appear.
        assert "mhUseWhyInCaption" not in html
        assert "Use in next caption" not in html

    def test_button_present_when_run_id_supplied(self):
        html = self._render(run_id="run-42")
        assert "mhUseWhyInCaption" in html
        assert "Use in next caption" in html
        # And the API URL is built correctly with the swim_id from the
        # achievement payload.
        assert "/api/runs/run-42/swim/swim-1/caption" in html


# ---------------------------------------------------------------------------
# 3. include_why=1 injects explainer text into the LLM prompt
# ---------------------------------------------------------------------------


@pytest.fixture
def caption_endpoint_client(client, tmp_path):
    """Build a TESTING app + seeded run so we can POST to the caption
    endpoint. The org gate is bypassed under TESTING."""
    run = {
        "run_id": "r1",
        "profile_id": "x",
        "meet": {"name": "Champs"},
        "recognition_report": {
            "ranked_achievements": [_ranked_achievement()],
        },
    }
    (tmp_path / "runs_v4" / "r1.json").write_text(json.dumps(run))
    return client


class TestIncludeWhyInjectsExplanation:
    def test_extra_instructions_reaches_system_prompt(
        self,
        caption_endpoint_client,
        monkeypatch,
    ):
        c = caption_endpoint_client
        captured: dict = {}

        def fake_call(system, user, max_tokens=400, **_):
            captured["system"] = system
            return "fresh caption with reasoning woven in"

        # is_available must say True so we hit the LIVE generation path
        # rather than the no_key short-circuit. The explainer is mocked
        # to a known-good shape so the test doesn't depend on whether
        # the explainer's internal LLM was reachable.
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
        monkeypatch.setattr(
            "mediahub.web.ai_caption.call_claude",
            fake_call,
        )
        monkeypatch.setattr(
            "mediahub.web.web._build_card_explanation",
            lambda ra: {
                "headline": "This swim ranked highly because it was a PB.",
                "bullets": ["Confirmed PB"],
                "source_lines": [],
            },
        )

        resp = c.post("/api/runs/r1/swim/swim-1/caption?tone=ai&include_why=1&n_variants=1")
        assert resp.status_code == 200
        sys_prompt = captured.get("system", "")
        # The endpoint surfaces _extra_instructions via the existing
        # "Additional requirement for this caption" channel.
        assert "Additional requirement" in sys_prompt, (
            "include_why=1 must inject the explainer text into the "
            "system prompt — got: " + sys_prompt[:400]
        )

    def test_no_include_why_no_extra_instructions(
        self,
        caption_endpoint_client,
        monkeypatch,
    ):
        c = caption_endpoint_client
        captured: dict = {}

        def fake_call(system, user, max_tokens=400, **_):
            captured["system"] = system
            return "regular caption"

        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
        monkeypatch.setattr(
            "mediahub.web.ai_caption.call_claude",
            fake_call,
        )

        resp = c.post("/api/runs/r1/swim/swim-1/caption?tone=ai&n_variants=1")
        assert resp.status_code == 200
        sys_prompt = captured.get("system", "")
        # Without include_why, the extra-instruction section is absent.
        assert "Additional requirement" not in sys_prompt

    def test_include_why_explanation_text_in_prompt(
        self,
        caption_endpoint_client,
        monkeypatch,
    ):
        """The explainer's grounded headline must literally appear in
        the injected extra-instructions — not just the section header.
        Mocks the explainer so the test doesn't depend on the
        explainer's internal LLM availability."""
        c = caption_endpoint_client
        captured: dict = {}
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
        monkeypatch.setattr(
            "mediahub.web.ai_caption.call_claude",
            lambda system, user, max_tokens=400, **_: captured.update(system=system) or "ok",
        )
        monkeypatch.setattr(
            "mediahub.web.web._build_card_explanation",
            lambda ra: {
                "headline": "This swim ranked highly because it was Emma's first sub-60.",
                "bullets": ["Confirmed PB", "First-time sub-barrier"],
                "source_lines": [],
            },
        )
        c.post("/api/runs/r1/swim/swim-1/caption?tone=ai&include_why=1&n_variants=1")
        sys_prompt = captured.get("system", "")
        assert "first sub-60" in sys_prompt, "explainer headline must literally land in the prompt"
        assert (
            "Confirmed PB" in sys_prompt
        ), "explainer bullets must be injected as grounded reasons"
        assert "Weave in at least one" in sys_prompt

    def test_fallback_explainer_text_NOT_injected(
        self,
        caption_endpoint_client,
        monkeypatch,
    ):
        """Bug-fix pin: when the explainer falls back to its
        "AI explanation unavailable" or "Generated for: ranked top-N"
        shape, we must NOT pass that error string through as a
        caption requirement — that would tell the caption LLM to
        include literal error text in the post."""
        c = caption_endpoint_client
        captured: dict = {}
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
        monkeypatch.setattr(
            "mediahub.web.ai_caption.call_claude",
            lambda system, user, max_tokens=400, **_: captured.update(system=system) or "ok",
        )
        # Force the explainer into its fallback shape.
        monkeypatch.setattr(
            "mediahub.web.web._build_card_explanation",
            lambda ra: {
                "headline": "AI explanation unavailable.",
                "bullets": [],
                "source_lines": [],
            },
        )
        c.post("/api/runs/r1/swim/swim-1/caption?tone=ai&include_why=1&n_variants=1")
        sys_prompt = captured.get("system", "")
        # The error string must NOT have made it into the prompt as a
        # requirement.
        assert "AI explanation unavailable" not in sys_prompt
        # And the "Additional requirement" section should be absent
        # (or at least not carrying the fallback text).
        assert "Additional requirement" not in sys_prompt, (
            "fallback explainer shouldn't trigger the extra-requirement " "channel at all"
        )

    def test_fallback_generated_for_NOT_injected(
        self,
        caption_endpoint_client,
        monkeypatch,
    ):
        """Same bug-fix pin, second fallback shape."""
        c = caption_endpoint_client
        captured: dict = {}
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
        monkeypatch.setattr(
            "mediahub.web.ai_caption.call_claude",
            lambda system, user, max_tokens=400, **_: captured.update(system=system) or "ok",
        )
        monkeypatch.setattr(
            "mediahub.web.web._build_card_explanation",
            lambda ra: {
                "headline": "Generated for: ranked top-3 by overall score.",
                "bullets": [],
                "source_lines": [],
            },
        )
        c.post("/api/runs/r1/swim/swim-1/caption?tone=ai&include_why=1&n_variants=1")
        sys_prompt = captured.get("system", "")
        assert "Generated for: ranked" not in sys_prompt
        assert "Additional requirement" not in sys_prompt


# ---------------------------------------------------------------------------
# 4. PAR-1 approval loop: stored approved captions reach the live prompt
# ---------------------------------------------------------------------------


class TestApprovedVoiceReachesPrompt:
    """End-to-end pin for the PAR-1 few-shot loop: a caption a human approved
    (persisted in web/caption_examples under DATA_DIR) is injected into the
    live caption endpoint's system prompt as a voice example."""

    def test_stored_example_injected_as_voice_example(
        self,
        caption_endpoint_client,
        monkeypatch,
    ):
        c = caption_endpoint_client
        from mediahub.web.caption_examples import append_example

        example = "Our captain was simply unstoppable in the relay last month!"
        append_example("x", example)  # the fixture run's profile_id

        captured: dict = {}
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
        monkeypatch.setattr(
            "mediahub.web.ai_caption.call_claude",
            lambda system, user, max_tokens=400, **_: captured.update(system=system)
            or "a fresh caption",
        )
        monkeypatch.setattr(
            "mediahub.web.web._build_card_explanation",
            lambda ra: {"headline": "", "bullets": [], "source_lines": []},
        )

        resp = c.post("/api/runs/r1/swim/swim-1/caption?tone=ai&n_variants=1")
        assert resp.status_code == 200
        assert (resp.get_json() or {}).get("caption") == "a fresh caption"
        sys_prompt = captured.get("system", "")
        assert "Voice examples" in sys_prompt
        assert example in sys_prompt
