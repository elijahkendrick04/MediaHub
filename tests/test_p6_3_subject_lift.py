"""P6.3 — subject_lift (Magic Grab): deterministic cutout + saliency reuse.

No provider key needed (it is key-free and unmetered). We stub the cutout
remover so no model runs, and assert the facade composes cutout + saliency.
"""

from __future__ import annotations

import io

import pytest


def _png(path, color=(40, 80, 120)):
    from PIL import Image

    Image.new("RGB", (64, 64), color).save(path)
    return path


def _rgba_png_bytes():
    # Noisy 256×256 so the encoded PNG comfortably clears the 1KB
    # "is this a real cutout" validity threshold.
    import os

    from PIL import Image

    buf = io.BytesIO()
    Image.frombytes("RGBA", (256, 256), os.urandom(256 * 256 * 4)).save(buf, format="PNG")
    return buf.getvalue()


def test_subject_lift_missing_source(tmp_path):
    import mediahub.media_ai.imagine as im

    res = im.subject_lift(tmp_path / "nope.jpg")
    assert res.status == "no_source"
    assert res.cutout_path == ""


def test_subject_lift_unavailable_when_no_remover(tmp_path, monkeypatch):
    import mediahub.media_ai.imagine as im
    import mediahub.media_ai.providers as providers

    src = _png(tmp_path / "photo.jpg")

    class _NoRemover:
        def is_available(self):
            return False

    monkeypatch.setattr(providers, "get_bg_remover", lambda: _NoRemover())
    res = im.subject_lift(src)
    assert res.status == "unavailable"


def test_subject_lift_success_composes_cutout_and_focus(tmp_path, monkeypatch):
    import mediahub.media_ai.imagine as im
    import mediahub.media_ai.providers as providers

    src = _png(tmp_path / "photo.jpg")
    cut_bytes = _rgba_png_bytes()

    class _Remover:
        name = "rembg"

        def is_available(self):
            return True

        def remove(self, s, d):
            from pathlib import Path

            Path(d).write_bytes(cut_bytes)
            return d

    monkeypatch.setattr(providers, "get_bg_remover", lambda: _Remover())
    # Stub saliency so the test is independent of energy-map maths.
    import mediahub.graphic_renderer.saliency as sal

    monkeypatch.setattr(sal, "focus_position", lambda path, ratio="4:5": "60% 40%")

    res = im.subject_lift(src, ratio="9:16")
    assert res.status == "generated"
    assert res.cutout_path.endswith("_cutout.png")
    assert res.focus_position == "60% 40%"


def test_subject_lift_failed_when_cutout_too_small(tmp_path, monkeypatch):
    import mediahub.media_ai.imagine as im
    import mediahub.media_ai.providers as providers

    src = _png(tmp_path / "photo.jpg")

    class _Remover:
        name = "rembg"

        def is_available(self):
            return True

        def remove(self, s, d):
            from pathlib import Path

            Path(d).write_bytes(b"tiny")  # < 1KB → treated as failed
            return d

    monkeypatch.setattr(providers, "get_bg_remover", lambda: _Remover())
    res = im.subject_lift(src)
    assert res.status == "failed"
