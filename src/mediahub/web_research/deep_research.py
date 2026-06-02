"""mediahub/web_research/deep_research.py — bounded deep-research ReAct loop.

Capability 3b. A model-agnostic, BOUNDED research loop built on Capability 1's
tool-calling (``ai_core.ask_with_tools``): the model gets two narrow tools —
``search`` (via ``WebResearcher``: SearXNG / DuckDuckGo) and ``fetch_url`` (via
the SSRF-hardened ``safe_fetch``) — and is asked to answer a question with
cited, verified facts.

**Cost (£0):** runs on MediaHub's EXISTING LLM provider — Gemini's free tier by
default, the same one captions use — so there is no new service or bill. Usage
is bounded by a hard round cap and a per-round token cap (env-tunable) so it
cannot run away (the council's token-budget requirement), and it only runs when
explicitly invoked.

**Honesty:** if the loop hits its round bound without concluding, the result is
``complete=False`` and the partial (possibly-wrong) synthesis is DISCARDED — it
is never returned as an answer (the council's "discard, don't poison"). Every
result also carries its source URLs and the subset on authoritative domains, so
whatever later persists a finding can gate STRUCTURALLY, not on model trust.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from mediahub.web_research import verify
from mediahub.web_research.safe_fetch import safe_fetch
from mediahub.web_research.search import WebResearcher

log = logging.getLogger(__name__)

DEFAULT_MAX_ROUNDS = 4
DEFAULT_MAX_TOKENS = 1200
_INCOMPLETE_MARKER = "still gathering evidence"

_SYSTEM = (
    "You are a meticulous web researcher. Answer the user's question using ONLY "
    "the search and fetch_url tools. Workflow: search for sources, then fetch the "
    "most promising one or two to CONFIRM facts before relying on them. Prefer "
    "official / authoritative sources. Never invent facts, names, times, or "
    "numbers — if the sources don't support a claim, say what you could and could "
    "not verify. When done, give a concise answer and list the source URLs you "
    "actually used. Be efficient: a few targeted searches and fetches, not many."
)

_TOOLS = [
    {
        "name": "search",
        "description": "Search the web. Returns a numbered list of results (title, URL, snippet).",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "The search query."}},
            "required": ["query"],
        },
    },
    {
        "name": "fetch_url",
        "description": (
            "Fetch the readable text of one web page by URL (truncated). Use after "
            "search to read and confirm a promising result."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "The page URL to read."}},
            "required": ["url"],
        },
    },
]


@dataclass
class ResearchResult:
    """Outcome of a research run. ``answer`` is "" when ``complete`` is False
    (partial synthesis is discarded). ``sources`` are the URLs the loop touched;
    ``authority_sources`` is the subset on authoritative domains."""

    answer: str
    sources: list[str] = field(default_factory=list)
    authority_sources: list[str] = field(default_factory=list)
    complete: bool = False
    rounds: int = 0
    tool_calls: int = 0


def _max_rounds() -> int:
    raw = os.environ.get("MEDIAHUB_RESEARCH_MAX_ROUNDS", "").strip()
    try:
        return max(1, min(8, int(raw))) if raw else DEFAULT_MAX_ROUNDS
    except ValueError:
        return DEFAULT_MAX_ROUNDS


def _max_tokens() -> int:
    raw = os.environ.get("MEDIAHUB_RESEARCH_MAX_TOKENS", "").strip()
    try:
        return max(256, min(4000, int(raw))) if raw else DEFAULT_MAX_TOKENS
    except ValueError:
        return DEFAULT_MAX_TOKENS


def deep_research(
    question: str, *, max_rounds: Optional[int] = None, provider: Optional[str] = None
) -> ResearchResult:
    """Run a bounded, cited research loop.

    Raises ``ProviderNotConfigured`` when no AI provider is configured (honest
    error — never fabricates research).
    """
    from mediahub.ai_core.llm import ask_with_tools  # lazy: provider may be absent

    question = (question or "").strip()
    if not question:
        return ResearchResult(answer="", complete=False)

    researcher = WebResearcher()
    sources: list[str] = []
    seen: set[str] = set()

    def _record(url: str) -> None:
        url = (url or "").strip()
        if url and url not in seen:
            seen.add(url)
            sources.append(url)

    def on_tool(name: str, args: dict) -> str:
        if name == "search":
            query = (args.get("query") or "").strip()
            if not query:
                return "(no query provided)"
            try:
                results = researcher.search(query, num=5)
            except Exception as e:
                return f"(search failed: {e})"
            if not results:
                return "(no results)"
            lines = []
            for i, r in enumerate(results, 1):
                _record(r.url)
                lines.append(f"{i}. {r.title}\n   {r.url}\n   {r.snippet}".rstrip())
            return "\n".join(lines)
        if name == "fetch_url":
            url = (args.get("url") or "").strip()
            _record(url)
            return safe_fetch(url) or "(could not fetch or parse this page)"
        return f"(unknown tool: {name})"

    rounds = max_rounds if max_rounds is not None else _max_rounds()
    rounds = max(1, min(8, int(rounds)))
    convo = ask_with_tools(
        _SYSTEM,
        question,
        tools=_TOOLS,
        on_tool_call=on_tool,
        max_tokens=_max_tokens(),
        max_rounds=rounds,
        provider=provider,
    )
    answer = (convo.text or "").strip()
    complete = bool(answer) and _INCOMPLETE_MARKER not in answer.lower()
    log.info(
        "deep_research: complete=%s rounds<=%d tool_calls=%d sources=%d",
        complete,
        rounds,
        len(convo.tool_calls),
        len(sources),
    )
    return ResearchResult(
        answer=answer if complete else "",
        sources=sources,
        authority_sources=verify.authority_sources(sources),
        complete=complete,
        rounds=rounds,
        tool_calls=len(convo.tool_calls),
    )


__all__ = ["ResearchResult", "deep_research"]
