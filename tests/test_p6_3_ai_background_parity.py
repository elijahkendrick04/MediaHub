"""P6.3 — ai_background generalised behind the imagine seam, byte-safe.

The renderer's MEDIAHUB_GEN_BG background now routes its Imagen call through the
shared ``imagen_predict`` client. These tests lock in that the public contract
(is_available, cache key, data-URI output) is unchanged.
"""

from __future__ import annotations

import importlib
import io

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for var in ("GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "MEDIAHUB_IMAGINE_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import mediahub.web.secrets_store as ss

    importlib.reload(ss)


def _png_bytes():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (7, 8, 9)).save(buf, format="PNG")
    return buf.getvalue()


class _Brief:
    palette = {"primary": "#001f3f", "secondary": "#000000", "accent": "#d4af37"}
    text_layers = {"event_name": "swimming"}


def test_is_available_unchanged_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    import mediahub.visual.ai_background as bg

    importlib.reload(bg)
    assert bg.is_available() is False


def test_background_delegates_to_shared_client(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    import mediahub.visual.ai_background as bg
    import mediahub.media_ai.imagine_providers.gemini_imagine as g

    importlib.reload(bg)
    png = _png_bytes()
    seen = {}

    def fake_predict(prompt, **kw):
        seen["prompt"] = prompt
        seen["kw"] = kw
        return [png]

    monkeypatch.setattr(g, "imagen_predict", fake_predict)
    uri = bg.background_data_uri_for(_Brief(), format_name="story")
    assert uri is not None
    assert uri.startswith("data:image/png;base64,")
    # The historic request semantics are preserved through the shared client.
    assert seen["kw"]["sample_count"] == 1
    assert seen["kw"]["allow_people"] is False
    assert seen["kw"]["safety"] == "block_only_high"
    # story → 9:16 aspect (the renderer's format→aspect mapping is unchanged).
    assert seen["kw"]["aspect_ratio"] == "9:16"


def test_background_caches_by_prompt(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    import mediahub.visual.ai_background as bg
    import mediahub.media_ai.imagine_providers.gemini_imagine as g

    importlib.reload(bg)
    calls = {"n": 0}

    def fake_predict(prompt, **kw):
        calls["n"] += 1
        return [_png_bytes()]

    monkeypatch.setattr(g, "imagen_predict", fake_predict)
    bg.background_data_uri_for(_Brief(), format_name="story")
    bg.background_data_uri_for(_Brief(), format_name="story")
    # Second identical request is a cache hit — the client is called once.
    assert calls["n"] == 1


def test_background_none_when_client_empty(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    import mediahub.visual.ai_background as bg
    import mediahub.media_ai.imagine_providers.gemini_imagine as g

    importlib.reload(bg)
    monkeypatch.setattr(g, "imagen_predict", lambda *a, **k: [])
    assert bg.background_data_uri_for(_Brief(), format_name="story") is None
