"""MediaHub chrome marks + the fixed product logo.

The footer mark and the logo backplate/ink bar still bind to the cascade
(currentColor / var(--mh-surface)) so the surrounding chrome re-skins. The
MediaHub *logo* identity bars (lane-yellow + medal-gold) and baseline are
the one exception: they are PINNED to MediaHub's own colours and never take
the active club's brand — maintainer decision, "the logo is the only thing
that doesn't change colour", so a club always knows whose product they're
in. (This deliberately overrides the earlier Stage-F3 "all authored marks
re-skin" rule for the logo only.) Uploaded SVGs are NEVER touched — the
serve route returns bytes byte-for-byte.
"""
from __future__ import annotations

import importlib
import io
import re
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, wm, cp, tmp_path


def _topnav_svg(body: str) -> str:
    """Extract the topnav SVG inner from a rendered page."""
    m = re.search(r'<svg width="28"[^>]*>(.+?)</svg>', body, re.DOTALL)
    return m.group(1) if m else ""


def _footer_svg(body: str) -> str:
    """Extract the footer SVG inner."""
    m = re.search(r'<svg width="18"[^>]*>(.+?)</svg>', body, re.DOTALL)
    return m.group(1) if m else ""


class TestTopnavSVG:
    def test_svg_is_rendered(self, app_client):
        client, _, _, _ = app_client
        body = client.get("/status").get_data(as_text=True)
        assert _topnav_svg(body), "topnav SVG missing from rendered page"

    def test_logo_does_not_theme_with_the_club_brand(self, app_client):
        """The logo is the one mark that does NOT re-skin: its identity bars +
        baseline must NOT bind to the themeable brand tokens, so a club's
        colours never recolour the product logo."""
        client, _, _, _ = app_client
        body = client.get("/status").get_data(as_text=True)
        svg = _topnav_svg(body)
        assert 'fill="var(--mh-primary)"' not in svg
        assert 'fill="var(--mh-tertiary)"' not in svg
        assert 'stroke="var(--mh-primary)"' not in svg
        # The neutral ink (#0A0B11) and paper (#F5F2E8) are still never raw
        # fills — the ink bar binds to currentColor, the plate to a token.
        assert "#0A0B11" not in svg
        assert "#F5F2E8" not in svg

    def test_backplate_uses_surface_token(self, app_client):
        client, _, _, _ = app_client
        body = client.get("/status").get_data(as_text=True)
        svg = _topnav_svg(body)
        # Backplate: var(--mh-surface) + var(--mh-outline-rule) stroke
        assert 'fill="var(--mh-surface)"' in svg
        assert 'stroke="var(--mh-outline-rule)"' in svg

    def test_ink_bar_uses_currentcolor(self, app_client):
        client, _, _, _ = app_client
        body = client.get("/status").get_data(as_text=True)
        svg = _topnav_svg(body)
        assert 'fill="currentColor"' in svg, (
            "paper-cream bar should bind to currentColor"
        )

    def test_brand_bar_is_pinned_lane_yellow(self, app_client):
        # The lane-yellow bar is MediaHub's fixed identity, not the club's primary.
        client, _, _, _ = app_client
        body = client.get("/status").get_data(as_text=True)
        svg = _topnav_svg(body)
        assert 'fill="#D4FF3A"' in svg

    def test_tertiary_bar_is_pinned_medal_gold(self, app_client):
        client, _, _, _ = app_client
        body = client.get("/status").get_data(as_text=True)
        svg = _topnav_svg(body)
        assert 'fill="#F4D58D"' in svg

    def test_baseline_is_pinned_lane_yellow(self, app_client):
        client, _, _, _ = app_client
        body = client.get("/status").get_data(as_text=True)
        svg = _topnav_svg(body)
        assert 'stroke="#D4FF3A"' in svg


class TestFooterSVG:
    """Footer SVG was already currentColor-driven pre-Stage F. Pin
    that as a contract — Stage F3 forbids regressing it."""

    def test_footer_uses_currentcolor(self, app_client):
        client, _, _, _ = app_client
        body = client.get("/status").get_data(as_text=True)
        svg = _footer_svg(body)
        # All three bars use currentColor (different opacities).
        cc_count = svg.count('fill="currentColor"')
        assert cc_count >= 3, (
            f"footer SVG should have ≥ 3 currentColor fills, got {cc_count}"
        )


class TestUploadedSVGBytesPreserved:
    """F3's "never auto-inject on uploaded SVGs" rule: the serve route
    returns bytes byte-for-byte. A fixture SVG with fill="#FF0000"
    must round-trip unchanged."""

    def test_svg_roundtrip_unchanged(self, app_client, tmp_path):
        client, wm, cp, root = app_client

        # Build a fixture SVG with a known hex fill.
        svg_bytes = (
            b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '
            b'viewBox="0 0 10 10"><rect width="10" height="10" '
            b'fill="#FF0000"/></svg>'
        )

        # Seed a profile + drop the logo onto disk via the canonical
        # brand.logos store_logo() API.
        from mediahub.web.club_profile import ClubProfile
        from mediahub.brand.logos import store_logo
        prof = ClubProfile(profile_id="svg-roundtrip", display_name="SVG Test")
        cp.save_profile(prof)

        meta = store_logo(
            profile_id=prof.profile_id,
            filename="test.svg",
            file_bytes=svg_bytes,
        )

        with client.session_transaction() as sess:
            sess["active_profile_id"] = prof.profile_id

        # Hit the serve route.
        url = "/organisation/setup/logo/" + meta["logo_id"]
        r = client.get(url)
        assert r.status_code == 200, f"serve returned {r.status_code}"
        # Bytes must be byte-for-byte identical to what we uploaded.
        assert r.data == svg_bytes, (
            "uploaded SVG bytes were altered by the serve route — "
            "Stage F3 forbids auto-modification of uploaded marks"
        )
        # And the fixture's known fill must still be there.
        assert b'fill="#FF0000"' in r.data
