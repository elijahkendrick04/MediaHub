"""Tests for media_library.heic — HEIC/HEIF upload ingest (roadmap 1.3).

iPhones save HEIC by default; an un-normalised upload would be a broken asset.
These cover the detector, the in-place normalise-to-JPEG, the non-HEIC
passthrough, and the honest-error path when the optional ``pillow_heif`` dep
isn't installed (simulated by forcing the registration to fail).
"""
from __future__ import annotations

import pytest
from PIL import Image

from mediahub.media_library import heic


def _has_heif_writer() -> bool:
    try:
        import io

        import pillow_heif

        pillow_heif.register_heif_opener()
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, format="HEIF")
        return True
    except Exception:
        return False


needs_heif = pytest.mark.skipif(not _has_heif_writer(), reason="pillow_heif HEIF encode unavailable")


def test_is_heic_detects_suffixes():
    assert heic.is_heic("photo.HEIC")
    assert heic.is_heic("clip.heif")
    assert heic.is_heic("burst.hif")
    assert not heic.is_heic("photo.jpg")
    assert not heic.is_heic("photo.png")
    assert not heic.is_heic("")


def test_non_heic_passthrough(tmp_path):
    p = tmp_path / "photo.jpg"
    Image.new("RGB", (16, 16), (10, 20, 30)).save(p)
    out, converted = heic.normalize_upload(p)
    assert out == p and converted is False


@needs_heif
def test_normalize_heic_to_jpeg(tmp_path):
    src = tmp_path / "IMG_1234.heic"
    Image.new("RGB", (40, 30), (200, 120, 60)).save(src, format="HEIF")
    out, converted = heic.normalize_upload(src)
    assert converted is True
    assert out.suffix == ".jpg"
    assert out.exists()
    assert not src.exists()  # the original HEIC is replaced
    with Image.open(out) as im:
        im.load()
        assert im.size == (40, 30)
        assert (im.format or "").upper() == "JPEG"


@needs_heif
def test_heic_bytes_to_jpeg(tmp_path):
    import io

    import pillow_heif

    pillow_heif.register_heif_opener()
    buf = io.BytesIO()
    Image.new("RGB", (24, 24), (30, 60, 90)).save(buf, format="HEIF")
    jpeg = heic.heic_bytes_to_jpeg(buf.getvalue())
    with Image.open(io.BytesIO(jpeg)) as im:
        im.load()
        assert (im.format or "").upper() == "JPEG"


def test_unsupported_raises_when_decoder_absent(tmp_path, monkeypatch):
    # Simulate a deployment without pillow_heif: registration reports false.
    monkeypatch.setattr(heic, "_registered", None)
    monkeypatch.setattr(heic, "register_heif", lambda: False)
    src = tmp_path / "x.heic"
    src.write_bytes(b"not-a-real-heic")
    with pytest.raises(heic.HeicUnsupported):
        heic.normalize_upload(src)


def test_is_available_is_boolean():
    assert isinstance(heic.is_available(), bool)
