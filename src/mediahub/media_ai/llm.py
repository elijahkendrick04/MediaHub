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
from typing import Any, Callable, Optional, Union

# The Gemini REST transport (HTTP call, key redaction, thinking-budget
# clamp, overload circuit breaker) is shared with ai_core.llm — one copy,
# both wrappers (deep-review finding #43). This module keeps the tolerant
# contract on top of it: helpers return text or None and generate() walks
# the provider chain.
from mediahub.ai_core import gemini_transport

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


def _log_call(
    *,
    provider: str,
    ok: bool,
    model: Optional[str] = None,
    tokens_in: Optional[int] = None,
    tokens_out: Optional[int] = None,
    duration_ms: Optional[float] = None,
    error_kind: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    try:
        from mediahub.observability import llm_usage as _u

        _u.record_call(
            provider=provider,
            ok=ok,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_ms=duration_ms,
            error_kind=error_kind,
            error_message=error_message,
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
    """Return env GEMINI_API_KEY (or GOOGLE_API_KEY), else stored secret.

    Canonical resolution lives in ``ai_core.gemini_transport``; this stays
    a module-level function (not a bare import alias) because tests and
    the background/imagery providers patch and import it here by name.
    """
    return gemini_transport.resolve_gemini_key()


def _has_gemini_key() -> bool:
    return bool(_resolve_gemini_key())


def _preferred_provider() -> str:
    """Return the operator's preferred provider key.

    'openai'    when MEDIAHUB_LLM_PROVIDER=openai
    'anthropic' when =anthropic or =claude (alias)
    'gemini'    otherwise (empty, 'gemini', 'auto', unknown).
    """
    pref = (os.environ.get("MEDIAHUB_LLM_PROVIDER") or "").strip().lower()
    if pref == "openai":
        return "openai"
    if pref in ("anthropic", "claude"):
        return "anthropic"
    return "gemini"


def _is_openai_on() -> bool:
    """True when an OpenAI-compatible endpoint is configured. Lazy import keeps
    media_ai.llm importable even if the adapter module is ever absent."""
    try:
        from mediahub.media_ai.llm_providers import is_openai_configured

        return is_openai_configured()
    except Exception:
        return False


def is_available() -> bool:
    """True if any real LLM provider is reachable."""
    return _has_gemini_key() or _has_anthropic_key() or _is_openai_on()


def active_provider() -> str:
    """Return the user-friendly name of the active LLM provider.

    Returns one of: 'openai-api', 'anthropic-api', 'gemini-api', 'heuristic'.
    The 'heuristic' label is the historical placeholder for "no provider
    configured"; callers that branch on it should treat it as
    "AI features unavailable".
    """
    pref = _preferred_provider()
    if pref == "openai" and _is_openai_on():
        return "openai-api"
    if pref == "anthropic" and _has_anthropic_key():
        return "anthropic-api"
    if _has_gemini_key():
        return "gemini-api"
    if _has_anthropic_key():
        return "anthropic-api"
    if _is_openai_on():
        return "openai-api"
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


def _call_anthropic(
    messages: list[dict], system: Optional[str], max_tokens: int, model: Optional[str] = None
) -> Optional[str]:
    if not _has_anthropic_key():
        return None
    client = _get_anthropic()
    if not client:
        return None
    use_model = model or DEFAULT_MODEL
    # Only fall back to the alt model when it's actually different (don't retry
    # the identical model the operator already pinned to ALT_MODEL).
    attempt_models = (use_model,) if use_model == ALT_MODEL else (use_model, ALT_MODEL)
    for attempt_model in attempt_models:
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
                provider="anthropic",
                ok=bool(text),
                model=attempt_model,
                tokens_in=tin,
                tokens_out=tout,
                duration_ms=(time.monotonic() - started) * 1000.0,
                error_kind=None if text else "empty_response",
                error_message=None if text else "Anthropic returned no text",
            )
            if text:
                return text
        except Exception as e:
            log.warning("anthropic call failed (%s): %s", attempt_model, e)
            _log_call(
                provider="anthropic",
                ok=False,
                model=attempt_model,
                duration_ms=(time.monotonic() - started) * 1000.0,
                error_kind=type(e).__name__,
                error_message=str(e),
            )
            # Only a model-specific failure (404 not-found / 529 overloaded) can
            # be helped by trying the alt model. For auth/bad-request/rate-limit
            # a second billable call won't succeed — stop instead of burning it.
            if getattr(e, "status_code", None) not in (404, 529):
                break
            continue
    return None


# ---------------------------------------------------------------------------
# Gemini (free default) — HTTP transport, key redaction, thinking-budget
# clamp and the overload circuit breaker all live in
# ai_core.gemini_transport (one copy for both LLM wrappers, finding #43).
# This side keeps the tolerant contract: helpers return text or None and
# write one usage-ledger row per attempt.
# ---------------------------------------------------------------------------


def _ledger_kind(e: "gemini_transport.GeminiTransportError") -> str:
    """Map a classified transport failure onto the ledger's ``error_kind``
    vocabulary (auth / rate_limited / transport / parse / http_NNN /
    no_candidates / malformed). One vocabulary for both Gemini surfaces
    now: gemini-vision rows adopted the text path's ``auth`` /
    ``rate_limited`` names (they used to land as raw ``http_401/403/429``
    — recorded in ADR-0030)."""
    if e.status in (401, 403):
        return "auth"
    if e.status == 429:
        return "rate_limited"
    return e.kind


def _gemini_via_transport(
    provider_label: str,
    payload: Union[dict[str, Any], Callable[[], dict[str, Any]]],
) -> Optional[str]:
    """One tolerant Gemini round-trip: text or ``None``, never raises.

    Skips the network entirely while the shared overload breaker is open
    (media_ai is the hot path — org-setup capture fires ~24 sequential
    calls, so a doomed round-trip per call turns ~10s into 60–80s).
    Breaker accounting itself happens inside the transport so outages
    seen by either wrapper trip the same switch.

    ``payload`` may be a zero-arg builder: expensive payload construction
    (vision's per-image base64 encode) then happens only after the no-key
    and breaker-open short-circuits, matching the pre-convergence cost of
    a skipped call (zero).
    """
    key = _resolve_gemini_key()
    if not key:
        return None
    model = gemini_transport.gemini_model()
    if gemini_transport.breaker_is_open():
        _log_call(
            provider=provider_label,
            ok=False,
            model=model,
            duration_ms=0.0,
            error_kind="breaker_open",
            error_message="Gemini circuit breaker is open; " "skipping to next provider",
        )
        return None
    if callable(payload):
        payload = payload()
    started = time.monotonic()
    try:
        data = gemini_transport.generate_content(
            payload, key=key, model=model, timeout_default=45.0
        )
        parts = gemini_transport.first_candidate_parts(data)
    except gemini_transport.GeminiTransportError as e:
        dur_ms = (time.monotonic() - started) * 1000.0
        if e.kind == "transport":
            log.warning("gemini transport failed: %s", e)
        elif e.status is not None and e.status not in (401, 403, 429):
            log.warning("gemini non-ok (%s): %s", e.status, e)
        _log_call(
            provider=provider_label,
            ok=False,
            model=model,
            duration_ms=dur_ms,
            error_kind=_ledger_kind(e),
            error_message=str(e)[:300],
        )
        return None
    dur_ms = (time.monotonic() - started) * 1000.0
    out = gemini_transport.text_from_parts(parts)
    if out:
        tin, tout = gemini_transport.usage_tokens(data)
        _log_call(
            provider=provider_label,
            ok=True,
            model=model,
            tokens_in=tin,
            tokens_out=tout,
            duration_ms=dur_ms,
        )
        return out
    _log_call(
        provider=provider_label,
        ok=False,
        model=model,
        duration_ms=dur_ms,
        error_kind="empty_response",
        error_message="Gemini returned no text",
    )
    return None


def _call_gemini(messages: list[dict], system: Optional[str], max_tokens: int) -> Optional[str]:
    """Call Google Gemini generateContent. Returns text or None.

    Free-tier limits (gemini-2.5-flash): 15 RPM, 1,500 RPD. Plenty for
    a small-club deployment; the dissertation's cost model assumes
    free tier handles the entire small-club tier.

    Returns None immediately (without an HTTP round-trip) while the
    overload circuit breaker is tripped. The caller's normal
    fall-through to Anthropic kicks in the same way it would on a real
    Gemini failure.
    """
    contents: list[dict] = []
    for m in messages or []:
        role = m.get("role", "user")
        content = m.get("content", "")
        # Gemini uses 'user' / 'model' role names.
        contents.append(
            {
                "role": "model" if role == "assistant" else "user",
                "parts": [{"text": str(content)}],
            }
        )
    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": gemini_transport.generation_config(max_tokens),
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    return _gemini_via_transport("gemini", payload)


def _call_gemini_vision(
    image_paths: list[str], prompt: str, system: Optional[str], max_tokens: int
) -> Optional[str]:
    """Gemini multimodal generateContent — same REST endpoint, inline_data parts.

    Honours the same overload circuit breaker as ``_call_gemini`` so a
    Gemini outage doesn't waste vision round-trips when text calls
    have already noticed the failure.
    """

    def _build_payload() -> dict[str, Any]:
        # Built lazily: base64-encoding up to 5 photos is the expensive part
        # of a vision call, and it must cost nothing when the breaker is
        # open or no key is configured (the guards run first).
        parts: list[dict] = []
        for p in image_paths[:5]:
            data, mt = _read_image_for_vision(p)
            if data is None:
                continue
            parts.append({"inline_data": {"mime_type": mt, "data": data}})
        parts.append({"text": prompt})
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": gemini_transport.generation_config(max_tokens),
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        return payload

    return _gemini_via_transport("gemini-vision", _build_payload)


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


def _call_anthropic_vision(
    image_paths: list[str], prompt: str, system: Optional[str], max_tokens: int
) -> Optional[str]:
    client = _get_anthropic()
    if not client:
        return None
    content_blocks: list[dict] = []
    for p in image_paths[:5]:
        data, mt = _read_image_for_vision(p)
        if data is None:
            continue
        content_blocks.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": mt, "data": data},
            }
        )
    content_blocks.append({"type": "text", "text": prompt})
    started = time.monotonic()
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
        text = "".join(parts).strip() or None
        usage = getattr(resp, "usage", None)
        tin = getattr(usage, "input_tokens", None) if usage else None
        tout = getattr(usage, "output_tokens", None) if usage else None
        _log_call(
            provider="anthropic-vision",
            ok=bool(text),
            model=DEFAULT_MODEL,
            tokens_in=tin,
            tokens_out=tout,
            duration_ms=(time.monotonic() - started) * 1000.0,
            error_kind=None if text else "empty_response",
            error_message=None if text else "Anthropic returned no text",
        )
        return text
    except Exception as e:
        log.warning("anthropic vision failed: %s", e)
        _log_call(
            provider="anthropic-vision",
            ok=False,
            model=DEFAULT_MODEL,
            duration_ms=(time.monotonic() - started) * 1000.0,
            error_kind=type(e).__name__,
            error_message=str(e),
        )
        return None


# ---------------------------------------------------------------------------
# Public API — generate / generate_json / generate_vision
# ---------------------------------------------------------------------------


def _provider_order() -> tuple[str, ...]:
    """Return providers to attempt, in order, based on operator preference.

    Default: gemini first, then anthropic as fallback.
    MEDIAHUB_LLM_PROVIDER=anthropic: anthropic first, then gemini.
    MEDIAHUB_LLM_PROVIDER=openai: openai first, then gemini, then anthropic.

    The 'openai' provider only joins the order when an OpenAI-compatible
    endpoint is actually configured; otherwise the order is unchanged and the
    feature is inert.
    """
    pref = _preferred_provider()
    base = ("anthropic", "gemini") if pref == "anthropic" else ("gemini", "anthropic")
    if not _is_openai_on():
        return base
    if pref == "openai":
        return ("openai",) + base
    return base + ("openai",)


def generate(
    prompt: str,
    *,
    system: Optional[str] = None,
    max_tokens: int = 1024,
    messages: Optional[list[dict]] = None,
    content_type: Optional[str] = None,
) -> str:
    """Generate plain text via the configured LLM provider.

    Raises ClaudeUnavailableError when no provider is configured —
    callers must catch and surface to the user honestly. There is no
    hardcoded fallback output in MediaHub by design.

    ``content_type`` labels the surface for per-type model routing
    (see :mod:`mediahub.media_ai.model_select`): hero surfaces such as
    ``"caption"`` / ``"spotlight"`` / ``"recap"`` earn the premium
    model on the OpenAI-compatible path. Gemini/Anthropic ignore it.
    """
    msgs = messages if messages else [{"role": "user", "content": prompt}]
    # Track which providers actually had a key and were CALLED, so an all-attempts-
    # failed outcome isn't reported as "not configured" (the same honest-error fix
    # generate_vision already carries; the hot-path generate() had been left out).
    attempted: list[str] = []
    for provider in _provider_order():
        if provider == "gemini" and _has_gemini_key():
            attempted.append(provider)
            out = _call_gemini(msgs, system, max_tokens)
        elif provider == "anthropic" and _has_anthropic_key():
            attempted.append(provider)
            out = _call_anthropic(msgs, system, max_tokens)
        elif provider == "openai" and _is_openai_on():
            from mediahub.media_ai.llm_providers import call_openai

            attempted.append(provider)
            out = call_openai(msgs, system, max_tokens, content_type=content_type)
        else:
            continue
        if out:
            return out
    if attempted:
        # Keys exist and calls were made — saying "not configured" would be a false
        # reason. The failure detail is in the usage ledger / logs the helpers write.
        raise ClaudeUnavailableError(
            "AI text generation failed (provider(s) attempted: "
            f"{', '.join(attempted)}). See the LLM usage log for the failure detail."
        )
    raise ClaudeUnavailableError(
        "AI features are unavailable on this deployment. The operator "
        "has not configured a Gemini or Anthropic API key. Contact your "
        "administrator."
    )


def generate_json(
    prompt: str,
    *,
    system: Optional[str] = None,
    max_tokens: int = 1024,
    fallback: Optional[dict] = None,
    content_type: Optional[str] = None,
) -> dict:
    """Generate a JSON dict from a prompt.

    Raises ClaudeUnavailableError when no provider is reachable.
    ``fallback`` is used only when the provider DID answer but produced
    unparseable output (rare); never to mask a missing provider.
    ``content_type`` threads through to :func:`generate` for per-type
    model routing on the OpenAI-compatible path.
    """
    sys_with_json = (system or "") + ("\n\nReturn ONLY a JSON object. No prose, no fences.")
    raw = generate(
        prompt, system=sys_with_json.strip(), max_tokens=max_tokens, content_type=content_type
    )
    parsed = _extract_json(raw)
    if parsed is not None:
        return parsed
    # The provider answered but the output didn't parse as JSON. Don't let that be
    # silently indistinguishable from an empty result at the ~20 call sites — log
    # it (a head snippet, never the whole blob) before falling back.
    log.warning(
        "generate_json: provider output was not parseable JSON (%d chars); using fallback. head=%r",
        len(raw or ""),
        (raw or "")[:120],
    )
    return fallback if fallback is not None else {}


def generate_vision(
    image_paths: list[str], prompt: str, *, system: Optional[str] = None, max_tokens: int = 1024
) -> str:
    """Vision generation — analyses one or more local images.

    Provider order respects ``MEDIAHUB_LLM_PROVIDER`` the same way
    text generation does. Returns the model's text. Raises
    ``ClaudeUnavailableError`` when no vision-capable provider is
    configured — or, honestly distinct, when configured providers were
    attempted and every call failed.
    """
    attempted: list[str] = []
    for provider in _provider_order():
        if provider == "anthropic" and _has_anthropic_key():
            attempted.append(provider)
            out = _call_anthropic_vision(image_paths, prompt, system, max_tokens)
            if out:
                return out
        elif provider == "gemini" and _has_gemini_key():
            attempted.append(provider)
            out = _call_gemini_vision(image_paths, prompt, system, max_tokens)
            if out:
                return out
    if attempted:
        # Keys exist and calls were made — saying "not configured" here
        # would be a false reason (honest-error rule). Details are in the
        # usage ledger / logs recorded by the vision helpers.
        raise ClaudeUnavailableError(
            "AI vision call failed (provider(s) attempted: "
            f"{', '.join(attempted)}). See the LLM usage log for the "
            "failure detail."
        )
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


def call_claude(system: str, user: str, model: Optional[str] = None, max_tokens: int = 512) -> str:
    """Back-compat wrapper. Routes through generate(). Always raises
    ClaudeUnavailableError when no provider is configured — no
    heuristic substitute.
    """
    if not is_available():
        raise ClaudeUnavailableError("AI features are unavailable on this deployment.")
    result = generate(user, system=system, max_tokens=max_tokens)
    if not result or result.startswith("Generated content unavailable"):
        raise ClaudeUnavailableError("LLM returned empty or heuristic fallback")
    if result.strip() in ("{}", "{}\n", "[]", "{\n}"):
        raise ClaudeUnavailableError("LLM returned heuristic JSON-empty sentinel")
    return result


__all__ = [
    "generate",
    "generate_json",
    "generate_vision",
    "is_available",
    "active_provider",
    "call_claude",
    "ClaudeUnavailableError",
    "DEFAULT_MODEL",
    "ALT_MODEL",
]
