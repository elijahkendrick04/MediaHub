"""Tests for the incremental render-stage cache (roadmap G1.24).

Covers the cache module in isolation (no Playwright needed) plus its two render
hooks: the asset-URI memoiser inside ``_img_to_data_uri`` and the on-disk PNG
cache inside ``render_html_to_png``. The end-to-end render assertions are guarded
behind a Playwright availability check, mirroring the other renderer tests; the
"pre-stored PNG is served" test proves the cache-hit path short-circuits the
screenshot *without* needing Chromium at all.

The invariant under test throughout: the cache only elides repeat work — an
identical (HTML, size, DPR) render is byte-for-byte what a fresh screenshot would
have produced, and the cache never changes a render's content.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from mediahub.graphic_renderer import render as R
from mediahub.graphic_renderer import render_cache as rc


# ---------------------------------------------------------------------------
# Isolation — each test gets a private DATA_DIR and a clean cache (in-memory +
# on-disk + counters), with the cache flags reset to their defaults.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MEDIAHUB_RENDER_CACHE", raising=False)
    monkeypatch.delenv("MEDIAHUB_RENDER_CACHE_MAX", raising=False)
    rc.clear()
    yield
    rc.clear()


def _have_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401

        with sync_playwright() as p:
            b = p.chromium.launch(args=["--no-sandbox"])
            b.close()
        return True
    except Exception:
        return False


_PLAYWRIGHT = _have_playwright()


def _brief_and_kit():
    from mediahub.brand.kit import BrandKit
    from mediahub.creative_brief.generator import generate as gen_brief
    from mediahub.media_requirements.evaluator import EvaluationResult

    bk = BrandKit(
        profile_id="test",
        display_name="Test Swim Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="TSC",
    )
    ev = EvaluationResult(
        content_item_id="ci-1",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout="individual_hero",
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
    return gen_brief(item, ev, bk, profile_id="test", meet_name="Manchester Open"), bk


# ---------------------------------------------------------------------------
# Configuration / flags
# ---------------------------------------------------------------------------


def test_cache_enabled_default_on(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_RENDER_CACHE", raising=False)
    assert rc.cache_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "OFF", "No", "off", "FALSE"])
def test_cache_disabled_flag_variants(monkeypatch, val):
    monkeypatch.setenv("MEDIAHUB_RENDER_CACHE", val)
    assert rc.cache_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "on", "yes", "anything"])
def test_cache_enabled_truthy_variants(monkeypatch, val):
    monkeypatch.setenv("MEDIAHUB_RENDER_CACHE", val)
    assert rc.cache_enabled() is True


def test_png_cache_dir_under_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    d = rc.png_cache_dir()
    assert d == tmp_path / "render_cache"
    assert d.is_dir()


# ---------------------------------------------------------------------------
# PNG-stage key
# ---------------------------------------------------------------------------


def test_png_cache_key_is_stable():
    k1 = rc.png_cache_key("<html>card</html>", 1080, 1350, 2)
    k2 = rc.png_cache_key("<html>card</html>", 1080, 1350, 2)
    assert k1 == k2
    assert len(k1) == 64  # sha256 hex


def test_png_cache_key_sensitive_to_html_size_dpr():
    base = rc.png_cache_key("<html>card</html>", 1080, 1350, 2)
    assert base != rc.png_cache_key("<html>CARD</html>", 1080, 1350, 2)
    assert base != rc.png_cache_key("<html>card</html>", 1081, 1350, 2)
    assert base != rc.png_cache_key("<html>card</html>", 1080, 1351, 2)
    assert base != rc.png_cache_key("<html>card</html>", 1080, 1350, 1)


def test_png_cache_key_no_dimension_html_collision():
    # Domain separation: the dimension suffix must not be forgeable from HTML.
    a = rc.png_cache_key("x", 1, 23, 4)
    b = rc.png_cache_key("x|1x23@4", 0, 0, 0)  # naive concat would collide
    assert a != b


def test_renderer_generation_salt_folds_into_key(monkeypatch):
    # A renderer-environment change (font refresh / Chromium bump) must move
    # every key, so persisted pre-upgrade PNGs stop being served as hits.
    base = rc.png_cache_key("<html>card</html>", 1080, 1350, 2)
    monkeypatch.setattr(rc, "_salt_cache", "deadbeefdeadbeef")
    assert rc.png_cache_key("<html>card</html>", 1080, 1350, 2) != base


def test_renderer_generation_is_cached_and_stable():
    a = rc._renderer_generation()
    b = rc._renderer_generation()
    assert a == b
    assert len(a) == 16


def test_compute_renderer_generation_tracks_fonts(tmp_path):
    d = tmp_path / "fonts"
    d.mkdir()
    empty = rc._compute_renderer_generation(d)
    (d / "Anton.woff2").write_bytes(b"font-bytes-v1")
    with_font = rc._compute_renderer_generation(d)
    assert with_font != empty
    # Unchanged environment → stable digest (keys keep hitting).
    assert rc._compute_renderer_generation(d) == with_font
    # A refreshed font file (new bytes → new size/mtime) changes the digest.
    (d / "Anton.woff2").write_bytes(b"font-bytes-v2-longer")
    assert rc._compute_renderer_generation(d) != with_font


# ---------------------------------------------------------------------------
# PNG-stage store / get
# ---------------------------------------------------------------------------


def test_store_and_get_png_roundtrip():
    key = rc.png_cache_key("html-A", 100, 200, 2)
    rc.reset_stats()
    assert rc.get_cached_png(key) is None  # miss
    rc.store_png(key, b"PNG-BYTES-A")
    got = rc.get_cached_png(key)  # hit
    assert got == b"PNG-BYTES-A"
    s = rc.stats()
    assert s["png_hits"] == 1 and s["png_misses"] == 1


def test_get_png_miss_returns_none_and_counts():
    rc.reset_stats()
    assert rc.get_cached_png("deadbeef") is None
    assert rc.stats()["png_misses"] == 1


def test_disabled_cache_neither_stores_nor_serves(monkeypatch):
    key = rc.png_cache_key("html-D", 100, 200, 2)
    rc.store_png(key, b"warm")  # warm it while enabled
    assert rc.get_cached_png(key) == b"warm"
    monkeypatch.setenv("MEDIAHUB_RENDER_CACHE", "0")
    assert rc.get_cached_png(key) is None  # disabled → never serves
    rc.store_png(rc.png_cache_key("html-E", 1, 1, 1), b"nope")  # disabled → no-op
    monkeypatch.setenv("MEDIAHUB_RENDER_CACHE", "1")
    assert rc.get_cached_png(rc.png_cache_key("html-E", 1, 1, 1)) is None


def test_store_png_bounds_disk_cache(monkeypatch):
    # The hard guarantee store_png makes: never exceed the cap. (Which specific
    # entries survive is the prune's job, tested deterministically below.)
    monkeypatch.setenv("MEDIAHUB_RENDER_CACHE_MAX", "3")
    for i in range(8):
        rc.store_png(rc.png_cache_key(f"card-{i}", 10, 10, 1), f"bytes-{i}".encode())
    assert len(list(rc.png_cache_dir().glob("*.png"))) <= 3


def test_prune_evicts_oldest_by_mtime(monkeypatch, tmp_path):
    # Drive the eviction order with explicit mtimes so the assertion can't be
    # flaky on filesystems with coarse mtime resolution.
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_RENDER_CACHE_MAX", "3")
    d = rc.png_cache_dir()
    for i in range(5):
        p = d / f"{i:02d}deadbeef.png"
        p.write_bytes(f"b{i}".encode())
        os.utime(p, (1000 + i, 1000 + i))  # strictly increasing
    rc._prune(d)
    survivors = {p.name for p in d.glob("*.png")}
    assert survivors == {"02deadbeef.png", "03deadbeef.png", "04deadbeef.png"}


def test_get_cached_png_touches_mtime_for_lru(monkeypatch, tmp_path):
    # A cache read must refresh the entry's mtime so the prune keeps hot entries.
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    key = rc.png_cache_key("hot", 10, 10, 1)
    rc.store_png(key, b"payload")
    p = rc.png_cache_dir() / f"{key}.png"
    os.utime(p, (1000, 1000))  # force it stale
    before = p.stat().st_mtime
    assert rc.get_cached_png(key) == b"payload"
    assert p.stat().st_mtime > before


# ---------------------------------------------------------------------------
# Asset-URI stage
# ---------------------------------------------------------------------------


def test_asset_data_uri_memoises_unchanged_file(tmp_path):
    f = tmp_path / "img.bin"
    f.write_bytes(b"abcdef")
    calls = {"n": 0}

    def loader(p):
        calls["n"] += 1
        return f"uri:{p.stat().st_size}"

    a = rc.asset_data_uri(f, loader=loader)
    b = rc.asset_data_uri(f, loader=loader)
    assert a == b == "uri:6"
    assert calls["n"] == 1, "unchanged file must only be encoded once"
    s = rc.stats()
    assert s["asset_hits"] == 1 and s["asset_misses"] == 1


def test_asset_data_uri_invalidates_on_content_change(tmp_path):
    f = tmp_path / "img.bin"
    f.write_bytes(b"abcdef")
    calls = {"n": 0}

    def loader(p):
        calls["n"] += 1
        return f"uri:{p.read_bytes().decode()}"

    first = rc.asset_data_uri(f, loader=loader)
    f.write_bytes(b"abcdefGHIJK")  # size + mtime change
    second = rc.asset_data_uri(f, loader=loader)
    assert calls["n"] == 2
    assert first != second


def test_asset_data_uri_disabled_bypasses(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_CACHE", "0")
    f = tmp_path / "img.bin"
    f.write_bytes(b"abcdef")
    calls = {"n": 0}

    def loader(p):
        calls["n"] += 1
        return "uri"

    rc.asset_data_uri(f, loader=loader)
    rc.asset_data_uri(f, loader=loader)
    assert calls["n"] == 2, "disabled cache must call the loader every time"


def test_asset_data_uri_missing_file_propagates_error(tmp_path):
    missing = tmp_path / "nope.png"

    def loader(p):
        return p.read_bytes().decode()  # raises FileNotFoundError

    with pytest.raises((FileNotFoundError, OSError)):
        rc.asset_data_uri(missing, loader=loader)


def test_img_to_data_uri_matches_direct_encode_and_caches(tmp_path):
    # A 1x1 PNG so the function picks the image/png mime branch.
    png_1x1 = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
        "de0000000c4944415408d76360000002000154a24f8c0000000049454e44ae42"
        "6082"
    )
    f = tmp_path / "pixel.png"
    f.write_bytes(png_1x1)

    rc.reset_stats()
    uri1 = R._img_to_data_uri(f)
    uri2 = R._img_to_data_uri(f)
    direct = R._encode_img_data_uri(Path(f))

    assert uri1 == uri2 == direct
    assert uri1.startswith("data:image/png;base64,")
    s = rc.stats()
    assert s["asset_hits"] == 1, "second _img_to_data_uri call should hit the cache"


# ---------------------------------------------------------------------------
# render_html_to_png hook — pre-stored hit needs NO Playwright
# ---------------------------------------------------------------------------


def test_prestored_png_served_without_render(tmp_path, monkeypatch):
    # If a hit returns our sentinel bytes (which no real render could produce),
    # the cache short-circuited Chromium entirely.
    monkeypatch.setenv("MEDIAHUB_RENDER_DPR", "1")
    dpr = R._dpr_render()
    html = "<html><body>sentinel</body></html>"
    key = rc.png_cache_key(html, 1080, 1350, dpr)
    rc.store_png(key, b"SENTINEL-NOT-A-REAL-PNG")

    out = tmp_path / "render" / "feed_portrait.png"
    n = R.render_html_to_png(html, out, (1080, 1350))

    assert n == len(b"SENTINEL-NOT-A-REAL-PNG")
    assert out.read_bytes() == b"SENTINEL-NOT-A-REAL-PNG"
    # No leftover working file from a real render.
    assert not out.with_suffix(out.suffix + ".render.html").exists()


def test_disabled_cache_ignores_prestored_png(tmp_path, monkeypatch):
    # With the cache off, a poisoned entry must be ignored. Without Playwright
    # the only honest outcome is a real render attempt (→ RuntimeError if absent,
    # → a real PNG if present); either way it must NOT return the sentinel.
    monkeypatch.setenv("MEDIAHUB_RENDER_DPR", "1")
    dpr = R._dpr_render()
    html = "<html><body>poison</body></html>"
    monkeypatch.setenv("MEDIAHUB_RENDER_CACHE", "1")
    key = rc.png_cache_key(html, 1080, 1350, dpr)
    rc.store_png(key, b"POISON")
    monkeypatch.setenv("MEDIAHUB_RENDER_CACHE", "0")

    out = tmp_path / "render" / "feed_portrait.png"
    try:
        R.render_html_to_png(html, out, (1080, 1350))
    except RuntimeError:
        return  # Playwright absent: correctly tried to render, didn't serve poison
    assert out.read_bytes() != b"POISON"


# ---------------------------------------------------------------------------
# End-to-end render (Playwright-gated)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _PLAYWRIGHT, reason="Playwright/Chromium not available")
def test_identical_render_hits_png_cache(tmp_path):
    brief, bk = _brief_and_kit()
    rc.reset_stats()

    r1 = R.render_brief(brief, output_dir=tmp_path / "a", size=(1080, 1350),
                        format_name="feed_portrait", brand_kit=bk)
    after_first = rc.stats()
    r2 = R.render_brief(brief, output_dir=tmp_path / "b", size=(1080, 1350),
                        format_name="feed_portrait", brand_kit=bk)
    after_second = rc.stats()

    h1 = hashlib.sha256(Path(r1.visual.file_path).read_bytes()).hexdigest()
    h2 = hashlib.sha256(Path(r2.visual.file_path).read_bytes()).hexdigest()

    assert after_first["png_misses"] >= 1 and after_first["png_hits"] == 0
    assert after_second["png_hits"] >= 1, "identical re-render must hit the cache"
    assert h1 == h2, "a cache hit must reproduce byte-identical PNG output"


@pytest.mark.skipif(not _PLAYWRIGHT, reason="Playwright/Chromium not available")
def test_changed_html_misses_cache(tmp_path, monkeypatch):
    brief, bk = _brief_and_kit()
    rc.reset_stats()

    monkeypatch.setenv("MEDIAHUB_RENDER_GRAIN", "1")
    on = R.render_brief(brief, output_dir=tmp_path / "on", size=(1080, 1350),
                        format_name="feed_portrait", brand_kit=bk)
    monkeypatch.setenv("MEDIAHUB_RENDER_GRAIN", "0")
    off = R.render_brief(brief, output_dir=tmp_path / "off", size=(1080, 1350),
                         format_name="feed_portrait", brand_kit=bk)

    # Different HTML → different keys → two misses, no hit, different bytes.
    s = rc.stats()
    assert s["png_hits"] == 0 and s["png_misses"] >= 2
    h_on = hashlib.sha256(Path(on.visual.file_path).read_bytes()).hexdigest()
    h_off = hashlib.sha256(Path(off.visual.file_path).read_bytes()).hexdigest()
    assert h_on != h_off


@pytest.mark.skipif(not _PLAYWRIGHT, reason="Playwright/Chromium not available")
def test_dpr_keys_cache_separately(tmp_path, monkeypatch):
    from PIL import Image

    brief, bk = _brief_and_kit()
    monkeypatch.setenv("MEDIAHUB_RENDER_GRAIN", "0")

    monkeypatch.setenv("MEDIAHUB_RENDER_DPR", "1")
    r1 = R.render_brief(brief, output_dir=tmp_path / "d1", size=(1080, 1350),
                        format_name="feed_portrait", brand_kit=bk)
    monkeypatch.setenv("MEDIAHUB_RENDER_DPR", "2")
    r2 = R.render_brief(brief, output_dir=tmp_path / "d2", size=(1080, 1350),
                        format_name="feed_portrait", brand_kit=bk)

    # Both keyed + cached independently, both correct final size.
    assert Image.open(r1.visual.file_path).size == (1080, 1350)
    assert Image.open(r2.visual.file_path).size == (1080, 1350)
    h1 = hashlib.sha256(Path(r1.visual.file_path).read_bytes()).hexdigest()
    h2 = hashlib.sha256(Path(r2.visual.file_path).read_bytes()).hexdigest()
    assert h1 != h2, "different DPR must not share a cache entry"


@pytest.mark.skipif(not _PLAYWRIGHT, reason="Playwright/Chromium not available")
def test_disabled_cache_still_renders_correctly(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_CACHE", "0")
    brief, bk = _brief_and_kit()
    rc.reset_stats()

    r1 = R.render_brief(brief, output_dir=tmp_path / "a", size=(1080, 1350),
                        format_name="feed_portrait", brand_kit=bk)
    r2 = R.render_brief(brief, output_dir=tmp_path / "b", size=(1080, 1350),
                        format_name="feed_portrait", brand_kit=bk)

    # No cache participation at all, but both renders are valid PNGs.
    assert rc.stats()["png_hits"] == 0
    assert Path(r1.visual.file_path).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert Path(r2.visual.file_path).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    # A disabled cache must not write anything to the on-disk store.
    assert list(rc.png_cache_dir().glob("*.png")) == []
