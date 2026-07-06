"""P6.3 — generate / similar via the Gemini provider (mocked HTTP).

The Imagen ``:predict`` shape is the one place network would happen, so we mock
``imagen_predict`` (the shared low-level client) and assert request shaping,
result/manifest shape, style presets, the no-people default, and honest errors.
"""

from __future__ import annotations

import importlib
import io

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for var in (
        "GOOGLE_API_KEY",
        "ANTHROPIC_API_KEY",
        "MEDIAHUB_IMAGINE_PROVIDER",
        "MEDIAHUB_IMAGINE_QUOTA_MONTHLY",
        "MEDIAHUB_IMAGINE_MODEL",
        "MEDIAHUB_IMAGEN_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    import mediahub.web.secrets_store as ss

    importlib.reload(ss)


def _png_bytes(color=(10, 20, 30)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, format="PNG")
    return buf.getvalue()


def test_generate_returns_stamped_result(monkeypatch):
    import mediahub.media_ai.imagine as im
    import mediahub.media_ai.imagine_providers.gemini_imagine as g

    png = _png_bytes()
    calls = {}

    def fake_predict(prompt, **kw):
        calls["prompt"] = prompt
        calls["kw"] = kw
        return [png]

    monkeypatch.setattr(g, "imagen_predict", fake_predict)

    results = im.generate("a navy and gold poolside backdrop", style="editorial", aspect="9:16")
    assert len(results) == 1
    r = results[0]
    assert r.data == png
    assert r.operation == "generate"
    assert r.provider == "gemini"
    assert r.model  # a model id was recorded
    # Style preset folded into the prompt that reached the client.
    assert "editorial" in calls["prompt"].lower()
    # No-people default propagated to the client.
    assert calls["kw"]["allow_people"] is False
    assert calls["kw"]["aspect_ratio"] == "9:16"
    # Manifest carries provenance facts.
    m = r.manifest
    assert m["operation"] == "generate"
    assert m["digital_source_type"] == "ai_generated"
    assert m["content_sha256"] == r.sha256
    assert m["provider"] == "gemini"


def test_generate_empty_prompt_rejected():
    import mediahub.media_ai.imagine as im

    with pytest.raises(im.ImagineError):
        im.generate("   ")


def test_generate_empty_provider_result_is_honest_error(monkeypatch):
    import mediahub.media_ai.imagine as im
    import mediahub.media_ai.imagine_providers.gemini_imagine as g

    monkeypatch.setattr(g, "imagen_predict", lambda *a, **k: [])  # no image
    with pytest.raises(im.ImagineError):
        im.generate("anything")


def test_generate_allow_people_opt_in(monkeypatch):
    import mediahub.media_ai.imagine as im
    import mediahub.media_ai.imagine_providers.gemini_imagine as g

    seen = {}

    def fake_predict(prompt, **kw):
        seen.update(kw)
        return [_png_bytes()]

    monkeypatch.setattr(g, "imagen_predict", fake_predict)
    im.generate("a swimmer mid-stroke", allow_people=True)
    assert seen["allow_people"] is True


def test_similar_requires_prompt_for_gemini(monkeypatch):
    import mediahub.media_ai.imagine as im
    import mediahub.media_ai.imagine_providers.gemini_imagine as g

    monkeypatch.setattr(g, "imagen_predict", lambda *a, **k: [_png_bytes()])
    img = im.ImageInput(data=_png_bytes(), mime="image/png")
    # Honest: gemini cannot condition on pixels, so a bare reference errors.
    with pytest.raises(im.ImagineError):
        im.similar(img)
    # With a description it re-rolls.
    results = im.similar(img, prompt="abstract gold ripples", n=2)
    assert len(results) >= 1
    assert results[0].operation == "similar"


def test_imagen_predict_request_shape(monkeypatch):
    """The low-level client posts the historic Imagen :predict payload."""
    import mediahub.media_ai.imagine_providers.gemini_imagine as g

    captured = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            import base64

            return {
                "predictions": [{"bytesBase64Encoded": base64.b64encode(_png_bytes()).decode()}]
            }

    def fake_post(url, headers=None, data=None, timeout=None):
        import json

        captured["url"] = url
        captured["headers"] = headers or {}
        captured["payload"] = json.loads(data)
        return _Resp()

    import requests

    monkeypatch.setattr(requests, "post", fake_post)
    out = g.imagen_predict("hello", aspect_ratio="3:4", sample_count=1)
    assert len(out) == 1
    params = captured["payload"]["parameters"]
    assert params["aspectRatio"] == "3:4"
    assert params["sampleCount"] == 1
    assert params["personGeneration"] == "dont_allow"
    assert ":predict" in captured["url"]
    # Key travels in the x-goog-api-key header, never the URL — a URL-borne
    # key would ride into every exception repr / access log.
    assert "test-key" not in captured["url"]
    assert captured["headers"].get("x-goog-api-key") == "test-key"


def test_imagen_predict_no_key_returns_empty(monkeypatch):
    import mediahub.media_ai.imagine_providers.gemini_imagine as g

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    import mediahub.web.secrets_store as ss

    importlib.reload(ss)
    assert g.imagen_predict("x") == []
