"""Provider-agnostic Claude/Gemini/ChatGPT interface for ai_core.

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

_PROVIDERS = ("claude", "openai", "gemini")


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
    if provider == "openai":
        return _resolve_key(("OPENAI_API_KEY",), "openai_api_key")
    if provider == "gemini":
        return _resolve_key(("GEMINI_API_KEY", "GOOGLE_API_KEY"), "gemini_api_key")
    return None


def list_provider_status() -> list[dict]:
    """For /settings: which providers are configured + which is active."""
    active = active_provider()
    out = []
    for p in _PROVIDERS:
        key = _key_for(p)
        out.append({
            "provider":   p,
            "configured": bool(key),
            "active":     (p == active),
        })
    return out


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


def set_preferred_provider(provider: str) -> None:
    """Persist the user's choice. Pass 'auto' to clear."""
    p = (provider or "").strip().lower()
    if p not in _PROVIDERS + ("auto",):
        raise ValueError(f"unknown provider: {provider!r}")
    try:
        from mediahub.web.secrets_store import set_secret
        set_secret("mediahub_llm_provider", None if p == "auto" else p)
    except Exception as e:
        raise ProviderError(f"could not persist provider choice: {e}") from e


def active_provider() -> Optional[str]:
    """Return the provider that will actually be used for the next call.

    Honours the user's pref if its key is configured, otherwise falls
    through the default order (claude → openai → gemini) and returns the
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
# OpenAI (ChatGPT) — text + native tool-use
# ---------------------------------------------------------------------------

_openai_client = None
_openai_client_key = None


def _openai_client_for(key: str):
    global _openai_client, _openai_client_key
    if _openai_client is not None and _openai_client_key == key:
        return _openai_client
    try:
        from openai import OpenAI
    except ImportError as e:
        raise ProviderError(f"openai SDK not installed: {e}")
    _openai_client = OpenAI(api_key=key)
    _openai_client_key = key
    return _openai_client


def _openai_model() -> str:
    return os.environ.get("MEDIAHUB_OPENAI_MODEL", "gpt-4o")


def _ask_openai(system: str, user: str, max_tokens: int) -> str:
    key = _key_for("openai")
    if not key:
        raise ProviderNotConfigured("OpenAI API key not configured.")
    client = _openai_client_for(key)
    try:
        resp = client.chat.completions.create(
            model=_openai_model(),
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        )
    except Exception as e:
        raise ProviderError(f"OpenAI call failed: {e}") from e
    try:
        return (resp.choices[0].message.content or "").strip()
    except (AttributeError, IndexError):
        return ""


def _ask_openai_with_tools(system: str, user: str, tools: list[dict],
                            on_tool_call: Callable[[str, dict], str],
                            max_tokens: int, max_rounds: int) -> ToolConversation:
    """OpenAI Chat Completions with function calling.

    `tools` arrives in the Anthropic schema; we translate to OpenAI's
    {"type":"function","function":{name,description,parameters}}. This
    means callers can pass one tools list and either provider works.
    """
    import json
    key = _key_for("openai")
    if not key:
        raise ProviderNotConfigured("OpenAI API key not configured.")
    client = _openai_client_for(key)
    model = _openai_model()
    # Translate tool schema once.
    oa_tools = [{"type": "function", "function": {
        "name":        t["name"],
        "description": t.get("description", ""),
        "parameters":  t.get("input_schema") or t.get("parameters")
                        or {"type": "object", "properties": {}},
    }} for t in tools]
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]
    convo = ToolConversation(text="", provider="openai")
    for _ in range(max_rounds):
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages,
                tools=oa_tools, max_tokens=max_tokens,
            )
        except Exception as e:
            raise ProviderError(f"OpenAI tool call failed: {e}") from e
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        # Append the assistant turn so the next call sees it.
        messages.append({
            "role":       "assistant",
            "content":    msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name,
                              "arguments": tc.function.arguments}}
                for tc in tool_calls
            ] if tool_calls else None,
        })
        if not tool_calls:
            convo.text = (msg.content or "").strip()
            return convo
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            try:
                r = on_tool_call(name, args)
            except Exception as e:
                r = f"(tool {name!r} failed: {e})"
            convo.tool_calls.append(ToolCallRecord(
                name=name, input=args, result=r, provider="openai",
            ))
            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      r,
            })
    convo.text = "(ChatGPT is still gathering evidence; try a smaller question.)"
    return convo


# ---------------------------------------------------------------------------
# Google Gemini — text + native function calling
# ---------------------------------------------------------------------------

def _gemini_model() -> str:
    return os.environ.get("MEDIAHUB_GEMINI_MODEL", "gemini-2.0-flash")


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
    "openai": (_ask_openai, _ask_openai_with_tools),
    "gemini": (_ask_gemini, _ask_gemini_with_tools),
}


def _legacy_backstop(system: str, user: str, max_tokens: int) -> Optional[str]:
    """Dev/test backstop — use the legacy media_ai.llm.generate() when no
    API-key provider is configured but its multi-tier (e.g. claude-cli)
    happens to be reachable. Keeps developer environments working without
    re-wiring tests. Returns None in production where nothing's reachable.
    """
    try:
        from mediahub.media_ai import llm as _legacy
    except Exception:
        return None
    try:
        if not _legacy.is_available():
            return None
        out = _legacy.generate(user, system=system, max_tokens=max_tokens)
        if isinstance(out, str) and out.strip() and not out.startswith(
                "Generated content unavailable"):
            return out.strip()
    except Exception:
        return None
    return None


def _fallback_chain(primary: Optional[str]) -> list[str]:
    """Return the provider order to try, starting with `primary` (if
    configured) then the remaining configured providers. Lets a rate-
    limited Gemini call fall through to OpenAI / Claude instead of
    erroring at the user."""
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
    """Plain-text in, plain-text out. Tries the active provider first,
    falls through to any other configured provider on a transient
    failure (rate limit, auth, 5xx)."""
    primary = (provider or active_provider() or "").lower() or None
    chain = _fallback_chain(primary) if primary else []
    last_err: Optional[Exception] = None
    for p in chain:
        try:
            return _DISPATCH[p][0](system, user, max_tokens)
        except ProviderError as e:
            last_err = e
            if not _is_transient(str(e)) or p == chain[-1]:
                raise
            # else: try the next configured provider
            log.warning("provider %s transient error, falling through: %s",
                        p, str(e)[:200])
            continue
    if last_err is not None:
        raise last_err
    backstop = _legacy_backstop(system, user, max_tokens)
    if backstop is not None:
        return backstop
    raise ProviderNotConfigured(
        "No LLM provider is configured. Add a Claude, OpenAI, or "
        "Gemini key in /settings."
    )


def ask_with_tools(system: str, user: str, *, tools: list[dict],
                    on_tool_call: Callable[[str, dict], str],
                    max_tokens: int = 1200, max_rounds: int = 5,
                    provider: Optional[str] = None) -> ToolConversation:
    """Tool-using conversation. Same fallback semantics as ask()."""
    primary = (provider or active_provider() or "").lower() or None
    chain = _fallback_chain(primary) if primary else []
    if not chain:
        raise ProviderNotConfigured(
            "No LLM provider is configured. Add a Claude, OpenAI, or "
            "Gemini key in /settings."
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
