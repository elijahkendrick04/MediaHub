"""P6.2 — the copilot orchestrator, tool registry, and session store."""

from __future__ import annotations

from unittest import mock

from mediahub.ai_core import ProviderError, ProviderNotConfigured
from mediahub.ai_core.llm import ToolConversation
from mediahub.assistant import copilot, session as S, tools
from mediahub.assistant.patch import parse_patch
from mediahub.creative_brief.generator import CreativeBrief


def _brief(**over) -> CreativeBrief:
    base = dict(
        id="cb_src", content_item_id="swim_1", profile_id="club", achievement_summary="",
        objective="", primary_hook="NEW PB", confidence_label="NEW PB", tone="data-led",
        layout_template="split_diagonal_hero", inspiration_pattern_id="", image_treatment="cutout",
        text_hierarchy=[], brand_instructions="", sponsor_instructions=None, sourced_asset_ids=[],
        safety_notes=[], why_this_design="", text_layers={"headline_line1": "OLD"},
        palette={"primary": "#0E5BFF", "secondary": "#101820", "accent": "#F4D58D"},
        format_priority=["story"],
    )
    base.update(over)
    return CreativeBrief(**base)


# ---------------------------------------------------------------------------
# Tool registry — bounded allow-list, never publishes
# ---------------------------------------------------------------------------


def test_tool_schemas_are_well_formed():
    for t in tools.TOOLS:
        assert t["name"] and t["description"]
        assert t["input_schema"]["type"] == "object"
    names = tools.tool_names()
    assert {"read_design", "read_brand", "read_facts", "list_formats", "propose_edit"} <= set(names)


def test_no_publish_or_write_tool_exists():
    banned = ("publish", "post", "schedule", "send", "approve", "delete", "fetch", "http")
    for name in tools.tool_names():
        assert not any(b in name.lower() for b in banned), name


class _Brand:
    display_name = "Test Swim Club"
    primary_colour = "#0E5BFF"
    secondary_colour = "#101820"
    accent_colour = "#F4D58D"


def test_dispatch_reads_and_proposes():
    captured = {}
    ref = {"brief": _brief()}
    def _on(patch):
        captured["patch"] = patch
        return "ok-applied"

    dispatch = tools.make_dispatch(
        design_ref=ref, brand_kit=_Brand(), facts={"swimmer_name": "Alice Lee", "time": "57.9"},
        on_propose=_on,
    )
    assert "split_diagonal_hero" in dispatch("read_design", {})
    assert "Alice Lee" in dispatch("read_facts", {})
    assert "primary" in dispatch("read_brand", {})
    assert "ig_story" in dispatch("list_formats", {})
    out = dispatch("propose_edit", {"ops": [{"kind": "set_mood", "mood": "bold"}]})
    assert out == "ok-applied" and captured["patch"].ops[0].kind == "set_mood"
    assert dispatch("propose_edit", {"ops": []}).startswith("No valid")


# ---------------------------------------------------------------------------
# Session store
# ---------------------------------------------------------------------------


def test_session_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = S.create_session("run1", "swim_1", profile_id="club")
    s.add_message("user", "hi")
    s.add_message("assistant", "hello")
    S.save_session(s)
    loaded = S.load_session("run1", "swim_1", s.session_id)
    assert loaded is not None and len(loaded.messages) == 2
    assert S.get_or_create("run1", "swim_1", s.session_id).session_id == s.session_id
    # unknown session id → fresh
    assert S.get_or_create("run1", "swim_1", "nope").session_id != s.session_id
    assert S.latest_session("run1", "swim_1") is not None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def _fake_convo_calling_propose(ops):
    def _fake(system, user, *, tools, on_tool_call, **kw):
        on_tool_call("read_design", {})
        result = on_tool_call("propose_edit", {"ops": ops})
        return ToolConversation(text="Updated the design.", provider="gemini", tool_calls=[])
    return _fake


def test_run_turn_applies_proposed_edits(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    sess = S.create_session("run1", "swim_1", profile_id="club")
    fake = _fake_convo_calling_propose([{"kind": "set_headline", "text": "SEASON BEST"}, {"kind": "set_mood", "mood": "triumphant"}])
    with mock.patch("mediahub.ai_core.ask_with_tools", fake):
        turn = copilot.run_turn(session=sess, user_message="punch it up", brief=_brief(), brand_kit=None, profile_id="club")
    assert turn.changed and turn.ai_available
    assert turn.brief.text_layers["headline_line1"] == "SEASON BEST"
    assert turn.brief.mood == "triumphant"
    assert [o.kind for o in turn.applied] == ["set_headline", "set_mood"]
    # session recorded the turn + an edit entry
    assert len(sess.messages) == 2 and len(sess.edits) == 1
    assert sess.edits[0]["brief_after"] == turn.brief.id


def test_run_turn_records_rejections(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    sess = S.create_session("run1", "swim_1")
    fake = _fake_convo_calling_propose([{"kind": "set_mood", "mood": "not_real"}])
    with mock.patch("mediahub.ai_core.ask_with_tools", fake):
        turn = copilot.run_turn(session=sess, user_message="x", brief=_brief())
    assert not turn.changed and turn.rejected


def test_run_turn_no_provider_is_honest(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    sess = S.create_session("run1", "swim_1")

    def boom(*a, **k):
        raise ProviderNotConfigured("no key")

    with mock.patch("mediahub.ai_core.ask_with_tools", boom):
        turn = copilot.run_turn(session=sess, user_message="make it navy", brief=_brief())
    assert turn.ai_available is False and not turn.changed
    assert "manual controls" in turn.reply
    assert turn.brief.text_layers["headline_line1"] == "OLD"  # untouched


def test_run_turn_provider_error_is_honest(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    sess = S.create_session("run1", "swim_1")

    def boom(*a, **k):
        raise ProviderError("boom")

    with mock.patch("mediahub.ai_core.ask_with_tools", boom):
        turn = copilot.run_turn(session=sess, user_message="x", brief=_brief())
    assert turn.ai_available is True and not turn.changed


def test_run_turn_explain_without_edit(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    sess = S.create_session("run1", "swim_1")

    def fake(system, user, *, tools, on_tool_call, **kw):
        on_tool_call("read_facts", {})
        return ToolConversation(text="It ranked first because it was a confirmed PB.", provider="gemini")

    with mock.patch("mediahub.ai_core.ask_with_tools", fake):
        turn = copilot.run_turn(session=sess, user_message="why did this rank first?", brief=_brief(), facts={"why": "confirmed PB"})
    assert not turn.changed and "ranked first" in turn.reply


def test_memory_injected_into_system_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.assistant import memory as _amem

    _amem.remember("club", "Never show times for 8-and-unders")
    sess = S.create_session("run1", "swim_1", profile_id="club")
    seen = {}

    def fake(system, user, *, tools, on_tool_call, **kw):
        seen["system"] = system
        return ToolConversation(text="ok", provider="gemini")

    with mock.patch("mediahub.ai_core.ask_with_tools", fake):
        copilot.run_turn(session=sess, user_message="hide the times", brief=_brief(), profile_id="club")
    assert "8-and-unders" in seen["system"]


def test_suggested_prompts_fallback():
    out = copilot.suggested_prompts()
    assert out and all(isinstance(s, str) for s in out)
