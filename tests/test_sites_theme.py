"""Microsite engine (roadmap 1.16) — build 1: the responsive brand theme."""

from __future__ import annotations

from mediahub.sites import theme


def _roles():
    return {
        "--mh-primary": "#0A2540",
        "--mh-secondary": "#1B3D5C",
        "--mh-surface": "#051433",
        "--mh-accent": "#FFB81C",
        "--mh-on-primary": "#FFFFFF",
        "--mh-on-surface": "#FFFFFF",
    }


def test_tokens_dark_and_light():
    dark = theme.site_tokens(_roles(), theme="dark")
    light = theme.site_tokens(_roles(), theme="light")
    # brand roles flow through to both
    assert dark["--site-brand"] == "#0A2540"
    assert dark["--site-accent"] == "#FFB81C"
    # dark uses the brand surface as the page; light uses white
    assert dark["--site-bg"] == "#051433"
    assert light["--site-bg"] == "#FFFFFF"
    assert light["--site-ink"] == "#14181F"


def test_style_is_self_contained_and_brand_tokened():
    css = theme.site_style(_roles(), theme="dark")
    # tokens present
    assert "--site-bg:#051433" in css.replace(" ", "")
    assert ".site-hero" in css and ".bio-link" in css and ".card-grid" in css
    # CLAUDE.md rule: never the Google Fonts CDN
    assert "fonts.googleapis.com" not in css
    assert "gstatic" not in css
    assert "@import" not in css


def test_style_is_deterministic():
    a = theme.site_style(_roles(), theme="dark")
    b = theme.site_style(_roles(), theme="dark")
    assert a == b
