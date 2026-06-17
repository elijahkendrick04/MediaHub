"""U.3 — Explainability & confidence surfaces made clear and trustworthy.

Pins the four U.3 deliverables on the review UI. Like U.1/U.2 this is
presentation-only: the deterministic engine (detectors + ranker) is never
recomputed or re-judged here — U.3 only makes its existing outputs
(``confidence_label``, ``quality_band``, ``priority``, the ranker ``factors``
and the near-miss category) *read* as the trustworthy intelligence they are.
The plain-English glosses are fixed UI legends for those deterministic enums
(the same pattern U.2 used for parse-note codes), NOT an AI surface — the
LLM-written "Why this card?" prose stays the only judgement surface, and still
honest-errors when no provider is configured.

  D1  confidence reads as intelligence, not a debug tag — a self-explaining
      ``_confidence_chip`` (label + plain meaning in a tooltip + optional %),
      and a *labelled* ``_worthiness_meter`` so the bare 0–1 ranking score
      isn't misread as a second confidence number.
  D2  the "why this card" reasoning leads with the ranker's own grounded
      ``plain_summary`` (``_render_factor_breakdown``) instead of the raw
      name/value/weight debug table — the data already existed, just hidden.
  D3  a clear, trustworthy "why not": the near-miss categories surfaced in
      plain English, close calls led out, nothing silently dropped.
  D4  a "how to read these cards" key so the whole surface reads as intelligent
      to a first-time volunteer.
"""

from __future__ import annotations

import json

import pytest

from mediahub.web import web as webmod


# --------------------------------------------------------------------------- #
# Fixtures (modelled on tests/test_u2_states.py)
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(webmod, "RUNS_DIR", runs, raising=False)
    app = webmod.app
    app.config["TESTING"] = True  # disables CSRF enforcement
    with app.test_client() as c:
        yield c


def _write_run(run_id, payload):
    (webmod.RUNS_DIR / f"{run_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def _review_body(client, run_id, expect=200):
    resp = client.get(f"/review/{run_id}")
    assert resp.status_code == expect, f"/review/{run_id} → {resp.status_code}"
    return resp.get_data(as_text=True)


def _ranked(**over):
    """A realistic ranked-achievement with grounded factors carrying
    plain_summary — the shape the ranker persists."""
    ra = {
        "rank": 1,
        "priority": 0.93,
        "quality_band": "elite",
        "suggested_post_type": "main_feed",
        "factors": [
            {
                "name": "magnitude",
                "value": 0.9,
                "weight": 0.30,
                "reason": "pb_confirmed",
                "plain_summary": "Strong on-paper achievement (pb confirmed).",
            },
            {
                "name": "rarity",
                "value": 0.7,
                "weight": 0.20,
                "reason": "rare",
                "plain_summary": "Rare at this level — national meet.",
            },
            {
                "name": "certainty",
                "value": 0.85,
                "weight": 0.10,
                "reason": "confidence 0.85",
                "plain_summary": "High confidence in the underlying data (0.85).",
            },
            {
                "name": "profile_priority",
                "value": 1.25,
                "weight": 0.0,
                "reason": "club priority",
                "plain_summary": "Club has flagged pb_confirmed as a priority (×1.25).",
            },
        ],
        "achievement": {
            "swim_id": "swimmerA:100FR:final",
            "swimmer_name": "Emma Davies",
            "event": "100m Freestyle",
            "time": "58.21",
            "type": "pb_confirmed",
            "pb": True,
            "confidence_label": "high",
            "confidence": 0.88,
            "headline": "First sub-60 in the 100 free",
            "evidence": [
                {
                    "source_name": "Meet results",
                    "statement": "Swam 58.21 in 100m Freestyle",
                    "source_url": None,
                }
            ],
        },
    }
    ra.update(over)
    return ra


def _run_payload(run_id="u3", traces=None, ranked=None):
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
            "ranked_achievements": ranked if ranked is not None else [_ranked()],
            "n_achievements": 1,
            "n_swims_analysed": 4,
            "n_elite": 1,
            "n_strong": 0,
            "n_story": 0,
            "swim_traces": traces or [],
            "meet_context": {"meet_level": "national"},
        },
    }


_CLOSE_TRACES = [
    {
        "swimmer_name": "Liam Hughes",
        "event": "50m Fly",
        "time_str": "28.40",
        "achievement_count": 0,
        "near_miss_category": "almost_pb",
        "summary": "pb_likely: time not faster than seed",
    },
    {
        "swimmer_name": "Mia Walsh",
        "event": "200m IM",
        "time_str": "2:34.10",
        "achievement_count": 0,
        "near_miss_category": "possible_pb_uncertain",
        "summary": "pb_confirmed: no prior PB data in cache",
    },
    {
        "swimmer_name": "Noah Field",
        "event": "100m Back",
        "time_str": "1:12.00",
        "achievement_count": 0,
        "near_miss_category": "lower_priority",
        "summary": "no notable achievement detected by any detector",
    },
]


# =========================================================================== #
# D1 — confidence chip + worthiness meter (confidence reads as intelligence)
# =========================================================================== #
class TestConfidenceChip:
    def test_label_meaning_and_class(self):
        for lab, cls in (("high", "good"), ("medium", "warn"), ("low", "bad")):
            html = webmod._confidence_chip(lab)
            assert f"mh-conf-chip {cls}" in html
            assert lab.capitalize() in html
            assert "Confidence" in html
            # the plain meaning rides in a title= tooltip
            assert 'title="' in html
            # the meaning is HTML-escaped into the title; compare like-for-like
            assert str(webmod._h(webmod._CONFIDENCE_MEANING[lab]))[:30] in html

    def test_unknown_label_is_safe_medium(self):
        html = webmod._confidence_chip("banana")
        assert "mh-conf-chip warn" in html  # falls back to medium styling, no crash

    def test_numeric_shown_only_when_in_range(self):
        assert "88%" in webmod._confidence_chip("high", numeric=0.88)
        # out-of-range / non-numeric never renders a bogus percentage
        assert "%" not in webmod._confidence_chip("high", numeric=0.0)
        assert "%" not in webmod._confidence_chip("high", numeric=1.7)
        assert "%" not in webmod._confidence_chip("high", numeric="oops")
        assert "%" not in webmod._confidence_chip("high", numeric=None)

    def test_escapes_label(self):
        html = webmod._confidence_chip('<x">')
        assert "<x" not in html.replace("mh-conf-chip", "")  # no raw injection


class TestWorthinessMeter:
    def test_labelled_and_percent(self):
        html = webmod._worthiness_meter(0.93)
        assert "mh-worth" in html
        assert "93%" in html
        assert "Worth" in html  # labelled — not a bare number
        assert "Separate from confidence" in html  # the trust-building distinction

    def test_clamped_and_safe(self):
        assert "100%" in webmod._worthiness_meter(2.0)
        assert "0%" in webmod._worthiness_meter(-1.0)
        assert "0%" in webmod._worthiness_meter("nope")


class TestBandChip:
    def test_meaning_tooltip_and_text(self):
        assert "ELITE" in webmod._band_chip("elite")
        assert "standout moment" in webmod._band_chip("elite")
        assert "NOT WORTHY" in webmod._band_chip("not_worthy")  # underscore humanised


# =========================================================================== #
# D2 — factor breakdown leads with plain_summary (reasoning reads as intelligent)
# =========================================================================== #
class TestFactorBreakdown:
    def test_leads_with_plain_summary_not_debug(self):
        html = webmod._render_factor_breakdown(_ranked()["factors"])
        assert "Strong on-paper achievement" in html
        assert "Rare at this level" in html
        assert "High confidence in the underlying data" in html
        # the contribution is shown as a bar, not a raw 3-dp value column
        assert "mh-factor-fill" in html
        assert "<th>Value</th>" not in html

    def test_profile_priority_shown_as_multiplier(self):
        html = webmod._render_factor_breakdown(_ranked()["factors"])
        assert "&times;1.25" in html

    def test_noop_override_suppressed(self):
        # a ×1.00 club override is noise, not trust — drop it
        html = webmod._render_factor_breakdown(
            [{"name": "profile_priority", "value": 1.0, "weight": 0.0}]
        )
        assert "No ranking factors" in html

    def test_non_contributing_factor_without_summary_skipped(self):
        factors = [
            {"name": "magnitude", "value": 0.9, "weight": 0.30, "plain_summary": "Big."},
            {"name": "barrier", "value": 0.0, "weight": 0.10, "plain_summary": ""},
        ]
        html = webmod._render_factor_breakdown(factors)
        assert html.count("<li") == 1  # only magnitude

    def test_rankfactor_object_path(self):
        class RF:
            def to_dict(self):
                return {
                    "name": "rarity",
                    "value": 0.7,
                    "weight": 0.20,
                    "plain_summary": "Rare at this level — national meet.",
                }

        assert "Rare at this level" in webmod._render_factor_breakdown([RF()])

    def test_empty_and_malformed_safe(self):
        for bad in ([], None, ["junk", 5, None]):
            assert webmod._render_factor_breakdown(bad).startswith("<p")

    def test_escapes_malicious_factor(self):
        html = webmod._render_factor_breakdown(
            [
                {
                    "name": "x",
                    "value": 0.5,
                    "weight": 0.3,
                    "plain_summary": "<script>alert(1)</script>",
                }
            ]
        )
        assert "<script>alert(1)" not in html
        assert "&lt;script&gt;" in html

    def test_falls_back_to_reason_when_no_plain_summary(self):
        html = webmod._render_factor_breakdown(
            [{"name": "magnitude", "value": 0.5, "weight": 0.3, "reason": "solid result"}]
        )
        assert "solid result" in html


# =========================================================================== #
# D3 — "why not": near-miss labels, hint, and the upgraded panel
# =========================================================================== #
class TestNearMiss:
    def test_every_category_has_plain_label(self):
        for cat in webmod._NEAR_MISS_ORDER:
            label, blurb = webmod._near_miss_label(cat)
            assert label and blurb

    def test_specific_labels(self):
        assert webmod._near_miss_label("almost_pb")[0] == "Almost a PB"
        assert webmod._near_miss_label("possible_pb_uncertain")[0] == "Possible PB — unconfirmed"
        assert webmod._near_miss_label("ambiguous_swimmer_match")[0] == "Swimmer unconfirmed"

    def test_unknown_category_defaults_to_outranked(self):
        assert webmod._near_miss_label("totally_unknown")[0] == "Outranked"

    def test_close_call_predicate(self):
        assert webmod._near_miss_is_close_call("almost_pb")
        assert not webmod._near_miss_is_close_call("lower_priority")
        assert not webmod._near_miss_is_close_call("")
        assert not webmod._near_miss_is_close_call(None)

    def test_hint_empty_when_nothing_ungenerated(self):
        assert webmod._render_near_miss_hint(0, 0) == ""

    def test_hint_leads_with_close_calls(self):
        h = webmod._render_near_miss_hint(5, 2)
        assert "5 swims" in h and "2 were close calls" in h
        assert "#mh-not-generated" in h

    def test_hint_singular_and_no_close_calls(self):
        assert "1 swim" in webmod._render_near_miss_hint(1, 0)
        assert "none were close calls" in webmod._render_near_miss_hint(1, 0)
        assert "1 was a close call" in webmod._render_near_miss_hint(3, 1)


# =========================================================================== #
# D4 — the "how to read these cards" key
# =========================================================================== #
class TestExplainabilityKey:
    def test_covers_every_axis(self):
        key = webmod._render_explainability_key()
        for term in (
            "How to read these cards",
            "Band",
            "Confidence",
            "Worth",
            "Why this card?",
            "Why not",
        ):
            assert term in key, term

    def test_honest_ai_framing(self):
        key = webmod._render_explainability_key()
        # the moat reads as intelligent *and* honest — never invents, says so
        assert "Written by AI" in key
        assert "never invented" in key

    def test_is_collapsible_disclosure(self):
        key = webmod._render_explainability_key()
        assert "<details" in key and "mh-explain-key" in key


# =========================================================================== #
# Integration — the real /review render carries every U.3 surface
# =========================================================================== #
class TestReviewRenderIntegration:
    def test_all_surfaces_present(self, client):
        _write_run("r1", _run_payload("r1", traces=_CLOSE_TRACES))
        body = _review_body(client, "r1")

        # D1
        assert "mh-conf-chip good" in body
        assert "Confidence&nbsp;&middot;&nbsp;High" in body
        assert "88%" in body  # numeric confidence
        assert "mh-worth" in body and "93%" in body
        # D2 — plain-English reasoning, no debug table header
        assert "Strong on-paper achievement" in body
        assert "Rare at this level" in body
        assert "&times;1.25" in body
        assert "<th>Value</th>" not in body
        # D4 — the key
        assert "How to read these cards" in body
        assert "Written by AI" in body
        # D3 — why-not surface
        assert "Almost a PB" in body
        assert "Possible PB — unconfirmed" in body
        assert "<th>Why not</th>" in body
        assert 'id="mh-not-generated"' in body
        assert "2 close calls" in body
        assert "were close calls" in body  # the discoverability hint

    def test_no_traces_means_no_hint(self, client):
        _write_run("r2", _run_payload("r2", traces=[]))
        body = _review_body(client, "r2")
        # nothing ungenerated → no rendered hint element (the CSS rule for the
        # class always lives in <style>, so check for the element specifically)
        assert '<div class="mh-nearmiss-hint"' not in body
        # but the core surfaces still render
        assert "mh-conf-chip" in body
        assert "How to read these cards" in body

    def test_low_confidence_card_reads_clearly(self, client):
        ra = _ranked(priority=0.22, quality_band="nice")
        ra["achievement"]["confidence_label"] = "low"
        ra["achievement"]["confidence"] = 0.41
        _write_run("r3", _run_payload("r3", ranked=[ra]))
        body = _review_body(client, "r3")
        assert "mh-conf-chip bad" in body
        assert "Confidence&nbsp;&middot;&nbsp;Low" in body
        assert "less sure" in body  # the plain meaning is on the page

    def test_empty_judged_run_renders_key_without_crashing(self, client):
        # No ranked achievements and no traces: the page (incl. the key) must
        # still render 200, and the near-miss hint stays absent.
        payload = _run_payload("r5", ranked=[], traces=[])
        payload["recognition_report"]["n_achievements"] = 0
        _write_run("r5", payload)
        body = _review_body(client, "r5")
        assert "How to read these cards" in body
        assert '<div class="mh-nearmiss-hint"' not in body

    def test_only_outranked_traces_hint_and_panel(self, client):
        # Traces present but no close calls: the hint says so honestly and the
        # "Not generated" panel does NOT auto-open (close calls are the signal).
        traces = [{"swimmer_name": "A", "event": "50 Free", "time_str": "30.00",
                   "achievement_count": 0, "near_miss_category": "lower_priority",
                   "summary": "outranked by stronger swims"}]
        _write_run("r6", _run_payload("r6", ranked=[], traces=traces))
        body = _review_body(client, "r6")
        assert "none were close calls" in body
        assert "Outranked" in body
        after_anchor = body.split('id="mh-not-generated"', 1)[1][:80]
        assert "<details open" not in after_anchor  # collapsed when no close calls

    def test_confidence_filter_still_works(self, client):
        # the filter keys off data-conf on each row — must survive the chip swap
        _write_run("r4", _run_payload("r4"))
        body = _review_body(client, "r4")
        assert 'data-conf="high"' in body
        assert 'id="f-conf"' in body  # the filter control is intact


# =========================================================================== #
# Guardrails — determinism + honest-error are NOT disturbed by U.3
# =========================================================================== #
class TestGuardrails:
    def test_presented_numbers_are_verbatim_from_ranker(self, client):
        # The worthiness meter must show the ranker's own priority, rounded for
        # display only — U.3 presents, it never recomputes the score.
        ra = _ranked(priority=0.667)
        _write_run("g1", _run_payload("g1", ranked=[ra]))
        body = _review_body(client, "g1")
        assert "67%" in body  # round(0.667*100) — not re-derived

    def test_lazy_why_card_affordance_preserved(self, client):
        # test_review_collapse invariant: the LLM "Why this card?" stays a
        # one-click lazy disclosure. U.3 touched the surrounding tags, not this.
        _write_run("g2", _run_payload("g2"))
        body = _review_body(client, "g2")
        assert "why-peek" in body
        assert "Show reasoning" in body

    def test_factor_breakdown_does_not_call_llm(self, monkeypatch):
        # D2 is pure deterministic presentation — it must never reach for a
        # provider (that would make the reasoning non-reproducible).
        import mediahub.ai_core as ai_core

        def _boom(*a, **k):
            raise AssertionError("factor breakdown must not call the LLM")

        monkeypatch.setattr(ai_core, "ask_with_tools", _boom, raising=False)
        html = webmod._render_factor_breakdown(_ranked()["factors"])
        assert "Strong on-paper achievement" in html

    def test_review_renders_without_llm_provider(self, client, monkeypatch):
        # No provider configured: the page (incl. all U.3 surfaces) still renders
        # 200; only the LLM-backed "Why this card?" prose honest-errors, lazily.
        from mediahub.media_ai import llm as _llm

        monkeypatch.setattr(_llm, "is_available", lambda: False)
        _write_run("g3", _run_payload("g3", traces=_CLOSE_TRACES))
        body = _review_body(client, "g3")
        assert "mh-conf-chip" in body
        assert "How to read these cards" in body
