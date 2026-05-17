"""V8 media_ai LLM wrapper tests.

Post-rewrite: there is NO heuristic fallback. When no LLM provider
is configured (which is the default in CI/test environments), the
public functions raise ClaudeUnavailableError honestly so callers
surface "AI features unavailable — contact your administrator" to
the user instead of inventing fake output.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mediahub.media_ai import generate, generate_json, is_available
from mediahub.media_ai.llm import ClaudeUnavailableError


@pytest.fixture(autouse=True)
def _no_providers(monkeypatch, tmp_path):
    """Clean env so these tests exercise the "no provider configured"
    contract rather than accidentally hitting a real LLM."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import importlib, mediahub.web.secrets_store as _ss
    importlib.reload(_ss)


def test_is_available_returns_bool():
    assert isinstance(is_available(), bool)


def test_is_available_false_with_no_keys():
    assert is_available() is False


def test_generate_raises_when_no_provider():
    """No silent fake output. Operator-config-removal contract: callers
    must catch and surface honestly to the user."""
    with pytest.raises(ClaudeUnavailableError):
        generate("Write one short sentence.", max_tokens=32)


def test_generate_json_raises_when_no_provider():
    with pytest.raises(ClaudeUnavailableError):
        generate_json("Extract athlete name.", fallback={"x": 1})
