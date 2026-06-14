"""UI 1.24 — moment-type marquee/ticker (SavoirFaire / SuperHi-inspired).

The landing page carries a continuous horizontal-scrolling ticker used as a
*section divider* between the outputs grid (bento) and the in-feed frames. It
names the kinds of moments the engine detects and ranks — PBs, medals,
comebacks, finals, club records and more — in a large editorial display band.

The loop is **pure CSS**: the moment list is rendered twice in the markup so a
`translateX(-50%)` keyframe lands exactly on the seam, with no JavaScript clone
(it deliberately does NOT reuse the JS-cloned `.mh-marquee` component, which
would double-clone and break the seam).

These tests pin:
  - the ticker renders on the home page with a descriptive aria-label
  - the vocabulary is exactly the honest, engine-backed moment set (the
    roadmap's five lead it) — no invented achievement types
  - the list is rendered twice (seamless pure-CSS loop) with the duplicate copy
    marked aria-hidden, and the filled/outline ("ghost") rhythm alternates
  - it sits as a divider between the bento grid and the frames section, and the
    pre-existing sport-agnostic marquee band is untouched (two distinct bands)
  - it does not opt into the JS marquee clone (`data-mh-speed` / `.mh-marquee`)
  - the CSS contract: brand display font, gold accent mark, edge-fade mask,
    hover-pause, and a reduced-motion gate that stops the animation dead
  - no CDN/remote reference is introduced
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from mediahub.web import web as webmod

_ROOT = Path(__file__).resolve().parents[1]
MOTION_CSS = (
    _ROOT / "src" / "mediahub" / "web" / "static" / "theme" / "theme-motion.css"
).read_text(encoding="utf-8")

# The canonical, honest vocabulary — order matters (the roadmap's five lead).
# Every entry maps onto a real deterministic detector:
#   Personal bests      -> PBConfirmed / PBLikely / OfficialPB
#   Medal finishes      -> MedalDetector
#   Comebacks           -> HeatToFinalDrop / comeback milestones
#   Finals              -> FinalAppearanceDetector
#   Club records        -> ClubRecordDetector
#   First-time swims    -> milestones (first gala / first event)
#   Qualifying times    -> QualifyingTimeDetector
#   Barrier breaks      -> FirstSubBarrierDetector
#   Relay wins          -> RelayMedalDetector
#   Multi-PB weekends   -> MultiPBWeekendDetector
EXPECTED = [
    "Personal bests",
    "Medal finishes",
    "Comebacks",
    "Finals",
    "Club records",
    "First-time swims",
    "Qualifying times",
    "Barrier breaks",
    "Relay wins",
    "Multi-PB weekends",
]

ITEM_RE = re.compile(
    r'<span class="mh-moment-ticker__item( is-ghost)?"( aria-hidden="true")?>([^<]+)</span>'
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(webmod, "RUNS_DIR", runs, raising=False)
    app = webmod.app
    app.config["TESTING"] = True  # disables CSRF enforcement (see _csrf_enforced)
    with app.test_client() as c:
        yield c


def _home(client) -> str:
    resp = client.get("/")
    assert resp.status_code == 200, resp.status_code
    return resp.get_data(as_text=True)


def _items(body: str):
    """Return [(text, is_ghost, is_hidden), ...] in document order."""
    return [
        (m.group(3), bool(m.group(1)), bool(m.group(2)))
        for m in ITEM_RE.finditer(body)
    ]


# --------------------------------------------------------------------------- #
# Renders on the home page
# --------------------------------------------------------------------------- #
class TestTickerOnHome:
    def test_section_present_with_aria_label(self, client):
        body = _home(client)
        assert '<section class="mh-moment-ticker"' in body
        assert 'aria-label="Moments MediaHub detects and ranks"' in body

    def test_viewport_and_track_structure(self, client):
        body = _home(client)
        assert 'class="mh-moment-ticker__viewport"' in body
        assert 'class="mh-moment-ticker__track"' in body

    def test_renders_list_twice_for_seamless_loop(self, client):
        # 10 moments × 2 identical copies = 20 item spans. Two copies are what
        # make translateX(-50%) seamless with no JS clone.
        items = _items(_home(client))
        assert len(items) == 2 * len(EXPECTED), [t for t, _g, _h in items]

    def test_first_copy_is_the_expected_vocabulary_in_order(self, client):
        items = _items(_home(client))
        first = [t for t, _g, _h in items[: len(EXPECTED)]]
        assert first == EXPECTED

    def test_second_copy_is_identical(self, client):
        items = _items(_home(client))
        second = [t for t, _g, _h in items[len(EXPECTED):]]
        assert second == EXPECTED

    def test_roadmap_five_moment_types_present(self, client):
        joined = " ".join(t.lower() for t, _g, _h in _items(_home(client)))
        for needle in ("personal bests", "medal", "comebacks", "finals", "club records"):
            assert needle in joined, f"roadmap moment type missing: {needle!r}"


# --------------------------------------------------------------------------- #
# Filled / outline ("ghost") rhythm + accessibility of the two copies
# --------------------------------------------------------------------------- #
class TestTickerRhythmAndAccessibility:
    def test_alternating_ghost_in_both_copies(self, client):
        # Even index filled, odd index outline — set in markup so the rhythm
        # continues cleanly across the seam (not via :nth-child).
        items = _items(_home(client))
        for copy_start in (0, len(EXPECTED)):
            copy = items[copy_start: copy_start + len(EXPECTED)]
            for i, (_t, ghost, _h) in enumerate(copy):
                assert ghost == (i % 2 == 1), f"ghost flag wrong at index {i}"

    def test_exactly_half_are_ghost(self, client):
        items = _items(_home(client))
        assert sum(1 for _t, g, _h in items if g) == len(EXPECTED)

    def test_first_copy_accessible_second_copy_aria_hidden(self, client):
        items = _items(_home(client))
        first = items[: len(EXPECTED)]
        second = items[len(EXPECTED):]
        assert all(not hidden for _t, _g, hidden in first), "first copy must be readable"
        assert all(hidden for _t, _g, hidden in second), "duplicate copy must be aria-hidden"

    def test_no_literal_separator_glyph_between_words(self, client):
        # The gold diamond mark is a CSS ::after pseudo-element, so no separator
        # character is injected as text (a screen reader reads clean words).
        body = _home(client)
        seg = body[body.find('class="mh-moment-ticker__track"'):]
        seg = seg[: seg.find("</section>")]
        between = re.sub(r"<[^>]+>", "", seg)  # strip tags, keep text nodes
        for glyph in ("✦", "✶", "✷", "•", "·", "/", "*", "◆", "★"):
            assert glyph not in between, f"unexpected separator glyph {glyph!r} in text"


# --------------------------------------------------------------------------- #
# Placement — a divider, and no regression to the existing marquee band
# --------------------------------------------------------------------------- #
class TestTickerPlacement:
    def test_sits_between_bento_and_frames(self, client):
        body = _home(client)
        i_bento = body.find('class="mh-bento mh-reveal-group"')
        i_tick = body.find('<section class="mh-moment-ticker"')
        i_frames = body.find('class="mh-frames mh-reveal"')
        assert -1 < i_bento < i_tick < i_frames, (i_bento, i_tick, i_frames)

    def test_after_hero(self, client):
        body = _home(client)
        i_hero = body.find('class="mh-hero"')
        i_tick = body.find('<section class="mh-moment-ticker"')
        assert -1 < i_hero < i_tick

    def test_existing_sport_marquee_band_untouched(self, client):
        # UI 1.24 is a *second*, distinct band — the sport-agnostic marquee
        # ("One engine · every sport") must still render, and earlier.
        body = _home(client)
        i_sports = body.find('class="mh-marquee-band"')
        i_tick = body.find('<section class="mh-moment-ticker"')
        assert i_sports != -1, "sport-agnostic marquee band disappeared"
        assert -1 < i_sports < i_tick
        assert "One engine" in body  # its label survives

    def test_does_not_reuse_js_marquee_clone(self, client):
        # The ticker must not carry the JS-cloned marquee classes nor the
        # data-mh-speed hook, or ui-kit.js would double-clone it (4 copies) and
        # break the pure-CSS seam.
        body = _home(client)
        seg = body[body.find('<section class="mh-moment-ticker"'):]
        seg = seg[: seg.find("</section>") + len("</section>")]
        assert "mh-marquee__track" not in seg
        assert "data-mh-speed" not in seg
        assert 'class="mh-marquee"' not in seg


# --------------------------------------------------------------------------- #
# Honest vocabulary — no invented achievement types
# --------------------------------------------------------------------------- #
class TestHonestVocabulary:
    def test_vocabulary_is_exactly_the_known_honest_set(self, client):
        items = _items(_home(client))
        seen = [t for t, _g, _h in items[: len(EXPECTED)]]
        assert seen == EXPECTED

    def test_no_fabricated_moment_types(self, client):
        # Guard against drift into claims the engine does not detect.
        joined = " ".join(t.lower() for t, _g, _h in _items(_home(client)))
        for fake in ("world record", "olympic", "national title", "world champion"):
            assert fake not in joined, f"fabricated moment type leaked: {fake!r}"


# --------------------------------------------------------------------------- #
# CSS contract (read the source; it is also inlined into the page)
# --------------------------------------------------------------------------- #
class TestTickerCss:
    def test_core_rules_exist(self):
        for sel in (
            ".mh-moment-ticker {",
            ".mh-moment-ticker__viewport {",
            ".mh-moment-ticker__track {",
            ".mh-moment-ticker__item {",
            ".mh-moment-ticker__item.is-ghost {",
            ".mh-moment-ticker__item::after {",
            "@keyframes mh-moment-ticker",
        ):
            assert sel in MOTION_CSS, f"missing CSS rule {sel}"

    def test_track_runs_the_keyframe_animation(self):
        block = MOTION_CSS[MOTION_CSS.find(".mh-moment-ticker__track {"):]
        block = block[: block.find("}")]
        assert "animation:" in block and "mh-moment-ticker" in block
        assert "linear" in block and "infinite" in block
        # max-content width is what makes the two-copy -50% loop seamless
        assert "max-content" in block

    def test_keyframe_translates_minus_half(self):
        kf = MOTION_CSS[MOTION_CSS.find("@keyframes mh-moment-ticker"):]
        kf = kf[: kf.find("}", kf.find("{")) + 1]
        assert "translateX(-50%)" in kf

    def test_item_uses_brand_display_font(self):
        block = MOTION_CSS[MOTION_CSS.find(".mh-moment-ticker__item {"):]
        block = block[: block.find("}")]
        assert "var(--font-display)" in block
        assert "uppercase" in block

    def test_ghost_uses_text_stroke_outline(self):
        block = MOTION_CSS[MOTION_CSS.find(".mh-moment-ticker__item.is-ghost {"):]
        block = block[: block.find("}")]
        assert "text-stroke" in block  # -webkit-text-stroke + text-stroke
        # solid-colour fallback first for engines without stroke support
        assert "color:" in block

    def test_accent_mark_is_brand_gold_pure_css(self):
        block = MOTION_CSS[MOTION_CSS.find(".mh-moment-ticker__item::after {"):]
        block = block[: block.find("}")]
        assert 'content: ""' in block  # CSS shape, not a glyph/text
        # the signature medal-gold accent, not the navy primary CTA fill
        assert "var(--mh-tertiary)" in block
        assert "rotate(45deg)" in block  # the diamond

    def test_hover_pauses(self):
        assert (
            ".mh-moment-ticker:hover .mh-moment-ticker__track { animation-play-state: paused; }"
            in MOTION_CSS
        )

    def test_edge_fade_mask_on_viewport(self):
        block = MOTION_CSS[MOTION_CSS.find(".mh-moment-ticker__viewport {"):]
        block = block[: block.find("}")]
        assert "mask-image" in block and "linear-gradient" in block

    def test_reduced_motion_stops_the_animation(self):
        rm = MOTION_CSS[MOTION_CSS.find("@media (prefers-reduced-motion: reduce)"):]
        # track is in the animation:none list
        kill = rm[: rm.find("animation: none !important;")]
        assert ".mh-moment-ticker__track" in kill
        # and the viewport mask is removed + made scrollable so it degrades to a
        # static, manually-scrollable strip
        assert ".mh-moment-ticker__viewport" in rm
        assert "overflow-x: auto" in rm[rm.find(".mh-moment-ticker__viewport"):]

    def test_css_ships_inlined_on_the_page(self, client):
        # The component CSS is concatenated into BASE_CSS, so it is actually
        # present on the rendered landing page, not just in the source file.
        body = _home(client)
        assert ".mh-moment-ticker__track {" in body
        assert "@keyframes mh-moment-ticker" in body


# --------------------------------------------------------------------------- #
# No remote/CDN reference introduced
# --------------------------------------------------------------------------- #
class TestNoRemoteRefs:
    def test_ticker_markup_has_no_remote_url(self, client):
        body = _home(client)
        seg = body[body.find('<section class="mh-moment-ticker"'):]
        seg = seg[: seg.find("</section>") + len("</section>")]
        assert "http://" not in seg and "https://" not in seg

    def test_ticker_css_has_no_cdn_or_webfont_import(self):
        block = MOTION_CSS[MOTION_CSS.find("Moment-type ticker"):]
        block = block[: block.find("Gradient-text")]
        low = block.lower()
        assert "googleapis" not in low and "gstatic" not in low
        assert "@import" not in low
        assert "url(http" not in low
