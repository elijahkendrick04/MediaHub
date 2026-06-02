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

import json
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

# Provider order: Gemini first (free default), Claude as the paid quality
# option, then an optional OpenAI-compatible endpoint (Groq / OpenRouter /
# Together / vLLM / Ollama / …) that only joins the chain when
# MEDIAHUB_LLM_ENDPOINTS is configured. The product stays Gemini-first;
# Anthropic or an OpenAI-compatible endpoint are explicit operator overrides
# via MEDIAHUB_LLM_PROVIDER=claude|anthropic|openai.
_PROVIDERS = ("gemini", "claude", "openai")


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
    if provider == "openai":
        # An OpenAI-compatible endpoint is "configured" whenever an endpoint
        # URL is set; the bearer key is optional (keyless local servers). Return
        # the key, or a sentinel so the provider still joins the fallback chain.
        from mediahub.ai_core import llm_client

        if not llm_client.endpoints_from_env():
            return None
        return llm_client.resolve_openai_key() or "configured-keyless"
    return None


def _preferred_pref() -> str:
    """Read the user's preferred provider. 'auto' = use the first configured.

    `anthropic` is accepted as an alias for `claude` so MEDIAHUB_LLM_PROVIDER
    carries the same meaning here as it does in media_ai.llm.
    """

    def _norm(v: str) -> str:
        v = (v or "").strip().lower()
        return "claude" if v == "anthropic" else v

    env = _norm(os.environ.get("MEDIAHUB_LLM_PROVIDER", ""))
    if env in _PROVIDERS + ("auto",):
        return env
    try:
        from mediahub.web.secrets_store import get_secret

        v = _norm(get_secret("mediahub_llm_provider") or "")
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
    return os.environ.get("MEDIAHUB_LLM_MODEL", "claude-sonnet-4-6")


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
    parts = [
        getattr(b, "text", "") or "" for b in resp.content if getattr(b, "type", None) == "text"
    ]
    return "".join(parts).strip()


def _ask_claude_with_tools(
    system: str,
    user: str,
    tools: list[dict],
    on_tool_call: Callable[[str, dict], str],
    max_tokens: int,
    max_rounds: int,
) -> ToolConversation:
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
                model=model,
                system=system,
                tools=tools,
                max_tokens=max_tokens,
                messages=messages,
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
                tu = {
                    "type": "tool_use",
                    "id": getattr(b, "id", ""),
                    "name": getattr(b, "name", ""),
                    "input": getattr(b, "input", {}) or {},
                }
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
            convo.tool_calls.append(
                ToolCallRecord(
                    name=tu["name"],
                    input=tu["input"],
                    result=r,
                    provider="claude",
                )
            )
            results.append({"type": "tool_result", "tool_use_id": tu["id"], "content": r})
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


def _gemini_thinking_budget() -> int:
    """See ``media_ai.llm._gemini_thinking_budget`` for context.

    Gemini 2.5+ ships thinking on by default; thinking tokens count
    against ``maxOutputTokens`` but never appear in the response text,
    so callers sized for the visible output get truncated mid-JSON.
    Default off here too. Operators can opt back in via
    ``MEDIAHUB_GEMINI_THINKING_BUDGET``.
    """
    raw = os.environ.get("MEDIAHUB_GEMINI_THINKING_BUDGET", "0").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _gemini_generation_config(max_tokens: int, *, temperature: float = 0.7) -> dict:
    cfg: dict = {"maxOutputTokens": int(max_tokens), "temperature": temperature}
    model = _gemini_model()
    if "2.5" in model or "3." in model:
        cfg["thinkingConfig"] = {"thinkingBudget": _gemini_thinking_budget()}
    return cfg


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
        "generationConfig": _gemini_generation_config(max_tokens),
    }
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{_gemini_model()}:generateContent"
    )
    try:
        r = requests.post(
            url,
            params={"key": key},
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=45,
        )
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
    parts = (cands[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()


def _ask_gemini_with_tools(
    system: str,
    user: str,
    tools: list[dict],
    on_tool_call: Callable[[str, dict], str],
    max_tokens: int,
    max_rounds: int,
) -> ToolConversation:
    """Gemini function-calling loop. Tool schema in Anthropic shape is
    translated to Gemini's functionDeclarations on the fly so callers
    pass the same `tools` list whichever provider is active."""
    import requests

    key = _key_for("gemini")
    if not key:
        raise ProviderNotConfigured("Gemini API key not configured.")
    # Translate tool schema.
    fn_decls = [
        {
            "name": t["name"],
            "description": t.get("description", ""),
            "parameters": t.get("input_schema")
            or t.get("parameters")
            or {"type": "object", "properties": {}},
        }
        for t in tools
    ]
    contents: list[dict] = [{"role": "user", "parts": [{"text": user}]}]
    convo = ToolConversation(text="", provider="gemini")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{_gemini_model()}:generateContent"
    )
    for _ in range(max_rounds):
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "tools": [{"functionDeclarations": fn_decls}],
            "generationConfig": _gemini_generation_config(max_tokens),
        }
        try:
            r = requests.post(
                url,
                params={"key": key},
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=60,
            )
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
            convo.tool_calls.append(
                ToolCallRecord(
                    name=name,
                    input=args,
                    result=r_str,
                    provider="gemini",
                )
            )
            tool_response_parts.append(
                {
                    "functionResponse": {
                        "name": name,
                        "response": {"content": r_str},
                    }
                }
            )
        contents.append({"role": "user", "parts": tool_response_parts})
    convo.text = "(Gemini is still gathering evidence; try a smaller question.)"
    return convo


# ---------------------------------------------------------------------------
# OpenAI-compatible endpoints (Groq / OpenRouter / Together / vLLM / Ollama)
# Transport lives in ai_core.llm_client; these wrap it into the ask() /
# ask_with_tools() provider contract with the same fallback semantics.
# ---------------------------------------------------------------------------
def _openai_client():
    from mediahub.ai_core import llm_client

    client = llm_client.client_from_env()
    if client is None:
        raise ProviderNotConfigured("No OpenAI-compatible endpoint configured.")
    return client


def _openai_default_model() -> Optional[str]:
    """Pick the model for ask()-style calls, reusing the media_ai routing
    knobs so both LLM wrappers resolve the same model name."""
    try:
        from mediahub.media_ai.model_select import models_from_env

        cheap, premium, _ = models_from_env()
        return cheap or premium
    except Exception:
        return None


def _ask_openai(system: str, user: str, max_tokens: int) -> str:
    from mediahub.ai_core import llm_client

    client = _openai_client()
    try:
        result = client.chat(
            [{"role": "user", "content": user}],
            model=_openai_default_model(),
            system=system,
            max_completion_tokens=max_tokens,
        )
    except llm_client.OpenAICompatError as e:
        raise ProviderError(f"OpenAI-compatible call failed: {e}") from e
    return (result.text or "").strip()


def _ask_openai_with_tools(
    system: str,
    user: str,
    tools: list[dict],
    on_tool_call: Callable[[str, dict], str],
    max_tokens: int,
    max_rounds: int,
) -> ToolConversation:
    """OpenAI function-calling loop. The Anthropic-shape `tools` list is
    translated to OpenAI's schema on the fly so callers pass the same list
    whichever provider is active. Endpoints that don't advertise tool support
    answer in plain text instead."""
    from mediahub.ai_core import llm_client

    client = _openai_client()
    model = _openai_default_model()
    convo = ToolConversation(text="", provider="openai")
    use_tools = None
    if client.supports_tools(model):
        use_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema")
                    or t.get("parameters")
                    or {"type": "object", "properties": {}},
                },
            }
            for t in tools
        ]
    messages: list[dict] = [{"role": "user", "content": user}]
    for _ in range(max_rounds):
        try:
            result = client.chat(
                messages,
                model=model,
                system=system,
                max_completion_tokens=max_tokens,
                tools=use_tools,
            )
        except llm_client.OpenAICompatError as e:
            raise ProviderError(f"OpenAI-compatible tool call failed: {e}") from e
        choices = (result.raw or {}).get("choices") or []
        msg = (choices[0].get("message") if choices else {}) or {}
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            convo.text = (result.text or "").strip()
            return convo
        # Echo the assistant turn (with its tool_calls) back into history.
        messages.append(
            {
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": tool_calls,
            }
        )
        for tc in tool_calls:
            fn = tc.get("function") or {}
            name = fn.get("name", "")
            raw_args = fn.get("arguments")
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args) if raw_args.strip() else {}
                except json.JSONDecodeError:
                    args = {}
            else:
                args = raw_args or {}
            try:
                r_str = on_tool_call(name, args)
            except Exception as e:
                r_str = f"(tool {name!r} failed: {e})"
            convo.tool_calls.append(
                ToolCallRecord(name=name, input=args, result=r_str, provider="openai")
            )
            messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": r_str})
    convo.text = "(the model is still gathering evidence; try a smaller question.)"
    return convo


# ---------------------------------------------------------------------------
# Public dispatch
# ---------------------------------------------------------------------------

_DISPATCH = {
    "claude": (_ask_claude, _ask_claude_with_tools),
    "gemini": (_ask_gemini, _ask_gemini_with_tools),
    "openai": (_ask_openai, _ask_openai_with_tools),
}


def _gemini_breaker_open() -> bool:
    """Forwarder to ``media_ai.llm._gemini_breaker_is_open``.

    Both LLM wrappers hit the same Gemini endpoint, so a 503 noticed
    by one warrants skipping Gemini in the other for the cool-off
    period too. Import lazily to keep ``ai_core`` independently
    importable if ``media_ai`` is ever vendored separately.
    """
    try:
        from mediahub.media_ai.llm import _gemini_breaker_is_open

        return _gemini_breaker_is_open()
    except Exception:
        return False


def _fallback_chain(primary: Optional[str]) -> list[str]:
    """Return the provider order to try, starting with `primary` (if
    configured) then the remaining configured providers. Lets a rate-
    limited Gemini call fall through to Claude instead of erroring
    at the user.

    Demotes Gemini to the tail of the chain while its overload
    circuit breaker is tripped — Claude (if configured) gets first
    shot so the call doesn't pay another wasted Gemini round-trip.
    """
    chain: list[str] = []
    if primary and _key_for(primary):
        chain.append(primary)
    for p in _PROVIDERS:
        if p != primary and _key_for(p):
            chain.append(p)
    # If Gemini is in the breaker cool-off, move it to the back of the
    # queue so any other configured provider is tried first.
    if _gemini_breaker_open() and "gemini" in chain and len(chain) > 1:
        chain = [p for p in chain if p != "gemini"] + ["gemini"]
    return chain


def _is_transient(err_msg: str) -> bool:
    """Heuristic: should we retry on the next configured provider?
    Auth errors, rate limits, and HTTP 5xx warrant trying another
    provider; everything else is the model returning legit nonsense
    and won't fix on a retry."""
    s = err_msg.lower()
    return (
        "429" in s
        or "rate" in s
        or "401" in s
        or "403" in s
        or "auth" in s
        or " 500" in s
        or "502" in s
        or "503" in s
        or "504" in s
        or "timeout" in s
        or "timed out" in s
        or "overloaded" in s
    )


def ask(system: str, user: str, *, max_tokens: int = 800, provider: Optional[str] = None) -> str:
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
            log.warning("provider %s transient error, falling through: %s", p, str(e)[:200])
            continue
    if last_err is not None:
        raise last_err
    raise ProviderError("All configured providers failed.")


def ask_with_tools(
    system: str,
    user: str,
    *,
    tools: list[dict],
    on_tool_call: Callable[[str, dict], str],
    max_tokens: int = 1200,
    max_rounds: int = 5,
    provider: Optional[str] = None,
) -> ToolConversation:
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
            return _DISPATCH[p][1](system, user, tools, on_tool_call, max_tokens, max_rounds)
        except ProviderError as e:
            last_err = e
            if not _is_transient(str(e)) or p == chain[-1]:
                raise
            log.warning("provider %s transient tool error, falling through: %s", p, str(e)[:200])
            continue
    if last_err is not None:
        raise last_err
    raise ProviderError("All configured providers failed.")
