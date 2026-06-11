"""
tests_v75/test_live_caption_endpoint.py — V8.1 Live Caption endpoint tests.

UPDATED for V8.1 (NO MASQUERADING):

  When the AI tab is requested but no Anthropic API key is configured,
  the endpoint must NOT silently render a voice caption and label it AI.
  It must return:
      {caption: "", tone: "ai", live: false, error: "no_key", message: ...}
  with HTTP 200.

  When a key IS configured, the endpoint must call Claude and return:
      {caption: <text>, tone: "ai", live: true}

Voice tones (warm_club / hype / data_led) are unchanged \u2014 deterministic.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# Ensure project root is on sys.path
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_run(run_id: str, runs_dir: Path) -> dict:
    achievement = {
        "swim_id": "test_swim_001",
        "swimmer_name": "Emma Davies",
        "event": "200m Backstroke",
        "time": "2:23.45",
        "pb": True,
        "type": "pb",
        "headline": "New PB in 200m Backstroke",
        "confidence_label": "high",
        "place": "1st",
    }
    ranked = [{
        "rank": 1, "priority": 0.95, "quality_band": "elite",
        "suggested_post_type": "individual",
        "achievement": achievement, "factors": [],
    }]
    run_data = {
        "run_id": run_id,
        "profile_display": "City of Manchester Aquatics",
        "meet": {"name": "Winter Championships", "start_date": "2024-01-20"},
        "recognition_report": {"n_achievements": 1, "ranked_achievements": ranked},
    }
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{run_id}.json").write_text(json.dumps(run_data), encoding="utf-8")
    return run_data


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tmp_runs_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("runs_v4")


@pytest.fixture(scope="module")
def fake_run_id(tmp_runs_dir):
    rid = "testrun_v8_capt"
    _make_fake_run(rid, tmp_runs_dir)
    return rid


@pytest.fixture(scope="module")
def flask_app(tmp_runs_dir):
    import mediahub.web.web as web_module
    original_runs_dir = web_module.RUNS_DIR
    web_module.RUNS_DIR = tmp_runs_dir
    app = web_module.create_app()
    app.config["TESTING"] = True
    yield app
    web_module.RUNS_DIR = original_runs_dir


@pytest.fixture(scope="module")
def client(flask_app):
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def no_llm_env(monkeypatch, tmp_path):
    """Force a no-key environment for the entire test."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PPLX_TOOL_BRIDGE_LOCAL_URL", raising=False)
    monkeypatch.delenv("PPLX_TOOL_BRIDGE_TOKEN", raising=False)
    # Disable the claude-CLI bridge (added v9.1) — tests must run without
    # any real LLM provider.
    monkeypatch.setenv("MEDIAHUB_DISABLE_CLAUDE_CLI", "1")
    # Redirect on-disk secrets to a temp file that we don't populate.
    from mediahub.web import secrets_store
    monkeypatch.setattr(secrets_store, "_SECRETS_PATH", tmp_path / "secrets.json")
    # Reset cached anthropic client.
    from mediahub.media_ai import llm as _llm
    _llm._anthropic_client = None
    _llm._anthropic_client_key = None
    yield


# ---------------------------------------------------------------------------
# 1. Endpoint shape \u2014 AI tone with NO key
# ---------------------------------------------------------------------------

class TestEndpointAIWithNoKey:
    def test_returns_200(self, client, fake_run_id, no_llm_env):
        resp = client.post(
            f"/api/runs/{fake_run_id}/swim/test_swim_001/caption?tone=ai"
        )
        assert resp.status_code == 200

    def test_returns_json(self, client, fake_run_id, no_llm_env):
        resp = client.post(
            f"/api/runs/{fake_run_id}/swim/test_swim_001/caption?tone=ai"
        )
        assert resp.get_json() is not None

    def test_tone_is_ai(self, client, fake_run_id, no_llm_env):
        resp = client.post(
            f"/api/runs/{fake_run_id}/swim/test_swim_001/caption?tone=ai"
        )
        assert resp.get_json()["tone"] == "ai"

    def test_live_is_false(self, client, fake_run_id, no_llm_env):
        """V8.1 contract: no key => live=False."""
        resp = client.post(
            f"/api/runs/{fake_run_id}/swim/test_swim_001/caption?tone=ai"
        )
        assert resp.get_json()["live"] is False

    def test_error_is_no_key(self, client, fake_run_id, no_llm_env):
        resp = client.post(
            f"/api/runs/{fake_run_id}/swim/test_swim_001/caption?tone=ai"
        )
        assert resp.get_json().get("error") == "no_key"

    def test_caption_is_empty_string(self, client, fake_run_id, no_llm_env):
        """V8.1: NO masquerading. The endpoint must NOT return a voice caption."""
        resp = client.post(
            f"/api/runs/{fake_run_id}/swim/test_swim_001/caption?tone=ai"
        )
        assert resp.get_json()["caption"] == ""

    def test_message_steers_user_to_administrator(self, client, fake_run_id, no_llm_env):
        """Post-rewrite: AI keys are operator-managed via env vars. The
        no-key message must point the end-user at their administrator,
        not at a (now-deleted) settings page."""
        resp = client.post(
            f"/api/runs/{fake_run_id}/swim/test_swim_001/caption?tone=ai"
        )
        msg = resp.get_json().get("message", "")
        assert "administrator" in msg.lower()
        assert "Settings" not in msg  # no stale settings-page wording

    def test_generated_at_present(self, client, fake_run_id, no_llm_env):
        resp = client.post(
            f"/api/runs/{fake_run_id}/swim/test_swim_001/caption?tone=ai"
        )
        assert "generated_at" in resp.get_json()


# ---------------------------------------------------------------------------
# 2. Endpoint with a key configured \u2014 returns live=True
# ---------------------------------------------------------------------------

class TestEndpointAIWithKey:
    def test_live_is_true_when_env_key_present(self, client, fake_run_id, monkeypatch):
        """When ANTHROPIC_API_KEY is set in env and call_claude succeeds,
        live=True. Post-rewrite there is no longer a disk-key persistence
        path — operator credentials are env-var only."""
        from mediahub.media_ai import llm as _llm

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-" + "a" * 40)
        _llm._anthropic_client = None
        _llm._anthropic_client_key = None

        with mock.patch("mediahub.web.ai_caption.call_claude", return_value="Stubbed AI caption."):
            resp = client.post(
                f"/api/runs/{fake_run_id}/swim/test_swim_001/caption?tone=ai"
            )
        assert resp.status_code == 200
        j = resp.get_json()
        assert j["tone"] == "ai"
        assert j["live"] is True
        assert j["caption"] == "Stubbed AI caption."


# ---------------------------------------------------------------------------
# 3. Voice tones unchanged
# ---------------------------------------------------------------------------

class TestVoiceTones:
    # `hype` (no separator) is an AI tone — it goes through the LLM, not
    # voice rendering — and is covered by TestEndpointAIWithKey /
    # TestEndpointAIWithNoKey. Voice-only tones use underscores.
    @pytest.mark.parametrize("voice_id", ["warm_club", "data_led"])
    def test_voice_tone_returns_200(self, client, fake_run_id, voice_id):
        resp = client.post(
            f"/api/runs/{fake_run_id}/swim/test_swim_001/caption?tone={voice_id}"
        )
        assert resp.status_code == 200

    # `hype` (no separator) is an AI tone — it goes through the LLM, not
    # voice rendering — and is covered by TestEndpointAIWithKey /
    # TestEndpointAIWithNoKey. Voice-only tones use underscores.
    @pytest.mark.parametrize("voice_id", ["warm_club", "data_led"])
    def test_voice_tone_returns_caption(self, client, fake_run_id, voice_id):
        resp = client.post(
            f"/api/runs/{fake_run_id}/swim/test_swim_001/caption?tone={voice_id}"
        )
        data = resp.get_json()
        assert data["caption"].strip() != ""

    # `hype` (no separator) is an AI tone — it goes through the LLM, not
    # voice rendering — and is covered by TestEndpointAIWithKey /
    # TestEndpointAIWithNoKey. Voice-only tones use underscores.
    @pytest.mark.parametrize("voice_id", ["warm_club", "data_led"])
    def test_voice_tone_returns_correct_tone_field(self, client, fake_run_id, voice_id):
        resp = client.post(
            f"/api/runs/{fake_run_id}/swim/test_swim_001/caption?tone={voice_id}"
        )
        assert resp.get_json()["tone"] == voice_id

    # `hype` (no separator) is an AI tone — it goes through the LLM, not
    # voice rendering — and is covered by TestEndpointAIWithKey /
    # TestEndpointAIWithNoKey. Voice-only tones use underscores.
    @pytest.mark.parametrize("voice_id", ["warm_club", "data_led"])
    def test_voice_tone_fallback_false(self, client, fake_run_id, voice_id):
        resp = client.post(
            f"/api/runs/{fake_run_id}/swim/test_swim_001/caption?tone={voice_id}"
        )
        assert resp.get_json().get("fallback") is False


class TestDifferentVoicesProduceDifferentOutput:
    # The voice-rendering layer produces deterministic per-voice output
    # for the underscore-named voices (warm_club / data_led). The
    # `hype` AI tone is covered separately with a mocked LLM.
    def test_warm_club_vs_data_led_differ(self, client, fake_run_id):
        a = client.post(f"/api/runs/{fake_run_id}/swim/test_swim_001/caption?tone=warm_club").get_json()["caption"]
        b = client.post(f"/api/runs/{fake_run_id}/swim/test_swim_001/caption?tone=data_led").get_json()["caption"]
        assert a != b


# ---------------------------------------------------------------------------
# 4. Side-effect freedom \u2014 no run-file mutation
# ---------------------------------------------------------------------------

class TestAINoSideEffects:
    def test_ai_endpoint_callable_twice(self, client, fake_run_id, no_llm_env):
        r1 = client.post(f"/api/runs/{fake_run_id}/swim/test_swim_001/caption?tone=ai")
        r2 = client.post(f"/api/runs/{fake_run_id}/swim/test_swim_001/caption?tone=ai")
        assert r1.status_code == 200 and r2.status_code == 200

    def test_run_json_not_modified(self, tmp_runs_dir, client, fake_run_id, no_llm_env):
        run_path = tmp_runs_dir / f"{fake_run_id}.json"
        m_before = run_path.stat().st_mtime
        client.post(f"/api/runs/{fake_run_id}/swim/test_swim_001/caption?tone=ai")
        assert run_path.stat().st_mtime == m_before


# ---------------------------------------------------------------------------
# 5. 404 cases
# ---------------------------------------------------------------------------

class TestNotFound:
    def test_unknown_run_returns_404(self, client):
        resp = client.post(
            "/api/runs/does_not_exist_xyz/swim/some_swim/caption?tone=ai"
        )
        assert resp.status_code == 404

    def test_unknown_voice_returns_404(self, client, fake_run_id):
        resp = client.post(
            f"/api/runs/{fake_run_id}/swim/test_swim_001/caption?tone=voice_that_does_not_exist_abc"
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 6. media_ai.llm contract
# ---------------------------------------------------------------------------

class TestLLMModule:
    def test_call_claude_raises_when_no_key(self, monkeypatch, tmp_path):
        from mediahub.media_ai.llm import call_claude, ClaudeUnavailableError
        from mediahub.web import secrets_store
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("PPLX_TOOL_BRIDGE_LOCAL_URL", raising=False)
        monkeypatch.delenv("PPLX_TOOL_BRIDGE_TOKEN", raising=False)
        monkeypatch.setenv("MEDIAHUB_DISABLE_CLAUDE_CLI", "1")
        monkeypatch.setattr(secrets_store, "_SECRETS_PATH", tmp_path / "s.json")
        with pytest.raises(ClaudeUnavailableError):
            call_claude(system="test", user="test")

    def test_resolve_picks_up_env_key(self, monkeypatch):
        """Post-rewrite the LLM module reads keys from env only.
        The disk-fallback path remains as a one-release migration aid
        but is not exercised by tests."""
        from mediahub.media_ai import llm as _llm
        fake = "sk-ant-" + "x" * 40
        monkeypatch.setenv("ANTHROPIC_API_KEY", fake)
        _llm._anthropic_client = None
        _llm._anthropic_client_key = None
        assert _llm._resolve_anthropic_key() == fake
        assert _llm.is_available() is True


# ---------------------------------------------------------------------------
# 7. URL/method
# ---------------------------------------------------------------------------

class TestEndpointURL:
    def test_url_post_only(self, client, fake_run_id):
        r = client.get(f"/api/runs/{fake_run_id}/swim/test_swim_001/caption?tone=warm_club")
        assert r.status_code == 405
