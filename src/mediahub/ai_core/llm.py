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
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class ProviderNotConfigured(RuntimeError):
    """Raised when no LLM provider has been configured."""


class ProviderError(RuntimeError):
    """Raised when an LLM provider's API call fails.

    ``transient`` marks a failure worth retrying on the next configured provider
    (transport error, 429, 5xx, 529, timeout, auth) versus a permanent one
    (400/404 bad request / model-not-found) a retry can't fix. Set it explicitly
    at the raise site so failover no longer depends solely on regexing the error
    message — a transport-level failure (``ConnectionError``, DNS, reset) carries
    no HTTP code in its text and the old regex never matched it, so failover
    never fired. ``None`` means "unclassified": ``ask()`` falls back to the
    message regex for older raise sites.
    """

    def __init__(self, *args: object, transient: Optional[bool] = None) -> None:
        super().__init__(*args)
        self.transient = transient


def _exc_transient(e: BaseException) -> bool:
    """Classify a caught provider exception: retry the next provider or not.

    Transport-level errors (no HTTP status) are transient; a status of 401/403
    (another provider may hold a valid key), 408/409/425/429/529 or any 5xx is
    transient; a definite 400/404 config/request error is not."""
    status = getattr(e, "status_code", None)
    if status is None:
        status = getattr(getattr(e, "response", None), "status_code", None)
    if status is None:
        return True  # transport-level (ConnectionError / DNS / reset / timeout)
    try:
        status = int(status)
    except (TypeError, ValueError):
        return True
    return status in (401, 403, 408, 409, 425, 429, 529) or 500 <= status <= 599


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
    # True when the round cap was hit before the model produced a final answer.
    # Downstream (deep_research / free-text chat) must branch on this flag rather
    # than substring-sniffing the "still gathering evidence" sentence — a real
    # answer that happens to contain that phrase must NOT be discarded.
    exhausted: bool = False


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
        raise ProviderError(f"Anthropic call failed: {e}", transient=_exc_transient(e)) from e
    parts = [
        getattr(b, "text", "") or "" for b in resp.content if getattr(b, "type", None) == "text"
    ]
    text = "".join(parts).strip()
    if not text:
        reason = getattr(resp, "stop_reason", None)
        raise ProviderError(f"Anthropic returned no text (stop_reason={reason})", transient=True)
    return text


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
            raise ProviderError(
                f"Anthropic tool call failed: {e}", transient=_exc_transient(e)
            ) from e
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
    convo.exhausted = True
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


def _redacted(text: str, key: Optional[str]) -> str:
    """Strip the Gemini API key from error text before it rides a
    ProviderError — messages are logged (ai_director) and surfaced to
    users via ClaudeUnavailableError, and a requests exception repr
    embeds the failing URL including its ``?key=…``. Reuses
    ``media_ai.llm._redact_key``; the lazy import keeps ``ai_core``
    independently importable.
    """
    try:
        from mediahub.media_ai.llm import _redact_key

        return _redact_key(text, key)
    except Exception:
        return text.replace(key, "***REDACTED***") if key and key in text else text


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


def _gemini_timeout(default: float) -> float:
    """Per-call read of ``MEDIAHUB_GEMINI_TIMEOUT`` (seconds).

    ``media_ai`` honours this operator knob; ``ai_core`` used to hardcode
    45/60s (deep-review finding #43), so raising the timeout for a slow
    Gemini day silently didn't apply to copilot / chat / deep-research
    calls. The call-site default (45s plain ask, 60s tool rounds) is
    preserved when the env is unset or unparseable.
    """
    raw = os.environ.get("MEDIAHUB_GEMINI_TIMEOUT", "").strip()
    if not raw:
        return default
    try:
        return max(1.0, float(raw))
    except ValueError:
        return default


def _gemini_generation_config(max_tokens: int) -> dict:
    # No temperature is sent — parity with media_ai._gemini_generation_config
    # (finding #43): both wrappers sample at the API default so the same
    # surface can't drift in output character depending on which wrapper
    # happened to serve it.
    cfg: dict = {"maxOutputTokens": int(max_tokens)}
    model = _gemini_model()
    if "2.5" in model or "3." in model:
        budget = _gemini_thinking_budget()
        # Pro models reject thinkingBudget < 128 (400 INVALID_ARGUMENT);
        # clamp there. Flash models keep 0 (thinking off).
        if "pro" in model:
            budget = max(128, budget)
        cfg["thinkingConfig"] = {"thinkingBudget": budget}
    return cfg


def _gemini_breaker_record(ok: bool) -> None:
    """Report a Gemini call outcome into the shared overload breaker.

    The breaker state lives in ``media_ai.llm`` (``/healthz/breaker`` reads
    its snapshot). ``ai_core`` used to *read* the breaker but never record
    into it (finding #43), so a Gemini outage seen only via chat / copilot /
    deep-research never tripped it and every caller kept paying the full
    round-trip timeout. Lazy import + broad except mirror
    ``_gemini_breaker_open``: a missing breaker must never sink an LLM call.
    """
    try:
        from mediahub.media_ai.llm import (
            _gemini_breaker_record_failure,
            _gemini_breaker_record_success,
        )

        if ok:
            _gemini_breaker_record_success()
        else:
            _gemini_breaker_record_failure()
    except Exception:
        pass


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
            json=payload,
            # Key in the x-goog-api-key header, NOT the URL: a URL-borne ?key=
            # rides into exception reprs, access logs and proxy logs (matches
            # media_ai/llm.py, which moved off the query param for this reason).
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
            timeout=_gemini_timeout(45.0),
        )
    except Exception as e:
        # Transport-level failure (ConnectionError / DNS / reset / timeout) — no
        # HTTP status, so it's transient: try the next provider. Counts toward
        # tripping the shared breaker (each such call eats the full timeout).
        _gemini_breaker_record(False)
        raise ProviderError(f"Gemini HTTP error: {_redacted(str(e), key)}", transient=True) from e
    if r.status_code != 200:
        # 5xx/overload trips the breaker; 4xx (incl. 429 rate limit) is not an
        # outage signal — same policy as media_ai._call_gemini.
        if r.status_code >= 500:
            _gemini_breaker_record(False)
        raise ProviderError(
            f"Gemini HTTP {r.status_code}: {_redacted(r.text[:240], key)}",
            transient=(r.status_code in (401, 403, 408, 409, 425, 429, 529))
            or 500 <= r.status_code <= 599,
        )
    try:
        data = r.json()
    except Exception as e:
        raise ProviderError(f"Gemini bad JSON: {e}", transient=True) from e
    # A decoded 200 proves the service is reachable — clear the breaker even
    # if the model output turns out unusable below.
    _gemini_breaker_record(True)
    cands = data.get("candidates") or []
    if not cands:
        raise ProviderError(f"Gemini empty response: {str(data)[:240]}", transient=True)
    parts = (cands[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
    if not text:
        # Candidates but no text (safety block / MAX_TOKENS) used to return "" —
        # a silent empty that surfaces later as a misleading JSON parse error.
        # Raise (transient) citing the reason so a fallback provider is tried.
        reason = cands[0].get("finishReason") or (data.get("promptFeedback") or {}).get(
            "blockReason"
        )
        raise ProviderError(f"Gemini returned no text (finishReason={reason})", transient=True)
    return text


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
                json=payload,
                # Key in the header, not the URL — see _ask_gemini above.
                headers={"Content-Type": "application/json", "x-goog-api-key": key},
                timeout=_gemini_timeout(60.0),
            )
        except Exception as e:
            _gemini_breaker_record(False)
            raise ProviderError(
                f"Gemini tool HTTP error: {_redacted(str(e), key)}", transient=True
            ) from e
        if r.status_code != 200:
            if r.status_code >= 500:
                _gemini_breaker_record(False)
            raise ProviderError(
                f"Gemini tool HTTP {r.status_code}: {_redacted(r.text[:240], key)}",
                transient=(r.status_code in (401, 403, 408, 409, 425, 429, 529))
                or 500 <= r.status_code <= 599,
            )
        try:
            data = r.json()
        except ValueError as e:
            # Pre-A this ValueError escaped raw (uncatchable by the
            # except-ProviderError failover in ask_with_tools); wrap it like
            # the plain-ask path does.
            raise ProviderError(f"Gemini bad JSON: {e}", transient=True) from e
        _gemini_breaker_record(True)
        cands = data.get("candidates") or []
        if not cands:
            raise ProviderError(f"Gemini empty response: {str(data)[:240]}", transient=True)
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
    convo.exhausted = True
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
        raise ProviderError(
            f"OpenAI-compatible call failed: {e}", transient=_exc_transient(e)
        ) from e
    text = (result.text or "").strip()
    if not text:
        raise ProviderError("OpenAI-compatible endpoint returned no text", transient=True)
    return text


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
            raise ProviderError(
                f"OpenAI-compatible tool call failed: {e}", transient=_exc_transient(e)
            ) from e
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
    convo.exhausted = True
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


# Word-bounded transient markers. Bare substrings misclassified permanent
# errors: "rate" matched 'generateContent' (the Gemini 404 body for a bad
# model name) and 'moderate'/'accurate'; "auth" matched 'author'. A permanent
# config error must surface as-is, not get retried on the other provider.
_TRANSIENT_RE = re.compile(
    r"\b(429|401|403|50[0-4]|529)\b"
    r"|rate.?limit"
    r"|quota"
    r"|resource.?exhausted"
    r"|unauthori[sz]ed"
    r"|timed?.?out"
    r"|overloaded"
)


def _is_transient(err_msg: str) -> bool:
    """Heuristic: should we retry on the next configured provider?
    Auth errors, rate limits, timeouts, and HTTP 5xx warrant trying
    another provider; everything else is the model returning legit
    nonsense and won't fix on a retry."""
    return bool(_TRANSIENT_RE.search(err_msg.lower()))


def _record(
    provider: str, *, ok: bool, started: float, error: Optional[BaseException] = None
) -> None:
    """Best-effort usage record for one ai_core provider call, so copilot /
    free-text chat / deep-research / autonomy calls are visible on
    /healthz/usage and count against the Gemini free-tier RPD tracker (ai_core
    used to record nothing). Never lets a logging failure sink an LLM call."""
    try:
        from mediahub.observability import llm_usage as _u

        _u.record_call(
            provider=provider,
            ok=ok,
            duration_ms=(time.monotonic() - started) * 1000.0,
            error_kind=type(error).__name__ if error else None,
            error_message=str(error)[:240] if error else None,
        )
    except Exception:
        pass


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
        started = time.monotonic()
        try:
            result = _DISPATCH[p][0](system, user, max_tokens)
            _record(p, ok=True, started=started)
            return result
        except ProviderError as e:
            _record(p, ok=False, started=started, error=e)
            last_err = e
            transient = e.transient if e.transient is not None else _is_transient(str(e))
            if not transient or p == chain[-1]:
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
    tool_calls_made = 0

    def _counting_tool_call(name: str, inp: dict) -> str:
        nonlocal tool_calls_made
        tool_calls_made += 1
        return on_tool_call(name, inp)

    for p in chain:
        started = time.monotonic()
        try:
            result = _DISPATCH[p][1](
                system, user, tools, _counting_tool_call, max_tokens, max_rounds
            )
            _record(p, ok=True, started=started)
            return result
        except ProviderError as e:
            _record(p, ok=False, started=started, error=e)
            last_err = e
            transient = e.transient if e.transient is not None else _is_transient(str(e))
            # Never fail over to another provider once a tool call has already run:
            # on_tool_call has lasting side effects (copilot applies + audit-logs
            # ops; free-text chat appends to research_log) that would REPLAY on the
            # fresh-provider restart. Only a first-request failure (no tools yet)
            # may retry elsewhere.
            if not transient or p == chain[-1] or tool_calls_made > 0:
                raise
            log.warning("provider %s transient tool error, falling through: %s", p, str(e)[:200])
            continue
    if last_err is not None:
        raise last_err
    raise ProviderError("All configured providers failed.")
