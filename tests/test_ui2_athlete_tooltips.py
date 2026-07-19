"""tests/test_ui2_athlete_tooltips.py — UI2.2 Athlete tooltips.

Roadmap UI2.2: hover Animated-Tooltips on athlete avatars / rosters on the
review + spotlight surfaces, showing name, club and a key stat, via the kit
``.mh-tooltip`` component.

This module pins the whole feature:

  1. Kit layer — the ``.mh-tooltip`` CSS lives in theme-motion.css (token-driven,
     reduced-motion-gated, reveals on hover/focus) and the ``bindTooltip``
     behaviour lives in ui-kit.js (pointer parallax, REDUCE-guarded, registered).
  2. The ``_athlete_avatar`` helper — initials, escaping, focusable vs
     decorative a11y modes, clean meta assembly.
  3. Wiring — the review queue, the spotlight roster, and the spotlight hero
     each render a ``.mh-tooltip`` chip carrying real, grounded facts.
  4. Safety — every value shown is HTML-escaped; the effect fails safe and
     introduces no CDN dependency.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

import mediahub.web as _webpkg  # noqa: E402

_WEB_DIR = Path(_webpkg.__file__).resolve().parent
_MOTION_CSS = (_WEB_DIR / "static" / "theme" / "theme-motion.css").read_text()
_UI_KIT_JS = (_WEB_DIR / "static" / "js" / "ui-kit.js").read_text()


# ===========================================================================
# 1. Kit CSS — the .mh-tooltip component is in the motion layer
# ===========================================================================
class TestKitCss:
    def test_core_tooltip_classes_present(self):
        for sel in (
            ".mh-tooltip",
            ".mh-tooltip__avatar",
            ".mh-tooltip__pop",
            ".mh-tooltip__name",
            ".mh-tooltip__meta",
            ".mh-tooltip__stat",
        ):
            assert sel in _MOTION_CSS, f"{sel} missing from theme-motion.css"

    def test_tip_custom_props_registered(self):
        # Registered so an unset value is a clean 0, not `unset`.
        assert "@property --mh-tip-rot" in _MOTION_CSS
        assert "@property --mh-tip-x" in _MOTION_CSS

    def test_reveals_on_both_hover_and_focus(self):
        # Pure-CSS reveal so the tooltip works with no JS at all, and is
        # keyboard-reachable when the chip is focusable.
        assert ".mh-tooltip:hover .mh-tooltip__pop" in _MOTION_CSS
        assert ".mh-tooltip:focus-within .mh-tooltip__pop" in _MOTION_CSS

    def test_token_driven_no_hardcoded_brand_colour(self):
        # The kit rule is: colour from tokens only, so a re-skinned brand
        # re-skins the effect. The accent stat must use --mh-primary.
        assert ".mh-tooltip__stat { color: var(--mh-primary); }" in _MOTION_CSS

    def test_reduced_motion_stops_the_chip_lift_and_tilt(self):
        # The reduce block keeps the (opacity) reveal but kills the chip-lift,
        # spring and parallax — nothing moves.
        idx = _MOTION_CSS.find("@media (prefers-reduced-motion: reduce)")
        assert idx != -1, "reduced-motion block missing"
        reduce_block = _MOTION_CSS[idx:]
        assert ".mh-tooltip__avatar" in reduce_block
        assert ".mh-tooltip__pop" in reduce_block
        assert "transform: none" in reduce_block

    def test_no_cdn_or_external_url_introduced(self):
        # Honours the self-hosted / no-CDN rule — the tooltip is pure tokens,
        # no webfont/CDN link. Scoped to the tooltip section so the unrelated
        # SVG-noise `xmlns` namespace in section 1 isn't a false positive.
        start = _MOTION_CSS.index("13. ANIMATED TOOLTIP")
        end = _MOTION_CSS.index("REDUCED MOTION", start)
        block = _MOTION_CSS[start:end]
        for bad in ("fonts.googleapis", "gstatic", "https://", "http://", "@import"):
            assert bad not in block, f"unexpected external ref in tooltip CSS: {bad}"


# ===========================================================================
# 2. Kit JS — bindTooltip behaviour, registered + reduced-motion-guarded
# ===========================================================================
class TestKitJs:
    def test_bind_tooltip_defined_and_registered(self):
        assert "function bindTooltip" in _UI_KIT_JS
        assert 'each(root, ".mh-tooltip", bindTooltip)' in _UI_KIT_JS

    def test_writes_the_parallax_custom_properties(self):
        assert "--mh-tip-rot" in _UI_KIT_JS
        assert "--mh-tip-x" in _UI_KIT_JS

    def test_pointer_tilt_skipped_under_reduced_motion(self):
        # Slice the whole bindTooltip body (up to the next section comment) —
        # not the first nested `function`, which would truncate it early.
        start = _UI_KIT_JS.index("function bindTooltip")
        body = _UI_KIT_JS[start : _UI_KIT_JS.index("Scroll progress", start)]
        assert (
            "if (REDUCE) return" in body
        ), "bindTooltip must early-return under prefers-reduced-motion"
        # Uses rAF + passive listeners like the rest of the kit.
        assert "requestAnimationFrame" in body
        assert "{ passive: true }" in body


# ===========================================================================
# 3. _athlete_avatar helper — initials, a11y modes, escaping, meta assembly
# ===========================================================================
@pytest.fixture(scope="module")
def web():
    import mediahub.web.web as wm

    return wm


class TestAvatarHelper:
    def test_initials(self, web):
        assert web._avatar_initials("Maya Patel") == "MP"
        assert web._avatar_initials("Cher") == "CH"  # single token → 2 letters
        assert web._avatar_initials("  ") == "?"
        assert web._avatar_initials("aiko van der berg") == "AB"  # first+last

    def test_focusable_exposes_aria_label_and_is_tabbable(self, web):
        h = web._athlete_avatar("Maya Patel", club="Riverside SC", stat="3 moments", focusable=True)
        assert 'class="mh-tooltip"' in h
        assert 'tabindex="0"' in h
        assert 'role="img"' in h
        assert 'aria-label="Maya Patel · Riverside SC · 3 moments"' in h

    def test_decorative_is_aria_hidden_and_not_tabbable(self, web):
        h = web._athlete_avatar(
            "Maya Patel", club="Riverside SC", stat="3 moments", focusable=False
        )
        assert 'aria-hidden="true"' in h
        assert "tabindex" not in h
        assert "aria-label" not in h

    def test_meta_line_omitted_when_empty(self, web):
        h = web._athlete_avatar("Solo Swimmer")
        assert "mh-tooltip__meta" not in h  # no club, no stat
        assert "mh-tooltip__sep" not in h

    def test_separator_only_when_both_club_and_stat(self, web):
        club_only = web._athlete_avatar("A B", club="Club X")
        assert "mh-tooltip__club" in club_only
        assert "mh-tooltip__sep" not in club_only
        both = web._athlete_avatar("A B", club="Club X", stat="2 moments")
        assert "mh-tooltip__sep" in both

    def test_escapes_name_club_and_stat(self, web):
        h = web._athlete_avatar(
            "<script>alert(1)</script>",
            club='Bad"Club',
            stat="<b>x</b>",
            focusable=True,
        )
        assert "<script>" not in h
        assert "&lt;script&gt;" in h
        assert "&lt;b&gt;x&lt;/b&gt;" in h
        # The escaped name must not break out of the aria-label attribute.
        assert '"><' not in h.split("aria-label=")[1][:80]

    def test_size_sets_the_chip_custom_property(self, web):
        h = web._athlete_avatar("A B", size=52)
        assert "--mh-tip-size:52px" in h


# ===========================================================================
# Integration — a seeded run rendered through the real Flask routes
# ===========================================================================
@pytest.fixture
def tip_app(tmp_path, monkeypatch, web_module):
    for env in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(env, raising=False)

    wm = web_module

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="riverside", display_name="Riverside SC"))

    run_id = "run-tip-" + uuid.uuid4().hex[:8]
    # Two swimmers: Maya (one elite + one strong = 2 moments, best elite),
    # Jordan (one strong = 1 moment, best strong).
    achievements = [
        {
            "achievement": {
                "swim_id": "riverside:Patel,Maya:100FR:gold",
                "swimmer_id": "riverside:Patel,Maya",
                "swimmer_name": "Maya Patel",
                "event": "100m Freestyle (LC)",
                "type": "medal_gold",
                "headline": "Maya Patel wins gold in 100m Freestyle",
                "confidence_label": "high",
                "confidence": 0.95,
            },
            "rank": 1,
            "priority": 9.0,
            "quality_band": "elite",
            "suggested_post_type": "feed",
        },
        {
            "achievement": {
                "swim_id": "riverside:Patel,Maya:200FR:pb",
                "swimmer_id": "riverside:Patel,Maya",
                "swimmer_name": "Maya Patel",
                "event": "200m Freestyle (LC)",
                "type": "personal_best",
                "headline": "Maya Patel sets a PB in 200m Freestyle",
                "confidence_label": "medium",
                "confidence": 0.7,
            },
            "rank": 2,
            "priority": 6.0,
            "quality_band": "strong",
            "suggested_post_type": "story",
        },
        {
            "achievement": {
                "swim_id": "riverside:Lee,Jordan:50BK:pb",
                "swimmer_id": "riverside:Lee,Jordan",
                "swimmer_name": "Jordan Lee",
                "event": "50m Backstroke (LC)",
                "type": "personal_best",
                "headline": "Jordan Lee sets a PB in 50m Backstroke",
                "confidence_label": "high",
                "confidence": 0.9,
            },
            "rank": 3,
            "priority": 5.0,
            "quality_band": "strong",
            "suggested_post_type": "story",
        },
    ]
    run_payload = {
        "run_id": run_id,
        "profile_id": "riverside",
        "profile_display": "Riverside SC",
        "club_filter": "Riverside SC",
        "meet": {"name": "Spring Invitational"},
        "cards": [],
        "trust": {"score": 0.9},
        "recognition_report": {
            "meet_name": "Spring Invitational",
            "ranked_achievements": achievements,
            "n_elite": 1,
            "n_strong": 2,
            "n_story": 0,
            "n_achievements": 3,
            "n_swims_analysed": 3,
        },
        "parse_warnings": [],
        "self_check": {},
        "detector_summary": {},
        "dispatch_log": {},
    }
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(run_payload))

    # DB row so /spotlight's recent-runs picker finds the meet.
    wm._init_db()
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, "
        "meet_name, file_name) VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "riverside", "Spring Invitational", "spring.hy3"),
    )
    conn.commit()
    conn.close()

    app = wm.create_app()
    app.config["TESTING"] = True  # bypass the org gate (standard test default)

    with app.test_client() as c:
        # Pin the active org so the run's tenant guard + spotlight scoping pass.
        with c.session_transaction() as sess:
            sess["active_profile_id"] = "riverside"
        yield {"client": c, "run_id": run_id}


class TestReviewSurface:
    def test_review_renders_athlete_avatars(self, tip_app):
        c = tip_app["client"]
        r = c.get(f"/review/{tip_app['run_id']}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert 'class="mh-tooltip"' in body
        # Initials chips for both swimmers.
        assert ">MP<" in body
        assert ">JL<" in body

    def test_review_tooltip_carries_grounded_per_swimmer_stat(self, tip_app):
        c = tip_app["client"]
        body = c.get(f"/review/{tip_app['run_id']}").get_data(as_text=True)
        # Maya: 2 ranked moments, best band elite.
        assert "2 moments" in body
        assert "best elite" in body
        # Jordan: a single moment (singular), best strong.
        assert "1 moment" in body
        assert "best strong" in body
        # Club resolved from the run's profile_display.
        assert "Riverside SC" in body

    def test_review_chips_are_decorative(self, tip_app):
        # Inside the row, the name/event/band are already visible text, so the
        # chip stays out of the tab order (decorative, aria-hidden).
        c = tip_app["client"]
        body = c.get(f"/review/{tip_app['run_id']}").get_data(as_text=True)
        assert 'mh-tooltip__avatar" aria-hidden="true"' in body


class TestSpotlightRoster:
    def test_roster_cards_render_avatars(self, tip_app):
        c = tip_app["client"]
        r = c.get(f"/spotlight?run_id={tip_app['run_id']}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert 'class="mh-tooltip"' in body
        assert ">MP<" in body and ">JL<" in body

    def test_roster_tooltip_shows_achievement_count(self, tip_app):
        c = tip_app["client"]
        body = c.get(f"/spotlight?run_id={tip_app['run_id']}").get_data(as_text=True)
        # Maya appears in two achievements → "2 achievements"; Jordan → "1 achievement".
        assert "2 achievements" in body
        assert "1 achievement" in body
        assert "Riverside SC" in body


class TestSpotlightHero:
    def test_hero_avatar_is_focusable_with_full_summary(self, tip_app):
        c = tip_app["client"]
        r = c.get(f"/spotlight/{tip_app['run_id']}/riverside:Patel,Maya")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert 'class="mh-tooltip"' in body
        # Standalone hero chip → keyboard reachable + AT summary.
        assert 'tabindex="0"' in body
        assert 'role="img"' in body
        # Grounded haul: 1 elite of 2 moments + club.
        assert "1 elite" in body
        assert "2 moments" in body
        assert "Riverside SC" in body
