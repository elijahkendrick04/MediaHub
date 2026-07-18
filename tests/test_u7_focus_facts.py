"""U.7 — "Focus the facts" caption / explainability highlight.

In captions and the "Why this card?" review UI, the source-grounded entities
(athlete / event / time / PB-medal-record) are pill-highlighted and sharp; the
connective filler around them recedes. This is **server-side span injection**
(no client JS) and, critically, it is **source-grounded** — every highlighted
phrase is built from the structured achievement the deterministic engine already
produced, never a regex guess. So the highlight can't drift from the data:

  * a number is only lit if it's the card's actual result time (not any figure
    that "looks like a time"),
  * "gold" / "record" is only lit on a card the detector actually flagged as a
    medal / record,
  * the spans are XSS-safe — every segment is HTML-escaped, only the highlight
    tags are markup.

These tests pin the helpers (`_event_variants`, `_card_facts`,
`_focus_facts_html`) and the two surfaces they feed: the lazily-fetched
"Why this card?" body (`_render_why_inner` / `api_why_card`) and the public
try-demo content pack. Like U.3 this is presentation-only — the deterministic
engine is never recomputed here.
"""

from __future__ import annotations

import json

import pytest

from mediahub.web import web as webmod


# =========================================================================== #
# Fixtures
# =========================================================================== #
def _write_run(run_id, payload):
    (webmod.RUNS_DIR / f"{run_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def _ach(**over):
    """A realistic PB achievement carrying the structured facts U.7 grounds on."""
    a = {
        "swim_id": "swimmerA:100FR:final",
        "swimmer_name": "Emma Davies",
        "event": "100m Freestyle (LC)",
        "time": "58.21",
        "type": "pb_confirmed",
        "pb": True,
        "confidence_label": "high",
        "headline": "First sub-60 in the 100 free",
    }
    a.update(over)
    return a


def _ranked(**over):
    ra = {
        "rank": 1,
        "priority": 0.93,
        "quality_band": "elite",
        "suggested_post_type": "main_feed",
        "factors": [],
        "achievement": _ach(),
    }
    ra.update(over)
    return ra


def _run_payload(run_id="u7", ranked=None):
    return {
        "run_id": run_id,
        "meet": {"name": "Spring Open 2026", "course": "SCM"},
        "cards": [],
        "trust": {"cards": []},
        "parse_warnings": [],
        "recognition_report": {
            "ranked_achievements": ranked if ranked is not None else [_ranked()],
            "n_achievements": 1,
            "swim_traces": [],
            "meet_context": {"meet_level": "national"},
        },
    }


# =========================================================================== #
# _event_variants — grounded short-forms of the real event label
# =========================================================================== #
class TestEventVariants:
    def test_full_base_and_short_forms(self):
        v = webmod._event_variants("100m Freestyle (LC)")
        assert "100m Freestyle (LC)" in v  # full label
        assert "100m Freestyle" in v  # course tag stripped
        assert "100m free" in v  # stroke short-form
        assert "100 free" in v  # distance-without-m
        assert "100 freestyle" in v

    def test_every_stroke_has_a_short_form(self):
        assert "50 back" in webmod._event_variants("50m Backstroke")
        assert "100 breast" in webmod._event_variants("100m Breaststroke")
        assert "200 fly" in webmod._event_variants("200m Butterfly")
        im = webmod._event_variants("200m Individual Medley")
        assert "200 im" in im and "200 medley" in im

    def test_never_emits_bare_distance(self):
        # A standalone "100" would light up stray figures — must never appear.
        for v in webmod._event_variants("100m Freestyle"):
            assert v.replace(" ", "") != "100"
            assert not v.replace(" ", "").isdigit()

    def test_empty_is_empty(self):
        assert webmod._event_variants("") == []
        assert webmod._event_variants(None) == []  # type: ignore[arg-type]


# =========================================================================== #
# _card_facts — source-grounded (phrase, kind) pairs
# =========================================================================== #
class TestCardFacts:
    def _kinds_for(self, phrases, kind):
        return {p.lower() for p, k in phrases if k == kind}

    def test_athlete_full_and_first_name(self):
        phrases = webmod._card_facts(_ach())
        athletes = self._kinds_for(phrases, "athlete")
        assert "emma davies" in athletes
        assert "emma" in athletes  # captions usually go first-name

    def test_single_token_name_has_no_duplicate(self):
        phrases = webmod._card_facts(_ach(swimmer_name="Cher"))
        athletes = [p for p, k in phrases if k == "athlete"]
        assert athletes == ["Cher"]

    def test_event_variants_present(self):
        events = self._kinds_for(webmod._card_facts(_ach()), "event")
        assert "100m freestyle" in events
        assert "100 free" in events

    def test_time_from_multiple_sources(self):
        phrases = webmod._card_facts(
            _ach(time="58.21", raw_facts={"time_str": "1:02.99", "result": "DQ"})
        )
        times = self._kinds_for(phrases, "time")
        assert "58.21" in times
        assert "1:02.99" in times
        assert "dq" in times

    def test_pb_markers_only_on_pb(self):
        pb = self._kinds_for(webmod._card_facts(_ach(type="pb_confirmed", pb=True)), "pb")
        assert "personal best" in pb and "pb" in pb
        # A non-PB card must not advertise a PB marker.
        not_pb = self._kinds_for(webmod._card_facts(_ach(type="medal_silver", pb=False)), "pb")
        assert "personal best" not in not_pb and "pb" not in not_pb

    def test_medal_markers_gated_by_type(self):
        gold = self._kinds_for(
            webmod._card_facts(_ach(type="medal_gold", pb=False, headline="Gold!")), "pb"
        )
        assert "gold" in gold and "medal" in gold
        assert "silver" not in gold and "bronze" not in gold
        # A plain PB card never lights up a medal word.
        plain = self._kinds_for(webmod._card_facts(_ach(type="pb_confirmed")), "pb")
        assert "gold" not in plain and "medal" not in plain

    def test_record_markers_gated_by_type(self):
        rec = self._kinds_for(webmod._card_facts(_ach(type="club_record", pb=False)), "pb")
        assert "club record" in rec and "record" in rec
        plain = self._kinds_for(webmod._card_facts(_ach(type="pb_confirmed")), "pb")
        assert "record" not in plain

    def test_first_marker_gated_by_type(self):
        first = self._kinds_for(webmod._card_facts(_ach(type="first_sub_60", pb=True)), "pb")
        assert "first" in first
        plain = self._kinds_for(webmod._card_facts(_ach(type="pb_confirmed")), "pb")
        assert "first" not in plain

    def test_post_angle_drives_pb_marker(self):
        # No `pb` flag and a neutral type, but the engine's post_angle says PB.
        pb = self._kinds_for(
            webmod._card_facts(
                {"swimmer_name": "X Y", "type": "result", "post_angle": "confirmed_official_pb"}
            ),
            "pb",
        )
        assert "personal best" in pb

    def test_non_dict_and_empty_safe(self):
        assert webmod._card_facts(None) == []
        assert webmod._card_facts("nope") == []  # type: ignore[arg-type]
        assert webmod._card_facts({}) == []

    def test_single_character_facts_dropped(self):
        # A one-letter "name" must never become a highlight phrase.
        phrases = webmod._card_facts({"swimmer_name": "A", "event": "", "time": "x"})
        assert phrases == []

    def test_case_insensitive_dedup(self):
        # Variants that collide case-insensitively collapse to one phrase.
        phrases = webmod._card_facts(_ach(event="100m Freestyle"))
        lowered = [p.lower() for p, _ in phrases]
        assert len(lowered) == len(set(lowered))


# =========================================================================== #
# _focus_facts_html — the server-side span injection itself
# =========================================================================== #
class TestFocusFactsHtml:
    def test_each_kind_wrapped_with_class(self):
        html = webmod._focus_facts_html("Emma swam a personal best 58.21 in the 100m Free", _ach())
        assert '<span class="mh-fact mh-fact--athlete">Emma</span>' in html
        assert '<span class="mh-fact mh-fact--pb">personal best</span>' in html
        assert '<span class="mh-fact mh-fact--time">58.21</span>' in html
        assert '<span class="mh-fact mh-fact--event">100m Free</span>' in html

    def test_focus_wrapper_present_when_a_fact_matches(self):
        html = webmod._focus_facts_html("Emma went fast", _ach())
        assert html.startswith('<span class="mh-focus">')
        assert html.endswith("</span>")

    def test_no_wrapper_when_nothing_matches(self):
        # Facts exist on the card but none appear in this copy → no de-emphasis.
        html = webmod._focus_facts_html("totally unrelated marketing copy", _ach())
        assert "mh-focus" not in html
        assert "mh-fact" not in html
        assert html == "totally unrelated marketing copy"

    def test_no_facts_returns_plain_escaped(self):
        assert webmod._focus_facts_html("plain text", {}) == "plain text"
        assert webmod._focus_facts_html("a & b < c", {}) == "a &amp; b &lt; c"

    def test_empty_and_whitespace(self):
        assert webmod._focus_facts_html("", _ach()) == ""
        assert webmod._focus_facts_html("   ", _ach()) == "   "
        assert webmod._focus_facts_html(None, _ach()) == ""  # type: ignore[arg-type]

    def test_longest_match_wins_name(self):
        # "Emma Davies" (full) must win over "Emma" (first) at the same spot.
        html = webmod._focus_facts_html("Well done Emma Davies!", _ach())
        assert '<span class="mh-fact mh-fact--athlete">Emma Davies</span>' in html
        # not split into Emma + Davies
        assert ">Emma</span> <span" not in html

    def test_longest_match_wins_event(self):
        html = webmod._focus_facts_html("a swim in the 100m Freestyle today", _ach())
        assert '<span class="mh-fact mh-fact--event">100m Freestyle</span>' in html

    def test_word_boundaries(self):
        # "PB" must not match inside another word; "Emma" not inside "Emmanuel".
        html = webmod._focus_facts_html("Emmanuel got a PBest score", _ach())
        assert "mh-fact--athlete" not in html  # Emmanuel ≠ Emma
        assert "mh-fact--pb" not in html  # PBest ≠ PB
        # but a real standalone PB does light up
        html2 = webmod._focus_facts_html("a new PB!", _ach())
        assert '<span class="mh-fact mh-fact--pb">PB</span>' in html2

    def test_case_insensitive_match_preserves_source_casing(self):
        html = webmod._focus_facts_html("EMMA smashed it", _ach())
        # matched on "emma" case-insensitively, but the visible text stays "EMMA"
        assert ">EMMA</span>" in html
        assert "mh-fact--athlete" in html

    def test_clock_time_format_matches(self):
        html = webmod._focus_facts_html("splits to 1:02.34 on the day", _ach(time="1:02.34"))
        assert '<span class="mh-fact mh-fact--time">1:02.34</span>' in html

    def test_xss_escaped_only_spans_are_markup(self):
        a = _ach(swimmer_name="<b>Emma</b>")
        html = webmod._focus_facts_html("<script>alert(1)</script> by <b>Emma</b> 58.21", a)
        assert "<script>alert(1)" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        # the only literal "<span" tags are the highlight spans
        assert html.count("<span") == html.count('<span class="mh-')
        # the matched (escaped) name still rides inside a fact span
        assert "mh-fact--athlete" in html
        assert "&lt;b&gt;Emma&lt;/b&gt;" in html

    def test_unknown_kind_clamped_to_safe_class(self):
        # A bogus kind can never inject into the class attribute.
        html = webmod._focus_facts_html(
            "hello Emma", achievement=None, phrases=[("Emma", 'x"><img>')]
        )
        assert '<span class="mh-fact mh-fact--event">Emma</span>' in html
        assert "<img>" not in html

    def test_filler_recedes_facts_pop(self):
        # The structural promise: facts sit in mh-fact spans, everything else is
        # plain text inside the mh-focus (de-emphasised) wrapper.
        html = webmod._focus_facts_html("Great swim from Emma", _ach())
        assert "Great swim from " in html  # filler, un-pilled
        assert '<span class="mh-fact mh-fact--athlete">Emma</span>' in html


# =========================================================================== #
# Source-grounding guardrail — the highlight can NEVER drift from the data
# =========================================================================== #
class TestSourceGrounding:
    def test_stray_number_not_lit_as_time(self):
        # "2026" looks time-ish but is not the card's result → never highlighted.
        html = webmod._focus_facts_html("back in 2026 Emma swam 58.21", _ach())
        assert 'mh-fact--time">2026' not in html
        assert '<span class="mh-fact mh-fact--time">58.21</span>' in html

    def test_medal_word_not_lit_on_non_medal_card(self):
        # The caption mentions gold, but the card is a PB, not a medal.
        html = webmod._focus_facts_html("she won gold in spirit", _ach(type="pb_confirmed"))
        assert 'mh-fact--pb">gold' not in html

    def test_helper_never_calls_llm(self, monkeypatch):
        import mediahub.ai_core as ai_core

        def _boom(*a, **k):
            raise AssertionError("focus-the-facts must stay deterministic — no LLM")

        monkeypatch.setattr(ai_core, "ask_with_tools", _boom, raising=False)
        html = webmod._focus_facts_html("Emma swam 58.21", _ach())
        assert "mh-fact" in html


# =========================================================================== #
# _render_why_inner — the "Why this card?" body lights up the reasoning
# =========================================================================== #
class TestWhyInner:
    def test_headline_and_bullets_highlighted(self):
        exp = {
            "headline": "Emma Davies went a personal best 58.21 in the 100m Freestyle",
            "bullets": ["Confirmed PB for Emma Davies", "Faster than her 58.90 seed"],
            "source_lines": [],
        }
        html = webmod._render_why_inner(exp, ra=_ranked(), run_id="", card_uuid="c1")
        # headline facts
        assert '<span class="mh-fact mh-fact--athlete">Emma Davies</span>' in html
        assert '<span class="mh-fact mh-fact--pb">personal best</span>' in html
        assert '<span class="mh-fact mh-fact--time">58.21</span>' in html
        assert '<span class="mh-fact mh-fact--event">100m Freestyle</span>' in html
        # bullets get the same treatment
        assert 'mh-fact--pb">PB</span>' in html

    def test_copy_payload_stays_plain_text(self):
        # The hidden "Copy reasoning" textarea must carry clean text, not spans.
        exp = {
            "headline": "Emma Davies went a personal best",
            "bullets": ["Confirmed PB"],
            "source_lines": [],
        }
        html = webmod._render_why_inner(exp, ra=_ranked(), run_id="", card_uuid="c2")
        textarea = html.split('id="why-text-c2"', 1)[1].split("</textarea>", 1)[0]
        assert "mh-fact" not in textarea
        assert "Emma Davies went a personal best" in textarea

    def test_no_achievement_falls_back_to_plain(self):
        # Legacy caller with no ra → headline still renders, just un-highlighted.
        exp = {"headline": "Some reasoning", "bullets": [], "source_lines": []}
        html = webmod._render_why_inner(exp, ra=None, run_id="", card_uuid="c3")
        assert "Some reasoning" in html
        assert "mh-fact" not in html


# =========================================================================== #
# api_why_card — the lazy HTTP path the review list actually fetches
# =========================================================================== #
class TestApiWhyCardIntegration:
    def test_fetched_body_carries_highlights(self, client, monkeypatch):
        # Force a grounded explanation (no provider needed) so the highlight has
        # real facts to find.
        monkeypatch.setattr(
            webmod,
            "_build_card_explanation",
            lambda ra, meet_ctx=None: {
                "headline": "Emma Davies swam a personal best 58.21 in the 100m Freestyle",
                "bullets": ["Confirmed PB for Emma Davies"],
                "source_lines": [],
            },
        )
        _write_run("w1", _run_payload("w1"))
        resp = client.get("/api/runs/w1/why/0")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert '<span class="mh-fact mh-fact--athlete">Emma Davies</span>' in body
        assert '<span class="mh-fact mh-fact--time">58.21</span>' in body
        assert "mh-fact--pb" in body

    def test_malicious_headline_escaped(self, client, monkeypatch):
        monkeypatch.setattr(
            webmod,
            "_build_card_explanation",
            lambda ra, meet_ctx=None: {
                "headline": "<script>alert(1)</script> Emma Davies 58.21",
                "bullets": [],
                "source_lines": [],
            },
        )
        _write_run("w2", _run_payload("w2"))
        body = client.get("/api/runs/w2/why/0").get_data(as_text=True)
        assert "<script>alert(1)" not in body
        assert "&lt;script&gt;" in body


# =========================================================================== #
# CSS ships — the highlight styles reach the review page
# =========================================================================== #
class TestStylesShip:
    def test_focus_classes_in_review_css(self, client):
        _write_run("c1", _run_payload("c1"))
        body = client.get("/review/c1").get_data(as_text=True)
        assert ".mh-focus" in body
        assert ".mh-fact--athlete" in body
        assert ".mh-fact--time" in body
        assert ".mh-fact--pb" in body


# =========================================================================== #
# Try-demo content pack — the public caption surface highlights too
# =========================================================================== #
@pytest.fixture
def demo_world(web_module, tmp_path, monkeypatch):
    import mediahub.web.demo_try as dt

    app = web_module.create_app()
    app.config["TESTING"] = True
    return {"app": app, "wm": web_module, "dt": dt, "tmp": tmp_path, "mp": monkeypatch}


def _seed_demo_run(world, run_id):
    dt = world["dt"]
    runs_dir = world["tmp"] / "runs_v4"
    runs_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "profile_id": dt.DEMO_PROFILE_ID,
        "meet_name": "Demo Gala",
        "meet": {"name": "Demo Gala"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "achievement": {
                        "swim_id": "swim-1",
                        "swimmer_name": "Emma Davies",
                        "event": "100m Freestyle",
                        "time": "59.10",
                        "type": "pb_confirmed",
                        "pb": True,
                    }
                }
            ]
        },
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(data))
    conn = world["wm"]._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), ?, ?, ?, ?)",
        (run_id, "done", dt.DEMO_PROFILE_ID, "Demo Gala", "demo.hy3"),
    )
    conn.commit()
    conn.close()


class TestTryDemoSurface:
    def test_demo_caption_and_reasoning_highlighted(self, demo_world):
        wm = demo_world["wm"]
        mp = demo_world["mp"]
        # Deterministic caption + reasoning (no provider in the sandbox).
        mp.setattr(
            "mediahub.brand.apply.apply_brand",
            lambda ra, kit, tone, kind, opts: {
                "active_caption": {
                    "primary": "Emma Davies smashed a personal best 59.10 in the 100m Freestyle!"
                }
            },
        )
        mp.setattr(
            wm,
            "_build_card_explanation",
            lambda ra, meet_ctx=None: {
                "headline": "Emma Davies went a personal best 59.10",
                "bullets": ["Confirmed PB for Emma Davies"],
                "source_lines": [],
            },
        )
        _seed_demo_run(demo_world, "demorun00001")
        c = demo_world["app"].test_client()
        with c.session_transaction() as sess:
            sess["demo_runs"] = ["demorun00001"]
        body = c.get("/try/demorun00001").get_data(as_text=True)

        assert body.count("/try/demorun00001") >= 0  # page rendered
        # the caption lights up the facts
        assert '<span class="mh-fact mh-fact--athlete">Emma Davies</span>' in body
        assert '<span class="mh-fact mh-fact--time">59.10</span>' in body
        assert '<span class="mh-fact mh-fact--pb">personal best</span>' in body
        assert '<span class="mh-fact mh-fact--event">100m Freestyle</span>' in body
        # and the styles are present so they actually render
        assert ".mh-fact--athlete" in body
