"""media_ai/llm.py — Gemini-first LLM wrapper.

Provider resolution order (post-operator-config rewrite):

  1. If MEDIAHUB_LLM_PROVIDER=anthropic AND ANTHROPIC_API_KEY is set
     → Anthropic primary, Gemini fallback (paid-but-higher-quality path)
  2. Otherwise → Gemini primary, Anthropic fallback if both keys are
     set (default zero-cost path — Gemini Flash free tier)

No more pplx-bridge, no more Claude CLI, no more OpenAI. The
intelligence layer is the moat; the underlying model is a commodity
chosen by the operator at deploy time via env vars, not by the user
in a settings UI.

Configuration is operator-only and exclusively via env vars:

  GEMINI_API_KEY=...           # default path — free at aistudio.google.com
  GOOGLE_API_KEY=...           # alias, same key
  ANTHROPIC_API_KEY=...        # optional paid override
  MEDIAHUB_LLM_PROVIDER=...    # 'anthropic' to prefer Anthropic; otherwise auto

All public functions are tolerant: they return a usable string when
a provider is configured, and raise ``ClaudeUnavailableError`` when
none is. The error name is kept for backward compatibility with
existing callers.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public errors
# ---------------------------------------------------------------------------

class ClaudeUnavailableError(RuntimeError):
    """Raised when no LLM provider can answer. Name kept for back-compat."""


# ---------------------------------------------------------------------------
# Usage logging — Phase 1.5 observability. Every successful or failed
# provider call lands one row in observability.llm_usage so the
# operator-facing /healthz/usage dashboard has real data.
#
# Recording is best-effort: a logging failure must NEVER fail an LLM
# call. We catch broadly here because the LLM path is hot and the cost
# of any logging exception leaking is higher than the cost of a missed
# data point.
# ---------------------------------------------------------------------------

def _log_call(*, provider: str, ok: bool, model: Optional[str] = None,
              tokens_in: Optional[int] = None, tokens_out: Optional[int] = None,
              duration_ms: Optional[float] = None,
              error_kind: Optional[str] = None,
              error_message: Optional[str] = None) -> None:
    try:
        from mediahub.observability import llm_usage as _u
        _u.record_call(
            provider=provider, ok=ok, model=model,
            tokens_in=tokens_in, tokens_out=tokens_out,
            duration_ms=duration_ms,
            error_kind=error_kind, error_message=error_message,
        )
    except Exception:
        pass


# Anthropic models — kept as module-level constants so other code that
# imports them (e.g. test fixtures) keeps working. Updated May 2026:
# Claude 4.x family is current; Claude 3.x is retired (404s).
DEFAULT_MODEL = os.environ.get("MEDIAHUB_LLM_MODEL", "claude-sonnet-4-6")
ALT_MODEL = "claude-haiku-4-5"


# ---------------------------------------------------------------------------
# Key resolution — env-first, with one-release on-disk fallback for self-
# hosted installs that pre-date the env-only migration. Disk fallback is
# slated for removal in the next major.
# ---------------------------------------------------------------------------

def _resolve_anthropic_key() -> Optional[str]:
    env = os.environ.get("ANTHROPIC_API_KEY")
    if env and env.strip():
        return env.strip()
    try:
        from mediahub.web.secrets_store import get_secret
        v = get_secret("anthropic_api_key")
        return v if v else None
    except Exception:
        return None


def _has_anthropic_key() -> bool:
    return bool(_resolve_anthropic_key())


def _resolve_gemini_key() -> Optional[str]:
    """Return env GEMINI_API_KEY (or GOOGLE_API_KEY), else stored secret."""
    for env_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        env = os.environ.get(env_name)
        if env and env.strip():
            return env.strip()
    try:
        from mediahub.web.secrets_store import get_secret
        v = get_secret("gemini_api_key")
        return v if v else None
    except Exception:
        return None


def _has_gemini_key() -> bool:
    return bool(_resolve_gemini_key())


def _preferred_provider() -> str:
    """Return 'anthropic' if explicitly preferred via env, else 'gemini'."""
    pref = (os.environ.get("MEDIAHUB_LLM_PROVIDER") or "").strip().lower()
    if pref == "anthropic":
        return "anthropic"
    # Everything else (empty, 'gemini', 'auto', unknown) defaults to Gemini.
    return "gemini"


def is_available() -> bool:
    """True if any real LLM provider is reachable."""
    return _has_gemini_key() or _has_anthropic_key()


def active_provider() -> str:
    """Return the user-friendly name of the active LLM provider.

    Returns one of: 'anthropic-api', 'gemini-api', 'heuristic'.
    The 'heuristic' label is the historical placeholder for "no provider
    configured"; callers that branch on it should treat it as
    "AI features unavailable".
    """
    if _preferred_provider() == "anthropic" and _has_anthropic_key():
        return "anthropic-api"
    if _has_gemini_key():
        return "gemini-api"
    if _has_anthropic_key():
        return "anthropic-api"
    return "heuristic"


# ---------------------------------------------------------------------------
# Anthropic (paid, optional)
# ---------------------------------------------------------------------------

_anthropic_client = None
_anthropic_client_key = None


def _get_anthropic():
    """Return an anthropic.Anthropic client built with the resolved key.

    Rebuilds when the key changes so an operator who rotates a key
    doesn't have to restart the process.
    """
    global _anthropic_client, _anthropic_client_key
    key = _resolve_anthropic_key()
    if not key:
        return None
    if _anthropic_client and _anthropic_client_key == key:
        return _anthropic_client
    try:
        import anthropic
        _anthropic_client = anthropic.Anthropic(api_key=key)
        _anthropic_client_key = key
    except Exception as e:
        log.debug("anthropic import/init failed: %s", e)
        _anthropic_client = False
        _anthropic_client_key = None
    return _anthropic_client if _anthropic_client else None


def _call_anthropic(messages: list[dict], system: Optional[str], max_tokens: int,
                    model: Optional[str] = None) -> Optional[str]:
    if not _has_anthropic_key():
        return None
    client = _get_anthropic()
    if not client:
        return None
    use_model = model or DEFAULT_MODEL
    last_err: Optional[Exception] = None
    for attempt_model in (use_model, ALT_MODEL):
        started = time.monotonic()
        try:
            kwargs = {
                "model": attempt_model,
                "messages": messages,
                "max_tokens": max_tokens,
            }
            if system:
                kwargs["system"] = system
            resp = client.messages.create(**kwargs)
            parts = [b.text for b in resp.content if hasattr(b, "text")]
            text = "".join(parts).strip() or None
            usage = getattr(resp, "usage", None)
            tin = getattr(usage, "input_tokens", None) if usage else None
            tout = getattr(usage, "output_tokens", None) if usage else None
            _log_call(
                provider="anthropic", ok=bool(text), model=attempt_model,
                tokens_in=tin, tokens_out=tout,
                duration_ms=(time.monotonic() - started) * 1000.0,
                error_kind=None if text else "empty_response",
                error_message=None if text else "Anthropic returned no text",
            )
            if text:
                return text
        except Exception as e:
            last_err = e
            log.warning("anthropic call failed (%s): %s", attempt_model, e)
            _log_call(
                provider="anthropic", ok=False, model=attempt_model,
                duration_ms=(time.monotonic() - started) * 1000.0,
                error_kind=type(e).__name__,
                error_message=str(e),
            )
            continue
    return None


# ---------------------------------------------------------------------------
# Gemini (free default)
# ---------------------------------------------------------------------------

# Gemini default updated May 2026: gemini-2.0-flash was deprecated and
# returns 410 Gone. gemini-2.5-flash is the current GA model with the
# same free-tier (1,500 req/day) and similar quality.
_GEMINI_MODEL = os.environ.get("MEDIAHUB_GEMINI_MODEL", "gemini-2.5-flash")
_GEMINI_TIMEOUT = int(os.environ.get("MEDIAHUB_GEMINI_TIMEOUT", "45"))

# ---------------------------------------------------------------------------
# Gemini overload circuit breaker
# ---------------------------------------------------------------------------
# When Gemini returns repeated 5xx / overload responses, every subsequent
# call in the same request still pays the round-trip cost before falling
# through to Anthropic. The org-setup capture step is the worst offender —
# it fires ~24 sequential Gemini calls (block_detector, content_extractor,
# endpoint_discoverer, strategy × every link), so a sustained Gemini
# outage turns a normal ~10s capture into a 60-80s hang and the user
# stares at a loader assuming the app is broken.
#
# The breaker is a tiny in-process trip switch: once we see N consecutive
# Gemini failures within a short window, skip Gemini entirely for a cool-
# off period and go straight to whatever's next in the provider order.
# Any Gemini success clears the trip.
#
# This is intentionally per-process, not cluster-wide. With two gunicorn
# workers on Render Standard the cost of the second worker independently
# discovering the outage is one wasted call per request batch, which is
# fine — we'd rather not bring in Redis just for this signal.
import threading as _bt

_GEMINI_BREAKER_THRESHOLD = int(
    os.environ.get("MEDIAHUB_GEMINI_BREAKER_THRESHOLD", "3")
)
_GEMINI_BREAKER_COOLDOWN_S = float(
    os.environ.get("MEDIAHUB_GEMINI_BREAKER_COOLDOWN_S", "60")
)
_gemini_breaker_lock = _bt.Lock()
_gemini_breaker_state: dict[str, float] = {
    "consecutive_failures": 0.0,  # float so it round-trips through env
    "tripped_until": 0.0,         # time.monotonic() value
}


def _gemini_breaker_is_open() -> bool:
    """True while we're skipping Gemini after sustained failures."""
    with _gemini_breaker_lock:
        return time.monotonic() < _gemini_breaker_state["tripped_until"]


def _gemini_breaker_record_failure() -> None:
    """Count a failure; trip the breaker when the threshold is hit."""
    with _gemini_breaker_lock:
        _gemini_breaker_state["consecutive_failures"] += 1
        if (
            _gemini_breaker_state["consecutive_failures"]
            >= _GEMINI_BREAKER_THRESHOLD
        ):
            _gemini_breaker_state["tripped_until"] = (
                time.monotonic() + _GEMINI_BREAKER_COOLDOWN_S
            )


def _gemini_breaker_record_success() -> None:
    """Any success clears the trip and resets the failure counter."""
    with _gemini_breaker_lock:
        _gemini_breaker_state["consecutive_failures"] = 0
        _gemini_breaker_state["tripped_until"] = 0.0


def gemini_breaker_snapshot() -> dict:
    """Return the current breaker state in a JSON-serialisable shape.

    Exposed for observability (the ``/healthz/breaker`` route reads
    this) so operators can tell whether silent "ai_directed=false"
    responses are caused by a tripped breaker. The values are
    per-process — multi-worker deployments will see one snapshot per
    gunicorn worker.
    """
    with _gemini_breaker_lock:
        now = time.monotonic()
        tripped_until = _gemini_breaker_state["tripped_until"]
        return {
            "open": now < tripped_until,
            "consecutive_failures": int(
                _gemini_breaker_state["consecutive_failures"]
            ),
            "seconds_until_reset": max(0.0, round(tripped_until - now, 1)),
            "threshold": _GEMINI_BREAKER_THRESHOLD,
            "cooldown_seconds": _GEMINI_BREAKER_COOLDOWN_S,
        }


def _call_gemini(messages: list[dict], system: Optional[str], max_tokens: int) -> Optional[str]:
    """Call Google Gemini generateContent. Returns text or None.

    Free-tier limits (gemini-2.5-flash): 15 RPM, 1,500 RPD. Plenty for
    a small-club deployment; the dissertation's cost model assumes
    free tier handles the entire small-club tier.

    Returns None immediately (without an HTTP round-trip) while the
    overload circuit breaker is tripped — see ``_gemini_breaker_*``
    above. The caller's normal fall-through to Anthropic kicks in
    the same way it would on a real Gemini failure.
    """
    key = _resolve_gemini_key()
    if not key:
        return None
    if _gemini_breaker_is_open():
        _log_call(provider="gemini", ok=False, model=_GEMINI_MODEL,
                  duration_ms=0.0, error_kind="breaker_open",
                  error_message="Gemini circuit breaker is open; "
                                "skipping to next provider")
        return None
    try:
        import requests
    except Exception:
        return None
    contents: list[dict] = []
    for m in messages or []:
        role = m.get("role", "user")
        content = m.get("content", "")
        # Gemini uses 'user' / 'model' role names.
        contents.append({
            "role": "model" if role == "assistant" else "user",
            "parts": [{"text": str(content)}],
        })
    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{_GEMINI_MODEL}:generateContent?key={key}"
    )
    started = time.monotonic()
    try:
        r = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=_GEMINI_TIMEOUT,
        )
    except Exception as e:
        log.warning("gemini transport failed: %s", e)
        _log_call(
            provider="gemini", ok=False, model=_GEMINI_MODEL,
            duration_ms=(time.monotonic() - started) * 1000.0,
            error_kind="transport",
            error_message=str(e),
        )
        return None
    dur_ms = (time.monotonic() - started) * 1000.0
    if r.status_code in (401, 403):
        _log_call(provider="gemini", ok=False, model=_GEMINI_MODEL,
                  duration_ms=dur_ms, error_kind="auth",
                  error_message=f"HTTP {r.status_code}")
        return None
    if r.status_code == 429:
        _log_call(provider="gemini", ok=False, model=_GEMINI_MODEL,
                  duration_ms=dur_ms, error_kind="rate_limited",
                  error_message="HTTP 429")
        return None
    if not r.ok:
        log.warning("gemini non-ok (%s): %s", r.status_code, r.text[:300])
        _log_call(provider="gemini", ok=False, model=_GEMINI_MODEL,
                  duration_ms=dur_ms, error_kind=f"http_{r.status_code}",
                  error_message=(r.text or "")[:300])
        # 5xx / overload signals warrant tripping the breaker so the
        # next call this request doesn't waste another round-trip.
        # 4xx (other than 429, handled above) are usually our fault
        # (bad payload) — don't trip on those.
        if r.status_code >= 500:
            _gemini_breaker_record_failure()
        return None
    try:
        data = r.json()
    except ValueError:
        _log_call(provider="gemini", ok=False, model=_GEMINI_MODEL,
                  duration_ms=dur_ms, error_kind="parse",
                  error_message="response was not JSON")
        return None
    candidates = data.get("candidates") if isinstance(data, dict) else None
    if not candidates:
        _log_call(provider="gemini", ok=False, model=_GEMINI_MODEL,
                  duration_ms=dur_ms, error_kind="no_candidates",
                  error_message="response had no candidates")
        return None
    first = candidates[0] if isinstance(candidates, list) else None
    if not isinstance(first, dict):
        _log_call(provider="gemini", ok=False, model=_GEMINI_MODEL,
                  duration_ms=dur_ms, error_kind="malformed",
                  error_message="first candidate not a dict")
        return None
    content = first.get("content") or {}
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        _log_call(provider="gemini", ok=False, model=_GEMINI_MODEL,
                  duration_ms=dur_ms, error_kind="malformed",
                  error_message="content.parts not a list")
        return None
    texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
    out = "".join(texts).strip()
    if out:
        usage = data.get("usageMetadata") if isinstance(data, dict) else None
        tin = (usage or {}).get("promptTokenCount") if isinstance(usage, dict) else None
        tout = (usage or {}).get("candidatesTokenCount") if isinstance(usage, dict) else None
        _log_call(
            provider="gemini", ok=True, model=_GEMINI_MODEL,
            tokens_in=tin, tokens_out=tout, duration_ms=dur_ms,
        )
        _gemini_breaker_record_success()
        return out
    _log_call(provider="gemini", ok=False, model=_GEMINI_MODEL,
              duration_ms=dur_ms, error_kind="empty_response",
              error_message="Gemini returned no text")
    return None


def _call_gemini_vision(image_paths: list[str], prompt: str,
                        system: Optional[str], max_tokens: int) -> Optional[str]:
    """Gemini multimodal generateContent — same REST endpoint, inline_data parts.

    Honours the same overload circuit breaker as ``_call_gemini`` so a
    Gemini outage doesn't waste vision round-trips when text calls
    have already noticed the failure.
    """
    key = _resolve_gemini_key()
    if not key:
        return None
    if _gemini_breaker_is_open():
        return None
    try:
        import requests
    except Exception:
        return None
    parts: list[dict] = []
    for p in image_paths[:5]:
        data, mt = _read_image_for_vision(p)
        if data is None:
            continue
        parts.append({"inline_data": {"mime_type": mt, "data": data}})
    parts.append({"text": prompt})
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{_GEMINI_MODEL}:generateContent?key={key}"
    )
    try:
        r = requests.post(url, json=payload, timeout=_GEMINI_TIMEOUT)
    except Exception:
        return None
    if not r.ok:
        if r.status_code >= 500:
            _gemini_breaker_record_failure()
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    candidates = data.get("candidates") if isinstance(data, dict) else None
    if not candidates:
        return None
    first = candidates[0] if isinstance(candidates, list) else None
    content = (first or {}).get("content") or {}
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return None
    texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
    out = "".join(texts).strip()
    if out:
        _gemini_breaker_record_success()
    return out or None


# ---------------------------------------------------------------------------
# Vision helpers
# ---------------------------------------------------------------------------

def _read_image_for_vision(path: str) -> tuple[Optional[str], Optional[str]]:
    """Return (base64_data, mime_type) for an image path, or (None, None)."""
    import base64
    try:
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
    except Exception as e:
        log.debug("vision image read failed: %s", e)
        return (None, None)
    lower = path.lower()
    if lower.endswith((".jpg", ".jpeg")):
        mt = "image/jpeg"
    elif lower.endswith(".webp"):
        mt = "image/webp"
    elif lower.endswith(".gif"):
        mt = "image/gif"
    else:
        mt = "image/png"
    return (data, mt)


def _call_anthropic_vision(image_paths: list[str], prompt: str,
                           system: Optional[str], max_tokens: int) -> Optional[str]:
    client = _get_anthropic()
    if not client:
        return None
    content_blocks: list[dict] = []
    for p in image_paths[:5]:
        data, mt = _read_image_for_vision(p)
        if data is None:
            continue
        content_blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": mt, "data": data},
        })
    content_blocks.append({"type": "text", "text": prompt})
    try:
        kwargs: dict = {
            "model": DEFAULT_MODEL,
            "messages": [{"role": "user", "content": content_blocks}],
            "max_tokens": max_tokens,
        }
        if system:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)
        parts = [b.text for b in resp.content if hasattr(b, "text")]
        return "".join(parts).strip() or None
    except Exception as e:
        log.debug("anthropic vision failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Public API — generate / generate_json / generate_vision
# ---------------------------------------------------------------------------

def _provider_order() -> tuple[str, ...]:
    """Return providers to attempt, in order, based on operator preference.

    Default: gemini first, then anthropic as fallback.
    MEDIAHUB_LLM_PROVIDER=anthropic: anthropic first, then gemini.
    """
    if _preferred_provider() == "anthropic":
        return ("anthropic", "gemini")
    return ("gemini", "anthropic")


def generate(prompt: str, *, system: Optional[str] = None, max_tokens: int = 1024,
             messages: Optional[list[dict]] = None) -> str:
    """Generate plain text via the configured LLM provider.

    Raises ClaudeUnavailableError when no provider is configured —
    callers must catch and surface to the user honestly. There is no
    hardcoded fallback output in MediaHub by design.
    """
    msgs = messages if messages else [{"role": "user", "content": prompt}]
    for provider in _provider_order():
        if provider == "gemini":
            out = _call_gemini(msgs, system, max_tokens)
        elif provider == "anthropic":
            out = _call_anthropic(msgs, system, max_tokens)
        else:
            continue
        if out:
            return out
    raise ClaudeUnavailableError(
        "AI features are unavailable on this deployment. The operator "
        "has not configured a Gemini or Anthropic API key. Contact your "
        "administrator."
    )


def generate_json(prompt: str, *, system: Optional[str] = None, max_tokens: int = 1024,
                  fallback: Optional[dict] = None) -> dict:
    """Generate a JSON dict from a prompt.

    Raises ClaudeUnavailableError when no provider is reachable.
    ``fallback`` is used only when the provider DID answer but produced
    unparseable output (rare); never to mask a missing provider.
    """
    sys_with_json = (system or "") + (
        "\n\nReturn ONLY a JSON object. No prose, no fences."
    )
    raw = generate(prompt, system=sys_with_json.strip(), max_tokens=max_tokens)
    parsed = _extract_json(raw)
    if parsed is not None:
        return parsed
    return fallback if fallback is not None else {}


def generate_vision(image_paths: list[str], prompt: str, *, system: Optional[str] = None,
                    max_tokens: int = 1024) -> str:
    """Vision generation — analyses one or more local images.

    Provider order respects ``MEDIAHUB_LLM_PROVIDER`` the same way
    text generation does. Returns the model's text. Raises
    ``ClaudeUnavailableError`` when no vision-capable provider is
    configured.
    """
    for provider in _provider_order():
        if provider == "anthropic" and _has_anthropic_key():
            out = _call_anthropic_vision(image_paths, prompt, system, max_tokens)
            if out:
                return out
        elif provider == "gemini" and _has_gemini_key():
            out = _call_gemini_vision(image_paths, prompt, system, max_tokens)
            if out:
                return out
    raise ClaudeUnavailableError(
        "AI vision features are unavailable on this deployment. The "
        "operator has not configured a Gemini or Anthropic API key. "
        "Contact your administrator."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json(raw: str) -> Optional[dict]:
    """Pull a JSON object out of an LLM response (strips fences if any)."""
    if not raw:
        return None
    text = raw.strip()
    # Remove ```json ... ``` fences
    fence = re.match(r"^```(?:json)?\s*(.+?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # Find first { ... } block
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        try:
            obj = json.loads(brace.group(0))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    return None


# ---------------------------------------------------------------------------
# Back-compat shim — V8 Live Caption API used `call_claude(system, user)`
# ---------------------------------------------------------------------------

def call_claude(system: str, user: str, model: Optional[str] = None,
                max_tokens: int = 512) -> str:
    """Back-compat wrapper. Routes through generate(). Always raises
    ClaudeUnavailableError when no provider is configured — no
    heuristic substitute.
    """
    if not is_available():
        raise ClaudeUnavailableError(
            "AI features are unavailable on this deployment."
        )
    result = generate(user, system=system, max_tokens=max_tokens)
    if not result or result.startswith("Generated content unavailable"):
        raise ClaudeUnavailableError("LLM returned empty or heuristic fallback")
    if result.strip() in ("{}", "{}\n", "[]", "{\n}"):
        raise ClaudeUnavailableError("LLM returned heuristic JSON-empty sentinel")
    return result


__all__ = [
    "generate", "generate_json", "generate_vision", "is_available",
    "active_provider", "call_claude",
    "ClaudeUnavailableError",
    "DEFAULT_MODEL", "ALT_MODEL",
]
