"""mediahub/ai_core/llm_client.py — OpenAI-compatible chat transport.

A provider-agnostic client speaking the OpenAI ``/v1/chat/completions`` wire
format. It works against any endpoint that implements that schema: Groq,
OpenRouter, Together, Fireworks, DeepInfra, a self-hosted vLLM / Ollama /
llama.cpp server, or the OpenAI API itself.

This module is the **swappable transport seam**. All HTTP for the ``openai``
provider lives here; the two MediaHub LLM wrappers (``media_ai.llm`` and
``ai_core.llm``) call into it rather than building requests themselves. It is
pure ``requests``, synchronous, no vendor SDK — the same architectural
constraints as the rest of MediaHub's AI path.

Configuration is env-only (see :func:`endpoints_from_env` /
:func:`resolve_openai_key`):

    MEDIAHUB_LLM_ENDPOINTS   comma-separated base URLs, each ending ``/v1``
                             (e.g. ``https://api.groq.com/openai/v1``).
                             Multiple entries => failover in listed order.
    MEDIAHUB_LLM_API_KEY     bearer token; optional — keyless local servers
                             (Ollama / llama.cpp) need no key.
    MEDIAHUB_LLM_TIMEOUT     per-request timeout in seconds (default 45).

When ``MEDIAHUB_LLM_ENDPOINTS`` is unset the feature is inert:
:func:`client_from_env` returns ``None`` and the ``openai`` provider is never
offered to either wrapper.

There are no heuristic fallbacks here: a failed call raises
:class:`OpenAICompatError` so the caller can fail honestly, consistent with
MediaHub's no-fake-content rule.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Iterator, Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 45.0

# Model-name substrings that reliably advertise tool/function calling. Used as
# a cheap heuristic by :meth:`OpenAICompatClient.supports_tools` before falling
# back to a live ``/models`` probe.
_TOOL_CAPABLE_HINTS = (
    "gpt-4", "gpt-4o", "gpt-3.5", "o1", "o3", "o4",
    "llama-3", "llama3", "llama-4", "mixtral", "mistral", "ministral",
    "qwen", "deepseek", "command-r", "firefunction", "gemma-2", "gemma2",
)

# Statuses worth retrying on the next configured endpoint. Everything else
# (e.g. 400/401/404) is a request/auth problem that won't fix on a retry.
_TRANSIENT_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class OpenAICompatError(RuntimeError):
    """Raised when every configured OpenAI-compatible endpoint fails."""


@dataclass
class ChatResult:
    """A single chat completion. ``raw`` carries the full decoded response so
    tool-calling callers can read ``choices[0].message.tool_calls``."""
    text: str
    model: str = ""
    raw: dict = field(default_factory=dict)
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None


def _is_transient_status(code: int) -> bool:
    """True when an HTTP status warrants failing over to the next endpoint."""
    return code in _TRANSIENT_STATUS or code >= 500


def _host(url: str) -> str:
    """Hostname only — safe to log. The bearer token rides an Authorization
    header, never the URL, so the netloc carries no secret."""
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url


class OpenAICompatClient:
    """Minimal OpenAI-compatible client with multi-endpoint failover.

    ``endpoints`` are base URLs each ending in ``/v1``; calls try them in
    order, advancing to the next on a transient failure and raising
    :class:`OpenAICompatError` once the list is exhausted. ``api_key`` may be
    ``None`` for keyless local servers (the Authorization header is omitted).
    """

    def __init__(self, endpoints, api_key=None, *, timeout=DEFAULT_TIMEOUT,
                 default_model=None):
        self.endpoints = [e.rstrip("/") for e in (endpoints or []) if e and e.strip()]
        if not self.endpoints:
            raise ValueError("OpenAICompatClient requires at least one endpoint URL")
        self.api_key = api_key.strip() if api_key and api_key.strip() else None
        try:
            self.timeout = max(1.0, float(timeout)) if timeout else DEFAULT_TIMEOUT
        except (TypeError, ValueError):
            self.timeout = DEFAULT_TIMEOUT
        self.default_model = default_model or None
        # endpoint URL -> set of lowercased model ids (lazy, cached).
        self._models_cache: dict[str, set] = {}

    # -- internal helpers ---------------------------------------------------
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _build_messages(self, messages, system) -> list:
        msgs = list(messages or [])
        if system and not any((m or {}).get("role") == "system" for m in msgs):
            msgs = [{"role": "system", "content": system}] + msgs
        return msgs

    def _parse_chat(self, data: dict, fallback_model: str) -> ChatResult:
        choices = (data or {}).get("choices") or []
        text = ""
        if choices:
            msg = choices[0].get("message") or {}
            text = (msg.get("content") or "").strip()
        usage = (data or {}).get("usage") or {}
        return ChatResult(
            text=text,
            model=(data or {}).get("model") or fallback_model,
            raw=data or {},
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
        )

    # -- public API ---------------------------------------------------------
    def chat(self, messages, *, model=None, system=None, max_completion_tokens=1024,
             tools=None, temperature=0.7, extra=None) -> ChatResult:
        """POST a chat completion, failing over across endpoints.

        Non-transient statuses (e.g. 400/401/404) raise immediately;
        transient ones (429/5xx/transport) advance to the next endpoint and
        raise only once the list is exhausted.
        """
        import requests  # noqa: PLC0415 — lazy, keeps module import light

        use_model = model or self.default_model
        if not use_model:
            raise OpenAICompatError("No model specified and no default_model configured.")
        payload: dict = {
            "model": use_model,
            "messages": self._build_messages(messages, system),
            "max_completion_tokens": max(16, int(max_completion_tokens)),
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
        if extra:
            payload.update(extra)

        last_err: Optional[Exception] = None
        for i, endpoint in enumerate(self.endpoints):
            is_last = i == len(self.endpoints) - 1
            url = f"{endpoint}/chat/completions"
            try:
                r = requests.post(url, json=payload, headers=self._headers(),
                                  timeout=self.timeout)
            except Exception as e:
                last_err = OpenAICompatError(f"transport error to {_host(endpoint)}: {e}")
                if is_last:
                    raise last_err from e
                log.warning("openai-compat transport error (%s); trying next endpoint",
                            _host(endpoint))
                continue
            if r.status_code == 200:
                return self._parse_chat(r.json(), use_model)
            err = OpenAICompatError(
                f"HTTP {r.status_code} from {_host(endpoint)}: {(r.text or '')[:240]}"
            )
            if not _is_transient_status(r.status_code) or is_last:
                raise err
            last_err = err
            log.warning("openai-compat HTTP %s from %s; trying next endpoint",
                        r.status_code, _host(endpoint))
        raise last_err or OpenAICompatError("all endpoints failed")

    def stream_chat(self, messages, *, model=None, system=None,
                    max_completion_tokens=1024, temperature=0.7, extra=None) -> Iterator[str]:
        """Yield content deltas from a streaming completion (SSE).

        Streaming uses the first endpoint only — mid-stream failover can't be
        done safely once bytes are flowing. Raises :class:`OpenAICompatError`
        if the request can't be opened.
        """
        import requests  # noqa: PLC0415

        use_model = model or self.default_model
        if not use_model:
            raise OpenAICompatError("No model specified and no default_model configured.")
        payload: dict = {
            "model": use_model,
            "messages": self._build_messages(messages, system),
            "max_completion_tokens": max(16, int(max_completion_tokens)),
            "temperature": temperature,
            "stream": True,
        }
        if extra:
            payload.update(extra)
        endpoint = self.endpoints[0]
        url = f"{endpoint}/chat/completions"
        try:
            r = requests.post(url, json=payload, headers=self._headers(),
                              timeout=self.timeout, stream=True)
        except Exception as e:
            raise OpenAICompatError(f"transport error to {_host(endpoint)}: {e}") from e
        if r.status_code != 200:
            raise OpenAICompatError(
                f"HTTP {r.status_code} from {_host(endpoint)}: {(r.text or '')[:240]}"
            )
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = obj.get("choices") or []
            if not choices:
                continue
            piece = (choices[0].get("delta") or {}).get("content")
            if piece:
                yield piece

    def _list_models(self) -> set:
        """Return the endpoint's advertised model ids (lowercased), cached.

        Best-effort: any failure yields an empty set and is cached so we don't
        re-probe a server that doesn't expose ``/models``.
        """
        endpoint = self.endpoints[0]
        if endpoint in self._models_cache:
            return self._models_cache[endpoint]
        import requests  # noqa: PLC0415

        ids: set = set()
        try:
            r = requests.get(f"{endpoint}/models", headers=self._headers(),
                             timeout=self.timeout)
            if r.status_code == 200:
                for m in (r.json().get("data") or []):
                    mid = m.get("id")
                    if mid:
                        ids.add(str(mid).lower())
        except Exception:
            log.debug("openai-compat /models probe failed for %s", _host(endpoint))
        self._models_cache[endpoint] = ids
        return ids

    def supports_tools(self, model=None) -> bool:
        """Best-effort: does this endpoint/model accept the ``tools`` param?

        A known tool-capable model name short-circuits to True. Otherwise we
        probe ``/models`` once: a server that advertises a model menu is a
        modern OpenAI-compatible server and near-universally supports tools.
        A failed/empty probe returns False so the caller falls back to a
        plain-text answer rather than sending an unsupported ``tools`` field.
        Never raises.
        """
        use_model = (model or self.default_model or "").lower()
        if use_model and any(h in use_model for h in _TOOL_CAPABLE_HINTS):
            return True
        return bool(self._list_models())

    def embeddings(self, inputs, *, model=None) -> list:
        """POST ``/embeddings`` and return one float vector per input string.

        The transport is implemented now so the seam is complete and testable;
        the in-product consumer (semantic retrieval) lands in a later
        capability. Raises :class:`OpenAICompatError` on failure.
        """
        import requests  # noqa: PLC0415

        use_model = model or self.default_model
        if not use_model:
            raise OpenAICompatError("No embedding model specified.")
        payload = {"model": use_model, "input": list(inputs)}
        endpoint = self.endpoints[0]
        url = f"{endpoint}/embeddings"
        try:
            r = requests.post(url, json=payload, headers=self._headers(),
                              timeout=self.timeout)
        except Exception as e:
            raise OpenAICompatError(f"transport error to {_host(endpoint)}: {e}") from e
        if r.status_code != 200:
            raise OpenAICompatError(
                f"HTTP {r.status_code} from {_host(endpoint)}: {(r.text or '')[:240]}"
            )
        return [row.get("embedding") for row in (r.json().get("data") or [])]


# ---------------------------------------------------------------------------
# Env-driven construction
# ---------------------------------------------------------------------------

def endpoints_from_env() -> list[str]:
    """Parse ``MEDIAHUB_LLM_ENDPOINTS`` (env, then secrets_store) into a list.

    Empty list => the OpenAI-compatible provider is inert/unconfigured.
    """
    raw = os.environ.get("MEDIAHUB_LLM_ENDPOINTS", "")
    if not raw.strip():
        try:
            from mediahub.web.secrets_store import get_secret
            raw = get_secret("mediahub_llm_endpoints") or ""
        except Exception:
            raw = ""
    return [e.strip().rstrip("/") for e in raw.split(",") if e.strip()]


def resolve_openai_key() -> Optional[str]:
    """Return the bearer token (env first, then secrets_store), or ``None``.

    ``None`` is a valid, supported state — keyless local servers need no key.
    """
    env = os.environ.get("MEDIAHUB_LLM_API_KEY", "")
    if env and env.strip():
        return env.strip()
    try:
        from mediahub.web.secrets_store import get_secret
        v = get_secret("mediahub_llm_api_key")
        return v.strip() if v and v.strip() else None
    except Exception:
        return None


def _timeout_from_env() -> float:
    raw = os.environ.get("MEDIAHUB_LLM_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT
    try:
        return max(1.0, float(raw))
    except ValueError:
        return DEFAULT_TIMEOUT


def client_from_env(*, default_model=None) -> Optional[OpenAICompatClient]:
    """Build a client from env, or ``None`` when no endpoint is configured."""
    endpoints = endpoints_from_env()
    if not endpoints:
        return None
    return OpenAICompatClient(
        endpoints,
        resolve_openai_key(),
        timeout=_timeout_from_env(),
        default_model=default_model,
    )


__all__ = [
    "OpenAICompatClient", "ChatResult", "OpenAICompatError",
    "endpoints_from_env", "resolve_openai_key", "client_from_env",
]
