"""mediahub/media_ai/llm_providers.py — OpenAI-compatible provider adapter.

Bridges the OpenAI-compatible transport (:mod:`mediahub.ai_core.llm_client`)
into the :mod:`mediahub.media_ai.llm` provider contract: a ``call_*`` function
that takes ``(messages, system, max_tokens)``, returns the model's text or
``None``, never raises, and records one usage row per attempt. It mirrors
``media_ai.llm._call_anthropic`` / ``_call_gemini`` so ``generate()`` can treat
``"openai"`` like any other provider in its failover chain.

Model routing (cheap vs premium per content type) is delegated to
:mod:`mediahub.media_ai.model_select`; the network transport lives in
:mod:`mediahub.ai_core.llm_client`. This module is the thin glue between them.

Inert unless ``MEDIAHUB_LLM_ENDPOINTS`` is configured.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from mediahub.ai_core import llm_client
from mediahub.media_ai import model_select

log = logging.getLogger(__name__)


def is_openai_configured() -> bool:
    """True when at least one OpenAI-compatible endpoint is configured."""
    return bool(llm_client.endpoints_from_env())


def call_openai(messages, system, max_tokens, *, content_type=None) -> Optional[str]:
    """Generate text via the configured OpenAI-compatible endpoint(s).

    Returns the text, or ``None`` on any failure (mirrors
    ``_call_anthropic``'s contract — ``generate()`` falls through to the next
    provider on ``None``). Never raises. Records one usage row per attempt and
    escalates to the premium model once on a transient/empty cheap result.
    """
    # Local import avoids an import cycle (media_ai.llm imports this module).
    from mediahub.ai_core.gemini_transport import redact_key as _redact_key
    from mediahub.media_ai.llm import _log_call

    client = llm_client.client_from_env()
    if client is None:
        return None

    cheap, premium, overrides = model_select.models_from_env()
    choice = model_select.select_model(
        content_type, cheap=cheap, premium=premium, overrides=overrides
    )
    if not choice.model:
        # Endpoints are configured but no model name is — we can't route.
        _log_call(
            provider="openai",
            ok=False,
            model=None,
            error_kind="no_model",
            error_message="MEDIAHUB_LLM_MODEL_CHEAP / _PREMIUM unset",
        )
        return None

    key = llm_client.resolve_openai_key()
    attempts = [choice]
    escalated = model_select.premium_fallback(choice, cheap=cheap, premium=premium)
    if escalated is not None:
        attempts.append(escalated)

    for attempt in attempts:
        started = time.monotonic()
        try:
            result = client.chat(
                messages,
                model=attempt.model,
                system=system,
                max_completion_tokens=max_tokens,
            )
            text = (result.text or "").strip() or None
            _log_call(
                provider="openai",
                ok=bool(text),
                model=attempt.model,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                duration_ms=(time.monotonic() - started) * 1000.0,
                error_kind=None if text else "empty_response",
                error_message=None if text else "endpoint returned no text",
            )
            if text:
                return text
        except llm_client.OpenAICompatError as e:
            msg = _redact_key(str(e), key)
            log.warning("openai-compat call failed (%s): %s", attempt.model, msg)
            _log_call(
                provider="openai",
                ok=False,
                model=attempt.model,
                duration_ms=(time.monotonic() - started) * 1000.0,
                error_kind=type(e).__name__,
                error_message=msg,
            )
            continue
    return None


__all__ = ["is_openai_configured", "call_openai"]
