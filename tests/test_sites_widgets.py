"""Microsite engine (roadmap 1.16) — build 3: the vetted widget catalogue."""

from __future__ import annotations

import pytest

from mediahub.sites import widgets


def _w(wtype, config, widget_id="w1"):
    return {"widget_id": widget_id, "widget_type": wtype, "config": config}


def test_countdown_renders_with_target_and_nonce():
    html = widgets.render_widget(
        _w("countdown", {"target": "2026-07-01", "label": "County Champs"}), nonce="N1"
    )
    assert "mhw-countdown" in html
    assert 'data-target="2026-07-01"' in html
    assert "County Champs" in html
    assert 'nonce="N1"' in html
    assert "setInterval" in html


def test_medal_tally_is_data_grounded_no_js():
    html = widgets.render_widget(_w("medal_tally", {"gold": 3, "silver": 2, "bronze": 1}))
    assert "mhw-tally" in html
    assert ">3<" in html and ">2<" in html and ">1<" in html
    assert "6 total" in html
    assert "<script" not in html  # pure HTML, no scripting


def test_lane_lookup_filter():
    html = widgets.render_widget(
        _w(
            "lane_lookup",
            {"entries": [{"name": "Sam", "event": "50 Free", "heat": "2", "lane": "4"}]},
        ),
        nonce="N2",
    )
    assert "mhw-lanes" in html and "Sam" in html and "50 Free" in html
    assert "data-q" in html and "addEventListener('input'" in html
    assert 'nonce="N2"' in html


def test_poll_with_vote_url_has_buttons_and_script():
    html = widgets.render_widget(
        _w("poll", {"question": "Best stroke?", "options": ["Fly", "Free"]}),
        nonce="N3",
        vote_url="/site/TKN/widget/w1/vote",
        counts={"Fly": 3, "Free": 1},
    )
    assert "mhw-poll" in html and "Best stroke?" in html
    assert 'data-vote="/site/TKN/widget/w1/vote"' in html
    assert "data-opt=" in html  # interactive buttons
    assert "75% (3)" in html  # initial bars from counts (3 of 4)
    assert 'nonce="N3"' in html


def test_poll_without_vote_url_is_readonly():
    html = widgets.render_widget(_w("poll", {"question": "Q?", "options": ["A", "B"]}))
    assert "mhw-poll" in html
    assert "data-opt=" not in html  # no voting buttons
    assert "<script" not in html


def test_escapes_config_xss():
    html = widgets.render_widget(
        _w("poll", {"question": "<script>x</script>", "options": ["<b>A</b>"]})
    )
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_empty_or_unknown_render_nothing():
    assert widgets.render_widget(_w("poll", {"options": []})) == ""
    assert widgets.render_widget(_w("lane_lookup", {"entries": []})) == ""
    assert widgets.render_widget(_w("totally_unknown", {})) == ""


def test_compose_widget_honest_error_without_provider(monkeypatch):
    from mediahub.media_ai import llm as _llm

    monkeypatch.setattr(_llm, "is_available", lambda: False)
    with pytest.raises(_llm.ClaudeUnavailableError):
        widgets.compose_widget("a countdown to our gala on 1 July")


def test_compose_widget_constrained_to_catalogue(monkeypatch):
    from mediahub.media_ai import llm as _llm

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(
        _llm,
        "generate_json",
        lambda prompt, **kw: {"widget_type": "countdown", "config": {"target": "2026-07-01"}},
    )
    out = widgets.compose_widget("countdown to the gala")
    assert out["widget_type"] == "countdown"
    assert out["config"]["target"] == "2026-07-01"

    # an off-catalogue choice is refused (the AI can never introduce a new type)
    monkeypatch.setattr(
        _llm, "generate_json", lambda prompt, **kw: {"widget_type": "iframe", "config": {}}
    )
    with pytest.raises(ValueError):
        widgets.compose_widget("embed an iframe")
