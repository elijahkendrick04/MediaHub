"""UI 1.17 — Content-cadence heatmap.

Pins the GitHub-contribution-graph-style year grid on the Activity page
(server-rendered inline SVG from run history; no JS library):

  * pure transforms — ``level_for`` thresholds, ``window_start`` Monday-anchoring,
    ``build_grid`` shape / counting / stats / streaks / month labels / future days
  * SVG rendering — well-formed XML, geometry, one square per in-range day, a
    per-day ``<title>`` tooltip, weekday + month axis labels, no animation
  * panel composition — metrics, accessible text alternative, legend, both the
    active and the empty-history variants
  * CSS — brace balance, the lane-yellow heat ramp, brand rules (no medal-gold,
    no Google-Fonts CDN), and the no-animation rule
  * the ``_cadence_activity_counts`` DB reader — per-day generated buckets,
    multi-tenant scoping, the one-year window
  * end-to-end on /activity — the panel renders for an org with runs, carries the
    injected CSS before the guardrails layer, stays scoped to the pinned org, and
    is absent for a club with no runs
"""
from __future__ import annotations

import importlib
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.web import cadence_heatmap as ch


# =========================================================================== #
# level_for
# =========================================================================== #
class TestLevelFor:
    def test_zero_and_negative_are_level_zero(self):
        assert ch.level_for(0) == 0
        assert ch.level_for(-5) == 0

    @pytest.mark.parametrize(
        "count,expected",
        [(1, 1), (2, 2), (3, 2), (4, 3), (5, 3), (6, 3), (7, 4), (50, 4)],
    )
    def test_default_threshold_buckets(self, count, expected):
        assert ch.level_for(count) == expected

    def test_levels_are_monotonic_non_decreasing(self):
        prev = 0
        for n in range(0, 40):
            lvl = ch.level_for(n)
            assert lvl >= prev
            assert 0 <= lvl <= 4
            prev = lvl

    def test_custom_thresholds(self):
        thresholds = (1, 5, 10, 20)
        assert ch.level_for(4, thresholds) == 1
        assert ch.level_for(5, thresholds) == 2
        assert ch.level_for(19, thresholds) == 3
        assert ch.level_for(20, thresholds) == 4


# =========================================================================== #
# window_start
# =========================================================================== #
class TestWindowStart:
    def test_anchors_on_monday(self):
        # Whatever day `end` falls on, the window starts on a Monday.
        for offset in range(0, 14):
            end = date(2026, 6, 1) + timedelta(days=offset)
            start = ch.window_start(end)
            assert start.weekday() == 0

    def test_spans_a_full_year_of_columns(self):
        end = date(2026, 6, 14)  # Sunday
        start = ch.window_start(end)
        # 53 columns => 52 whole weeks back from this week's Monday.
        assert (end - start).days == 52 * 7 + end.weekday()

    def test_respects_custom_weeks_and_week_start(self):
        end = date(2026, 6, 10)  # Wednesday
        start = ch.window_start(end, weeks=13, week_start=6)  # Sunday-start
        assert start.weekday() == 6  # Sunday
        assert (end - start).days == 12 * 7 + ((end.weekday() - 6) % 7)


# =========================================================================== #
# build_grid
# =========================================================================== #
class TestBuildGrid:
    def test_shape_is_weeks_by_seven(self):
        grid = ch.build_grid({}, end=date(2026, 6, 14))
        assert len(grid.weeks) == ch.DEFAULT_WEEKS
        assert all(len(col) == 7 for col in grid.weeks)

    def test_custom_week_count(self):
        grid = ch.build_grid({}, end=date(2026, 6, 14), weeks=13)
        assert len(grid.weeks) == 13

    def test_last_in_range_day_is_end(self):
        end = date(2026, 6, 10)  # Wednesday
        grid = ch.build_grid({}, end=end)
        in_range = [c for col in grid.weeks for c in col if not c.future]
        assert in_range[-1].day == end
        # Days are chronological and contiguous.
        for earlier, later in zip(in_range, in_range[1:]):
            assert later.day - earlier.day == timedelta(days=1)

    def test_future_days_flagged_and_empty(self):
        end = date(2026, 6, 10)  # Wednesday -> Thu..Sun are future
        grid = ch.build_grid({(end + timedelta(days=1)).isoformat(): 9}, end=end)
        future = [c for col in grid.weeks for c in col if c.future]
        assert len(future) == 4
        for cell in future:
            assert cell.day > end
            assert cell.count == 0 and cell.level == 0

    def test_counts_single_generated_lane(self):
        end = date(2026, 6, 14)
        day = (end - timedelta(days=2)).isoformat()
        grid = ch.build_grid({day: 5}, end=end)
        cell = next(c for col in grid.weeks for c in col if c.day.isoformat() == day)
        assert cell.count == 5
        assert cell.level == ch.level_for(5)

    def test_accepts_date_object_and_string_keys(self):
        end = date(2026, 6, 14)
        d = end - timedelta(days=3)
        e = end - timedelta(days=4)
        grid = ch.build_grid({d: 4, e.isoformat(): 1}, end=end)
        assert grid.total == 5
        assert grid.active_days == 2

    def test_ignores_garbage_and_nonpositive_counts(self):
        end = date(2026, 6, 14)
        d = (end - timedelta(days=1)).isoformat()
        grid = ch.build_grid(
            {d: "nope", (end - timedelta(days=2)).isoformat(): 0,
             (end - timedelta(days=3)).isoformat(): -2},
            end=end,
        )
        assert grid.total == 0
        assert grid.active_days == 0

    def test_data_outside_the_window_is_excluded(self):
        end = date(2026, 6, 14)
        grid = ch.build_grid(
            {(end - timedelta(days=400)).isoformat(): 7, end.isoformat(): 2},
            end=end,
        )
        assert grid.total == 2  # the 400-day-old run is out of range

    def test_summary_statistics(self):
        end = date(2026, 6, 14)  # Sunday
        gen = {}
        for i in range(3):  # today, -1, -2 => current streak 3
            gen[(end - timedelta(days=i)).isoformat()] = 1
        for i in range(5, 10):  # 5 consecutive earlier days, count 2
            gen[(end - timedelta(days=i)).isoformat()] = 2
        grid = ch.build_grid(gen, end=end)
        assert grid.total == 3 * 1 + 5 * 2
        assert grid.active_days == 8
        assert grid.current_streak == 3
        assert grid.longest_streak == 5
        assert grid.busiest_count == 2
        assert grid.max_count == 2

    def test_current_streak_zero_when_today_idle(self):
        end = date(2026, 6, 14)
        grid = ch.build_grid({(end - timedelta(days=2)).isoformat(): 4}, end=end)
        assert grid.current_streak == 0
        assert grid.longest_streak == 1

    def test_month_labels_cover_the_year_with_valid_names(self):
        grid = ch.build_grid({}, end=date(2026, 6, 14))
        assert 11 <= len(grid.month_labels) <= 13
        cols = [col for col, _ in grid.month_labels]
        assert cols == sorted(cols)  # strictly left-to-right
        assert all(0 <= col < ch.DEFAULT_WEEKS for col in cols)
        assert all(name in ch._MONTH_ABBR for _, name in grid.month_labels)


# =========================================================================== #
# render_svg
# =========================================================================== #
class TestRenderSvg:
    @pytest.fixture
    def grid(self):
        end = date(2026, 6, 14)
        gen = {(end - timedelta(days=i)).isoformat(): (i % 8) for i in range(0, 60)}
        gen[end.isoformat()] += 3
        gen[(end - timedelta(days=1)).isoformat()] += 1
        return ch.build_grid(gen, end=end)

    def test_is_well_formed_xml(self, grid):
        ET.fromstring(ch.render_svg(grid))

    def test_root_is_svg_with_viewbox_and_role(self, grid):
        svg = ch.render_svg(grid)
        assert svg.startswith("<svg")
        assert svg.rstrip().endswith("</svg>")
        root = ET.fromstring(svg)
        assert root.attrib.get("viewBox")
        assert root.attrib.get("role") == "img"
        assert root.attrib.get("aria-label")

    def test_geometry_matches_cell_maths(self):
        grid = ch.build_grid({}, end=date(2026, 6, 14))
        cell, gap, pad_left, pad_top, pad_right, pad_bottom = 11, 3, 30, 18, 6, 6
        svg = ch.render_svg(grid)
        n = len(grid.weeks)
        width = pad_left + n * cell + (n - 1) * gap + pad_right
        height = pad_top + 7 * cell + 6 * gap + pad_bottom
        root = ET.fromstring(svg)
        assert root.attrib["viewBox"] == f"0 0 {width} {height}"
        assert root.attrib["width"] == str(width)
        assert root.attrib["height"] == str(height)

    def test_one_rect_per_in_range_day(self):
        end = date(2026, 6, 10)  # Wednesday -> 4 future days
        grid = ch.build_grid({}, end=end)
        svg = ch.render_svg(grid)
        assert svg.count("<rect") == ch.DEFAULT_WEEKS * 7 - 4

    def test_every_cell_carries_a_title_tooltip(self, grid):
        svg = ch.render_svg(grid)
        # One <title> per drawn day (no-JS native tooltip).
        assert svg.count("<title>") == svg.count("<rect")

    def test_titles_describe_activity(self):
        end = date(2026, 6, 14)
        d = (end - timedelta(days=2))
        svg = ch.render_svg(ch.build_grid({d: 3}, end=end))
        assert "3 generated" in svg
        assert "posted" not in svg  # MediaHub never posts — no phantom lane
        assert "no activity" in svg  # the many empty days

    def test_all_heat_levels_present_with_rich_data(self, grid):
        for lvl in range(5):
            assert f"mh-cad-l{lvl}" in ch.render_svg(grid)

    def test_weekday_and_month_axis_labels(self, grid):
        svg = ch.render_svg(grid)
        for day_label in ("Mon", "Wed", "Fri"):
            assert f">{day_label}</text>" in svg
        assert 'class="mh-cad-dow"' in svg
        assert 'class="mh-cad-mon"' in svg

    def test_no_animation_elements(self, grid):
        svg = ch.render_svg(grid)
        # No over-animation: the heatmap is static (nothing to freeze under
        # prefers-reduced-motion).
        assert "<animate" not in svg
        assert "animateTransform" not in svg
        assert "@keyframes" not in svg

    def test_is_deterministic(self, grid):
        assert ch.render_svg(grid) == ch.render_svg(grid)


# =========================================================================== #
# Panel composition
# =========================================================================== #
class TestCadencePanel:
    def test_panel_is_well_formed_and_structured(self):
        end = date(2026, 6, 14)
        gen = {(end - timedelta(days=i)).isoformat(): (i % 5) for i in range(30)}
        html = ch.cadence_panel_html(gen, {end.isoformat(): 2}, end=end)
        # A single <section> root that parses cleanly catches any markup slip.
        root = ET.fromstring(html)
        assert root.tag == "section"
        assert "mh-cad-panel" in root.attrib.get("class", "")
        assert "mh-reveal" in root.attrib.get("class", "")
        assert "mh-cad-svg" in html
        assert "Content cadence" in html

    def test_panel_has_accessible_text_alternative(self):
        end = date(2026, 6, 14)
        html = ch.cadence_panel_html({end.isoformat(): 5}, end=end)
        assert 'class="mh-visually-hidden"' in html
        summary = html.split('class="mh-visually-hidden">', 1)[1].split("</p>", 1)[0]
        assert "generated" in summary
        # MediaHub never posts: screen readers must not hear a permanently
        # empty "0 posted" lane.
        assert "posted" not in summary
        assert "active" in summary and "streak" in summary

    def test_aria_summary_never_mentions_posting(self):
        end = date(2026, 6, 14)
        grid = ch.build_grid({end.isoformat(): 2}, end=end)
        assert "posted" not in ch.aria_summary(grid)

    def test_transitional_posted_arg_merges_into_the_single_lane(self):
        # The web.py caller still passes its (always-empty) posted dict
        # positionally; any counts are folded into the one generated lane.
        end = date(2026, 6, 14)
        merged = ch.cadence_panel_html({end.isoformat(): 2}, {end.isoformat(): 3}, end=end)
        single = ch.cadence_panel_html({end.isoformat(): 5}, end=end)
        assert merged == single

    def test_panel_shows_metrics_and_legend(self):
        end = date(2026, 6, 14)
        gen = {(end - timedelta(days=i)).isoformat(): 1 for i in range(4)}
        html = ch.cadence_panel_html(gen, end=end)
        assert "active day" in html
        assert "day streak" in html
        # GitHub-style Less .. More legend, reusing the cell classes.
        assert "Less" in html and "More" in html
        assert "mh-cad-legend-svg" in html

    def test_empty_history_variant(self):
        end = date(2026, 6, 14)
        html = ch.cadence_panel_html({}, {}, end=end)
        ET.fromstring(html)  # still well-formed
        assert "<b>0</b>" in html  # zeroed metrics
        assert "this grid" in html.lower()  # the encouraging empty foot-note

    def test_singular_plural_wording(self):
        end = date(2026, 6, 14)
        html = ch.cadence_panel_html({end.isoformat(): 1}, end=end)
        assert "<b>1</b> piece<" in html
        assert "<b>1</b> active day<" in html

    def test_is_deterministic(self):
        end = date(2026, 6, 14)
        gen = {(end - timedelta(days=i)).isoformat(): i for i in range(20)}
        assert ch.cadence_panel_html(gen, end=end) == ch.cadence_panel_html(gen, end=end)


# =========================================================================== #
# CSS
# =========================================================================== #
class TestCadenceCss:
    def test_brace_balance(self):
        css = ch.CADENCE_HEATMAP_CSS
        assert css.count("{") == css.count("}")

    def test_defines_all_five_heat_levels(self):
        css = ch.CADENCE_HEATMAP_CSS
        for lvl in range(5):
            assert f".mh-cad-l{lvl}" in css

    def test_stays_on_brand(self):
        css = ch.CADENCE_HEATMAP_CSS
        # Lane-yellow is the activity/heat accent.
        assert "var(--lane)" in css
        # Medal-gold is reserved for athlete achievements — never chrome.
        assert "var(--medal" not in css
        assert "var(--gold" not in css
        # Self-hosted fonts only — no Google Fonts CDN may sneak in.
        assert "googleapis" not in css
        assert "gstatic" not in css

    def test_no_animation_in_css(self):
        css = ch.CADENCE_HEATMAP_CSS
        assert "@keyframes" not in css
        assert "animation:" not in css


# =========================================================================== #
# DB reader + end-to-end on /activity
# =========================================================================== #
@pytest.fixture
def gated_client(tmp_path, monkeypatch):
    """Fresh DATA_DIR with the org gate enforced; web module reloaded so the
    module-level DB_PATH / RUNS_DIR re-resolve against tmp_path."""
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

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(
        profile_id="club-a", display_name="Club A",
        brand_voice_summary="A friendly club.",
    ))
    save_profile(ClubProfile(
        profile_id="club-b", display_name="Club B",
        brand_voice_summary="A serious club.",
    ))

    with app.test_client() as c:
        yield c, wm


def _insert_run(wm, run_id, profile_id, created_at, status="done"):
    conn = wm._db()
    conn.execute(
        "INSERT INTO runs (id, created_at, finished_at, status, profile_id, "
        "meet_name, file_name, our_swims, n_cards, n_queue, error) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0, 0, NULL)",
        (run_id, created_at, created_at, status, profile_id,
         f"Meet {run_id}", f"{run_id}.pdf"),
    )
    conn.commit()
    conn.close()


def _pin(client, profile_id):
    resp = client.post("/api/organisation/active", data={"profile_id": profile_id})
    assert resp.status_code == 200, resp.get_data(as_text=True)


class TestCadenceActivityCounts:
    def test_buckets_runs_by_day_and_scopes_to_profile(self, gated_client):
        _, wm = gated_client
        today = datetime.now(timezone.utc).date()
        d0 = today.isoformat()
        d1 = (today - timedelta(days=1)).isoformat()
        _insert_run(wm, "a1", "club-a", f"{d0}T09:00:00+00:00")
        _insert_run(wm, "a2", "club-a", f"{d0}T15:00:00+00:00")
        _insert_run(wm, "a3", "club-a", f"{d1}T11:00:00+00:00")
        _insert_run(wm, "b1", "club-b", f"{d0}T10:00:00+00:00")

        gen, post = wm._cadence_activity_counts("club-a", today)
        assert gen == {d0: 2, d1: 1}  # club-b's run does not leak in
        assert post == {}

    def test_excludes_runs_older_than_the_window(self, gated_client):
        _, wm = gated_client
        today = datetime.now(timezone.utc).date()
        old = (ch.window_start(today) - timedelta(days=3)).isoformat()
        _insert_run(wm, "old", "club-a", f"{old}T09:00:00+00:00")
        _insert_run(wm, "new", "club-a", f"{today.isoformat()}T09:00:00+00:00")
        gen, _ = wm._cadence_activity_counts("club-a", today)
        assert today.isoformat() in gen
        assert old[:10] not in gen

    def test_empty_profile_id_is_safe(self, gated_client):
        _, wm = gated_client
        assert wm._cadence_activity_counts("", datetime.now(timezone.utc).date()) == ({}, {})


class TestActivityPageRendersHeatmap:
    def test_panel_renders_for_org_with_runs(self, gated_client):
        c, wm = gated_client
        today = datetime.now(timezone.utc).date()
        for i in range(6):
            _insert_run(
                wm, f"a{i}", "club-a",
                f"{(today - timedelta(days=i)).isoformat()}T09:00:00+00:00",
            )
        _pin(c, "club-a")
        body = c.get("/activity").get_data(as_text=True)
        # The aria-label string only appears on the rendered <section>, never
        # in the always-injected <style> block.
        assert "Content cadence over the last year" in body
        assert "<svg class=\"mh-cad-svg\"" in body
        # The combined cell class only appears on a real drawn square, proving
        # at least one lit day made it into the grid (not just the CSS rule).
        assert 'class="mh-cad-cell mh-cad-l1"' in body

    def test_heatmap_css_injected_before_guardrails(self, gated_client):
        c, wm = gated_client
        today = datetime.now(timezone.utc).date()
        _insert_run(wm, "a0", "club-a", f"{today.isoformat()}T09:00:00+00:00")
        _pin(c, "club-a")
        body = c.get("/activity").get_data(as_text=True)
        assert ".mh-cad-panel" in body
        marker = "RESPONSIVE GUARDRAILS (2026)"
        assert marker in body
        assert body.index(".mh-cad-panel") < body.index(marker)

    def test_heatmap_scoped_to_pinned_org(self, gated_client):
        c, wm = gated_client
        today = datetime.now(timezone.utc).date()
        _insert_run(wm, "b0", "club-b", f"{today.isoformat()}T09:00:00+00:00")
        # Club A has no runs at all -> empty hero, no heatmap panel.
        _pin(c, "club-a")
        body = c.get("/activity").get_data(as_text=True)
        assert "No runs yet for this organisation" in body
        assert "Content cadence over the last year" not in body

    def test_panel_absent_when_no_runs(self, gated_client):
        c, _ = gated_client
        _pin(c, "club-a")
        body = c.get("/activity").get_data(as_text=True)
        assert "Content cadence over the last year" not in body
