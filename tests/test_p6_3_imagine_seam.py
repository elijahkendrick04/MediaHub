"""P6.3 — the imagine provider seam: resolution, capabilities, honest errors.

No network: every test either configures no provider (honest-error paths) or
mocks the provider's low-level client.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    # Clear provider keys and any explicit provider pin so each test starts from
    # a known-honest baseline. DATA_DIR → tmp so secrets_store can't smuggle a
    # key in from the dev sandbox.
    for var in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "ANTHROPIC_API_KEY",
        "MEDIAHUB_IMAGINE_PROVIDER",
        "MEDIAHUB_IMAGINE_LOCAL_ENDPOINT",
        "MEDIAHUB_IMAGINE_QUOTA_MONTHLY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import mediahub.web.secrets_store as ss

    importlib.reload(ss)


def _imagine():
    import mediahub.media_ai.imagine as im

    return im


def _providers():
    import mediahub.media_ai.imagine_providers as ip

    return ip


def test_no_provider_when_nothing_configured():
    ip = _providers()
    assert ip.get_imagine_provider() is None


def test_facade_honest_when_nothing_configured():
    im = _imagine()
    assert im.is_available() is False
    assert im.active_provider_name() == ""
    # Deterministic subject_lift is always offered; provider ops are not.
    assert im.available_operations() == {"subject_lift"}


def test_generate_raises_provider_not_configured():
    im = _imagine()
    with pytest.raises(im.ProviderNotConfigured):
        im.generate("a poolside backdrop")


def test_gemini_selected_when_key_present(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    ip = _providers()
    prov = ip.get_imagine_provider()
    assert prov is not None
    assert prov.name == "gemini"
    assert prov.capabilities() == {"generate", "similar"}
    assert prov.supports("generate") is True
    assert prov.supports("edit") is False


def test_explicit_local_is_honoured_and_honest_errors(monkeypatch):
    # An operator who *asks* for local must not be silently switched to a billed
    # cloud call — even with a Gemini key present.
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("MEDIAHUB_IMAGINE_PROVIDER", "local")
    ip = _providers()
    prov = ip.get_imagine_provider()
    assert prov is not None and prov.name == "local"
    assert prov.is_available() is False
    im = _imagine()
    with pytest.raises(im.ProviderNotConfigured):
        im.generate("anything")


def test_explicit_gemini_without_key_honest_errors(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_IMAGINE_PROVIDER", "gemini")
    ip = _providers()
    prov = ip.get_imagine_provider()
    assert prov is not None and prov.name == "gemini"
    assert prov.is_available() is False


def test_unknown_provider_value_ignored(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_IMAGINE_PROVIDER", "midjourney")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    ip = _providers()
    # Falls through to the in-house-first resolution → gemini (key present).
    prov = ip.get_imagine_provider()
    assert prov is not None and prov.name == "gemini"


def test_unsupported_op_raises_imagine_unsupported(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    im = _imagine()
    img = im.ImageInput(data=b"\x89PNG", mime="image/png")
    with pytest.raises(im.ImagineUnsupported):
        im.edit(img, "make the sky bluer")
    with pytest.raises(im.ImagineUnsupported):
        im.remove(img)


def test_available_operations_includes_gemini_caps(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    im = _imagine()
    ops = im.available_operations()
    assert "generate" in ops and "similar" in ops and "subject_lift" in ops
    assert "edit" not in ops  # gemini doesn't claim it; honest


def test_all_operations_constant_is_the_full_vocabulary():
    im = _imagine()
    for op in ("generate", "similar", "edit", "expand", "remove", "upscale",
               "style_match", "subject_lift"):
        assert op in im.ALL_OPERATIONS
