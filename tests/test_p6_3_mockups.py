"""P6.3 Build 2 — deterministic product mockups (PIL compositing, key-free)."""

from __future__ import annotations

import io

import pytest


def _art(color=(20, 60, 120), size=(800, 1000)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_list_templates_shape():
    from mediahub.mockups import list_templates

    tpls = list_templates()
    ids = {t["id"] for t in tpls}
    assert {"poster_wall", "framed_print", "phone_post", "flatlay"} <= ids
    for t in tpls:
        assert t["label"] and t["description"] and t["aspect"]


@pytest.mark.parametrize("tid", ["poster_wall", "framed_print", "phone_post", "flatlay"])
def test_compose_each_template(tid):
    from PIL import Image
    from mediahub.mockups import compose_mockup, MOCKUP_TEMPLATES

    out = compose_mockup(_art(), tid, accent="#d4af37")
    img = Image.open(io.BytesIO(out))
    tpl = MOCKUP_TEMPLATES[tid]
    assert img.size == (tpl.width, tpl.height)
    assert img.format == "PNG"


def test_unknown_template_errors():
    from mediahub.mockups import compose_mockup, MockupError

    with pytest.raises(MockupError):
        compose_mockup(_art(), "does_not_exist")


def test_bad_artwork_errors():
    from mediahub.mockups import compose_mockup, MockupError

    with pytest.raises(MockupError):
        compose_mockup(b"not an image", "poster_wall")


def test_deterministic_bytes():
    from mediahub.mockups import compose_mockup

    a = compose_mockup(_art(), "phone_post", accent="#123456")
    b = compose_mockup(_art(), "phone_post", accent="#123456")
    assert a == b


def test_accent_changes_output():
    from mediahub.mockups import compose_mockup

    neutral = compose_mockup(_art(), "poster_wall", accent=None)
    gold = compose_mockup(_art(), "poster_wall", accent="#d4af37")
    # The brand tint visibly changes the backdrop, so the bytes differ.
    assert neutral != gold


def test_landscape_art_fits_without_crash():
    from mediahub.mockups import compose_mockup

    out = compose_mockup(_art(size=(1600, 600)), "framed_print")
    assert len(out) > 0
