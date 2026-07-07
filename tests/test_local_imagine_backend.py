"""Roadmap 1.1 — the in-house local diffusion backend on the ``imagine`` seam.

The local backend is a self-hosted inference server reached over HTTP, so the
one place network would happen is ``requests.post``. Every test either configures
no endpoint (honest-error / resolution paths) or mocks ``requests.post`` — nothing
touches the network. DATA_DIR → tmp keeps the quota ledger and secrets isolated.
"""

from __future__ import annotations

import base64
import importlib
import io
import json

import pytest


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for var in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "ANTHROPIC_API_KEY",
        "MEDIAHUB_IMAGINE_PROVIDER",
        "MEDIAHUB_IMAGINE_LOCAL_ENDPOINT",
        "MEDIAHUB_IMAGINE_LOCAL_TOKEN",
        "MEDIAHUB_IMAGINE_LOCAL_MODEL",
        "MEDIAHUB_IMAGINE_LOCAL_CAPABILITIES",
        "MEDIAHUB_IMAGINE_LOCAL_STEPS",
        "MEDIAHUB_IMAGINE_LOCAL_TIMEOUT",
        "MEDIAHUB_IMAGINE_QUOTA_MONTHLY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import mediahub.web.secrets_store as ss
    import mediahub.observability.imagine_usage as iu

    importlib.reload(ss)
    importlib.reload(iu)


def _png(color=(10, 20, 30)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg(color=(40, 50, 60)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, format="JPEG")
    return buf.getvalue()


class _Resp:
    """A stand-in for a ``requests`` response."""

    def __init__(self, *, jbody=None, content=None, ctype=None, status=200, text=None):
        self._j = jbody
        self.content = content or b""
        self.status_code = status
        self.headers = {
            "Content-Type": ctype or ("application/json" if jbody is not None else "image/png")
        }
        self.text = text if text is not None else (json.dumps(jbody) if jbody is not None else "")

    def json(self):
        if self._j is None:
            raise ValueError("not json")
        return self._j


@pytest.fixture
def post(monkeypatch):
    """Patch ``requests.post`` with a programmable, capturing fake."""
    import requests

    state = {"resp": _Resp(jbody={"images": [base64.b64encode(_png()).decode()]}), "calls": []}

    def fake_post(url, json=None, headers=None, timeout=None):
        state["calls"].append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        resp = state["resp"]
        return resp(url) if callable(resp) else resp

    monkeypatch.setattr(requests, "post", fake_post)
    return state


def _set_endpoint(monkeypatch, url="http://imagine:8800", token=None):
    monkeypatch.setenv("MEDIAHUB_IMAGINE_LOCAL_ENDPOINT", url)
    if token:
        monkeypatch.setenv("MEDIAHUB_IMAGINE_LOCAL_TOKEN", token)


def _im():
    import mediahub.media_ai.imagine as im

    return im


def _provider():
    from mediahub.media_ai.imagine_providers.local_imagine import LocalImagineProvider

    return LocalImagineProvider()


# ---------------------------------------------------------------------------
# Resolution / availability / in-house-first precedence
# ---------------------------------------------------------------------------


def test_unavailable_with_no_endpoint():
    p = _provider()
    assert p.is_available() is False
    assert p.capabilities() == set()
    assert p.default_model() == "flux.1-schnell"


def test_available_with_endpoint(monkeypatch):
    _set_endpoint(monkeypatch)
    assert _provider().is_available() is True


def test_endpoint_makes_local_the_default_provider(monkeypatch):
    import mediahub.media_ai.imagine_providers as ip

    _set_endpoint(monkeypatch)
    prov = ip.get_imagine_provider()
    assert prov is not None and prov.name == "local"


def test_local_wins_over_gemini_in_house_first(monkeypatch):
    """A configured local endpoint beats a present Gemini key (in-house first)."""
    import mediahub.media_ai.imagine_providers as ip

    _set_endpoint(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    prov = ip.get_imagine_provider()
    assert prov is not None and prov.name == "local"


def test_explicit_gemini_honoured_even_with_local_endpoint(monkeypatch):
    import mediahub.media_ai.imagine_providers as ip

    _set_endpoint(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("MEDIAHUB_IMAGINE_PROVIDER", "gemini")
    prov = ip.get_imagine_provider()
    assert prov is not None and prov.name == "gemini"


def test_model_id_overridable(monkeypatch):
    _set_endpoint(monkeypatch)
    monkeypatch.setenv("MEDIAHUB_IMAGINE_LOCAL_MODEL", "sdxl-turbo")
    assert _provider().default_model() == "sdxl-turbo"


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


def test_default_capabilities(monkeypatch):
    _set_endpoint(monkeypatch)
    caps = _provider().capabilities()
    assert caps == {"generate", "similar", "edit", "expand", "remove", "style_match"}
    assert "upscale" not in caps  # opt-in (needs a dedicated upscaler model)


def test_capabilities_all(monkeypatch):
    _set_endpoint(monkeypatch)
    monkeypatch.setenv("MEDIAHUB_IMAGINE_LOCAL_CAPABILITIES", "all")
    assert "upscale" in _provider().capabilities()


def test_capabilities_subset_filters_unknown(monkeypatch):
    _set_endpoint(monkeypatch)
    monkeypatch.setenv("MEDIAHUB_IMAGINE_LOCAL_CAPABILITIES", "generate, edit , frobnicate")
    assert _provider().capabilities() == {"generate", "edit"}


def test_available_operations_reflects_local(monkeypatch):
    _set_endpoint(monkeypatch)
    ops = _im().available_operations()
    for op in ("generate", "edit", "expand", "remove", "style_match", "subject_lift"):
        assert op in ops


# ---------------------------------------------------------------------------
# Request shaping
# ---------------------------------------------------------------------------


def test_generate_request_shape(monkeypatch, post):
    _set_endpoint(monkeypatch, token="sek-ret")
    monkeypatch.setenv("MEDIAHUB_IMAGINE_LOCAL_STEPS", "4")
    res = _im().generate("a poolside backdrop", style="editorial", aspect="9:16")
    call = post["calls"][-1]
    assert call["url"] == "http://imagine:8800/generate"
    assert call["headers"]["Authorization"] == "Bearer sek-ret"
    body = call["json"]
    assert body["aspect"] == "9:16"
    assert body["allow_people"] is False
    assert body["n"] == 1
    assert body["steps"] == 4
    assert body["model"] == "flux.1-schnell"
    assert "editorial" in body["prompt"].lower()  # style preset folded in
    assert res[0].provider == "local"
    assert res[0].model == "flux.1-schnell"
    assert res[0].operation == "generate"
    assert res[0].manifest["digital_source_type"] == "ai_generated"


def test_no_auth_header_without_token(monkeypatch, post):
    _set_endpoint(monkeypatch)  # no token
    _im().generate("x")
    assert "Authorization" not in post["calls"][-1]["headers"]


def test_generate_n_clamped(monkeypatch, post):
    _set_endpoint(monkeypatch)
    _im().generate("x", n=99)
    assert post["calls"][-1]["json"]["n"] == 4


def test_allow_people_opt_in(monkeypatch, post):
    _set_endpoint(monkeypatch)
    _im().generate("a swimmer mid-stroke", allow_people=True)
    assert post["calls"][-1]["json"]["allow_people"] is True


def test_edit_posts_mask_and_composite_provenance(monkeypatch, post):
    _set_endpoint(monkeypatch)
    img = _im().ImageInput(data=_png(), mime="image/png", mask=_png((1, 1, 1)))
    res = _im().edit(img, "add a lane rope")
    call = post["calls"][-1]
    assert call["url"].endswith("/edit")
    assert call["json"]["mask"]  # base64 mask present
    assert call["json"]["prompt"] == "add a lane rope"
    assert res.operation == "edit"
    assert res.manifest["digital_source_type"] == "ai_composite"


def test_expand_request_shape(monkeypatch, post):
    _set_endpoint(monkeypatch)
    img = _im().ImageInput(data=_png())
    _im().expand(img, aspect="16:9", prompt="more sky")
    call = post["calls"][-1]
    assert call["url"].endswith("/expand")
    assert call["json"]["aspect"] == "16:9"
    assert call["json"]["prompt"] == "more sky"
    assert call["json"]["image"]


def test_remove_request_shape(monkeypatch, post):
    _set_endpoint(monkeypatch)
    img = _im().ImageInput(data=_png(), mask=_png((2, 2, 2)))
    _im().remove(img)
    call = post["calls"][-1]
    assert call["url"].endswith("/remove")
    assert call["json"]["mask"]


def test_style_match_request_shape(monkeypatch, post):
    _set_endpoint(monkeypatch)
    img = _im().ImageInput(data=_png())
    _im().style_match(img, style="poster", palette={"accent": "#102030"})
    call = post["calls"][-1]
    assert call["url"].endswith("/style_match")
    assert call["json"]["style"] == "poster"
    assert call["json"]["palette"] == {"accent": "#102030"}


def test_similar_needs_no_prompt_for_local(monkeypatch, post):
    """Local conditions on pixels (img2img), so a bare reference is valid."""
    _set_endpoint(monkeypatch)
    img = _im().ImageInput(data=_png())
    res = _im().similar(img)  # no prompt — would honest-error on gemini
    assert post["calls"][-1]["url"].endswith("/similar")
    assert res[0].operation == "similar"


# ---------------------------------------------------------------------------
# Tolerant response parsing
# ---------------------------------------------------------------------------


def test_response_images_list_of_b64(monkeypatch, post):
    _set_endpoint(monkeypatch)
    png = _png((9, 9, 9))
    post["resp"] = _Resp(jbody={"images": [base64.b64encode(png).decode()]})
    assert _im().generate("x")[0].data == png


def test_response_images_list_of_dicts(monkeypatch, post):
    _set_endpoint(monkeypatch)
    png = _png((8, 7, 6))
    post["resp"] = _Resp(jbody={"images": [{"b64": base64.b64encode(png).decode(), "seed": 11}]})
    out = _im().generate("x")
    assert out[0].data == png


def test_response_openai_data_shape(monkeypatch, post):
    _set_endpoint(monkeypatch)
    png = _png((5, 5, 5))
    post["resp"] = _Resp(jbody={"data": [{"b64_json": base64.b64encode(png).decode()}]})
    assert _im().generate("x")[0].data == png


def test_response_single_image_field(monkeypatch, post):
    _set_endpoint(monkeypatch)
    png = _png((3, 3, 3))
    post["resp"] = _Resp(jbody={"image": base64.b64encode(png).decode()})
    assert _im().generate("x")[0].data == png


def test_response_data_uri(monkeypatch, post):
    _set_endpoint(monkeypatch)
    png = _png((4, 4, 4))
    uri = "data:image/png;base64," + base64.b64encode(png).decode()
    post["resp"] = _Resp(jbody={"images": [uri]})
    assert _im().generate("x")[0].data == png


def test_response_raw_image_bytes(monkeypatch, post):
    _set_endpoint(monkeypatch)
    png = _png((2, 2, 2))
    post["resp"] = _Resp(content=png, ctype="image/png")
    out = _im().generate("x")
    assert out[0].data == png and out[0].mime == "image/png"


def test_response_raw_jpeg_mime_from_header(monkeypatch, post):
    _set_endpoint(monkeypatch)
    jpg = _jpeg()
    post["resp"] = _Resp(content=jpg, ctype="image/jpeg")
    out = _im().generate("x")
    assert out[0].data == jpg and out[0].mime == "image/jpeg"


def test_response_mime_sniffed_when_unlabelled(monkeypatch, post):
    _set_endpoint(monkeypatch)
    jpg = _jpeg()
    # JSON carries a jpeg under an untyped field — mime is sniffed from bytes.
    post["resp"] = _Resp(jbody={"images": [base64.b64encode(jpg).decode()]})
    assert _im().generate("x")[0].mime == "image/jpeg"


# ---------------------------------------------------------------------------
# Honest errors
# ---------------------------------------------------------------------------


def test_no_endpoint_provider_not_configured():
    im = _im()
    with pytest.raises(im.ProviderNotConfigured):
        im.generate("x")


def test_explicit_local_no_endpoint_honest_errors(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_IMAGINE_PROVIDER", "local")
    monkeypatch.setenv("GEMINI_API_KEY", "k")  # must NOT silently switch to cloud
    im = _im()
    with pytest.raises(im.ProviderNotConfigured):
        im.generate("x")


def test_non_2xx_is_honest_error(monkeypatch, post):
    _set_endpoint(monkeypatch)
    post["resp"] = _Resp(jbody={"error": "boom"}, status=500)
    im = _im()
    with pytest.raises(im.ImagineError) as ei:
        im.generate("x")
    assert "500" in str(ei.value)


def test_empty_images_is_honest_error(monkeypatch, post):
    _set_endpoint(monkeypatch)
    post["resp"] = _Resp(jbody={"images": []})
    im = _im()
    with pytest.raises(im.ImagineError):
        im.generate("x")


def test_no_image_error_does_not_leak_endpoint(monkeypatch, post):
    """The ImagineError text can reach customers via the studio UI, so the
    internal endpoint URL must never appear in it (server log only)."""
    _set_endpoint(monkeypatch, url="http://imagine-internal:8800")
    post["resp"] = _Resp(jbody={"images": []})
    im = _im()
    with pytest.raises(im.ImagineError) as ei:
        im.generate("x")
    assert "imagine-internal" not in str(ei.value)
    assert "8800" not in str(ei.value)


def test_network_exception_is_honest_error(monkeypatch):
    _set_endpoint(monkeypatch)
    import requests

    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(requests, "post", boom)
    im = _im()
    with pytest.raises(im.ImagineError):
        im.generate("x")


def test_unsupported_op_honest_errors(monkeypatch, post):
    """Upscale is not in the default caps → ImagineUnsupported via the facade."""
    _set_endpoint(monkeypatch)
    im = _im()
    img = im.ImageInput(data=_png())
    with pytest.raises(im.ImagineUnsupported):
        im.upscale(img)


def test_upscale_works_when_capability_enabled(monkeypatch, post):
    _set_endpoint(monkeypatch)
    monkeypatch.setenv("MEDIAHUB_IMAGINE_LOCAL_CAPABILITIES", "all")
    im = _im()
    img = im.ImageInput(data=_png())
    res = im.upscale(img, factor=4)
    assert post["calls"][-1]["url"].endswith("/upscale")
    assert post["calls"][-1]["json"]["factor"] == 4
    assert res.operation == "upscale"


def test_token_redacted_in_error(monkeypatch, post):
    _set_endpoint(monkeypatch, token="super-secret-token")
    post["resp"] = _Resp(
        status=502, ctype="text/plain", text="upstream failed: token super-secret-token"
    )
    im = _im()
    with pytest.raises(im.ImagineError) as ei:
        im.generate("x")
    assert "super-secret-token" not in str(ei.value)
    assert "***" in str(ei.value)


# ---------------------------------------------------------------------------
# Through the facade: quota metering + provenance
# ---------------------------------------------------------------------------


def test_facade_meters_quota_and_records_model(monkeypatch, post):
    _set_endpoint(monkeypatch)
    import mediahub.observability.imagine_usage as iu

    im = _im()
    out = im.generate("a navy and gold backdrop", org_id="club-x")
    assert out[0].model == "flux.1-schnell"
    assert out[0].manifest["provider"] == "local"
    assert iu.count_for_org("club-x") == 1


def test_facade_quota_exceeded(monkeypatch, post):
    _set_endpoint(monkeypatch)
    monkeypatch.setenv("MEDIAHUB_IMAGINE_QUOTA_MONTHLY", "0")
    im = _im()
    with pytest.raises(im.QuotaExceeded):
        im.generate("x", org_id="club-x")
