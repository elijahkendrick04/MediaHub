"""tests/test_mobile_action_dock.py — U.13 floating mobile action dock.

U.13 adds a fixed bottom-centre, thumb-reachable capsule (Create / Library /
Approve) shown on the review/approve flow on mobile only, hidden on desktop.
Inspired by Duties (duties.xyz).

These tests pin the contract on three surfaces:

* ``_layout(..., dock=...)`` — the dock renders only when a page opts in, with
  the right links and ARIA/JS hooks, and never otherwise.
* ``/review/<run_id>`` — the real review page carries the dock; the generic
  pages (home) and the review early-return error pages do not.
* ``theme-components.css`` — the dock is desktop-hidden, mobile-shown, stacks
  below modals + above the bottom-tab bar it replaces, highlights the targeted
  card, and is a no-op under prefers-reduced-motion.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

# Deep-review #129: assert the dock's *controls* via stable data-testid hooks
# instead of scraping its ``mh-*`` CSS classes out of the rendered template, so
# the web.py blueprint decomposition can restyle/restructure the markup without
# breaking this file. The CSS-file contract tests below (TestDockCss) keep
# asserting on the stylesheet directly — that is the stylesheet's own contract,
# not template scraping, so it stays.
from tests._semantic import (
    assert_body_flag,
    assert_has_control,
    assert_no_control,
    scope,
)

_CSS = _ROOT / "src" / "mediahub" / "web" / "static" / "theme" / "theme-components.css"

# Browser-test plumbing (mirrors tests/test_activity_count_up.py): the dock CSS
# is inlined into the page (BASE_CSS folds in theme-components.css), so
# page.set_content() reproduces the real responsive + JS behaviour with no live
# server. Skips cleanly where Playwright / the pinned Chromium are absent.
import os  # noqa: E402

_SKIP_BROWSER = os.environ.get("MEDIAHUB_SKIP_BROWSER_TESTS", "").lower() in ("1", "true", "yes")
from tests._pw_chromium import resolve_prebaked_chromium

_PINNED_CHROMIUM = resolve_prebaked_chromium()


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401

        return True
    except ImportError:
        return False


def _chromium_available() -> bool:
    return _PINNED_CHROMIUM.is_file()


def _launch_browser():
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        executable_path=str(_PINNED_CHROMIUM),
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    return pw, browser


def _serve_dock(page, body):
    """Serve ``body`` from a routable http origin and stub the card-workflow POST.

    sub_18-1 makes the optimistic status flip *revert* when its POST fails. A
    ``set_content`` page has an ``about:blank`` origin, so the card's relative
    ``fetch`` resolves to an unfetchable ``about:blank/…`` URL and always
    rejects — which now rolls the approve straight back to ``queue``. Serving the
    page over a fake http origin (via ``page.route`` + ``goto``) gives those
    relative POSTs a routable URL we can fulfil with a 200 ``{"status":
    "approved"}``, simulating the save landing — the dock's real happy path."""

    def _handler(route):
        req = route.request
        if req.resource_type == "document":
            route.fulfill(status=200, content_type="text/html", body=body)
        elif req.method == "POST":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"status": "approved"}),
            )
        else:
            # Inlined CSS means no real subresources; anything else (a self-hosted
            # font probe) can harmlessly fail.
            route.abort()

    page.route("**/*", _handler)
    page.goto("http://dock.test/review")


# ---------------------------------------------------------------------------
# Fixtures / helpers (mirrors tests/test_review_body_content.py)
# ---------------------------------------------------------------------------


def _seed_run(tmp_path, wm, profile_id, run_payload):
    """Write run JSON to disk and insert a matching DB row."""
    run_id = run_payload["run_id"]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(run_payload))
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs "
        "(id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, profile_id, (run_payload.get("meet") or {}).get("name", ""), "test.hy3"),
    )
    conn.commit()
    conn.close()
    return run_id


def _make_run_payload(profile_id, achievements):
    run_id = "run-dock-" + uuid.uuid4().hex[:8]
    return {
        "run_id": run_id,
        "profile_id": profile_id,
        "profile_display": "Test Club",
        "meet": {"name": "DOCK TEST INVITATIONAL"},
        "cards": [
            {
                "card_id": f"card-{a['swim_id']}",
                "swim_id": a["swim_id"],
                "swimmer_name": a["swimmer_name"],
                "event": a["event"],
                "headline": a["headline"],
                "id": f"card-{a['swim_id']}",
            }
            for a in achievements
        ],
        "trust": {"score": 0.85},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "rank": i + 1,
                    "achievement": {
                        "swim_id": a["swim_id"],
                        "swimmer_name": a["swimmer_name"],
                        "event": a["event"],
                        "headline": a["headline"],
                        "type": a.get("type", "pb"),
                        "confidence_label": "high",
                    },
                    "quality_band": "elite",
                    "priority": 0.9,
                    "suggested_post_type": "story",
                    "factors": [],
                }
                for i, a in enumerate(achievements)
            ],
            "n_elite": len(achievements),
            "n_achievements": len(achievements),
            "n_swims_analysed": len(achievements),
        },
        "parse_warnings": [],
        "self_check": {},
        "detector_summary": {},
        "dispatch_log": {},
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="org-test",
            display_name="Test Club",
            brand_voice_summary="Clear and energetic.",
        )
    )

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    with app.test_client() as client:
        r = client.post("/api/organisation/active", data={"profile_id": "org-test"})
        assert r.status_code == 200, r.get_json()
        yield {"client": client, "wm": wm, "tmp_path": tmp_path, "app": app}


# ---------------------------------------------------------------------------
# Unit: _layout(dock=...) contract
# ---------------------------------------------------------------------------


class TestLayoutDockContract:
    def test_no_dock_by_default(self, env):
        wm = env["wm"]
        with env["app"].test_request_context("/"):
            html = wm._layout("Anything", "<p>body</p>")
        assert_no_control(html, "action-dock")
        assert_body_flag(html, "has-dock", present=False)

    def test_dock_renders_when_opted_in(self, env):
        wm = env["wm"]
        with env["app"].test_request_context("/"):
            html = wm._layout("Anything", "<p>body</p>", dock={"builder": "/pack/abc"})
        assert_has_control(html, "action-dock", tag="nav")
        assert_body_flag(html, "has-dock", present=True)

    def test_dock_links_use_url_for(self, env):
        wm = env["wm"]
        with env["app"].test_request_context("/"):
            html = wm._layout("Anything", "<p>body</p>", dock={"builder": "/pack/abc"})
            from flask import url_for

            # Scope to the dock, then assert each link is a real <a> pointing
            # where url_for resolves (one source of truth for the URL).
            dock = scope(html, "action-dock")
            assert_has_control(dock, "dock-create", tag="a", href=url_for("make_page"))
            assert_has_control(dock, "dock-library", tag="a", href=url_for("media_library_page"))
        assert_has_control(html, "action-dock", attrs={"data-builder-url": "/pack/abc"})

    def test_create_library_are_links_approve_is_button(self, env):
        wm = env["wm"]
        with env["app"].test_request_context("/"):
            html = wm._layout("X", "<p>b</p>", dock={"builder": "/pack/abc"})
        dock = scope(html, "action-dock")
        # Create/Library are navigation links; Approve is an action button that
        # still carries the data-mh-dock-approve hook the production dock script
        # binds its click handler to.
        assert_has_control(dock, "dock-create", tag="a", text_contains="Create")
        assert_has_control(dock, "dock-library", tag="a", text_contains="Library")
        assert_has_control(
            dock, "dock-approve", tag="button", role="button", attrs={"data-mh-dock-approve": True}
        )

    def test_label_and_count_hooks_present(self, env):
        wm = env["wm"]
        with env["app"].test_request_context("/"):
            html = wm._layout("X", "<p>b</p>", dock={"builder": "/pack/abc"})
        # The label/count spans keep their data-mh-dock-* hooks (the production
        # script writes the live label + queue count through them); assert both
        # the hook and, for the count, that it stays aria-hidden (the button's
        # aria-label carries the number for screen readers).
        assert_has_control(html, "dock-label", attrs={"data-mh-dock-label": True})
        assert_has_control(
            html, "dock-count", attrs={"data-mh-dock-count": True, "aria-hidden": "true"}
        )

    def test_dock_js_present_and_feature_detected(self, env):
        wm = env["wm"]
        with env["app"].test_request_context("/"):
            html = wm._layout("X", "<p>b</p>", dock={"builder": "/pack/abc"})
        # The sync hook is *defined* here (the always-emitted workflow handler
        # only *calls* it, guarded) + the approve-and-advance wiring reuses the
        # existing per-card workflow buttons + a queue-empty builder fallback.
        assert "window.mhDockSync = sync" in html
        assert 'data-mh-wf="approved"' in html  # dock reuses the per-card button
        assert "window.location.assign(builder)" in html

    def test_dock_js_is_noop_without_dock(self, env):
        """The dock script is only emitted on dock pages — a page without a
        dock must not ship the dock behaviour (the workflow handler's guarded
        ``if (window.mhDockSync)`` call is fine; the *definition* must be gone)."""
        wm = env["wm"]
        with env["app"].test_request_context("/"):
            html = wm._layout("X", "<p>b</p>")
        assert "window.mhDockSync = sync" not in html
        assert "U.13 — Floating mobile action dock" not in html


# ---------------------------------------------------------------------------
# Integration: /review/<run_id> carries the dock; other surfaces do not
# ---------------------------------------------------------------------------


class TestDockOnReview:
    def _seed(self, env, n=3):
        achs = [
            {
                "swim_id": f"s{i}",
                "swimmer_name": f"Swimmer {i}",
                "event": f"{50 * i}m Free",
                "headline": f"PB {i}",
            }
            for i in range(1, n + 1)
        ]
        payload = _make_run_payload("org-test", achs)
        return _seed_run(env["tmp_path"], env["wm"], "org-test", payload)

    def test_dock_present_on_review(self, env):
        run_id = self._seed(env)
        body = env["client"].get(f"/review/{run_id}").get_data(as_text=True)
        assert_has_control(body, "action-dock", tag="nav")
        assert_body_flag(body, "has-dock", present=True)

    def test_builder_url_points_at_content_pack(self, env):
        run_id = self._seed(env)
        body = env["client"].get(f"/review/{run_id}").get_data(as_text=True)
        assert_has_control(body, "action-dock", attrs={"data-builder-url": f"/pack/{run_id}"})

    def test_create_and_library_links_in_dock(self, env):
        run_id = self._seed(env)
        body = env["client"].get(f"/review/{run_id}").get_data(as_text=True)
        dock = scope(body, "action-dock")
        assert_has_control(dock, "dock-create", tag="a", href="/make")
        assert_has_control(dock, "dock-library", tag="a", href="/media-library")
        assert_has_control(dock, "dock-approve", role="button", attrs={"data-mh-dock-approve": True})

    def test_initial_queue_count_rendered_server_side(self, env):
        """The count chip is server-rendered (the dock script keeps it live, but
        the initial value must be right for no-JS / pre-hydration)."""
        run_id = self._seed(env, n=4)  # 4 fresh cards, none decided → all queued
        body = env["client"].get(f"/review/{run_id}").get_data(as_text=True)
        assert_has_control(body, "dock-count", text="4")

    def test_dock_absent_on_home(self, env):
        body = env["client"].get("/").get_data(as_text=True)
        assert_no_control(body, "action-dock")
        assert_body_flag(body, "has-dock", present=False)

    def test_dock_absent_on_failed_run_review(self, env):
        """A terminally-failed run renders the U.2 error state via _layout with
        no dock — the dock belongs to the real review/approve surface only."""
        run_id = "run-dock-fail-" + uuid.uuid4().hex[:8]
        payload = {
            "run_id": run_id,
            "profile_id": "org-test",
            "meet": {},
            "error": "parser could not read the file",
            "parse_warnings": [],
        }
        _seed_run(env["tmp_path"], env["wm"], "org-test", payload)
        body = env["client"].get(f"/review/{run_id}").get_data(as_text=True)
        assert "couldn" in body.lower()  # the failure hero rendered
        assert_no_control(body, "action-dock")
        assert_body_flag(body, "has-dock", present=False)


# ---------------------------------------------------------------------------
# CSS: desktop-hidden / mobile-shown / stacking / highlight / reduced-motion
# ---------------------------------------------------------------------------


class TestDockCss:
    @pytest.fixture(scope="class")
    def css(self):
        return _CSS.read_text(encoding="utf-8")

    def test_dock_rule_exists(self, css):
        assert ".mh-action-dock" in css

    def test_hidden_by_default_shown_on_mobile(self, css):
        # Desktop default: display:none, declared before the mobile media query.
        assert re.search(r"\.mh-action-dock\s*\{\s*display:\s*none", css)
        # And it becomes a flex capsule inside the <=720px breakpoint.
        mobile = css[css.find("@media (max-width: 720px)") :]
        assert ".mh-action-dock" in mobile
        assert re.search(r"\.mh-action-dock\s*\{[^}]*display:\s*flex", mobile, re.DOTALL)

    def test_replaces_bottomnav_when_present(self, css):
        # The contextual dock and the generic bottom-tab bar must never stack.
        assert re.search(r"\.mh-has-dock\s+\.mh-bottomnav\s*\{\s*display:\s*none", css)

    def test_fixed_bottom_centre_capsule(self, css):
        block = _mobile_dock_block(css)
        assert "position: fixed" in block
        assert "left: 50%" in block
        assert "translateX(-50%)" in block
        assert "border-radius: var(--radius-pill)" in block

    def test_thumb_safe_and_notch_aware(self, css):
        # Touch targets >= 44px and the capsule respects the home-bar inset.
        assert "env(safe-area-inset-bottom" in css
        assert re.search(r"min-height:\s*5\dpx", css)  # 52px items

    def test_stacks_below_modal_above_bottomnav(self, css):
        block = _mobile_dock_block(css)
        m = re.search(r"z-index:\s*(\d+)", block)
        assert m, "dock needs an explicit z-index"
        z = int(m.group(1))
        assert 95 <= z < 1000, f"z-index {z} must sit above bottomnav(95), below modals(1000)"

    def test_primary_pill_uses_brand_accent(self, css):
        block = _rule_block(css, ".mh-action-dock .mh-dock-primary {")
        assert "var(--lane)" in block  # lane-yellow signature accent
        assert "var(--lane-ink)" in block

    def test_target_card_highlight_rule(self, css):
        assert ".ach-row.mh-dock-target" in css

    def test_reduced_motion_disables_animation(self, css):
        rm = css[css.rfind("@media (prefers-reduced-motion: reduce)") :]
        # The last reduced-motion block (the one we added) neutralises the dock.
        assert ".mh-action-dock" in css[css.find(".mh-action-dock") :]
        assert re.search(
            r"@media \(prefers-reduced-motion: reduce\)\s*\{[^}]*\.mh-action-dock\s*\{\s*animation:\s*none",
            css,
            re.DOTALL,
        )

    def test_no_google_fonts_cdn_introduced(self, css):
        # Self-hosted-fonts invariant (CLAUDE.md) — the dock added no CDN link.
        assert "fonts.googleapis.com" not in css
        assert "fonts.gstatic.com" not in css


# ---------------------------------------------------------------------------
# Browser: the dock is desktop-hidden / mobile-shown, and "Approve" actually
# approves the highlighted card + advances the queue (the real JS path).
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _chromium_available(), reason="prebaked chromium not found")
class TestDockBrowserBehaviour:
    def _review_body(self, env, n=4):
        achs = [
            {
                "swim_id": f"s{i}",
                "swimmer_name": f"Swimmer {i}",
                "event": f"{50 * i}m Free",
                "headline": f"PB {i}",
            }
            for i in range(1, n + 1)
        ]
        run_id = _seed_run(
            env["tmp_path"], env["wm"], "org-test", _make_run_payload("org-test", achs)
        )
        return env["client"].get(f"/review/{run_id}").get_data(as_text=True)

    _PROBE = """
    (idx) => {
      var dock = document.querySelector('[data-testid=action-dock]');
      var rows = Array.prototype.slice.call(document.querySelectorAll('.ach-row'));
      var tIdx = rows.findIndex(function(r){ return r.classList.contains('mh-dock-target'); });
      var countEl = dock ? dock.querySelector('[data-testid=dock-count]') : null;
      var labelEl = dock ? dock.querySelector('[data-testid=dock-label]') : null;
      // NB: the dock is position:fixed, for which offsetParent is always null —
      // use computed display to tell desktop (none) from mobile (flex).
      return {
        dockVisible: !!(dock && getComputedStyle(dock).display !== 'none'),
        count: countEl ? countEl.textContent.trim() : null,
        label: labelEl ? labelEl.textContent.trim() : null,
        isDone: dock ? dock.classList.contains('is-done') : null,
        targetIdx: tIdx,
        targetStatus: tIdx >= 0 ? rows[tIdx].getAttribute('data-status') : null,
        probedStatus: (idx != null && rows[idx]) ? rows[idx].getAttribute('data-status') : null,
      };
    }
    """

    def test_dock_hidden_on_desktop_viewport(self, env):
        body = self._review_body(env)
        pw, browser = _launch_browser()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.set_content(body)
            page.wait_for_timeout(150)
            state = page.evaluate(self._PROBE, None)
        finally:
            browser.close()
            pw.stop()
        assert state["dockVisible"] is False, "dock must be hidden on desktop"

    def test_dock_shown_and_targets_a_card_on_mobile(self, env):
        body = self._review_body(env, n=4)
        pw, browser = _launch_browser()
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.set_content(body)
            page.wait_for_timeout(200)
            state = page.evaluate(self._PROBE, None)
        finally:
            browser.close()
            pw.stop()
        assert state["dockVisible"] is True, "dock must show on a mobile viewport"
        assert state["count"] == "4", f"initial queue count should be 4, got {state['count']}"
        assert state["targetIdx"] >= 0, "a queued card must be highlighted on load"
        assert state["targetStatus"] == "queue"
        assert state["isDone"] is False

    def test_approve_pill_approves_focused_card_and_advances(self, env):
        body = self._review_body(env, n=4)
        pw, browser = _launch_browser()
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            _serve_dock(page, body)
            page.wait_for_timeout(200)
            before = page.evaluate(self._PROBE, None)
            # Drive the real click handler (the per-card workflow button it
            # delegates to does an optimistic DOM update before its fetch, so
            # the about:blank network failure doesn't affect the assertions).
            page.evaluate("document.querySelector('[data-testid=dock-approve]').click()")
            page.wait_for_timeout(250)
            after = page.evaluate(self._PROBE, before["targetIdx"])
        finally:
            browser.close()
            pw.stop()
        assert before["targetStatus"] == "queue"
        # The card that was highlighted is now approved …
        assert after["probedStatus"] == "approved", "tapped card should be approved"
        # … the queue count dropped …
        assert after["count"] == "3", f"count should drop to 3, got {after['count']}"
        # … and the highlight advanced to a different, still-queued card.
        assert after["targetIdx"] != before["targetIdx"], "target should advance"
        assert after["targetStatus"] == "queue"

    def test_clearing_the_queue_switches_to_open_builder(self, env):
        body = self._review_body(env, n=3)
        pw, browser = _launch_browser()
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            _serve_dock(page, body)
            page.wait_for_timeout(200)
            for _ in range(3):  # approve all three
                page.evaluate("document.querySelector('[data-testid=dock-approve]').click()")
                page.wait_for_timeout(120)
            state = page.evaluate(self._PROBE, None)
        finally:
            browser.close()
            pw.stop()
        assert state["isDone"] is True, "dock should enter the done state at queue=0"
        assert state["label"] == "Open builder"
        assert state["targetIdx"] == -1, "no card should be highlighted when done"


def _rule_block(css: str, selector: str) -> str:
    """Return the declaration block for the first occurrence of ``selector``."""
    i = css.find(selector)
    assert i >= 0, f"selector not found: {selector}"
    start = css.find("{", i)
    end = css.find("}", start)
    return css[start : end + 1]


def _mobile_dock_block(css: str) -> str:
    """The ``.mh-action-dock`` capsule rule *inside* the dock's own <=720px
    media query. Anchored on the U.13 section header so it never collides with
    the bottom-tab bar's own ``@media (max-width: 720px)`` block above it, nor
    with the desktop ``.mh-action-dock { display: none }`` default."""
    section = css[css.find("U.13 — FLOATING MOBILE ACTION DOCK") :]
    assert section, "U.13 dock CSS section not found"
    mq = section[section.find("@media (max-width: 720px)") :]
    return _rule_block(mq, ".mh-action-dock {")
