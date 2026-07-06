"""contact_sheet carries the athlete photo ONCE in the render HTML.

The six film frames all show the same real shot; before this fix the full
base64 data URI was substituted into every frame (~6x HTML bloat per
MB-scale cutout). Now the URI rides a single ``--mh-athlete-img`` custom
property and each frame's ``<img>`` references it via ``content: var(...)``.

Structural assertions run everywhere; the visual check (each frame really
paints the photo) drives Chromium and is skipped when Playwright is missing.
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import pytest


def _have_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(args=["--no-sandbox"])
                browser.close()
                return True
            except Exception:
                return False
    except Exception:
        return False


def _brand():
    from mediahub.brand.kit import BrandKit

    return BrandKit(
        profile_id="t",
        display_name="Test Swim Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="TSC",
    )


def _brief():
    from mediahub.creative_brief.generator import generate as gen_brief
    from mediahub.media_requirements.evaluator import EvaluationResult

    ev = EvaluationResult(
        content_item_id="ci-1",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout="contact_sheet",
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier="high",
        confidence_label="NEW PB",
        explain="ok",
    )
    item = {
        "id": "ci-1",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
        },
    }
    brief = gen_brief(
        item, ev, _brand(), profile_id="t", meet_name="Manchester Open", venue_name="Pool"
    )
    brief.layout_template = "contact_sheet"
    return brief


def _photo(tmp_path: Path, rgb=(200, 30, 30)) -> Path:
    from PIL import Image

    p = tmp_path / "athlete.png"
    Image.new("RGB", (400, 500), rgb).save(p)
    return p


def _render(tmp_path: Path):
    from mediahub.graphic_renderer.render import render_brief

    return render_brief(
        _brief(),
        output_dir=tmp_path / "out",
        size=(1080, 1350),
        format_name="feed_portrait",
        athlete_path=_photo(tmp_path),
        skip_cutout=True,
        brand_kit=_brand(),
    )


@pytest.mark.skipif(not _have_playwright(), reason="Playwright/Chromium not available")
class TestContactSheetPhotoOnce:
    @pytest.fixture(autouse=True)
    def _v2_on(self, monkeypatch):
        # conftest pins the legacy engine; contact_sheet is a v2 archetype.
        monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")

    def test_data_uri_appears_exactly_once(self, tmp_path):
        res = _render(tmp_path)
        payload = base64.b64encode(_photo(tmp_path).read_bytes()).decode("ascii")
        assert res.html.count(payload) == 1, "athlete photo inlined more than once"
        # Carried by the custom property, referenced per frame.
        assert "--mh-athlete-img:url(" in res.html
        assert res.html.count('<img class="athlete-cutout"') == 6

    def test_every_frame_paints_the_photo(self, tmp_path):
        """Visual parity: all six frames render the (solid-red) shot — the
        content: var(--mh-athlete-img) reference really resolves."""
        from PIL import Image

        res = _render(tmp_path)
        im = Image.open(res.visual.file_path).convert("RGB")
        w, h = im.size
        # The grid spans the middle band of the card; sample well inside each
        # of the 3x2 frames (grid sits between header/sprockets and caption).
        grid_top, grid_bottom = 0.14 * h, 0.62 * h
        row_h = (grid_bottom - grid_top) / 2
        pad_x, col_w = 64 / 1080 * w, (w - 2 * (64 / 1080 * w)) / 3
        for r in range(2):
            for c in range(3):
                x = int(pad_x + col_w * (c + 0.5))
                y = int(grid_top + row_h * (r + 0.35))
                px = im.getpixel((x, y))
                assert px[0] > 120 and px[0] > px[2] + 40, (
                    f"frame ({r},{c}) at ({x},{y}) not showing the photo: {px}"
                )

    def test_no_photo_frames_stay_clean(self, tmp_path):
        from mediahub.graphic_renderer.render import render_brief

        res = render_brief(
            _brief(),
            output_dir=tmp_path / "out2",
            size=(1080, 1350),
            format_name="feed_portrait",
            brand_kit=_brand(),
        )
        # No photo → no var declaration carrying a URI.
        assert "--mh-athlete-img:url(" not in res.html
        # The frame <img> tags are comment-wrapped out of the live DOM.
        assert "<!--photo-only" in res.html
        assert '<img class="athlete-cutout"' not in res.html.replace(
            "<!--photo-only <img", "<!--photo-only IMG"
        )
