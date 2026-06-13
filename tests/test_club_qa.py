"""Tests for club_qa — the "ask the data" bounded tool-loop agent.

Offline throughout: the LLM loop is faked, so these tests pin the parts we
own — the three read-only tools' output, tenant isolation, provenance
collection, and honest provider-error propagation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from mediahub.club_qa import QAEnv, answer_club_question
from mediahub.club_qa.agent import (
    _fmt_cs,
    _tool_get_athlete_history,
    _tool_get_run_details,
    _tool_list_recent_runs,
)


def _run(run_id: str, profile_id: str, meet_name: str, start_date: str) -> dict:
    return {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {
            "name": meet_name,
            "start_date": start_date,
            "venue": "Demo Pool",
            "course": "LC",
        },
        "recognition_report": {
            "ranked_achievements": [
                {
                    "achievement": {
                        "swimmer_name": "Alice Lee",
                        "swimmer_id": "s1",
                        "event": "100m Freestyle",
                        "time": "57.95",
                        "headline": "New PB in 100 Free",
                        "type": "pb_confirmed",
                        "raw_facts": {"time_str": "57.95"},
                    },
                    "priority": 0.92,
                }
            ]
        },
    }


@pytest.fixture
def env(tmp_path) -> QAEnv:
    runs = tmp_path / "runs_v4"
    runs.mkdir()
    (runs / "r1.json").write_text(json.dumps(_run("r1", "org-a", "Spring Open 2026", "2026-04-10")))
    (runs / "r2.json").write_text(json.dumps(_run("r2", "org-a", "Winter Gala 2025", "2025-12-01")))
    # Another org's run and an ownerless legacy run — both invisible to org-a.
    (runs / "rx.json").write_text(json.dumps(_run("rx", "org-b", "Rival Meet", "2026-03-01")))
    (runs / "r0.json").write_text(json.dumps(_run("r0", "", "Untagged Meet", "2026-01-01")))
    # Sidecars must never be mistaken for runs.
    (runs / "r1__workflow.json").write_text("{}")
    return QAEnv(
        runs_dir=runs,
        profile_id="org-a",
        athletes_db_path=tmp_path / "athletes.db",
    )


# --- time formatting ----------------------------------------------------------


def test_fmt_cs():
    assert _fmt_cs(5795) == "57.95"
    assert _fmt_cs(12834) == "2:08.34"
    assert _fmt_cs(None) == ""
    assert _fmt_cs(0) == ""


# --- tools ---------------------------------------------------------------------


def test_list_recent_runs_is_org_scoped_and_newest_first(env):
    out = _tool_list_recent_runs(env)
    assert "Spring Open 2026" in out and "Winter Gala 2025" in out
    # Strict tenancy: other orgs' and ownerless runs never leak into answers.
    assert "Rival Meet" not in out and "Untagged Meet" not in out
    assert out.index("Spring Open 2026") < out.index("Winter Gala 2025")


def test_get_run_details_returns_achievements(env):
    out = _tool_get_run_details(env, "r1")
    assert "Spring Open 2026" in out
    assert "Alice Lee" in out and "57.95" in out and "pb_confirmed" in out


def test_get_run_details_refuses_foreign_and_unknown_runs(env):
    assert _tool_get_run_details(env, "rx").startswith("No run")
    assert _tool_get_run_details(env, "r0").startswith("No run")
    assert _tool_get_run_details(env, "nope").startswith("No run")


def test_athlete_history_reads_registry(env):
    from mediahub.athletes import record_run_swims

    record_run_swims(
        "org-a",
        "r1",
        [{"name": "Alice Lee", "event": "100FRLC", "time_cs": 5795, "swim_date": "2026-04-10"}],
        db_path=env.athletes_db_path,
    )
    out = _tool_get_athlete_history(env, "Alice Lee")
    assert "Alice Lee" in out
    assert "57.95" in out
    assert "Spring Open 2026" in out  # run_id mapped to its meet name


def test_athlete_history_unknown_name(env):
    out = _tool_get_athlete_history(env, "Nobody Here")
    assert "No athlete named" in out


# --- the agent loop -------------------------------------------------------------


@dataclass
class _FakeConvo:
    text: str
    provider: str = "fake"
    tool_calls: list = field(default_factory=list)


def test_answer_collects_provenance_and_passes_tools(monkeypatch, env):
    """Drive the agent with a fake loop that uses every tool like a model would."""
    transcript: dict = {}

    def fake_ask_with_tools(system, user, *, tools, on_tool_call, **kw):
        transcript["system"] = system
        transcript["tools"] = [t["name"] for t in tools]
        listing = on_tool_call("list_recent_runs", {})
        details = on_tool_call("get_run_details", {"run_id": "r1"})
        denied = on_tool_call("get_run_details", {"run_id": "rx"})
        unknown = on_tool_call("made_up_tool", {})
        transcript["listing"] = listing
        transcript["denied"] = denied
        transcript["unknown"] = unknown
        assert "Alice Lee" in details
        return _FakeConvo(
            text="Alice Lee's best 100m Freestyle is 57.95, at Spring Open 2026.",
            tool_calls=[1, 2, 3, 4],
        )

    monkeypatch.setattr("mediahub.ai_core.ask_with_tools", fake_ask_with_tools)
    res = answer_club_question("What is Alice's best 100 Free?", env)

    assert "57.95" in res.answer
    assert res.tool_calls == 4
    # Only the run that actually answered (and was owned) is cited.
    assert res.runs_consulted == [{"run_id": "r1", "meet_name": "Spring Open 2026"}]
    # Grounding rules reach the model; all three tools are offered.
    assert "ONLY the tools" in transcript["system"]
    assert set(transcript["tools"]) == {
        "list_recent_runs",
        "get_run_details",
        "get_athlete_history",
    }
    assert transcript["denied"].startswith("No run")
    assert "unknown tool" in transcript["unknown"]


def test_provider_not_configured_propagates(monkeypatch, env):
    from mediahub.ai_core import ProviderNotConfigured

    def boom(*a, **kw):
        raise ProviderNotConfigured("no provider configured")

    monkeypatch.setattr("mediahub.ai_core.ask_with_tools", boom)
    with pytest.raises(ProviderNotConfigured):
        answer_club_question("anything", env)


def test_empty_question_short_circuits_without_llm(monkeypatch, env):
    def boom(*a, **kw):  # pragma: no cover — must not be reached
        raise AssertionError("LLM must not be called for an empty question")

    monkeypatch.setattr("mediahub.ai_core.ask_with_tools", boom)
    res = answer_club_question("   ", env)
    assert "No question" in res.answer
