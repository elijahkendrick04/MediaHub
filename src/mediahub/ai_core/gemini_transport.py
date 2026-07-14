"""mediahub/ai_core/gemini_transport.py — the one Gemini REST transport.

Both LLM wrappers speak to the same ``generativelanguage`` endpoint:

- ``media_ai.llm`` — the tolerant content-generation surface (helpers
  return text or ``None``; ``generate()`` walks the provider chain and
  raises ``ClaudeUnavailableError`` only when everything failed), and
- ``ai_core.llm`` — the strict ``ask()`` / ``ask_with_tools()`` surface
  (helpers raise ``ProviderError(transient=…)`` so failover can branch).

Until 2026-07 each carried its own near line-for-line copy of the HTTP
call, the generationConfig / thinking-budget clamp, the key redaction and
the overload-breaker wiring — and the copies drifted (deep-review finding
#43: hardcoded timeouts, a stray ``temperature``, a breaker only one
wrapper recorded into). This module is the single copy:

- URL + headers — the API key rides the ``x-goog-api-key`` header, never
  the URL, so it can't leak into exception reprs / access / proxy logs;
- per-call model + timeout resolution (``MEDIAHUB_GEMINI_MODEL``,
  ``MEDIAHUB_GEMINI_TIMEOUT``);
- generationConfig incl. the 2.5+/Pro ``thinkingBudget`` clamp. No
  ``temperature`` is sent — both wrappers sample at the API default so the
  same surface can't drift in output character by wrapper;
- transient-vs-permanent HTTP status classification (cross-*provider*
  failover semantics: 401/403 are transient because another provider holds
  a different key — distinct from ``llm_client.py``'s same-key
  multi-*endpoint* set, where auth failures are permanent);
- the Gemini overload circuit breaker. State lives here now; the transport
  records outcomes for every caller, so an outage first seen by chat /
  copilot / deep-research trips the breaker captions consult too.

What deliberately does NOT live here: provider failover order, the
tolerant-``None`` vs strict-``raise`` error contracts, usage-ledger rows
(``observability.llm_usage``), and the breaker *skip* policy — media_ai
short-circuits to ``None`` while the breaker is open (hot path, ~24-call
capture batches), ai_core demotes Gemini to the tail of its chain but
still tries it last. Those belong to the wrappers; this module only moves
bytes and reports outcomes honestly. No templates, no fabricated output:
every failure raises :class:`GeminiTransportError` with a redacted,
classified reason.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Optional

log = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Statuses worth retrying on the *next provider* (Gemini → Anthropic):
# auth (another provider has its own key), contention/rate limits,
# overload, plus any 5xx via status_transient(). A definite 400/404
# config error is permanent — retrying it elsewhere buries the real
# message.
_TRANSIENT_HTTP_STATUSES = frozenset({401, 403, 408, 409, 425, 429, 529})


class GeminiTransportError(RuntimeError):
    """One failed Gemini round-trip, classified.

    ``kind``      machine-readable failure class: ``transport`` (no HTTP
                  status: DNS / reset / timeout), ``http_<status>``,
                  ``parse`` (200 but undecodable body), ``no_candidates``,
                  ``malformed`` (decoded but shape-invalid), or
                  ``dependency`` (requests missing).
    ``status``    the HTTP status when one exists, else ``None``.
    ``transient`` whether trying another provider could help; the message
                  is always key-redacted before it gets here.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: str,
        status: Optional[int] = None,
        transient: bool,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.transient = transient


# ---------------------------------------------------------------------------
# Env resolution — key, model, timeout (all per call; operator can rotate
# the key or retarget the model without a process restart)
# ---------------------------------------------------------------------------


def resolve_gemini_key() -> Optional[str]:
    """Env ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY`` first, then secrets store."""
    for env_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        v = os.environ.get(env_name, "").strip()
        if v:
            return v
    try:
        from mediahub.web.secrets_store import get_secret

        v = get_secret("gemini_api_key")
        return v.strip() if v and v.strip() else None
    except Exception:
        return None


def gemini_model() -> str:
    # May 2026: gemini-2.0-flash was deprecated by Google. gemini-2.5-flash
    # is the current GA model with the same free-tier quotas (1,500 req/day).
    return os.environ.get("MEDIAHUB_GEMINI_MODEL", "gemini-2.5-flash")


def gemini_timeout(default: float = 45.0) -> float:
    """Per-call read of ``MEDIAHUB_GEMINI_TIMEOUT`` (seconds).

    The call-site default is preserved when the env is unset or
    unparseable — 45s for plain asks, 60s for tool rounds (tool responses
    carry function-call payloads and run longer).
    """
    raw = os.environ.get("MEDIAHUB_GEMINI_TIMEOUT", "").strip()
    if not raw:
        return default
    try:
        return max(1.0, float(raw))
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Key redaction — defence-in-depth even though the key rides a header now
# ---------------------------------------------------------------------------


def redact_key(text: str, key: Optional[str]) -> str:
    """Strip the Gemini API key from arbitrary text before it can ride an
    error message into logs, operator dashboards or user-facing errors.

    Rewrites both the literal key and any ``key=`` query-param fragment
    (URL-encoded leftovers included) to a stable redaction sentinel.
    """
    if not text:
        return text
    out = text
    if key:
        out = out.replace(key, "***REDACTED***")
    out = re.sub(r"(?i)(\?|&)key=[^&\s'\")]+", r"\1key=***REDACTED***", out)
    return out


# ---------------------------------------------------------------------------
# generationConfig — thinking budget clamp, no temperature
# ---------------------------------------------------------------------------


def thinking_budget() -> int:
    """Tokens the model may spend on internal "thinking".

    Gemini 2.5+ ships thinking on by default; thinking tokens count
    against ``maxOutputTokens`` but never appear in the response text, so
    callers sized for the visible output get truncated mid-JSON. Default 0
    (off) — operators opt back in via ``MEDIAHUB_GEMINI_THINKING_BUDGET``.
    """
    raw = os.environ.get("MEDIAHUB_GEMINI_THINKING_BUDGET", "0").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def generation_config(max_tokens: int, model: Optional[str] = None) -> dict:
    """Build generationConfig. No ``temperature`` is sent — both wrappers
    sample at the API default (finding #43 parity)."""
    cfg: dict = {"maxOutputTokens": int(max_tokens)}
    use_model = model or gemini_model()
    # thinkingConfig is only honoured by 2.5+ models; sending it to an older
    # model is rejected as an unknown field.
    if "2.5" in use_model or "3." in use_model:
        budget = thinking_budget()
        # Pro models reject thinkingBudget < 128 (400 INVALID_ARGUMENT);
        # clamp there. Flash models keep 0 (thinking off).
        if "pro" in use_model:
            budget = max(128, budget)
        cfg["thinkingConfig"] = {"thinkingBudget": budget}
    return cfg


# ---------------------------------------------------------------------------
# Transient classification
# ---------------------------------------------------------------------------


def status_transient(status: int) -> bool:
    """True when an HTTP status warrants trying the next *provider*."""
    return status in _TRANSIENT_HTTP_STATUSES or 500 <= status <= 599


# ---------------------------------------------------------------------------
# Gemini overload circuit breaker (state moved here from media_ai.llm)
# ---------------------------------------------------------------------------
# When Gemini returns repeated transport failures / 5xx, every subsequent
# call still pays the round-trip (worst case the full timeout) before
# falling through to Anthropic. The org-setup capture step is the worst
# offender — ~24 sequential Gemini calls — so a sustained outage turns a
# ~10s capture into a 60–80s hang. The breaker is a tiny in-process trip
# switch: N consecutive failures within the window → skip/demote Gemini
# for a cool-off period. Any decoded 200 clears it.
#
# Intentionally per-process, not cluster-wide: with two gunicorn workers
# the cost of the second worker independently discovering the outage is
# one wasted call per request batch — not worth bringing in Redis.


def _safe_int(value: object, default: int) -> int:
    """Coerce an already-read env value to int, falling back to ``default`` on a
    bad value instead of raising at import time and taking down every importer
    (e.g. web.py). Takes the value (not the name) so the ``os.environ.get(...)``
    call stays visible to the env-inventory grep."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        log.warning("gemini_transport: expected an int env value, got %r; using %d", value, default)
        return default


def _safe_float(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        log.warning(
            "gemini_transport: expected a numeric env value, got %r; using %s", value, default
        )
        return default


_BREAKER_THRESHOLD = _safe_int(os.environ.get("MEDIAHUB_GEMINI_BREAKER_THRESHOLD", "3"), 3)
_BREAKER_COOLDOWN_S = _safe_float(os.environ.get("MEDIAHUB_GEMINI_BREAKER_COOLDOWN_S", "60"), 60.0)
_breaker_lock = threading.Lock()
_breaker_state: dict[str, float] = {
    "consecutive_failures": 0.0,  # float so it round-trips through env
    "tripped_until": 0.0,  # time.monotonic() value
}


def breaker_is_open() -> bool:
    """True while Gemini is being skipped/demoted after sustained failures."""
    with _breaker_lock:
        return time.monotonic() < _breaker_state["tripped_until"]


def breaker_record_failure() -> None:
    """Count a failure; trip the breaker when the threshold is hit."""
    with _breaker_lock:
        _breaker_state["consecutive_failures"] += 1
        if _breaker_state["consecutive_failures"] >= _BREAKER_THRESHOLD:
            _breaker_state["tripped_until"] = time.monotonic() + _BREAKER_COOLDOWN_S


def breaker_record_success() -> None:
    """Any success clears the trip and resets the failure counter."""
    with _breaker_lock:
        _breaker_state["consecutive_failures"] = 0
        _breaker_state["tripped_until"] = 0.0


def breaker_snapshot() -> dict:
    """Current breaker state, JSON-serialisable (``/healthz/breaker`` reads
    this). Values are per-process — multi-worker deployments see one
    snapshot per gunicorn worker."""
    with _breaker_lock:
        now = time.monotonic()
        tripped_until = _breaker_state["tripped_until"]
        return {
            "open": now < tripped_until,
            "consecutive_failures": int(_breaker_state["consecutive_failures"]),
            "seconds_until_reset": max(0.0, round(tripped_until - now, 1)),
            "threshold": _BREAKER_THRESHOLD,
            "cooldown_seconds": _BREAKER_COOLDOWN_S,
        }


# ---------------------------------------------------------------------------
# The transport call
# ---------------------------------------------------------------------------


def generate_content(
    payload: dict,
    *,
    key: str,
    model: Optional[str] = None,
    timeout_default: float = 45.0,
) -> dict:
    """POST ``models/<model>:generateContent``; return the decoded body.

    ``key`` is required and caller-resolved — the wrapper that checked
    which key is configured is the one whose key gets sent (keeps tests'
    monkeypatched resolvers authoritative). Raises
    :class:`GeminiTransportError` (message always key-redacted) on
    transport failure, non-200, or an undecodable body.

    Breaker accounting (both wrappers, both directions — finding #43):
    transport errors and 5xx record a failure; any decoded 200 records a
    success (the service answered — an unusable *model* output is not an
    availability signal). Rate limits (429) and other 4xx are our
    problem or a quota, not an outage, and don't count. This function
    does NOT check ``breaker_is_open()`` — skip/demote policy stays with
    the wrappers.
    """
    try:
        import requests  # noqa: PLC0415 — lazy, keeps module import light
    except ImportError as e:  # pragma: no cover - requests is a hard dep
        raise GeminiTransportError(
            f"requests not available: {e}", kind="dependency", transient=False
        ) from e

    use_model = model or gemini_model()
    url = f"{GEMINI_API_BASE}/{use_model}:generateContent"
    try:
        r = requests.post(
            url,
            json=payload,
            # Key in the x-goog-api-key header, NOT the URL — a URL-borne
            # ?key= rides into exception reprs, access logs and proxy logs.
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
            timeout=gemini_timeout(timeout_default),
        )
    except Exception as e:
        # No HTTP status: DNS / reset / timeout. Transient (another provider
        # may answer) and the breaker's most expensive case — each such call
        # eats the full request timeout — so it counts toward tripping.
        breaker_record_failure()
        raise GeminiTransportError(
            redact_key(str(e), key), kind="transport", transient=True
        ) from e
    if r.status_code != 200:
        if r.status_code >= 500:
            breaker_record_failure()
        raise GeminiTransportError(
            redact_key((r.text or "")[:300], key),
            kind=f"http_{r.status_code}",
            status=r.status_code,
            transient=status_transient(r.status_code),
        )
    try:
        data = r.json()
    except ValueError as e:
        raise GeminiTransportError(
            "response was not JSON", kind="parse", status=200, transient=True
        ) from e
    # A decoded 200 proves the service is reachable — clear the breaker even
    # if the model output turns out unusable downstream.
    breaker_record_success()
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Response-shape helpers (shared candidates/parts walk)
# ---------------------------------------------------------------------------


def first_candidate_parts(data: dict) -> list[dict]:
    """Return the first candidate's ``parts`` list, or raise (classified).

    ``no_candidates`` — safety block / empty response; ``malformed`` — the
    body decoded but isn't the documented shape. Both transient: another
    provider may still answer the same prompt.
    """
    candidates = data.get("candidates") if isinstance(data, dict) else None
    if not candidates:
        raise GeminiTransportError(
            f"response had no candidates: {str(data)[:240]}",
            kind="no_candidates",
            transient=True,
        )
    first = candidates[0] if isinstance(candidates, list) else None
    if not isinstance(first, dict):
        raise GeminiTransportError(
            "first candidate not a dict", kind="malformed", transient=True
        )
    content = first.get("content") or {}
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise GeminiTransportError(
            "content.parts not a list", kind="malformed", transient=True
        )
    return parts


def text_from_parts(parts: list) -> str:
    """Concatenated text parts, stripped. May legitimately be empty
    (safety block / MAX_TOKENS ate the budget) — empty-output policy
    belongs to the wrappers."""
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()


def finish_reason(data: dict) -> Optional[str]:
    """Why the model stopped, for honest empty-output errors."""
    if not isinstance(data, dict):
        return None
    cands = data.get("candidates") or []
    reason = cands[0].get("finishReason") if cands and isinstance(cands[0], dict) else None
    if reason:
        return reason
    feedback = data.get("promptFeedback") or {}
    return feedback.get("blockReason") if isinstance(feedback, dict) else None


def usage_tokens(data: dict) -> tuple[Optional[int], Optional[int]]:
    """(tokens_in, tokens_out) from usageMetadata, when present."""
    usage = data.get("usageMetadata") if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        return (None, None)
    return (usage.get("promptTokenCount"), usage.get("candidatesTokenCount"))


__all__ = [
    "GEMINI_API_BASE",
    "GeminiTransportError",
    "resolve_gemini_key",
    "gemini_model",
    "gemini_timeout",
    "redact_key",
    "thinking_budget",
    "generation_config",
    "status_transient",
    "breaker_is_open",
    "breaker_record_failure",
    "breaker_record_success",
    "breaker_snapshot",
    "generate_content",
    "first_candidate_parts",
    "text_from_parts",
    "finish_reason",
    "usage_tokens",
]
