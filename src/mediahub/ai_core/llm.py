"""Provider-agnostic Claude (Anthropic) + Gemini interface for ai_core.

Public API:

  ask(system, user)                           → str (plain text)
  ask_with_tools(system, user, tools, on_tool_call) → ToolConversation

Both raise ``ProviderNotConfigured`` if no provider is configured (or
the explicitly-chosen one is missing its key) and ``ProviderError`` on
a transport / API error.

No templates, no JSON envelopes, no heuristic substitutes. If the model
won't answer, the caller is told and surfaces it to the user.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

class ProviderNotConfigured(RuntimeError):
    """Raised when no LLM provider has been configured."""


class ProviderError(RuntimeError):
    """Raised when an LLM provider's API call fails."""


@dataclass
class ToolCallRecord:
    name: str
    input: dict
    result: str
    provider: str = ""


@dataclass
class ToolConversation:
    text: str
    provider: str = ""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

# Provider order: Gemini first (free default), Claude as paid quality option.
# OpenAI was deliberately removed in the operator-config rewrite — the
# product is Gemini-first per the dissertation's cost model, with Anthropic
# as an explicit operator override via MEDIAHUB_LLM_PROVIDER=claude.
_PROVIDERS = ("gemini", "claude")


def _resolve_key(env_names: tuple[str, ...], secret_name: str) -> Optional[str]:
    for env_name in env_names:
        v = os.environ.get(env_name, "").strip()
        if v:
            return v
    try:
        from mediahub.web.secrets_store import get_secret
        v = get_secret(secret_name)
        return v.strip() if v else None
    except Exception:
        return None


def _key_for(provider: str) -> Optional[str]:
    if provider == "claude":
        return _resolve_key(("ANTHROPIC_API_KEY",), "anthropic_api_key")
    if provider == "gemini":
        return _resolve_key(("GEMINI_API_KEY", "GOOGLE_API_KEY"), "gemini_api_key")
    return None


def _preferred_pref() -> str:
    """Read the user's preferred provider. 'auto' = use the first configured."""
    env = os.environ.get("MEDIAHUB_LLM_PROVIDER", "").strip().lower()
    if env in _PROVIDERS + ("auto",):
        return env
    try:
        from mediahub.web.secrets_store import get_secret
        v = (get_secret("mediahub_llm_provider") or "").strip().lower()
        if v in _PROVIDERS + ("auto",):
            return v
    except Exception:
        pass
    return "auto"


def active_provider() -> Optional[str]:
    """Return the provider that will actually be used for the next call.

    Honours the user's pref if its key is configured, otherwise falls
    through the default order (gemini → claude) and returns the
    first configured one. None if nothing is configured.
    """
    pref = _preferred_pref()
    if pref in _PROVIDERS and _key_for(pref):
        return pref
    for p in _PROVIDERS:
        if _key_for(p):
            return p
    return None


# ---------------------------------------------------------------------------
# Anthropic (Claude) — text + native tool-use
# ---------------------------------------------------------------------------

_anthropic_client = None
_anthropic_client_key = None


def _anthropic_client_for(key: str):
    global _anthropic_client, _anthropic_client_key
    if _anthropic_client is not None and _anthropic_client_key == key:
        return _anthropic_client
    try:
        import anthropic
    except ImportError as e:
        raise ProviderError(f"anthropic SDK not installed: {e}")
    _anthropic_client = anthropic.Anthropic(api_key=key)
    _anthropic_client_key = key
    return _anthropic_client


def _anthropic_model() -> str:
    return os.environ.get("MEDIAHUB_LLM_MODEL", "claude-sonnet-4-5-20250929")


def _ask_claude(system: str, user: str, max_tokens: int) -> str:
    key = _key_for("claude")
    if not key:
        raise ProviderNotConfigured("Anthropic API key not configured.")
    client = _anthropic_client_for(key)
    try:
        resp = client.messages.create(
            model=_anthropic_model(),
            system=system,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": user}],
        )
    except Exception as e:
        raise ProviderError(f"Anthropic call failed: {e}") from e
    parts = [getattr(b, "text", "") or "" for b in resp.content
             if getattr(b, "type", None) == "text"]
    return "".join(parts).strip()


def _ask_claude_with_tools(system: str, user: str, tools: list[dict],
                            on_tool_call: Callable[[str, dict], str],
                            max_tokens: int, max_rounds: int) -> ToolConversation:
    key = _key_for("claude")
    if not key:
        raise ProviderNotConfigured("Anthropic API key not configured.")
    client = _anthropic_client_for(key)
    model = _anthropic_model()
    messages: list[dict] = [{"role": "user", "content": user}]
    convo = ToolConversation(text="", provider="claude")
    for _ in range(max_rounds):
        try:
            resp = client.messages.create(
                model=model, system=system, tools=tools,
                max_tokens=max_tokens, messages=messages,
            )
        except Exception as e:
            raise ProviderError(f"Anthropic tool call failed: {e}") from e
        blocks: list[dict] = []
        tool_uses: list[dict] = []
        texts: list[str] = []
        for b in resp.content:
            t = getattr(b, "type", None)
            if t == "text":
                txt = getattr(b, "text", "") or ""
                texts.append(txt)
                blocks.append({"type": "text", "text": txt})
            elif t == "tool_use":
                tu = {"type": "tool_use", "id": getattr(b, "id", ""),
                      "name": getattr(b, "name", ""),
                      "input": getattr(b, "input", {}) or {}}
                tool_uses.append(tu)
                blocks.append(tu)
        messages.append({"role": "assistant", "content": blocks})
        if not tool_uses:
            convo.text = "\n\n".join(t.strip() for t in texts if t and t.strip()).strip()
            return convo
        results: list[dict] = []
        for tu in tool_uses:
            try:
                r = on_tool_call(tu["name"], tu["input"])
            except Exception as e:
                r = f"(tool {tu['name']!r} failed: {e})"
            convo.tool_calls.append(ToolCallRecord(
                name=tu["name"], input=tu["input"], result=r, provider="claude",
            ))
            results.append({"type": "tool_result",
                             "tool_use_id": tu["id"], "content": r})
        messages.append({"role": "user", "content": results})
    convo.text = "(Claude is still gathering evidence; try a smaller question.)"
    return convo


# ---------------------------------------------------------------------------
# Gemini (Google) — text + native tool-use; free-tier default
# ---------------------------------------------------------------------------
def _gemini_model() -> str:
    # May 2026: gemini-2.0-flash was deprecated by Google and now
    # returns HTTP 404 "model is no longer available to new users".
    # gemini-2.5-flash is the current GA model with the same free-tier
    # quotas (1,500 req/day) and equivalent capability.
    return os.environ.get("MEDIAHUB_GEMINI_MODEL", "gemini-2.5-flash")


def _ask_gemini(system: str, user: str, max_tokens: int) -> str:
    key = _key_for("gemini")
    if not key:
        raise ProviderNotConfigured("Gemini API key not configured.")
    try:
        import requests
    except ImportError as e:
        raise ProviderError(f"requests not available: {e}")
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": int(max_tokens),
                              "temperature": 0.7},
    }
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{_gemini_model()}:generateContent"
    )
    try:
        r = requests.post(url, params={"key": key}, json=payload,
                          headers={"Content-Type": "application/json"},
                          timeout=45)
    except Exception as e:
        raise ProviderError(f"Gemini HTTP error: {e}") from e
    if r.status_code != 200:
        raise ProviderError(f"Gemini HTTP {r.status_code}: {r.text[:240]}")
    try:
        data = r.json()
    except Exception as e:
        raise ProviderError(f"Gemini bad JSON: {e}") from e
    cands = data.get("candidates") or []
    if not cands:
        raise ProviderError(f"Gemini empty response: {str(data)[:240]}")
    parts = ((cands[0].get("content") or {}).get("parts") or [])
    return "".join(p.get("text", "") for p in parts
                    if isinstance(p, dict)).strip()


def _ask_gemini_with_tools(system: str, user: str, tools: list[dict],
                            on_tool_call: Callable[[str, dict], str],
                            max_tokens: int, max_rounds: int) -> ToolConversation:
    """Gemini function-calling loop. Tool schema in Anthropic shape is
    translated to Gemini's functionDeclarations on the fly so callers
    pass the same `tools` list whichever provider is active."""
    import requests
    import json
    key = _key_for("gemini")
    if not key:
        raise ProviderNotConfigured("Gemini API key not configured.")
    # Translate tool schema.
    fn_decls = [{
        "name":        t["name"],
        "description": t.get("description", ""),
        "parameters":  t.get("input_schema") or t.get("parameters")
                        or {"type": "object", "properties": {}},
    } for t in tools]
    contents: list[dict] = [{"role": "user", "parts": [{"text": user}]}]
    convo = ToolConversation(text="", provider="gemini")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{_gemini_model()}:generateContent"
    )
    for _ in range(max_rounds):
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents":          contents,
            "tools":             [{"functionDeclarations": fn_decls}],
            "generationConfig":  {"maxOutputTokens": int(max_tokens),
                                   "temperature": 0.7},
        }
        try:
            r = requests.post(url, params={"key": key}, json=payload,
                              headers={"Content-Type": "application/json"},
                              timeout=60)
        except Exception as e:
            raise ProviderError(f"Gemini tool HTTP error: {e}") from e
        if r.status_code != 200:
            raise ProviderError(f"Gemini tool HTTP {r.status_code}: {r.text[:240]}")
        data = r.json()
        cands = data.get("candidates") or []
        if not cands:
            raise ProviderError(f"Gemini empty response: {str(data)[:240]}")
        content = cands[0].get("content") or {}
        parts = content.get("parts") or []
        # Capture the assistant turn whole so the next loop sees it.
        contents.append({"role": "model", "parts": parts})
        fn_calls = []
        text_buf: list[str] = []
        for part in parts:
            if "functionCall" in part:
                fn_calls.append(part["functionCall"])
            elif "text" in part:
                text_buf.append(part.get("text", ""))
        if not fn_calls:
            convo.text = "".join(text_buf).strip()
            return convo
        tool_response_parts = []
        for fc in fn_calls:
            name = fc.get("name", "")
            args = fc.get("args", {}) or {}
            try:
                r_str = on_tool_call(name, args)
            except Exception as e:
                r_str = f"(tool {name!r} failed: {e})"
            convo.tool_calls.append(ToolCallRecord(
                name=name, input=args, result=r_str, provider="gemini",
            ))
            tool_response_parts.append({"functionResponse": {
                "name":     name,
                "response": {"content": r_str},
            }})
        contents.append({"role": "user", "parts": tool_response_parts})
    convo.text = "(Gemini is still gathering evidence; try a smaller question.)"
    return convo


# ---------------------------------------------------------------------------
# Public dispatch
# ---------------------------------------------------------------------------

_DISPATCH = {
    "claude": (_ask_claude, _ask_claude_with_tools),
    "gemini": (_ask_gemini, _ask_gemini_with_tools),
}


def _fallback_chain(primary: Optional[str]) -> list[str]:
    """Return the provider order to try, starting with `primary` (if
    configured) then the remaining configured providers. Lets a rate-
    limited Gemini call fall through to Claude instead of erroring
    at the user."""
    chain: list[str] = []
    if primary and _key_for(primary):
        chain.append(primary)
    for p in _PROVIDERS:
        if p != primary and _key_for(p):
            chain.append(p)
    return chain


def _is_transient(err_msg: str) -> bool:
    """Heuristic: should we retry on the next configured provider?
    Auth errors, rate limits, and HTTP 5xx warrant trying another
    provider; everything else is the model returning legit nonsense
    and won't fix on a retry."""
    s = err_msg.lower()
    return (
        "429" in s or "rate" in s
        or "401" in s or "403" in s
        or "auth" in s
        or " 500" in s or "502" in s or "503" in s or "504" in s
        or "timeout" in s or "timed out" in s
        or "overloaded" in s
    )


def ask(system: str, user: str, *, max_tokens: int = 800,
        provider: Optional[str] = None) -> str:
    """Plain-text in, plain-text out.

    Tries the active provider first; on a *transient* failure (429, 401,
    403, 5xx, timeout) it walks through any other configured AI provider
    so the user isn't blocked by one model's rate limit. There is no
    fallback to hardcoded templates / heuristics anywhere in the
    codebase — when every configured AI fails, the caller gets the raw
    ProviderError so the UI can surface "your AI is unavailable
    because X; fix it by Y" instead of silently producing fake content.
    """
    primary = (provider or active_provider() or "").lower() or None
    chain = _fallback_chain(primary) if primary else []
    if not chain:
        raise ProviderNotConfigured(
            "AI features are unavailable on this deployment. The "
            "operator has not configured a Gemini or Anthropic API key. "
            "Contact your administrator."
        )
    last_err: Optional[Exception] = None
    for p in chain:
        try:
            return _DISPATCH[p][0](system, user, max_tokens)
        except ProviderError as e:
            last_err = e
            if not _is_transient(str(e)) or p == chain[-1]:
                raise
            log.warning("provider %s transient error, falling through: %s",
                        p, str(e)[:200])
            continue
    if last_err is not None:
        raise last_err
    raise ProviderError("All configured providers failed.")


def ask_with_tools(system: str, user: str, *, tools: list[dict],
                    on_tool_call: Callable[[str, dict], str],
                    max_tokens: int = 1200, max_rounds: int = 5,
                    provider: Optional[str] = None) -> ToolConversation:
    """Tool-using conversation. Same fallback semantics as ask()."""
    primary = (provider or active_provider() or "").lower() or None
    chain = _fallback_chain(primary) if primary else []
    if not chain:
        raise ProviderNotConfigured(
            "AI features are unavailable on this deployment. The "
            "operator has not configured a Gemini or Anthropic API key. "
            "Contact your administrator."
        )
    last_err: Optional[Exception] = None
    for p in chain:
        try:
            return _DISPATCH[p][1](system, user, tools, on_tool_call,
                                    max_tokens, max_rounds)
        except ProviderError as e:
            last_err = e
            if not _is_transient(str(e)) or p == chain[-1]:
                raise
            log.warning("provider %s transient tool error, falling through: %s",
                        p, str(e)[:200])
            continue
    if last_err is not None:
        raise last_err
    raise ProviderError("All configured providers failed.")
