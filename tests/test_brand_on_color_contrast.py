"""Regression guard for the brand-cascade on-colour (button/label ink).

The Adaptive Theming Engine recolours the whole UI to each club's brand. A
button's background becomes the brand *seed* (``--mh-primary`` resolves to brand
tone 400, i.e. the raw seed), while its label colour is ``--lane-ink`` which
aliases ``--mh-on-primary``. Before this fix ``--mh-on-primary`` was a *static*
near-black (#0A0B11): fine on the lane-yellow default, but on a dark brand seed
(the signed-out navy default #0E2A47, a maroon/navy club) the primary CTA
rendered dark-on-dark at ~1.3:1 — a WCAG fail and the first thing a visitor saw.

``brand_on_color`` re-derives the ink from the live seed using the deterministic
contrast science, and ``_theme_seed_style_block`` now emits it per request so it
travels with the cascade. These tests pin the pass condition the Council made
binding: **button-text ink ≥ WCAG 2.x AA (4.5:1) against its resolved background
for every representative club palette** — so the dark-brand failure can never
recur for the next navy / maroon / dark-green club onboarded.
"""

from __future__ import annotations

import re

import pytest

from mediahub.theming.contrast import brand_on_color, wcag2_ratio

AA = 4.5

# Representative club palettes — the corpus the on-colour rule must satisfy.
# Spans the lane-yellow default, the signed-out navy default, real dark club
# brands (Swansea maroon, a navy, a dark green), saturated mids, and the
# near-white / near-black extremes.
CORPUS = {
    "lane-yellow (default brand)": "#D4FF3A",
    "navy (signed-out default)": "#0E2A47",
    "swansea maroon": "#A30D2D",
    "royal blue": "#1D4ED8",
    "forest green": "#14532D",
    "sheffield red": "#EE2737",
    "teal": "#0F766E",
    "violet": "#6D28D9",
    "near-white brand": "#F5F2E8",
    "near-black brand": "#0A0B11",
    "orange": "#EA580C",
    "sky": "#38BDF8",
}


class TestBrandOnColorHelper:
    @pytest.mark.parametrize("name,seed", list(CORPUS.items()))
    def test_button_ink_clears_AA_for_every_palette(self, name, seed):
        ink = brand_on_color(seed)
        ratio = wcag2_ratio(ink, seed)
        assert ratio >= AA, (
            f"{name} ({seed}): on-colour {ink} only {ratio}:1 — below AA {AA}:1. "
            f"A club with this brand would get an unreadable primary CTA."
        )

    def test_returns_valid_hex(self):
        for seed in CORPUS.values():
            assert re.fullmatch(r"#[0-9A-Fa-f]{6}", brand_on_color(seed))

    def test_lane_yellow_default_is_unchanged(self):
        # The lane-yellow default must keep its existing near-black ink so this
        # fix is a no-op for the reference palette (no surprise regression).
        assert brand_on_color("#D4FF3A").upper() == "#0A0B11"

    def test_dark_navy_default_flips_to_light_ink(self):
        # The exact reported bug: navy #0E2A47 must get the paper-cream ink,
        # not the static near-black that measured 1.35:1 on the live site.
        ink = brand_on_color("#0E2A47")
        assert ink.upper() == "#F5F2E8"
        assert wcag2_ratio(ink, "#0E2A47") >= AA

    def test_original_bug_pair_was_below_AA(self):
        # Document the defect this guards against: the old static pairing.
        assert wcag2_ratio("#0A0B11", "#0E2A47") < AA  # ~1.35:1


@pytest.fixture
def fresh_app(app, web_module, monkeypatch):
    """Clean app + isolated DATA_DIR so the seed block renders against a
    throwaway profile store (mirrors tests/test_default_theme.py)."""
    monkeypatch.delenv("MEDIAHUB_ADAPTIVE_THEME", raising=False)
    from mediahub.theming.theme_store import _read_cached

    _read_cached.cache_clear()
    return app, web_module


def _on_primary_from_body(body: str) -> str:
    m = re.search(r"--mh-on-primary:\s*(#[0-9A-Fa-f]{6})", body)
    assert m, "seed block did not emit a --mh-on-primary override"
    return m.group(1)


class TestSeedBlockEmitsLegibleOnColor:
    def test_signed_out_navy_default_cta_is_legible(self, fresh_app):
        app, _wm = fresh_app
        with app.test_client() as c:
            body = c.get("/status").get_data(as_text=True)
        assert 'id="mh-theme-seed"' in body
        ink = _on_primary_from_body(body)
        # The signed-out default seed is navy #0E2A47 (BrandKit.generic_default).
        assert (
            wcag2_ratio(ink, "#0E2A47") >= AA
        ), "signed-out landing CTA still fails contrast — the headline bug"

    def test_dark_brand_club_cta_is_legible(self, fresh_app):
        app, wm = fresh_app
        from mediahub.web.club_profile import ClubProfile, save_profile

        seed = "#A30D2D"  # a dark maroon club brand
        prof = ClubProfile(profile_id="maroon-club", display_name="Maroon SC")
        prof.brand_primary = seed
        prof.brand_palette_extracted = {"primary": seed}
        prof.brand_kit = {
            "profile_id": "maroon-club",
            "display_name": "Maroon SC",
            "primary_colour": seed,
        }
        save_profile(prof)
        with app.test_client() as c:
            with c.session_transaction() as s:
                s["active_profile_id"] = "maroon-club"
            body = c.get("/status").get_data(as_text=True)
        ink = _on_primary_from_body(body)
        assert wcag2_ratio(ink, seed) >= AA
