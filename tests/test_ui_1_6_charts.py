"""UI 1.6 — Animated results/data charts (Mixpanel-inspired).

MediaHub's first-party, build-on-scroll charts: a vertical bar/podium chart
and a cohort/area trend chart, drawn as pure HTML/SVG by ``web/charts.py``
(no charting SDK, no canvas, no external fetch). They surface on two places —
the landing "sample-outputs" section (honest sample data) and the in-app
Review page (real per-run data) — and animate as they scroll into view via the
shared ``bindReveals`` observer, degrading to a fully-drawn chart with no JS or
under ``prefers-reduced-motion``.

These tests pin:
  * the renderer's structure, scaling, value formatting, tone allow-list and
    XSS-safety, plus robust empty/edge-case handling;
  * the area chart's SVG geometry, gradient-id uniqueness, dot policy and
    self-containment (no remote refs);
  * the CSS contract: the animation is ``.mh-js``-gated, reduced-motion snaps
    to the final state, custom properties drive the geometry, nothing is loaded
    from a CDN;
  * the JS contract: charts ride the existing reveal observer;
  * the landing page renders both chart types in a clearly-sampled section, in
    the right place, with no charting CDN sneaking in;
  * the Review page renders real run data only, with graceful omission when
    there is nothing to chart, and a DOM-safe gradient id from the run id.
"""
from __future__ import annotations

import json
import re
import xml.dom.minidom as minidom
from pathlib import Path

import pytest

from mediahub.web import charts as ch
from mediahub.web import web as webmod

_ROOT = Path(__file__).resolve().parents[1]
_CSS_PATH = _ROOT / "src" / "mediahub" / "web" / "static" / "theme" / "theme-components.css"
_CSS = _CSS_PATH.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(webmod, "RUNS_DIR", runs, raising=False)
    app = webmod.app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _write_run(run_id: str, payload: dict) -> None:
    (webmod.RUNS_DIR / f"{run_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def _ranked(rank: int, priority: float, band: str):
    return {
        "rank": rank,
        "priority": priority,
        "quality_band": band,
        "suggested_post_type": "main_feed",
        "factors": [],
        "achievement": {
            "swim_id": f"s{rank}:100FR:final",
            "swimmer_name": f"Swimmer {rank}",
            "event": "100m Freestyle",
            "time": "58.21",
            "type": "pb_confirmed",
            "pb": True,
            "confidence_label": "high",
            "confidence": 0.85,
            "headline": "PB",
            "evidence": [],
        },
    }


def _run_payload(*, n_elite=2, n_strong=3, n_story=3, n_ranked=8, run_id="rc"):
    ranked = [
        _ranked(i + 1, round(0.95 - 0.06 * i, 3), "elite" if i < 2 else ("strong" if i < 5 else "story"))
        for i in range(n_ranked)
    ]
    return {
        "run_id": run_id,
        "meet": {
            "name": "Spring Open 2026",
            "start_date": "2026-03-01",
            "end_date": "2026-03-02",
            "course": "SCM",
            "venue": "City Pool",
        },
        "cards": [],
        "trust": {"cards": []},
        "parse_warnings": [],
        "recognition_report": {
            "ranked_achievements": ranked,
            "n_achievements": n_ranked,
            "n_swims_analysed": 30,
            "n_elite": n_elite,
            "n_strong": n_strong,
            "n_story": n_story,
            "swim_traces": [],
            "meet_context": {},
        },
    }


def _line_points(area_html: str):
    """Parse the (x, y) points out of an area chart's line path."""
    m = re.search(r'class="mh-chart-area-line" d="M([^"]+)"', area_html)
    assert m, "no area line path found"
    body = m.group(1)
    pts = []
    for chunk in body.split("L"):
        chunk = chunk.strip()
        if not chunk:
            continue
        x, y = chunk.split(",")
        pts.append((float(x), float(y)))
    return pts


# =========================================================================== #
# 1) Bar / podium renderer
# =========================================================================== #
class TestBarChart:
    def test_basic_structure(self):
        html = ch.bar_chart(
            [{"label": "Free", "value": 8, "tone": "lane"}],
            caption="Medals",
            chart_id="t",
        )
        assert '<figure class="mh-chart mh-chart--bars"' in html
        assert "data-mh-animate" in html
        assert 'role="group"' in html and 'aria-label="' in html
        assert "mh-chart-bar-fill" in html
        assert "</figure>" in html

    def test_heights_scaled_to_tallest(self):
        html = ch.bar_chart(
            [
                {"label": "A", "value": 10},
                {"label": "B", "value": 5},
                {"label": "C", "value": 0},
            ],
            chart_id="t",
        )
        # Tallest bar fills the plot; half-value bar is 50%; zero is 0%.
        assert "--mh-bar:100%" in html
        assert "--mh-bar:50%" in html
        assert "--mh-bar:0%" in html

    def test_whole_numbers_count_up(self):
        html = ch.bar_chart([{"label": "A", "value": 12}], chart_id="t")
        assert 'data-mh-count="12"' in html

    def test_custom_text_is_static_not_counted(self):
        html = ch.bar_chart(
            [{"label": "Gold", "value": 9, "text": "58.21s"}], chart_id="t"
        )
        assert "58.21s" in html
        # A pre-formatted readout is shown verbatim — never count-animated.
        assert "data-mh-count" not in html

    def test_fractions_shown_static(self):
        html = ch.bar_chart([{"label": "A", "value": 0.9}], chart_id="t")
        assert "0.9" in html
        assert "data-mh-count" not in html

    def test_thousands_separator(self):
        html = ch.bar_chart([{"label": "A", "value": 1234}], chart_id="t")
        assert "1,234" in html
        assert 'data-mh-count="1234"' in html  # the raw target stays machine-clean

    def test_tone_allowlist_blocks_injection(self):
        html = ch.bar_chart(
            [{"label": "A", "value": 1, "tone": 'lane" onload="x'}], chart_id="t"
        )
        assert "onload" not in html
        assert "tone-neutral" in html

    def test_known_tones_pass_through(self):
        for tone in ("gold", "silver", "bronze", "lane", "info", "good", "bad"):
            html = ch.bar_chart([{"label": "A", "value": 1, "tone": tone}], chart_id="t")
            assert f"tone-{tone}" in html

    def test_label_is_escaped(self):
        html = ch.bar_chart(
            [{"label": "<script>alert(1)</script>", "value": 1}], chart_id="t"
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_caption_is_escaped(self):
        html = ch.bar_chart(
            [{"label": "A", "value": 1}], caption="<b>x</b>", chart_id="t"
        )
        assert "<b>x</b>" not in html
        assert "&lt;b&gt;" in html

    def test_empty_is_safe(self):
        html = ch.bar_chart([], caption="Nothing")
        assert "is-empty" in html
        assert "<figure" in html and "</figure>" in html

    def test_all_zero_no_division_error(self):
        html = ch.bar_chart([{"label": "A", "value": 0}, {"label": "B", "value": 0}], chart_id="t")
        assert "--mh-bar:0%" in html

    def test_negative_clamped(self):
        html = ch.bar_chart([{"label": "A", "value": 10}, {"label": "B", "value": -5}], chart_id="t")
        # Negative cannot produce a negative height.
        assert "--mh-bar:-" not in html

    def test_dataclass_input_accepted(self):
        html = ch.bar_chart([ch.BarDatum(label="A", value=3, tone="gold")], chart_id="t")
        assert "tone-gold" in html

    def test_xaxis_ticks_one_per_label(self):
        html = ch.bar_chart(
            [{"label": "Free", "value": 1}, {"label": "Back", "value": 2}], chart_id="t"
        )
        assert html.count("mh-chart-xtick") == 2

    def test_animate_false_drops_attr_and_countup(self):
        html = ch.bar_chart([{"label": "A", "value": 5}], animate=False, chart_id="t")
        assert "data-mh-animate" not in html
        assert "data-mh-count" not in html

    def test_figure_id_emitted_when_given(self):
        html = ch.bar_chart([{"label": "A", "value": 1}], chart_id="run-bands-x")
        assert 'id="mh-chart-run-bands-x"' in html

    def test_no_figure_id_when_absent(self):
        html = ch.bar_chart([{"label": "A", "value": 1}])
        assert "id=" not in html


# =========================================================================== #
# 2) Cohort / area renderer
# =========================================================================== #
class TestAreaChart:
    def _area(self, vals, **kw):
        pts = [{"label": "", "value": v} for v in vals]
        return ch.area_chart(pts, chart_id=kw.pop("chart_id", "t"), **kw)

    def test_basic_structure(self):
        html = self._area([1, 2, 3])
        assert '<figure class="mh-chart mh-chart--area' in html
        assert "data-mh-animate" in html
        assert 'role="group"' in html
        assert 'class="mh-chart-area-line"' in html
        assert 'pathLength="1"' in html  # normalises the draw-on-scroll length

    def test_needs_two_points(self):
        assert "is-empty" in ch.area_chart([{"label": "x", "value": 1}], chart_id="t")
        assert "is-empty" in ch.area_chart([], chart_id="t")

    def test_svg_is_well_formed(self):
        html = self._area([2, 5, 4, 9])
        svg = re.search(r"<svg.*</svg>", html, re.S).group(0)
        minidom.parseString(svg)  # raises on malformed XML

    def test_svg_self_contained_no_remote(self):
        html = self._area([2, 5, 4, 9]).lower()
        assert "googleapis" not in html and "gstatic" not in html
        assert 'href="http' not in html and "href='http" not in html
        assert "url(http" not in html and "@import" not in html
        assert "<image" not in html and "data:image" not in html

    def test_peak_value_maps_to_highest_point(self):
        # value 9 is the max → its point should have the smallest y (top of plot).
        pts = _line_points(self._area([2, 5, 4, 9]))
        ys = [y for _x, y in pts]
        peak_idx = 3
        assert pts[peak_idx][1] == min(ys), pts
        # x advances left→right, first point at the left padding.
        xs = [x for x, _y in pts]
        assert xs == sorted(xs)
        assert xs[0] == pytest.approx(8.0, abs=0.01)

    def test_area_fill_closes_to_baseline(self):
        html = self._area([2, 5, 4, 9])
        m = re.search(r'class="mh-chart-area-fill" d="([^"]+)"', html)
        assert m and m.group(1).strip().endswith("Z")  # closed path
        # baseline = viewBox height (120) - bottom pad (12) = 108
        assert "108.00" in m.group(1)

    def test_gradient_id_from_chart_id(self):
        html = self._area([1, 2], chart_id="abc123")
        assert "mh-area-grad-abc123" in html
        assert 'fill="url(#mh-area-grad-abc123)"' in html

    def test_gradient_id_sanitised(self):
        html = self._area([1, 2], chart_id='x"><script>')
        assert "<script>" not in html
        # only the alnum survivors form the id
        assert "mh-area-grad-x" in html

    def test_gradient_id_unique_when_unspecified(self):
        a = ch.area_chart([{"label": "", "value": 1}, {"label": "", "value": 2}])
        b = ch.area_chart([{"label": "", "value": 1}, {"label": "", "value": 2}])
        id_a = re.search(r"mh-area-grad-(\w+)", a).group(1)
        id_b = re.search(r"mh-area-grad-(\w+)", b).group(1)
        assert id_a != id_b

    def test_dots_shown_for_small_series(self):
        html = self._area([1, 2, 3, 4])
        assert html.count("mh-chart-area-dot") == 4

    def test_dots_hidden_for_large_series(self):
        html = self._area(list(range(1, 20)))  # 19 points > 12
        assert "mh-chart-area-dot" not in html

    def test_xaxis_present_with_labels(self):
        html = ch.area_chart(
            [{"label": "Sep", "value": 1}, {"label": "Oct", "value": 2}], chart_id="t"
        )
        assert "mh-chart-xaxis" in html
        assert "Sep" in html and "Oct" in html

    def test_xaxis_omitted_when_labels_blank(self):
        html = self._area([1, 2, 3])
        assert "mh-chart-xaxis" not in html

    def test_tone_sets_accent_class(self):
        assert "tone-info" in ch.area_chart(
            [{"label": "", "value": 1}, {"label": "", "value": 2}], tone="info", chart_id="t"
        )
        # unknown tone → neutral, never an injected class
        html = ch.area_chart(
            [{"label": "", "value": 1}, {"label": "", "value": 2}],
            tone='x" onload="y',
            chart_id="t",
        )
        assert "onload" not in html and "tone-neutral" in html

    def test_label_escaped(self):
        html = ch.area_chart(
            [{"label": "<x>", "value": 1}, {"label": "y", "value": 2}], chart_id="t"
        )
        assert "<x>" not in html and "&lt;x&gt;" in html

    def test_all_zero_no_division_error(self):
        pts = _line_points(self._area([0, 0, 0]))
        ys = {y for _x, y in pts}
        assert len(ys) == 1  # flat line, no NaN/crash


# =========================================================================== #
# 3) CSS contract
# =========================================================================== #
class TestChartCss:
    def test_core_rules_exist(self):
        for sel in (
            ".mh-chart {",
            ".mh-chart-bars",
            ".mh-chart-bar-fill",
            ".mh-chart-bar-val",
            ".mh-chart-area-svg",
            ".mh-chart-area-line",
            ".mh-chart-area-fill",
            ".mh-charts-grid",
            ".mh-chart-card",
        ):
            assert sel in _CSS, f"missing CSS rule {sel}"

    def test_uses_custom_properties(self):
        assert "--mh-bar" in _CSS
        assert "--mh-chart-accent" in _CSS

    def test_bar_grow_is_js_gated(self):
        # The collapsed start-state only applies with .mh-js — so no-JS visitors
        # see the final bar, never a permanently-empty plot.
        assert ".mh-js .mh-chart--bars[data-mh-animate]:not(.is-in) .mh-chart-bar-fill" in _CSS
        block = _CSS[_CSS.find(".mh-js .mh-chart--bars[data-mh-animate]:not(.is-in) .mh-chart-bar-fill"):]
        head = block[: block.find("}")]
        assert "scaleY(0)" in head

    def test_area_draw_is_js_gated(self):
        assert ".mh-js .mh-chart--area[data-mh-animate] .mh-chart-area-line" in _CSS
        assert "stroke-dashoffset" in _CSS

    def test_reduced_motion_snaps_to_final(self):
        block = _CSS[_CSS.find("UI 1.6"):]
        assert "prefers-reduced-motion: reduce" in block
        rm = block[block.find("prefers-reduced-motion"):]
        # bars un-scale and the line fully draws, with no transition
        assert "transform: none" in rm
        assert "stroke-dashoffset: 0" in rm
        assert "transition: none" in rm

    def test_responsive_rules_present(self):
        block = _CSS[_CSS.find("UI 1.6"):]
        assert "max-width: 560px" in block  # tighter chart height on phones
        assert "max-width: 760px" in block  # charts grid collapses to 1 col

    def test_no_cdn_in_chart_css(self):
        block = _CSS[_CSS.find("UI 1.6"):].lower()
        for bad in ("googleapis", "gstatic", "cdn.", "http://", "https://", "@import"):
            assert bad not in block, f"chart CSS must stay self-hosted ({bad})"


# =========================================================================== #
# 4) JS contract — charts ride the shared reveal observer
# =========================================================================== #
class TestRevealJs:
    def test_bindreveals_observes_charts(self, client):
        body = client.get("/").get_data(as_text=True)
        # The observer collects animated charts alongside the reveal blocks.
        assert ".mh-chart[data-mh-animate]" in body

    def test_no_charting_sdk_loaded(self, client):
        body = client.get("/").get_data(as_text=True).lower()
        for sdk in ("chart.js", "chartjs", "d3.", "d3.min", "plotly", "highcharts",
                    "apexcharts", "echarts", "chart.umd"):
            assert sdk not in body, f"no charting SDK allowed ({sdk})"


# =========================================================================== #
# 6) Review page — real run data only
# =========================================================================== #
class TestReviewCharts:
    def _review(self, client, run_id):
        resp = client.get(f"/review/{run_id}")
        assert resp.status_code == 200, f"/review/{run_id} -> {resp.status_code}"
        return resp.get_data(as_text=True)

    def test_meet_at_a_glance_present(self, client):
        _write_run("rc", _run_payload())
        body = self._review(client, "rc")
        assert "Meet at a glance" in body
        assert "Moments by quality band" in body
        assert "Content-worthiness by rank" in body

    def test_band_chart_uses_real_counts(self, client):
        # n_elite=2, n_strong=4, n_story=1 → those exact bars, no invention.
        _write_run("rc", _run_payload(n_elite=2, n_strong=4, n_story=1))
        body = self._review(client, "rc")
        chart = body[body.find("Moments by quality band"):body.find("Content-worthiness by rank")]
        assert 'data-mh-count="2"' in chart  # elite
        assert 'data-mh-count="4"' in chart  # strong
        assert 'data-mh-count="1"' in chart  # story

    def test_worthiness_chart_present_with_ranked(self, client):
        _write_run("rc", _run_payload(n_ranked=8))
        body = self._review(client, "rc")
        assert "mh-chart--area" in body
        assert "mh-area-grad-run-worth-rc" in body

    def test_charts_build_on_scroll(self, client):
        _write_run("rc", _run_payload())
        body = self._review(client, "rc")
        assert "data-mh-animate" in body

    def test_omitted_when_no_data(self, client):
        # Empty judged run: no bands, no ranked achievements → no chart card.
        payload = _run_payload(n_elite=0, n_strong=0, n_story=0, n_ranked=0)
        _write_run("empty", payload)
        body = self._review(client, "empty")
        assert "Meet at a glance" not in body

    def test_area_omitted_when_fewer_than_two_ranked(self, client):
        # One ranked achievement → band bar still shows, but no worthiness curve.
        payload = _run_payload(n_elite=1, n_strong=0, n_story=0, n_ranked=1)
        _write_run("one", payload)
        body = self._review(client, "one")
        assert "Moments by quality band" in body
        assert "Content-worthiness by rank" not in body

    def test_gradient_id_is_dom_safe(self, client):
        # A run id is sanitised into the SVG gradient id — no id breakage / no
        # markup injection even if the id ever carried odd characters.
        payload = _run_payload(run_id="ab-cd")
        _write_run("ab-cd", payload)
        body = self._review(client, "ab-cd")
        assert "mh-area-grad-run-worth-ab-cd" in body
