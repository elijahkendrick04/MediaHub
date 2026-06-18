"""tests/test_ui_cycle_placeholder.py — UI 1.1 cycling example-prompt placeholder.

Roadmap **UI 1.1** (Phase 1 product polish, inspired by Cosmos): the CREATE /
Free-Text "describe a moment" input and the ask-the-data / web-research query
boxes animate their placeholder through curated real example prompts ("Try: Tom
Davies PB 100m free", "Try: top three at county finals") to guide first-time
users — pure vanilla JS, no new deps, ``prefers-reduced-motion`` respected, with
the static ``placeholder=""`` each field already carries kept as the no-JS /
reduced-motion fallback. (The /activity search migrated to the UI2.6 Vanish
input — its coverage lives in tests/test_ui_vanish_search.py.)

Two layers, matching tests/test_activity_count_up.py:

  1. **Server-side** — every wired surface renders ``data-mh-cycle-placeholder``
     with a parseable, HTML-safe pipe list of "Try: …" phrases (apostrophes
     round-trip), the static placeholder is preserved, and the global
     ``bindCyclePlaceholders()`` JS (with its reduced-motion guard) ships in the
     layout on every page.
  2. **Browser-side** (Playwright) — the placeholder actually types/cycles with
     a caret on /free-text, and stays frozen on the static fallback under
     ``prefers-reduced-motion: reduce``.

The Playwright tier skips when Playwright or the pinned Chromium build is absent,
mirroring tests/test_activity_count_up.py and tests/test_browser_cascade.py.
"""

from __future__ import annotations

import html as _html
import importlib
import os
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_SKIP_BROWSER = os.environ.get("MEDIAHUB_SKIP_BROWSER_TESTS", "").lower() in ("1", "true", "yes")
_PINNED_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")

# The two roadmap-mandated example prompts — UI 1.1 names these verbatim, so
# they must survive into the shipped attribute or the feature drifted from spec.
_MANDATED = ("Try: Tom Davies PB 100m free", "Try: top three at county finals")
_CARET = "│"  # the thin typewriter caret bindCyclePlaceholders appends


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401

        return True
    except ImportError:
        return False


def _chromium_available() -> bool:
    return _PINNED_CHROMIUM.is_file()


# ── helpers ──────────────────────────────────────────────────────────────────


def _parse_cycle(html: str, field_id: str) -> list[str]:
    """Pull the pipe-list out of one field's ``data-mh-cycle-placeholder``.

    Mirrors the client: HTML-unescape the attribute, split on ``|``, trim, drop
    empties. Asserts the attribute is present on (near) the field so a missing
    wiring fails loudly rather than returning ``[]``.
    """
    # The attribute may sit before or after id="" on the tag — match either order
    # but stay within the one tag (no '>' in between).
    pat_after = re.compile(
        r'id="%s"[^>]*?data-mh-cycle-placeholder="([^"]*)"' % re.escape(field_id)
    )
    pat_before = re.compile(
        r'data-mh-cycle-placeholder="([^"]*)"[^>]*?id="%s"' % re.escape(field_id)
    )
    m = pat_after.search(html) or pat_before.search(html)
    assert m, f"no data-mh-cycle-placeholder on #{field_id}"
    raw = _html.unescape(m.group(1))
    return [p.strip() for p in raw.split("|") if p.strip()]


def _static_placeholder(html: str, field_id: str) -> str:
    m = re.search(r'id="%s"[^>]*?\splaceholder="([^"]*)"' % re.escape(field_id), html) or re.search(
        r'placeholder="([^"]*)"[^>]*?\sid="%s"' % re.escape(field_id), html
    )
    assert m, f"no static placeholder on #{field_id}"
    return _html.unescape(m.group(1))


# ── fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture
def app_mod(tmp_path, monkeypatch):
    """Isolated Flask app + one ready profile; research console enabled."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    # /web-research is opt-in; turn it on so its query box is reachable here.
    monkeypatch.setenv("MEDIAHUB_RESEARCH_UI", "1")
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True  # gate bypassed → every page renders

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="test-org",
            display_name="Test Org",
            brand_voice_summary="Testing.",
        )
    )

    # The /activity search toolbar only renders once the org has ≥1 run — seed
    # one so #mh-activity-search (a wired surface) is reachable.
    conn = wm._db()
    conn.execute(
        "INSERT INTO runs (id, created_at, finished_at, status, profile_id, "
        "meet_name, file_name, our_swims, n_cards, n_queue, n_achievements, error) "
        "VALUES ('run-1', datetime('now'), datetime('now'), 'done', 'test-org', "
        "'Spring Gala', 'spring.pdf', 3, 2, 1, 2, NULL)"
    )
    conn.commit()
    conn.close()
    return app, wm


def _get(app, path: str) -> str:
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["active_profile_id"] = "test-org"
        r = c.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}"
        return r.get_data(as_text=True)


# ── server-side: the JS framework ─────────────────────────────────────────────


class TestBindingShipsInLayout:
    """The cycling-placeholder JS (and its reduced-motion guard) is global."""

    def test_binding_present_on_every_page(self, app_mod):
        app, _ = app_mod
        # Pick a plain page that has no cycle field of its own — the binding must
        # still ship, since it lives in _layout, not the page body.
        html = _get(app, "/settings")
        assert "function bindCyclePlaceholders()" in html
        assert "MH.bindCyclePlaceholders = bindCyclePlaceholders" in html
        assert "[data-mh-cycle-placeholder]" in html  # the selector it binds to

    def test_reduced_motion_guard(self, app_mod):
        app, _ = app_mod
        html = _get(app, "/free-text")
        # The media query is declared and the binding early-returns on it.
        assert "prefers-reduced-motion" in html
        assert "if (prefersReduced) return;" in html

    def test_static_fallback_is_no_js_path(self, app_mod):
        """No-JS users keep a real, informative placeholder on every field."""
        app, _ = app_mod
        html = _get(app, "/free-text")
        assert _static_placeholder(html, "ft-prompt").startswith("e.g.")


# ── server-side: each wired surface ───────────────────────────────────────────


class TestWiredSurfaces:
    """Every surface UI 1.1 names carries a valid cycle list + static fallback."""

    def _check_field(self, html, field_id, must_contain):
        phrases = _parse_cycle(html, field_id)
        assert len(phrases) >= 2, f"#{field_id}: want ≥2 phrases, got {phrases}"
        assert all(phrases), f"#{field_id}: empty phrase slipped through"
        # Every example reads as a guiding "Try: …" hint.
        assert all(p.startswith("Try:") for p in phrases), phrases
        joined = " | ".join(phrases)
        for needle in must_contain:
            assert needle in joined, f"#{field_id} missing {needle!r}"
        # Static fallback survives for no-JS / reduced-motion users.
        assert _static_placeholder(html, field_id).strip()
        return phrases

    def test_free_text_describe_a_moment(self, app_mod):
        """The CREATE / Free-Text input — the headline surface for UI 1.1."""
        app, _ = app_mod
        html = _get(app, "/free-text")
        phrases = self._check_field(html, "ft-prompt", _MANDATED)
        # Apostrophes must survive the escape→attribute→unescape round-trip.
        assert "Try: Maya's first sub-30 50m fly" in phrases

    # NOTE: the /activity search migrated from the UI 1.1 cycle to the UI2.6
    # Vanish input (.mh-vanish overlay placeholder, native placeholder removed),
    # so its rotating-placeholder coverage now lives in
    # tests/test_ui_vanish_search.py rather than here.

    def test_free_text_chat_reply(self, app_mod):
        app, wm = app_mod
        from mediahub.free_text_chat.session import create_session

        chat = create_session()
        html = _get(app, f"/free-text/chat/{chat.chat_id}")
        self._check_field(html, "chat-reply", _MANDATED)

    def test_web_research_query(self, app_mod):
        app, _ = app_mod
        html = _get(app, "/web-research")
        assert "__CYCLE_PH__" not in html  # replacement token fully substituted
        self._check_field(html, "rq", ["Try: 2024 county championship headline results"])

    def test_club_qa_query(self, app_mod):
        app, _ = app_mod
        html = _get(app, "/club-qa")
        assert "__CYCLE_PH__" not in html
        self._check_field(html, "qaq", ["Try: our medal count at the spring gala"])


class TestAttributeIntegrity:
    """The escaped attribute is XSS-safe and parses identically to the JS."""

    def test_no_unescaped_markup_or_quotes(self, app_mod):
        app, _ = app_mod
        for path, fid in (("/free-text", "ft-prompt"), ("/web-research", "rq")):
            html = _get(app, path)
            m = re.search(r'id="%s"[^>]*?data-mh-cycle-placeholder="([^"]*)"' % fid, html)
            assert m
            rawattr = m.group(1)
            # Attribute body must contain no literal double-quote, '<' or '>'
            # (would break the tag / allow injection); only entity-escaped forms.
            assert '"' not in rawattr and "<" not in rawattr and ">" not in rawattr

    def test_helper_round_trips(self, app_mod):
        _, wm = app_mod
        attr = wm._cycle_ph_attr(["A's pick", "B & C", "plain"])
        m = re.match(r'data-mh-cycle-placeholder="(.*)"$', attr)
        assert m, attr
        rawattr = m.group(1)
        assert "&" in rawattr  # the literal & got escaped
        phrases = [p.strip() for p in _html.unescape(rawattr).split("|") if p.strip()]
        assert phrases == ["A's pick", "B & C", "plain"]

    def test_module_constants_well_formed(self, app_mod):
        _, wm = app_mod
        for const in (
            wm._CYCLE_PH_MOMENT,
            wm._CYCLE_PH_RESEARCH,
            wm._CYCLE_PH_ASKDATA,
        ):
            assert len(const) >= 2
            assert all(isinstance(p, str) and p.startswith("Try:") for p in const)
            assert all("|" not in p for p in const)  # the pipe is the delimiter


# ── browser-side: real typewriter behaviour ───────────────────────────────────


def _launch_browser():
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        executable_path=str(_PINNED_CHROMIUM),
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    return pw, browser


@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _chromium_available(), reason="chromium-1194 not at pinned path")
class TestCyclePlaceholderBrowser:
    """The placeholder really animates (and really stops for reduced motion)."""

    def _free_text_html(self, app) -> str:
        return _get(app, "/free-text")

    def test_placeholder_types_and_cycles(self, app_mod):
        app, _ = app_mod
        body = self._free_text_html(app)

        pw, browser = _launch_browser()
        try:
            # Motion explicitly enabled so the binding does NOT early-return.
            ctx = browser.new_context(reduced_motion="no-preference")
            page = ctx.new_page()
            page.set_content(body)
            page.wait_for_load_state("domcontentloaded")
            # Sample the placeholder at 80 ms cadence for 4 s, capturing the
            # typewriter frames into a page-side array (no round-trip lag).
            page.evaluate(
                """() => {
                    window.__caps = [];
                    var el = document.getElementById('ft-prompt');
                    window.__t = setInterval(function(){
                        window.__caps.push(el.getAttribute('placeholder'));
                    }, 80);
                }"""
            )
            page.wait_for_timeout(4000)
            caps = page.evaluate("() => { clearInterval(window.__t); return window.__caps; }")
        finally:
            browser.close()
            pw.stop()

        assert caps, "no placeholder samples captured"
        distinct = set(caps)
        # A typewriter that types "Try: Tom Davies PB 100m free" char-by-char
        # produces many distinct frames; a static placeholder would give 1.
        assert len(distinct) >= 10, f"placeholder barely changed: {sorted(distinct)[:5]}"
        # The caret rode along on at least some frames.
        assert any(_CARET in c for c in caps), "typewriter caret never appeared"
        # At least one frame is a genuine growing prefix of the first phrase.
        phrase0 = "Try: Tom Davies PB 100m free"
        stripped = {c.replace(_CARET, "") for c in caps}
        assert any(len(s) >= 5 and phrase0.startswith(s) for s in stripped), (
            f"no prefix of {phrase0!r} seen; sample={sorted(stripped)[:6]}"
        )

    def test_reduced_motion_freezes_static_placeholder(self, app_mod):
        app, _ = app_mod
        body = self._free_text_html(app)
        static = _static_placeholder(body, "ft-prompt")

        pw, browser = _launch_browser()
        try:
            ctx = browser.new_context(reduced_motion="reduce")
            page = ctx.new_page()
            page.set_content(body)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(1500)  # longer than several type ticks
            ph = page.eval_on_selector("#ft-prompt", "el => el.getAttribute('placeholder')")
        finally:
            browser.close()
            pw.stop()

        assert ph == static, f"reduced-motion placeholder changed: {ph!r}"
        assert _CARET not in ph  # no typewriter caret under reduced motion
