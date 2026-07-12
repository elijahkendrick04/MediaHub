"""mediahub/memory/embedder.py — cloud text embeddings for semantic memory.

Capability 2 is **cloud-only** by design: there is no local/on-CPU embedding
model. This wraps Capability 1's OpenAI-compatible transport
(:mod:`mediahub.ai_core.llm_client`) pointed at an embeddings endpoint, so any
``/v1/embeddings`` provider works — OpenAI, OpenRouter, Together, DeepInfra, or
**Gemini via its OpenAI-compatibility layer**
(``https://generativelanguage.googleapis.com/v1beta/openai``), reusing the
operator's existing ``GEMINI_API_KEY``.

Configuration is env-only and the feature is **inert when unconfigured**
(``is_configured()`` is False → callers no-op honestly, never fabricate):

    MEDIAHUB_EMBED_ENDPOINT   OpenAI-compatible base URL (e.g. ending /v1, or
                              the Gemini /v1beta/openai base). Falls back to the
                              first ``MEDIAHUB_LLM_ENDPOINTS`` entry.
    MEDIAHUB_EMBED_MODEL      embedding model id (e.g. text-embedding-004,
                              text-embedding-3-small).
    MEDIAHUB_EMBED_API_KEY    bearer token. Falls back to ``MEDIAHUB_LLM_API_KEY``,
                              then ``GEMINI_API_KEY`` when the endpoint is Google's.
    MEDIAHUB_EMBED_TIMEOUT    per-request timeout in seconds (default 45).

Honest-error rule (CLAUDE.md): when no embedding backend is reachable, callers
surface that the feature is unavailable — there is NO keyword/heuristic
fallback.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

_GOOGLE_OPENAI_HOST = "generativelanguage.googleapis.com"
DEFAULT_TIMEOUT = 45.0


class EmbedderUnavailable(RuntimeError):
    """Raised when embeddings are requested but no backend is reachable."""


@dataclass(frozen=True)
class EmbedResult:
    """A batch of embeddings plus the model identity needed to store them.

    ``model_id`` and ``dim`` are persisted with every vector so vectors from
    different models/dimensions are never compared (cosine across mismatched
    models is silent garbage).
    """

    vectors: list[list[float]]
    model_id: str
    dim: int


def embed_endpoint() -> Optional[str]:
    """Resolve the embeddings base URL (env first, then the chat endpoint)."""
    v = os.environ.get("MEDIAHUB_EMBED_ENDPOINT", "").strip()
    if v:
        return v.rstrip("/")
    try:
        from mediahub.ai_core.llm_client import endpoints_from_env

        eps = endpoints_from_env()
        return eps[0] if eps else None
    except Exception:
        return None


def embed_model() -> Optional[str]:
    return os.environ.get("MEDIAHUB_EMBED_MODEL", "").strip() or None


def is_configured() -> bool:
    """True when both an endpoint and a model are configured."""
    return bool(embed_endpoint() and embed_model())


def _resolve_key(endpoint: str) -> Optional[str]:
    v = os.environ.get("MEDIAHUB_EMBED_API_KEY", "").strip()
    if v:
        return v
    # Gemini's OpenAI-compat layer authenticates with the Gemini key.
    if _GOOGLE_OPENAI_HOST in endpoint:
        for n in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            g = os.environ.get(n, "").strip()
            if g:
                return g
    try:
        from mediahub.ai_core.llm_client import resolve_openai_key

        return resolve_openai_key()
    except Exception:
        return None


def _timeout() -> float:
    raw = os.environ.get("MEDIAHUB_EMBED_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT
    try:
        return max(1.0, float(raw))
    except ValueError:
        return DEFAULT_TIMEOUT


def embed(texts: list[str]) -> EmbedResult:
    """Embed a batch of texts via the configured cloud endpoint.

    Raises :class:`EmbedderUnavailable` when unconfigured or the call fails —
    never returns a fabricated vector.
    """
    model = embed_model()
    if not texts:
        return EmbedResult(vectors=[], model_id=model or "", dim=0)
    endpoint = embed_endpoint()
    if not endpoint or not model:
        raise EmbedderUnavailable(
            "Embeddings are not configured (set MEDIAHUB_EMBED_ENDPOINT and "
            "MEDIAHUB_EMBED_MODEL)."
        )
    try:
        from mediahub.ai_core.llm_client import OpenAICompatClient, OpenAICompatError
    except Exception as e:  # pragma: no cover - import guard
        raise EmbedderUnavailable(f"LLM client unavailable: {e}") from e

    client = OpenAICompatClient(
        [endpoint], _resolve_key(endpoint), timeout=_timeout(), default_model=model
    )
    try:
        raw = client.embeddings(list(texts), model=model)
    except OpenAICompatError as e:
        raise EmbedderUnavailable(f"embedding call failed: {e}") from e
    rows = raw or []
    # Never silently drop a null row: that would misalign vectors against texts
    # (vector i no longer belongs to text i). Require one non-empty vector per
    # input and raise otherwise.
    if len(rows) != len(texts):
        raise EmbedderUnavailable(
            f"embedding endpoint returned {len(rows)} vectors for {len(texts)} inputs"
        )
    vectors = []
    for v in rows:
        if not v:
            raise EmbedderUnavailable("embedding endpoint returned an empty/null vector row")
        vectors.append([float(x) for x in v])
    if not vectors or not vectors[0]:
        raise EmbedderUnavailable("embedding endpoint returned no vectors")
    dim = len(vectors[0])
    if any(len(v) != dim for v in vectors):
        raise EmbedderUnavailable("embedding endpoint returned ragged dimensions")
    return EmbedResult(vectors=vectors, model_id=model, dim=dim)


def embed_one(text: str) -> EmbedResult:
    """Embed a single string. Same contract as :func:`embed`."""
    return embed([text])


__all__ = [
    "EmbedderUnavailable",
    "EmbedResult",
    "embed",
    "embed_one",
    "is_configured",
    "embed_endpoint",
    "embed_model",
]
