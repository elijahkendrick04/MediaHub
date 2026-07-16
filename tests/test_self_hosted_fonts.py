"""Self-hosted fonts — Council verdict (2026-05-31).

The fonts used to load from the Google Fonts CDN, which (a) intermittently fell
back to Impact/Oswald when the CDN was blocked/slow — what the owner saw — and
(b) transmits EU/UK visitor IPs to Google (the Munich GDPR ruling). The fix keeps
the same families but serves them first-party. These tests guard that the CDN
never creeps back across all three public surfaces (web UI, still-graphic
renderer, Remotion video) — each surface's class skips cleanly until that
surface's assets exist.
"""

from __future__ import annotations

import base64
import importlib
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

# --- Web UI -----------------------------------------------------------------
FONTS_CSS = _ROOT / "src" / "mediahub" / "web" / "static" / "theme" / "fonts.css"
FONTS_DIR = _ROOT / "src" / "mediahub" / "web" / "static" / "fonts"
FAMILIES = ["Big Shoulders Display", "Fraunces", "Hanken Grotesk", "JetBrains Mono"]


class TestWebFontAssets:
    def test_woff2_files_present(self):
        assert len(list(FONTS_DIR.glob("*.woff2"))) >= 30

    def test_every_family_has_woff2(self):
        names = [p.name for p in FONTS_DIR.glob("*.woff2")]
        for prefix in ("bigshoulders", "fraunces", "hanken", "jetbrains"):
            assert any(n.startswith(prefix + "-") for n in names), f"no woff2 for {prefix}"

    def test_fonts_css_first_party_only(self):
        css = FONTS_CSS.read_text()
        for fam in FAMILIES:
            assert f"'{fam}'" in css
        assert "googleapis" not in css and "gstatic" not in css
        srcs = re.findall(r"url\(\.\./fonts/([^)]+\.woff2)\)", css)
        assert srcs
        for fn in srcs:
            assert (FONTS_DIR / fn).is_file(), f"fonts.css references missing {fn}"

    def test_fraunces_is_variable(self):
        css = FONTS_CSS.read_text()
        assert re.search(r"font-family: 'Fraunces';[^}]*font-weight: 400 900;", css, re.S), (
            "Fraunces must be self-hosted as a variable font (font-weight: 400 900)"
        )

    def test_metric_tuned_fallback_exists(self):
        css = FONTS_CSS.read_text()
        assert "Hanken Grotesk Fallback" in css and "size-adjust" in css


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    a = wm.create_app()
    a.config["TESTING"] = True
    return a


class TestWebRenderedHead:
    def test_no_cdn_in_html(self, app):
        with app.test_client() as c:
            body = c.get("/status").get_data(as_text=True)
        assert "fonts.googleapis.com" not in body and "fonts.gstatic.com" not in body

    def test_links_first_party_and_preloads(self, app):
        with app.test_client() as c:
            body = c.get("/status").get_data(as_text=True)
        assert "/static/theme/fonts.css" in body
        assert 'rel="preload"' in body and "/static/fonts/" in body
        assert "hanken-latin-normal-400.woff2" in body

    def test_body_stack_uses_metric_fallback(self, app):
        with app.test_client() as c:
            body = c.get("/status").get_data(as_text=True)
        assert "Hanken Grotesk Fallback" in body

    @pytest.mark.parametrize(
        "font_file",
        [
            "hanken-latin-normal-400.woff2",
            "bigshoulders-latin-normal-800.woff2",
            # Regression: fraunces-latin-italic-400-900.woff2 returned 502 on /dpa
            # (2026-06-13, Render cold-start) and was absent from MIME coverage.
            "fraunces-latin-italic-400-900.woff2",
            # Regression: bigshoulders-latin-normal-600.woff2 returned net::ERR_ABORTED
            # on /account/2fa (2026-06-18) — 600-weight was absent from MIME coverage
            # even though 800-weight was tested.
            "bigshoulders-latin-normal-600.woff2",
        ],
    )
    def test_woff2_served_as_font_mimetype(self, app, font_file):
        # Regression: Python's mimetypes omits font/woff2 on some Linux
        # systems, causing Flask to serve woff2 as application/octet-stream
        # and Playwright/browsers to trigger a download instead of loading.
        # Covers the HTML preload fonts (web.py) plus fraunces italic
        # (CSS @font-face only, loaded on demand by pages like /dpa).
        with app.test_client() as c:
            resp = c.get(f"/static/fonts/{font_file}")
        assert resp.status_code == 200
        assert "font/woff2" in resp.content_type, (
            f"{font_file}: expected font/woff2 Content-Type, got {resp.content_type!r}"
        )
        cd = resp.headers.get("Content-Disposition", "")
        assert "attachment" not in cd, f"{font_file}: woff2 must not be served as an attachment"


# --- Still-graphic renderer (Playwright HTML->PNG) --------------------------
_RL = _ROOT / "src" / "mediahub" / "graphic_renderer" / "layouts"
_RENDER_PY = _ROOT / "src" / "mediahub" / "graphic_renderer" / "render.py"


class TestRendererFonts:
    def test_renderer_woff2_present(self):
        names = {p.name for p in (_RL / "fonts").glob("*.woff2")}
        # playfair-display joined as the serif display register (D5).
        for slug in (
            "bebas-neue",
            "anton",
            "bowlby-one",
            "space-grotesk",
            "inter",
            "jetbrains-mono",
            "playfair-display",
        ):
            assert f"{slug}.woff2" in names, f"missing renderer font {slug}.woff2"

    def test_shared_css_first_party(self):
        css = (_RL / "_shared.css").read_text()
        assert "gstatic" not in css and "googleapis" not in css
        srcs = re.findall(r"url\(fonts/([^)]+\.woff2)\)", css)
        assert len(srcs) >= 6
        for fn in srcs:
            assert (_RL / "fonts" / fn).is_file()

    def test_render_py_drops_cdn_and_resolves_local(self):
        rp = _RENDER_PY.read_text()
        assert "gstatic" not in rp and "googleapis" not in rp
        assert '"url(fonts/"' in rp and "as_uri()" in rp


# --- Remotion (MP4 reels) ---------------------------------------------------
# Remotion previously approximated the brand headline with SYSTEM font stacks.
# Council 2026-05-31: load the SAME self-hosted brand woff2 so the reel matches
# the still card + web — first-party (never the Google CDN), guarded by
# delayRender/continueRender so no frame is captured before the fonts load.
_REMOTION = _ROOT / "src" / "mediahub" / "remotion"
_REMOTION_SRC = _REMOTION / "src"


class TestRemotionFonts:
    def test_no_cdn_or_webfont_loader_in_remotion(self):
        offenders = []
        for path in _REMOTION_SRC.rglob("*"):
            if path.suffix in (".ts", ".tsx", ".js", ".css") and path.is_file():
                t = path.read_text(encoding="utf-8", errors="replace")
                for needle in ("googleapis", "gstatic", "@remotion/google-fonts", "@fontsource"):
                    if needle in t:
                        offenders.append(f"{path.name}: {needle}")
        assert not offenders, f"Remotion must not load remote/webfonts: {offenders}"

    def test_brand_woff2_bundled_in_public(self):
        pub = _REMOTION / "public" / "fonts"
        names = {p.name for p in pub.glob("*.woff2")}
        # playfair-display joined as the serif display register (D5).
        for slug in (
            "bebas-neue",
            "anton",
            "bowlby-one",
            "space-grotesk",
            "inter",
            "jetbrains-mono",
            "playfair-display",
        ):
            assert f"{slug}.woff2" in names, f"missing bundled reel font {slug}.woff2"

    def test_fonts_module_uses_staticfile_and_delayrender_guard(self):
        src = (_REMOTION_SRC / "fonts.ts").read_text()
        assert "staticFile(" in src and "@font-face" in src
        # The binding guardrail: hold the render until fonts.ready.
        assert "delayRender(" in src and "continueRender(" in src
        assert "document.fonts" in src
        # Wired into the entry so every render registers the faces.
        assert "ensureBrandFonts" in (_REMOTION_SRC / "index.ts").read_text()
