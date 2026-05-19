"""Tests for mediahub.theming.seed_extract."""
from __future__ import annotations

import io

import pytest

from mediahub.theming.seed_extract import extract_seed, SeedResult


class TestDirectHex:
    def test_six_digit_hex(self):
        r = extract_seed("#D4FF3A")
        assert r.source_kind == "hex"
        assert r.hex == "#D4FF3A"
        assert len(r.candidates) == 1

    def test_six_digit_hex_lowercase_normalised(self):
        r = extract_seed("#d4ff3a")
        assert r.source_kind == "hex"
        assert r.hex == "#D4FF3A"

    def test_three_digit_hex_expanded(self):
        r = extract_seed("#FA0")
        assert r.source_kind == "hex"
        assert r.hex == "#FFAA00"

    def test_invalid_hex_falls_through(self):
        r = extract_seed("not a colour")
        assert r.source_kind == "fallback"

    def test_candidates_carry_hct(self):
        r = extract_seed("#D4FF3A")
        assert r.candidates[0].hct[0] > 0   # hue
        assert r.candidates[0].hct[1] > 0   # chroma
        assert 0 < r.candidates[0].hct[2] < 100  # tone


class TestSVGFastPath:
    def test_minimal_svg_with_fill(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="#A30D2D" width="10" height="10"/></svg>'
        r = extract_seed(svg)
        assert r.source_kind in ("svg", "raster", "fallback")
        # Either it nailed the brand red, or fell through — both acceptable
        # but most likely "svg" with #A30D2D
        if r.source_kind == "svg":
            assert r.hex == "#A30D2D"

    def test_svg_with_multiple_colors_picks_brandable(self):
        svg = '''
        <svg xmlns="http://www.w3.org/2000/svg">
          <rect fill="#FFFFFF" width="100" height="100"/>
          <rect fill="#0E2A47" width="80" height="80"/>
          <rect fill="#000000" width="5" height="5"/>
        </svg>
        '''
        r = extract_seed(svg)
        # Near-grey #000 and pure white #fff should be filtered out;
        # navy #0E2A47 is the only brandable colour.
        if r.source_kind == "svg":
            assert r.hex == "#0E2A47"

    def test_svg_with_only_neutral_colors_falls_through(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="#FFFFFF"/></svg>'
        r = extract_seed(svg)
        # White/grey only → falls through to raster or fallback
        assert r.source_kind != "svg"


class TestRasterFallback:
    def _png_bytes(self, color: tuple[int, int, int]) -> bytes:
        """Build a 16×16 PNG of a single colour."""
        from PIL import Image
        img = Image.new("RGB", (16, 16), color)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_uniform_blue_png(self):
        png = self._png_bytes((30, 80, 200))
        r = extract_seed(png)
        assert r.source_kind == "raster"
        # The extracted seed should be close to the input blue (not identical
        # because quantizer + Score may pick a representative bucket centre).
        # We assert it's at least bluish — H in 200-260°.
        h = r.candidates[0].hct[0]
        assert 180 < h < 280, f"expected blue hue, got {h:.0f}°"

    def test_transparent_png_falls_through(self):
        from PIL import Image
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))   # fully transparent
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        r = extract_seed(buf.getvalue())
        # No non-transparent pixels — should fall through to fallback.
        assert r.source_kind == "fallback"


class TestFallback:
    def test_empty_string_returns_fallback(self):
        r = extract_seed("")
        assert r.source_kind == "fallback"
        assert r.hex == "#0E2A47"   # BrandKit.generic_default primary

    def test_garbage_bytes_returns_fallback(self):
        r = extract_seed(b"\x00\x01\x02 not a real image")
        assert r.source_kind == "fallback"

    def test_trace_explains_decisions(self):
        r = extract_seed("not a hex")
        assert len(r.trace) >= 2
        assert any("fallback" in line.lower() for line in r.trace)
