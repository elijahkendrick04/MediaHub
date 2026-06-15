"""Site-wide UX/UI effect coverage — the landing-page motion kit, spread.

Yesterday's Phase-U work landed a rich motion/effect layer (scroll-reveal,
decode-in headlines, count-up stats, card hover-lift, hero entrance). The
*engine* for all of it is global — it ships in ``_layout`` (inline CSS/JS) and
``ui-kit.js`` on every page — but the landing page was the only surface that
actually *wore* the signature effects.

This test pins the follow-up: the effects are now incorporated across all of the
main navigable surfaces, not just the home page. Three contracts:

  1. ``BASE_CSS`` carries the two *global* enhancements that reach every page
     with no per-page markup — the shared ``.mh-hero`` header entrance and the
     interactive-card hover-lift — and both stand down under
     ``prefers-reduced-motion``.
  2. Every page's ``<body>`` is tagged ``data-page="<active>"`` so page-scoped
     effects (and the home-hero opt-out) can key off it.
  3. The signature decode-in (``.mh-scramble``) rides the primary ``<h1>`` of
     the main navigable pages — signed-out *and* signed-in — while the landing
     hero ``<h1>`` stays deliberately attribute-free (its bespoke word-cycle
     owns that headline).

Presentation-only: the deterministic engine, AI surfaces and explainability
logic are untouched. Mirrors the fixture/gating style of
``tests/test_activity_count_up.py`` and ``tests/test_u5_scroll_reveal.py``.
"""

from __future__ import annotations

import re

import pytest

from mediahub.web import web as webmod


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    app = webmod.app
    app.config["TESTING"] = True

    # One saved, ready org so the signed-in page variants render.
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="fx-org",
            display_name="Effect SC",
            brand_voice_summary="Testing.",
            brand_capture_status="ok",
        )
    )
    with app.test_client() as c:
        yield c


def _get(client, path, *, signed_in=False):
    if signed_in:
        with client.session_transaction() as s:
            s["active_profile_id"] = "fx-org"
    else:
        with client.session_transaction() as s:
            s.pop("active_profile_id", None)
    resp = client.get(path, follow_redirects=True)
    assert resp.status_code == 200, f"GET {path} → {resp.status_code}"
    return resp.get_data(as_text=True)


def _primary_h1(body: str) -> str:
    """The first <h1 …>…</h1> on the page — its primary heading."""
    m = re.search(r"<h1\b[^>]*>.*?</h1>", body, re.DOTALL)
    assert m, "page has no <h1>"
    return m.group(0)


# =========================================================================== #
# 1) Global CSS — reaches every page with zero per-page markup
# =========================================================================== #
class TestGlobalEffectCss:
    def test_shared_hero_entrance_is_defined(self):
        css = webmod.BASE_CSS
        assert 'body:not([data-page="home"]) main.wrap .mh-hero > h1' in css
        assert 'body:not([data-page="home"]) main.wrap .mh-hero > .mh-hero-eyebrow' in css
        assert 'body:not([data-page="home"]) main.wrap .mh-hero > .lede' in css
        # staggered cadence
        assert "animation-delay: 0.04s" in css
        assert "animation-delay: 0.12s" in css
        assert "animation-delay: 0.20s" in css

    def test_hero_entrance_excludes_the_landing_hero(self):
        # The home hero keeps its bespoke treatment — the entrance selector is
        # gated to :not([data-page="home"]).
        css = webmod.BASE_CSS
        assert ':not([data-page="home"]) main.wrap .mh-hero > h1' in css

    def test_hero_entrance_stands_down_under_reduced_motion(self):
        css = webmod.BASE_CSS
        assert re.search(
            r"@media \(prefers-reduced-motion: reduce\) \{[^@]*"
            r"body:not\(\[data-page=\"home\"\]\) main\.wrap \.mh-hero > \.lede \{ animation: none; \}",
            css,
            re.DOTALL,
        ), "hero entrance is not neutralised under prefers-reduced-motion"

    def test_interactive_card_hover_lifts_site_wide(self):
        css = webmod.BASE_CSS
        # transform + box-shadow joined the card transition …
        assert "box-shadow var(--transition), transform var(--transition)" in css
        # … and the lift only engages for motion-allowed fine-pointer hover.
        assert (
            "@media (prefers-reduced-motion: no-preference) and "
            "(hover: hover) and (pointer: fine)" in css
        )
        assert "transform: translateY(-2px)" in css
        assert "a.card:active, .card[data-interactive]:active { transform: translateY(0); }" in css

    def test_non_interactive_cards_do_not_lift(self):
        # The lift is scoped to a.card / [data-interactive] — a plain info card
        # never moves (correct affordance). No bare ``.card:hover { transform``.
        css = webmod.BASE_CSS
        assert not re.search(r"(?<![a-z.\]])\.card:hover\s*\{[^}]*transform", css)


# =========================================================================== #
# 2) Every page tags its <body> with the active page id
# =========================================================================== #
class TestBodyPageTag:
    @pytest.mark.parametrize(
        "path,expected",
        [
            ("/", "home"),
            ("/make", "create"),
            ("/templates", "templates"),
            ("/settings", "settings"),
            ("/sign-in", "signin"),
        ],
    )
    def test_body_carries_data_page(self, client, path, expected):
        body = _get(client, path)
        assert f'data-page="{expected}"' in body, f"{path} missing data-page={expected}"

    def test_data_page_is_always_present(self, client):
        # Whatever the active id, the tag is there so page-scoped CSS can key
        # off it (pricing, e.g., rides the signed-out nav as active="signin").
        for path in ("/", "/pricing", "/status", "/media-library"):
            body = _get(client, path)
            assert re.search(r'<body[^>]*\sdata-page="[a-z_]+"', body), f"{path} has no data-page"


# =========================================================================== #
# 3) The decode-in (.mh-scramble) signature rides the primary heading of
#    every main page — but never the landing hero.
# =========================================================================== #
class TestDecodeInHeadlines:
    def test_landing_hero_h1_stays_attribute_free(self, client):
        # The U.9 word-cycle owns the hero headline; it must stay bare.
        body = _get(client, "/")
        assert _primary_h1(body) == re.search(r"<h1>.*?</h1>", body, re.DOTALL).group(0)
        assert "mh-scramble" not in _primary_h1(body)

    @pytest.mark.parametrize(
        "path",
        ["/make", "/templates", "/settings", "/pricing", "/sign-in", "/status", "/media-library"],
    )
    def test_signed_out_pages_decode_their_heading(self, client, path):
        body = _get(client, path)
        assert "mh-scramble" in _primary_h1(body), f"{path} heading is not a decode-in"

    @pytest.mark.parametrize(
        "path", ["/plan", "/activity", "/season", "/media-library", "/settings"]
    )
    def test_signed_in_pages_decode_their_heading(self, client, path):
        body = _get(client, path, signed_in=True)
        assert "mh-scramble" in _primary_h1(body), f"{path} (signed in) heading is not a decode-in"

    def test_templates_still_has_exactly_one_h1(self, client):
        # The decode-in is a class on the existing <h1>, not a second heading —
        # the gallery's heading-order contract is preserved.
        body = _get(client, "/templates")
        assert body.count("<h1") == 1
