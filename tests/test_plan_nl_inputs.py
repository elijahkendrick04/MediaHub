"""Plan ↔ Free-Text: natural-language planner inputs + the Plan/Create move.

Covers the three parts of the change:

1. **``content_engine.nl_inputs.interpret_planner_inputs``** — the Free-Text
   feature's NL interpretation + web research brought to the planner's direct
   inputs. The AI only *proposes* structured inputs: goals are constrained to
   the sport's enabled post types (never invented), past-dated events/blackouts
   are dropped, venues survive, and an unconfigured provider is an honest error
   with no heuristic fallback.
2. **``POST /api/plan/interpret``** — org-scoped, empty-note guard, happy path,
   and an honest provider error surfaced as 503.
3. **The nav move** — Plan is gone from the desktop top bar but reachable from
   the Create page (and still on the ``g→p`` shortcut), and the Plan page now
   reads as living under Create with the AI describe-box, venue and goals
   controls on the surface.
"""

from __future__ import annotations

import importlib
import sys
import types
from datetime import date
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

GOAL_CHOICES = [
    ("sponsor_activation", "Sponsor Activation"),
    ("event_preview", "Event Preview"),
    ("meet_recap", "Meet Recap"),
]
ANCHOR = date(2026, 6, 17)


# ---------------------------------------------------------------------------
# Unit: interpret_planner_inputs
# ---------------------------------------------------------------------------


_RESEARCH_QUERY = "County Championships 2026 date"


def _install_fake_llm(monkeypatch, proposal, *, research=False, provider="gemini"):
    """Patch ai_core.ask_with_tools to drive the on_tool_call wiring the way a
    real model would: optionally research, then propose, then return text.

    Network is ALWAYS stubbed at ``WebResearcher.search`` — the network boundary
    ``ResearchClient`` wraps — mirroring the proven offline pattern in
    tests/test_deep_research.py. Patching the class *method* (not replacing the
    ``ResearchClient`` class) is robust under full-suite ordering, where an
    earlier test can otherwise leave ``ResearchClient`` resolving to a class our
    patch never touched (which let the real web search run on CI)."""
    import mediahub.ai_core as ai_core
    from mediahub.web_research import search as searchmod
    from mediahub.web_research.search import SearchResult

    monkeypatch.setattr(
        searchmod.WebResearcher,
        "search",
        lambda self, q, num=5: [
            SearchResult("https://swimming.org/champs", "County Champs 2026", "12 July 2026 at Ponds Forge.", "searxng")
        ],
        raising=True,
    )

    def fake_ask_with_tools(system, user, *, tools, on_tool_call, max_tokens=1200, max_rounds=4):
        names = {t["name"] for t in tools}
        if research and "research_web" in names:
            on_tool_call("research_web", {"query": _RESEARCH_QUERY, "reason": "confirm"})
        on_tool_call("propose_inputs", proposal)
        return types.SimpleNamespace(text="done", provider=provider)

    monkeypatch.setattr(ai_core, "ask_with_tools", fake_ask_with_tools, raising=True)


def test_interpret_shapes_events_blackouts_goals(monkeypatch):
    from mediahub.content_engine.nl_inputs import interpret_planner_inputs

    _install_fake_llm(
        monkeypatch,
        {
            "upcoming_events": [
                {"name": "County Championships", "date": "2026-07-12", "venue": "Ponds Forge"},
                {"name": "Old Gala", "date": "2020-01-01"},  # past → dropped
            ],
            "blackout_dates": ["2026-08-31", "1999-01-01"],  # past dropped
            "goals": [
                {"post_type": "sponsor_activation", "note": "push new sponsor"},
                {"post_type": "not_a_real_type", "note": "should drop"},  # not enabled
            ],
            "summary": "County Champs, a blackout, and a sponsor goal.",
        },
    )

    out = interpret_planner_inputs("…note…", goal_choices=GOAL_CHOICES, today=ANCHOR)

    assert out["upcoming_events"] == [
        {"name": "County Championships", "date": "2026-07-12", "venue": "Ponds Forge"}
    ]
    assert out["blackout_dates"] == ["2026-08-31"]
    assert out["goals"] == [{"post_type": "sponsor_activation", "note": "push new sponsor"}]
    assert out["summary"].startswith("County Champs")
    assert out["provider"] == "gemini"


def test_interpret_threads_web_research(monkeypatch):
    """When the model researches, the hits are recorded for display/provenance —
    sourced from the stubbed WebResearcher, never the live network."""
    from mediahub.content_engine.nl_inputs import interpret_planner_inputs

    _install_fake_llm(monkeypatch, {"summary": "checked the date"}, research=True)
    out = interpret_planner_inputs("County champs?", goal_choices=GOAL_CHOICES, today=ANCHOR)

    assert out["research"], "research the model ran should be recorded"
    log = out["research"][0]
    assert log["query"] == _RESEARCH_QUERY
    hit = log["hits"][0]
    assert hit["domain"] == "swimming.org" and hit["title"] == "County Champs 2026"


def test_interpret_drops_goal_for_unenabled_type(monkeypatch):
    from mediahub.content_engine.nl_inputs import interpret_planner_inputs

    _install_fake_llm(
        monkeypatch,
        {"goals": [{"post_type": "athlete_spotlight", "note": "x"}]},  # not in GOAL_CHOICES
        research=False,
    )
    out = interpret_planner_inputs("note", goal_choices=GOAL_CHOICES, today=ANCHOR)
    assert out["goals"] == []  # invented/unenabled type can never be targeted


def test_interpret_no_research_when_disabled(monkeypatch):
    from mediahub.content_engine.nl_inputs import interpret_planner_inputs

    captured_tools = {}

    import mediahub.ai_core as ai_core

    def fake(system, user, *, tools, on_tool_call, max_tokens=1200, max_rounds=4):
        captured_tools["names"] = {t["name"] for t in tools}
        on_tool_call("propose_inputs", {"summary": "ok"})
        return types.SimpleNamespace(text="", provider="gemini")

    monkeypatch.setattr(ai_core, "ask_with_tools", fake, raising=True)
    out = interpret_planner_inputs("note", goal_choices=GOAL_CHOICES, allow_research=False)
    assert "research_web" not in captured_tools["names"]
    assert out["research"] == []


def test_interpret_empty_note_is_honest_error(monkeypatch):
    from mediahub.ai_core import ProviderError
    from mediahub.content_engine.nl_inputs import interpret_planner_inputs

    with pytest.raises(ProviderError):
        interpret_planner_inputs("   ", goal_choices=GOAL_CHOICES)


def test_interpret_propagates_unconfigured_provider(monkeypatch):
    import mediahub.ai_core as ai_core
    from mediahub.ai_core import ProviderNotConfigured
    from mediahub.content_engine.nl_inputs import interpret_planner_inputs

    def boom(*a, **k):
        raise ProviderNotConfigured("no key configured")

    monkeypatch.setattr(ai_core, "ask_with_tools", boom, raising=True)
    with pytest.raises(ProviderNotConfigured):
        interpret_planner_inputs("note", goal_choices=GOAL_CHOICES)


# ---------------------------------------------------------------------------
# Web surface — route + nav move
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_with_org(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-test", display_name="Test Club"))
    application = wm.create_app()
    application.config["TESTING"] = True
    application.config["SECRET_KEY"] = "test-secret"
    return application


def _with_org(client, org_id: str = "org-test"):
    with client.session_transaction() as sess:
        sess["active_profile_id"] = org_id


def _primary_nav(html: str) -> str:
    a = html.find('id="mh-primary-nav"')
    assert a != -1, "top bar primary nav missing"
    return html[a : html.find("</nav>", a)]


def test_interpret_route_requires_org(app_with_org):
    with app_with_org.test_client() as client:
        r = client.post("/api/plan/interpret", json={"text": "x"})
        assert r.status_code == 403


def test_interpret_route_rejects_empty_note(app_with_org):
    with app_with_org.test_client() as client:
        _with_org(client)
        r = client.post("/api/plan/interpret", json={"text": "   "})
        assert r.status_code == 400


def test_interpret_route_happy_path(app_with_org, monkeypatch):
    import mediahub.content_engine.nl_inputs as nl

    seen = {}

    def fake_interpret(text, *, goal_choices, **kw):
        seen["text"] = text
        seen["goal_slugs"] = {s for s, _ in goal_choices}
        return {
            "upcoming_events": [{"name": "County", "date": "2026-07-12", "venue": "Ponds Forge"}],
            "blackout_dates": ["2026-08-31"],
            "goals": [{"post_type": "meet_recap", "note": "push recap"}],
            "summary": "ok",
            "research": [],
            "provider": "gemini",
        }

    monkeypatch.setattr(nl, "interpret_planner_inputs", fake_interpret, raising=True)
    with app_with_org.test_client() as client:
        _with_org(client)
        r = client.post("/api/plan/interpret", json={"text": "County champs on the 12th"})
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is True
        assert body["parsed"]["upcoming_events"][0]["venue"] == "Ponds Forge"
        # The route resolved the org's sport and handed real enabled slugs in.
        assert "meet_recap" in seen["goal_slugs"]
        assert seen["text"] == "County champs on the 12th"


def test_interpret_route_surfaces_provider_error(app_with_org, monkeypatch):
    import mediahub.content_engine.nl_inputs as nl
    from mediahub.ai_core import ProviderNotConfigured

    def boom(*a, **k):
        raise ProviderNotConfigured("no key")

    monkeypatch.setattr(nl, "interpret_planner_inputs", boom, raising=True)
    with app_with_org.test_client() as client:
        _with_org(client)
        r = client.post("/api/plan/interpret", json={"text": "note"})
        assert r.status_code == 503
        assert "no key" in r.get_json()["error"]


def test_plan_removed_from_top_bar_but_create_present(app_with_org):
    with app_with_org.test_client() as client:
        _with_org(client)
        html = client.get("/make").get_data(as_text=True)
        nav = _primary_nav(html)
        assert ">Create</a>" in nav
        assert ">Plan</a>" not in nav, "Plan must be gone from the desktop top bar"
        # …but the keyboard shortcut to Plan is intentionally kept.
        assert ">Go to Plan</a>" in html


def test_create_page_surfaces_plan_entry(app_with_org):
    with app_with_org.test_client() as client:
        _with_org(client)
        html = client.get("/make").get_data(as_text=True)
        # Plan is the predominant entry at the top of Create; like every tile it
        # opens its own "how it works" first slide, which then continues into the
        # planner itself.
        assert "Open Plan" in html
        assert 'href="/make/plan"' in html
        intro = client.get("/make/plan").get_data(as_text=True)
        assert "How it works" in intro
        assert 'href="/plan"' in intro  # the slide's CTA opens the planner


def test_plan_page_lives_under_create_with_nl_and_goals(app_with_org):
    with app_with_org.test_client() as client:
        _with_org(client)
        html = client.get("/plan").get_data(as_text=True)
        # Reads as living under Create (top-bar Create is the active item).
        assert 'class="active">Create</a>' in html
        # The Free-Text-style describe box + its interpret wiring.
        assert 'id="mh-plan-nl"' in html
        assert "Describe what" in html
        assert "function mhPlanInterpret" in html
        assert "/api/plan/interpret" in html
        # The optimised planning levers: venue on events + the goals control.
        assert 'id="mh-plan-ev-venue"' in html
        assert 'id="mh-plan-goals"' in html
        assert "function mhPlanAddGoal" in html


def test_inputs_route_round_trips_goals(app_with_org):
    """Regression: the save path keeps goals (the form used to drop them)."""
    with app_with_org.test_client() as client:
        _with_org(client)
        r = client.post(
            "/api/plan/inputs",
            json={
                "upcoming_events": [],
                "blackout_dates": [],
                "goals": [{"post_type": "meet_recap", "note": "push recap"}],
            },
        )
        assert r.status_code == 200
        assert r.get_json()["inputs"]["goals"] == [{"post_type": "meet_recap", "note": "push recap"}]
        # And it persists for the next load.
        got = client.get("/api/plan/inputs").get_json()["inputs"]
        assert got["goals"] == [{"post_type": "meet_recap", "note": "push recap"}]
