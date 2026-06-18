"""P6.3 Build 2 — grab_text (vision OCR). Mocks the vision LLM; no network."""

from __future__ import annotations

import importlib

import pytest


def _png(path):
    from PIL import Image

    Image.new("RGB", (40, 40), (30, 30, 30)).save(path)
    return path


@pytest.fixture
def imagine_with_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MEDIAHUB_IMAGINE_QUOTA_MONTHLY", raising=False)
    import mediahub.observability.imagine_usage as iu

    importlib.reload(iu)
    import mediahub.media_ai.imagine as im

    return im, iu


def test_grab_text_missing_image(imagine_with_ledger, tmp_path):
    im, iu = imagine_with_ledger
    with pytest.raises(im.ImagineError):
        im.grab_text(tmp_path / "nope.png")


def test_grab_text_no_vision_provider(imagine_with_ledger, tmp_path, monkeypatch):
    im, iu = imagine_with_ledger
    src = _png(tmp_path / "p.png")
    import mediahub.media_ai.llm as llm

    monkeypatch.setattr(llm, "is_available", lambda: False)
    with pytest.raises(im.ProviderNotConfigured):
        im.grab_text(src)


def test_grab_text_success_and_metered(imagine_with_ledger, tmp_path, monkeypatch):
    im, iu = imagine_with_ledger
    src = _png(tmp_path / "p.png")
    import mediahub.media_ai.llm as llm

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(
        llm, "generate_vision", lambda paths, prompt, **k: "WELSH NATIONALS\n100m Free\n55.21"
    )
    res = im.grab_text(src, org_id="club-a")
    assert res.found is True
    assert res.blocks == ["WELSH NATIONALS", "100m Free", "55.21"]
    assert iu.count_for_org("club-a") == 1


def test_grab_text_empty_result(imagine_with_ledger, tmp_path, monkeypatch):
    im, iu = imagine_with_ledger
    src = _png(tmp_path / "p.png")
    import mediahub.media_ai.llm as llm

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm, "generate_vision", lambda paths, prompt, **k: "   ")
    res = im.grab_text(src)
    assert res.found is False
    assert res.blocks == []


def test_grab_text_vision_unavailable_maps_to_provider_error(
    imagine_with_ledger, tmp_path, monkeypatch
):
    im, iu = imagine_with_ledger
    src = _png(tmp_path / "p.png")
    import mediahub.media_ai.llm as llm

    monkeypatch.setattr(llm, "is_available", lambda: True)

    def _boom(paths, prompt, **k):
        raise llm.ClaudeUnavailableError("no key")

    monkeypatch.setattr(llm, "generate_vision", _boom)
    with pytest.raises(im.ProviderNotConfigured):
        im.grab_text(src, org_id="club-a")
    # A failed call is not counted against quota.
    assert iu.count_for_org("club-a") == 0


def test_grab_text_in_available_operations(imagine_with_ledger, monkeypatch):
    im, iu = imagine_with_ledger
    import mediahub.media_ai.llm as llm

    monkeypatch.setattr(llm, "is_available", lambda: True)
    assert "grab_text" in im.available_operations()
    monkeypatch.setattr(llm, "is_available", lambda: False)
    assert "grab_text" not in im.available_operations()
