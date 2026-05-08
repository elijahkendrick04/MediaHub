"""V8.1 Issue 7 §4 — cutout provider tests.

These tests verify the **request shape** sent to Photoroom and the model
chosen on Replicate, plus the provider-selector fall-back behaviour.

The live HTTP / SDK calls are mocked: tests never hit the network.
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mediahub.media_ai.providers import _resolve_provider_choice, get_bg_remover
from mediahub.media_ai.providers.photoroom_provider import (
    DEFAULT_ENDPOINT as PHOTOROOM_ENDPOINT,
    PhotoroomBgRemover,
)
from mediahub.media_ai.providers.replicate_provider import (
    DEFAULT_MODEL as REPLICATE_MODEL,
    ReplicateBgRemover,
)


# ---------------------------------------------------------------------------
# Photoroom request-shape contract
# ---------------------------------------------------------------------------

def _fake_response(status=200, content=b"\x89PNG\r\n\x1a\nfake", content_type="image/png"):
    r = mock.Mock()
    r.status_code = status
    r.content = content
    r.headers = {"content-type": content_type}
    r.text = ""
    r.json = mock.Mock(return_value={})
    return r


def test_photoroom_request_shape():
    prov = PhotoroomBgRemover(api_key="test_key_123")
    src = b"\x89PNG\r\n\x1a\norig"

    with mock.patch(
        "media_ai.providers.photoroom_provider.requests.post",
        return_value=_fake_response(),
    ) as post:
        out = prov.cutout(src)

    assert out.startswith(b"\x89PNG"), "should return bytes from response"
    assert post.call_count == 1
    args, kwargs = post.call_args

    # Endpoint
    assert args[0] == PHOTOROOM_ENDPOINT
    assert PHOTOROOM_ENDPOINT == "https://sdk.photoroom.com/v1/segment"

    # Auth header
    headers = kwargs["headers"]
    assert headers["x-api-key"] == "test_key_123"

    # Multipart upload field name MUST be `image_file`
    files = kwargs["files"]
    assert "image_file" in files
    assert files["image_file"][1] == src  # raw bytes preserved

    # Form data must request a transparent PNG
    data = kwargs["data"]
    assert data["format"] == "png"
    assert data["bg_color"] == "transparent"


def test_photoroom_endpoint_override_via_env(monkeypatch):
    monkeypatch.setenv("PHOTOROOM_ENDPOINT", "https://staging.example/v1/segment")
    prov = PhotoroomBgRemover(api_key="k")
    assert prov.endpoint == "https://staging.example/v1/segment"


def test_photoroom_raises_on_missing_key(monkeypatch):
    # Make sure neither env nor secrets store provides a key.
    monkeypatch.delenv("PHOTOROOM_API_KEY", raising=False)
    with mock.patch(
        "media_ai.providers.photoroom_provider._resolve_photoroom_key",
        return_value=None,
    ):
        prov = PhotoroomBgRemover()
        assert prov.is_available() is False
        with pytest.raises(RuntimeError, match="PHOTOROOM_API_KEY"):
            prov.cutout(b"x")


def test_photoroom_raises_on_http_error():
    prov = PhotoroomBgRemover(api_key="k")
    bad = _fake_response(status=402, content_type="application/json")
    bad.json = mock.Mock(return_value={"error": "out of credits"})
    with mock.patch(
        "media_ai.providers.photoroom_provider.requests.post",
        return_value=bad,
    ):
        with pytest.raises(RuntimeError, match="402"):
            prov.cutout(b"x")


# ---------------------------------------------------------------------------
# Replicate request-shape contract
# ---------------------------------------------------------------------------

def test_replicate_default_model_is_851_labs():
    """Spec V8.1 §4 mandates 851-labs/background-remover."""
    assert REPLICATE_MODEL == "851-labs/background-remover"
    prov = ReplicateBgRemover(token="r8_xxxxxxxxxxxxxxxxxx")
    assert prov.model == REPLICATE_MODEL


def test_replicate_cutout_passes_correct_model_and_image():
    prov = ReplicateBgRemover(token="r8_xxxxxxxxxxxxxxxxxx")
    src = b"raw bytes"

    fake_client = mock.Mock()
    fake_client.run = mock.Mock(return_value="https://replicate.delivery/x.png")

    fake_replicate_module = mock.Mock()
    fake_replicate_module.Client = mock.Mock(return_value=fake_client)

    with mock.patch.dict(sys.modules, {"replicate": fake_replicate_module}):
        with mock.patch(
            "media_ai.providers.replicate_provider.requests.get",
            return_value=_fake_response(content=b"\x89PNGcut"),
        ) as fetch:
            out = prov.cutout(src)

    assert out == b"\x89PNGcut"

    # Client constructed with the resolved token
    fake_replicate_module.Client.assert_called_once_with(api_token="r8_xxxxxxxxxxxxxxxxxx")
    # The model passed to .run MUST be 851-labs/background-remover
    run_args, run_kwargs = fake_client.run.call_args
    assert run_args[0] == "851-labs/background-remover"
    # `image` input must be a file-like wrapping the original bytes
    image_arg = run_kwargs["input"]["image"]
    assert isinstance(image_arg, io.BytesIO)
    assert image_arg.getvalue() == src
    # Output URL was fetched
    fetch.assert_called_once_with("https://replicate.delivery/x.png", timeout=60)


def test_replicate_model_override_via_env(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_REPLICATE_BG_MODEL", "qa-org/qa-bg")
    prov = ReplicateBgRemover(token="r8_xxxxxxxxxxxxxxxxxx")
    assert prov.model == "qa-org/qa-bg"


# ---------------------------------------------------------------------------
# Provider selector
# ---------------------------------------------------------------------------

def test_resolve_provider_choice_default_local(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_CUTOUT_PROVIDER", raising=False)
    monkeypatch.delenv("MEDIAHUB_BG_PROVIDER", raising=False)
    with mock.patch(
        "swim_content_v4.secrets_store.get_secret", return_value=None,
    ):
        assert _resolve_provider_choice() == "local"


def test_resolve_provider_choice_env_wins(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_CUTOUT_PROVIDER", "photoroom")
    assert _resolve_provider_choice() == "photoroom"

    monkeypatch.setenv("MEDIAHUB_CUTOUT_PROVIDER", "replicate")
    assert _resolve_provider_choice() == "replicate"

    # rembg aliases to local
    monkeypatch.setenv("MEDIAHUB_CUTOUT_PROVIDER", "rembg")
    assert _resolve_provider_choice() == "local"


def test_resolve_provider_choice_unknown_falls_back_to_local(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_CUTOUT_PROVIDER", "magic-ai")
    monkeypatch.delenv("MEDIAHUB_BG_PROVIDER", raising=False)
    assert _resolve_provider_choice() == "local"


def test_resolve_provider_choice_legacy_env(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_CUTOUT_PROVIDER", raising=False)
    monkeypatch.setenv("MEDIAHUB_BG_PROVIDER", "replicate")
    assert _resolve_provider_choice() == "replicate"


def test_get_bg_remover_falls_back_when_photoroom_unconfigured(monkeypatch):
    """Spec: do NOT break the no-API-key path."""
    monkeypatch.setenv("MEDIAHUB_CUTOUT_PROVIDER", "photoroom")
    monkeypatch.delenv("PHOTOROOM_API_KEY", raising=False)
    with mock.patch(
        "media_ai.providers.photoroom_provider._resolve_photoroom_key",
        return_value=None,
    ):
        rem = get_bg_remover()
    assert rem is not None
    # Falls back to local rembg
    assert rem.__class__.__name__ != "PhotoroomBgRemover"


def test_get_bg_remover_falls_back_when_replicate_unconfigured(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_CUTOUT_PROVIDER", "replicate")
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    with mock.patch(
        "media_ai.providers.replicate_provider._resolve_replicate_token",
        return_value=None,
    ):
        rem = get_bg_remover()
    assert rem is not None
    assert rem.__class__.__name__ != "ReplicateBgRemover"
