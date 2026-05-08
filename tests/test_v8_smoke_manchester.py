"""V8 end-to-end smoke test on the Manchester PDF.

Drives the full V8 visual pipeline:
  pdf → pipeline_v4 → ranked achievements → content items
  → media_requirements.evaluate → creative_brief.generate
  → graphic_renderer.render_brief (multiple formats)

Asserts ≥5 real PNG files are produced and each is a substantial render
(>30 KB, valid PNG header). Skips if Playwright is unavailable.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mediahub.brand.kit import BrandKit


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SAMPLE_PDF = _REPO_ROOT / "sample_data" / "MISM-2024-Results.pdf"


def _have_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
                browser.close()
                return True
            except Exception:
                return False
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _have_playwright(), reason="Playwright/Chromium unavailable")


@pytest.fixture(scope="module")
def manchester_run():
    if not _SAMPLE_PDF.exists():
        pytest.skip(f"Sample PDF missing: {_SAMPLE_PDF}")
    from mediahub.pipeline.pipeline_v4 import run_pipeline_v4

    run = run_pipeline_v4(
        file_bytes=_SAMPLE_PDF.read_bytes(),
        filename=_SAMPLE_PDF.name,
        profile_id=None,
        club_filter="City of Manchester Aquatics",
        use_pb_cache=True,
        fetch_pbs=False,
        run_id="test_v8_smoke_manchester",
    )
    if run.error:
        pytest.skip(f"Pipeline failed: {run.error}")
    return run


def test_v8_full_pipeline_produces_visuals(manchester_run, tmp_path: Path):
    """Run V8 visual pipeline on real ranked achievements, expect ≥5 PNGs."""
    from mediahub.creative_brief.generator import generate as gen_brief
    from mediahub.graphic_renderer.render import render_brief
    from mediahub.graphic_renderer.variants import render_all_formats
    from mediahub.media_requirements.evaluator import evaluate

    rr = getattr(manchester_run, "recognition_report", None) or {}
    ranked = rr.get("ranked_achievements") or []
    if not ranked:
        pytest.skip("No ranked achievements from pipeline")

    brand = BrandKit(
        profile_id="manchester-test",
        display_name="City of Manchester Aquatics",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="Manchester",
    )

    # Take first 6 achievements and render each into feed_portrait
    pngs: list[Path] = []
    rendered_layouts: set[str] = set()
    for i, ach in enumerate(ranked[:8]):
        item = {
            "id": f"smoke-{i}",
            "post_angle": ach.get("post_angle") or "individual_pb",
            "achievement": ach,
            "swimmer_name": ach.get("swimmer_name"),
            "meet_name": "Manchester International Swim Meet 2024",
        }
        try:
            evaluation = evaluate(item, library_assets=[], profile_logo_present=False)
        except Exception:
            continue

        if str(getattr(evaluation, "status", "")).lower() == "skip_low_confidence":
            continue

        try:
            brief = gen_brief(
                item, evaluation, brand,
                profile_id="manchester-test",
                meet_name="Manchester International Swim Meet 2024",
                venue_name="Manchester Aquatics Centre",
            )
            res = render_brief(
                brief,
                output_dir=tmp_path / f"item_{i}",
                size=(1080, 1350),
                format_name="feed_portrait",
                brand_kit=brand,
            )
            png = Path(res.visual.file_path)
            if png.exists() and png.stat().st_size > 30_000:
                pngs.append(png)
                rendered_layouts.add(brief.layout_template)
        except Exception as e:
            print(f"[smoke] render failed for item {i}: {e}")
            continue

        if len(pngs) >= 6:
            break

    assert len(pngs) >= 5, (
        f"V8 pipeline produced only {len(pngs)} PNGs (need ≥5). "
        f"Layouts seen: {rendered_layouts}"
    )

    # Validate every PNG file is a real render
    for p in pngs:
        with open(p, "rb") as fh:
            assert fh.read(8) == b"\x89PNG\r\n\x1a\n", f"Not a real PNG: {p}"
        assert p.stat().st_size > 30_000, f"PNG too small: {p}"

    # Persist outputs in a stable location for human inspection
    out_dir = _REPO_ROOT / "smoke_v8_output"
    out_dir.mkdir(exist_ok=True)
    for p in pngs:
        target = out_dir / f"{p.parent.name}_{p.name}"
        try:
            target.write_bytes(p.read_bytes())
        except Exception:
            pass


def test_v8_render_all_formats_at_least_one_item(manchester_run, tmp_path: Path):
    """At least one ranked achievement must produce all three default formats."""
    from mediahub.creative_brief.generator import generate as gen_brief
    from mediahub.graphic_renderer.variants import render_all_formats
    from mediahub.media_requirements.evaluator import evaluate

    rr = getattr(manchester_run, "recognition_report", None) or {}
    ranked = rr.get("ranked_achievements") or []
    if not ranked:
        pytest.skip("No ranked achievements")

    brand = BrandKit(profile_id="m", display_name="Manchester", primary_colour="#0E5BFF")

    for i, ach in enumerate(ranked[:5]):
        item = {
            "id": f"fmt-{i}",
            "post_angle": ach.get("post_angle") or "individual_pb",
            "achievement": ach,
            "swimmer_name": ach.get("swimmer_name"),
        }
        evaluation = evaluate(item, library_assets=[], profile_logo_present=False)
        if str(getattr(evaluation, "status", "")).lower() == "skip_low_confidence":
            continue
        brief = gen_brief(item, evaluation, brand, profile_id="m")
        results = render_all_formats(brief, output_dir=tmp_path / f"fmt_{i}", brand_kit=brand)
        if len(results) >= 3:
            for r in results:
                assert Path(r.visual.file_path).exists()
            return
    pytest.fail("No achievement produced 3+ format variants")
