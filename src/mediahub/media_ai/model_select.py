"""mediahub/media_ai/model_select.py — per-content-type model routing.

Pure, HTTP-free policy: given a content type, decide whether to spend the
cheap model or the premium one, and which model name to use. Hero surfaces —
the copy a human actually reads on a finished post — earn the premium model;
internal/bulk steps take the cheap one. Operators tune the two model names,
plus per-type overrides, via env (see :func:`models_from_env`).

Consumed by :mod:`mediahub.media_ai.llm_providers`. Kept separate from any
network code so the routing logic is trivially unit-testable and so the
deterministic "which model for which surface" decision stays in one place.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

# Content types whose output is read directly by an end audience and so
# justify the premium model. Everything else defaults to the cheap model.
HERO_CONTENT_TYPES = frozenset({
    "caption", "caption_live", "spotlight", "athlete_spotlight",
    "meet_recap", "recap", "story", "creative_direction", "brand_voice",
})


@dataclass(frozen=True)
class ModelChoice:
    """A resolved model decision: the model name and whether it's the premium
    tier (used to decide whether a premium retry is still available)."""
    model: str
    premium: bool


def _env_or_secret(env_name: str, secret_name: str) -> Optional[str]:
    v = os.environ.get(env_name, "")
    if v and v.strip():
        return v.strip()
    try:
        from mediahub.web.secrets_store import get_secret
        s = get_secret(secret_name)
        return s.strip() if s and s.strip() else None
    except Exception:
        return None


def models_from_env() -> tuple[Optional[str], Optional[str], dict]:
    """Return ``(cheap, premium, overrides)`` from env / secrets_store.

    ``MEDIAHUB_LLM_MODEL_CHEAP`` / ``_PREMIUM``  — model names.
    ``MEDIAHUB_LLM_MODEL_OVERRIDES``             — ``"type=model,type2=model2"``.

    Any may be unset; callers handle ``None`` / ``{}``.
    """
    cheap = _env_or_secret("MEDIAHUB_LLM_MODEL_CHEAP", "mediahub_llm_model_cheap")
    premium = _env_or_secret("MEDIAHUB_LLM_MODEL_PREMIUM", "mediahub_llm_model_premium")
    overrides_raw = _env_or_secret(
        "MEDIAHUB_LLM_MODEL_OVERRIDES", "mediahub_llm_model_overrides"
    ) or ""
    overrides: dict = {}
    for pair in overrides_raw.split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        k, _, v = pair.partition("=")
        k, v = k.strip().lower(), v.strip()
        if k and v:
            overrides[k] = v
    return cheap, premium, overrides


def select_model(content_type, *, cheap=None, premium=None,
                 overrides=None) -> ModelChoice:
    """Pick the model for ``content_type``.

    Precedence: explicit per-type override > hero-type => premium > cheap.
    A half-configured deployment still works: when premium is requested but
    unset we fall back to cheap, and vice-versa. The returned ``model`` is
    ``""`` only when neither cheap nor premium is configured — the caller
    treats that as "can't route".
    """
    ct = (content_type or "").strip().lower()
    ov = overrides or {}
    if ct in ov:
        return ModelChoice(ov[ct], premium=ct in HERO_CONTENT_TYPES)
    if ct in HERO_CONTENT_TYPES:
        chosen = premium or cheap
        if chosen:
            return ModelChoice(chosen, premium=bool(premium))
    chosen = cheap or premium
    return ModelChoice(chosen or "", premium=bool(chosen) and not cheap)


def premium_fallback(choice, *, cheap=None, premium=None) -> Optional[ModelChoice]:
    """Return a premium :class:`ModelChoice` to retry with after a cheap-model
    failure, or ``None`` when there's no *distinct* premium model to escalate
    to (so the caller doesn't pay a pointless identical second call)."""
    if choice.premium:
        return None
    if premium and premium != choice.model:
        return ModelChoice(premium, premium=True)
    return None


__all__ = [
    "HERO_CONTENT_TYPES", "ModelChoice",
    "models_from_env", "select_model", "premium_fallback",
]
