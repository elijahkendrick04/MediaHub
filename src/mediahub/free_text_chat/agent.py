"""Free-text chat assistant — Claude-driven brief builder with tool use.

The agent talks to Claude (Anthropic API) using native tool-use. Claude
decides when to research the web, when to ask a clarifying question, and
when to propose a brief — there is no hand-coded action enum, no JSON
parsing protocol, no rules about "ask one question at a time" baked into
this module. All reasoning is the model's.

Tools exposed to Claude:
  - research_web(query)     → server runs the existing ResearchClient
                              and returns snippets so Claude can ground.
  - propose_brief(brief)    → marks the brief as pending in the session
                              so the UI can show Accept / Decline.

Anything Claude says outside a tool call is rendered as a chat message
to the user.

Per user direction, this module requires Anthropic to be configured.
Other providers (Gemini, claude-cli) are not used here because Claude's
tool-use API is the abstraction we rely on. If no Anthropic key is
present, the chat surfaces a clear "configure Anthropic in Settings"
message rather than silently degrading.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from .session import ChatSession, save_session


_SYSTEM_PROMPT = """\
You are MediaHub's brief-building assistant. You help a sports club or
society turn a free-text idea into a structured brief that the content
generator turns into a branded post.

Your behaviour, in plain language:
- Talk to the user like a thoughtful editor. Reuse facts they've already
  given you — never re-ask.
- When you want to verify a name, venue, event, or PB, use the
  `research_web` tool. Don't guess facts about real people / clubs / venues.
- When you have enough to build a brief, call the `propose_brief` tool.
  The brief object is yours to shape — what you'd hand a designer.
- After a brief is proposed and the user pushes back, call
  `propose_brief` again with a revised version.
- Don't pile questions. Ask the one thing that unblocks you most.
"""


_TOOLS = [
    {
        "name": "research_web",
        "description": (
            "Search the web for evidence about a swimmer, club, venue, event, "
            "or any fact you want to verify before answering. Use this whenever "
            "you'd otherwise have to guess about a real-world entity. Returns a "
            "list of snippets with title, url, snippet, and domain."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query":  {"type": "string",
                           "description": "The web search query."},
                "reason": {"type": "string",
                           "description": "Why you need this (for audit/logging)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "propose_brief",
        "description": (
            "Propose a content brief for the user to accept or decline. The "
            "brief is whatever structured object the content generators need "
            "— headline, body, hashtags, visual concept, tone, platform, etc. "
            "Call this again to revise the brief after user feedback."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brief":   {"type": "object",
                            "description": "The brief object."},
                "summary": {"type": "string",
                            "description": "One-line summary of the brief shown to the user."},
            },
            "required": ["brief"],
        },
    },
]


# Anthropic-side model id is read from llm.py's DEFAULT_MODEL (the env var
# MEDIAHUB_LLM_MODEL takes precedence in production).
def _model() -> str:
    from mediahub.media_ai import llm
    return llm.DEFAULT_MODEL


def _get_client():
    """Return an Anthropic client or None if unconfigured."""
    from mediahub.media_ai import llm
    return llm._get_anthropic()


def _build_messages(session: ChatSession) -> list[dict]:
    """Map the session's message log to Anthropic message blocks."""
    out: list[dict] = []
    for m in session.messages:
        role = m.get("role")
        content = m.get("content", "")
        if role == "user":
            out.append({"role": "user", "content": content})
        elif role == "assistant":
            out.append({"role": "assistant", "content": content})
        elif role == "system_note":
            # Surface system notes (e.g. tool-use audit trail rendered for
            # the UI) as user messages so Claude can still see them across
            # a restart of the conversation. New tool_use round-trips done
            # WITHIN this call live in the local `working` list below.
            out.append({"role": "user", "content": content})
    return out


def _run_research(query: str) -> list[dict]:
    try:
        from mediahub.context_engine.research import ResearchClient
        client = ResearchClient(num_results=4)
        hits = client.search(query, num=4)
    except Exception:
        return []
    out: list[dict] = []
    for h in hits:
        snip = (h.snippet or "").strip()
        if not snip:
            continue
        out.append({
            "title":   (h.title or "")[:160],
            "url":     h.url,
            "snippet": snip[:400],
            "domain":  h.domain,
        })
    return out


def next_assistant_turn(session: ChatSession,
                        club_brand: Optional[dict] = None,
                        max_tool_rounds: int = 4) -> dict:
    """One assistant turn. Returns a dict describing what to show the user.

    Shape of the return value:
      {"kind": "message",  "text": str}           — plain chat reply / question
      {"kind": "brief",    "brief": dict,         — Claude proposed a brief
                            "summary": str}
      {"kind": "error",    "text": str}           — provider not configured / call failed
    """
    client = _get_client()
    if client is None:
        msg = (
            "Anthropic (Claude) isn't configured, so the brief-building chat "
            "can't run. Add an Anthropic API key in Settings — the chat uses "
            "Claude's tool-use to research and reason."
        )
        session.add_assistant_message(msg, meta={"error": "no_anthropic"})
        save_session(session)
        return {"kind": "error", "text": msg}

    system = _SYSTEM_PROMPT
    if club_brand:
        system = system + "\n\nClub/brand context (JSON):\n" + json.dumps(
            club_brand, ensure_ascii=False
        )

    messages = _build_messages(session)
    if not messages:
        return {"kind": "error", "text": "No user message to respond to."}

    proposed_brief: Optional[dict] = None
    proposed_summary: Optional[str] = None
    final_text_parts: list[str] = []

    for _round in range(max_tool_rounds):
        try:
            resp = client.messages.create(
                model=_model(),
                system=system,
                tools=_TOOLS,
                max_tokens=1200,
                messages=messages,
            )
        except Exception as e:
            msg = f"Claude call failed: {str(e)[:240]}"
            session.add_assistant_message(msg, meta={"error": "claude_call_failed"})
            save_session(session)
            return {"kind": "error", "text": msg}

        # Build the assistant message we'll append to `messages` for the
        # NEXT round, preserving all content blocks (text + tool_use).
        assistant_blocks: list[dict] = []
        tool_uses: list[dict] = []
        text_blocks: list[str] = []
        for b in resp.content:
            t = getattr(b, "type", None)
            if t == "text":
                text_blocks.append(getattr(b, "text", "") or "")
                assistant_blocks.append({"type": "text",
                                          "text": getattr(b, "text", "") or ""})
            elif t == "tool_use":
                tu = {
                    "type":  "tool_use",
                    "id":    getattr(b, "id", ""),
                    "name":  getattr(b, "name", ""),
                    "input": getattr(b, "input", {}) or {},
                }
                tool_uses.append(tu)
                assistant_blocks.append(tu)

        messages.append({"role": "assistant", "content": assistant_blocks})

        # No tool calls — Claude is done, the text blocks are the reply.
        if not tool_uses:
            final_text_parts = text_blocks
            break

        # Run tools, append tool_result blocks, loop.
        tool_results: list[dict] = []
        for tu in tool_uses:
            name = tu["name"]
            inp = tu["input"] or {}
            if name == "research_web":
                query = (inp.get("query") or "").strip()
                hits = _run_research(query) if query else []
                session.research_log.append({
                    "query":  query,
                    "reason": inp.get("reason", ""),
                    "hits":   hits,
                })
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": tu["id"],
                    "content":     json.dumps({"hits": hits}, ensure_ascii=False),
                })
            elif name == "propose_brief":
                brief = inp.get("brief") or {}
                summary = inp.get("summary") or ""
                if isinstance(brief, dict):
                    proposed_brief = brief
                    proposed_summary = summary
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": tu["id"],
                    "content":     json.dumps({"ok": True}, ensure_ascii=False),
                })
            else:
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": tu["id"],
                    "content":     json.dumps({"error": f"unknown tool: {name}"}),
                    "is_error":    True,
                })
        messages.append({"role": "user", "content": tool_results})

    # Persist the assistant's final reply.
    text = "\n\n".join(t.strip() for t in final_text_parts if t and t.strip()).strip()
    if proposed_brief is not None:
        session.pending_brief = proposed_brief
        shown_summary = proposed_summary or text or "Here's a draft brief."
        session.add_assistant_message(shown_summary, meta={
            "kind":  "brief",
            "brief": proposed_brief,
        })
        save_session(session)
        return {"kind": "brief", "brief": proposed_brief, "summary": shown_summary}

    if not text:
        text = "(no reply — try again)"
    session.add_assistant_message(text, meta={"kind": "message"})
    save_session(session)
    return {"kind": "message", "text": text}
