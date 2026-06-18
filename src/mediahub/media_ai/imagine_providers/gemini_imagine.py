"""Gemini / Imagen image provider (P6.3).

The first cloud backend on the ``imagine`` seam, generalising the single-purpose
``MEDIAHUB_GEN_BG`` call (``visual/ai_background.py``) into the full
text-to-image surface. It speaks the same Gemini ``generativelanguage`` Imagen
``:predict`` endpoint and reuses the *same* Gemini key the rest of MediaHub
uses — no separate token.

What this provider does today (honestly):

  * ``generate`` — text → image, with sport-editorial style presets, aspect
    ratios, and an opt-in ``allow_people`` gate (default off, per the
    no-synthetic-people rule).
  * ``similar``  — on-style variations: re-roll the same prompt for ``n``
    samples (Imagen ``:predict`` is text-driven, so a reference image steers the
    prompt rather than conditioning pixels).

The editing family (edit / expand / remove / upscale / style_match) is **not**
claimed here: Imagen's public ``:predict`` surface does not expose mask-based
inpaint / outpaint uniformly, so the facade honest-errors for those until the
local diffusion backend (P5.6) — the intended default — fills them. Over-
claiming a capability and returning a stubbed image would violate MediaHub's
honest-error rule.

``imagen_predict`` is the shared low-level client: it is the one place the Imagen
HTTP shape lives, so :mod:`mediahub.visual.ai_background` calls it too and the
rendered-background bytes stay byte-identical.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Optional

from .base import GeneratedImage, ImageInput, ImagineProvider

log = logging.getLogger(__name__)

_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _default_model() -> str:
    # Prefer an imagine-specific override, then the legacy gen-bg model var, then
    # the production Imagen 4 model. Operators can pin a fast/ultra tier.
    return (
        os.environ.get("MEDIAHUB_IMAGINE_MODEL")
        or os.environ.get("MEDIAHUB_IMAGEN_MODEL")
        or "imagen-4.0-generate-001"
    )


def _default_timeout() -> int:
    raw = os.environ.get("MEDIAHUB_IMAGINE_TIMEOUT") or os.environ.get(
        "MEDIAHUB_IMAGEN_TIMEOUT", "60"
    )
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 60


def resolve_gemini_key() -> Optional[str]:
    """Reuse the same Gemini key the rest of MediaHub uses."""
    try:
        from mediahub.media_ai.llm import _resolve_gemini_key

        return _resolve_gemini_key()
    except Exception:
        for env_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            v = os.environ.get(env_name)
            if v:
                return v
        return None


# Aspect ratios Imagen 4 accepts. Anything else is snapped to the nearest.
_SUPPORTED_ASPECTS = {"1:1", "9:16", "16:9", "3:4", "4:3"}


def _coerce_aspect(aspect: str) -> str:
    a = (aspect or "").strip()
    if a in _SUPPORTED_ASPECTS:
        return a
    # Map common MediaHub format names through to an Imagen aspect.
    alias = {
        "square": "1:1",
        "feed_square": "1:1",
        "portrait": "3:4",
        "feed_portrait": "3:4",
        "story": "9:16",
        "reel_cover": "9:16",
        "landscape": "16:9",
    }
    return alias.get(a, "1:1")


def imagen_predict(
    prompt: str,
    *,
    aspect_ratio: str = "1:1",
    sample_count: int = 1,
    model: Optional[str] = None,
    timeout: Optional[int] = None,
    allow_people: bool = False,
    safety: str = "block_only_high",
) -> list[bytes]:
    """POST to Imagen ``:predict`` and return raw image bytes per prediction.

    The single source of truth for the Imagen HTTP shape. Returns an empty list
    on any failure (no key, non-200, malformed body) — callers decide whether an
    empty result is a soft fall-back (the renderer background) or a hard honest
    error (the imagine facade).
    """
    key = resolve_gemini_key()
    if not key:
        return []
    try:
        import requests  # type: ignore
    except Exception:
        return []

    mdl = model or _default_model()
    url = f"{_GEMINI_API_BASE}/models/{mdl}:predict?key={key}"
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": max(1, int(sample_count)),
            "aspectRatio": _coerce_aspect(aspect_ratio),
            # Default to no people unless the caller explicitly opts in — the
            # product rule is "no synthetic AI-generated people unless
            # explicitly requested".
            "personGeneration": "allow_adult" if allow_people else "dont_allow",
            "safetySetting": safety,
        },
    }
    try:
        r = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=timeout or _default_timeout(),
        )
    except Exception as e:  # pragma: no cover - network error path
        log.debug("imagine.gemini: predict POST failed: %s", e)
        return []
    if r.status_code != 200:
        log.debug("imagine.gemini: non-200 %s %s", r.status_code, (r.text or "")[:300])
        return []
    try:
        body = r.json()
    except Exception as e:  # pragma: no cover - malformed body
        log.debug("imagine.gemini: response not JSON: %s", e)
        return []

    out: list[bytes] = []
    for pred in body.get("predictions") or []:
        if not isinstance(pred, dict):
            continue
        b64 = pred.get("bytesBase64Encoded")
        if not b64:
            continue
        try:
            out.append(base64.b64decode(b64))
        except Exception:  # pragma: no cover - decode error
            continue
    return out


class GeminiImagineProvider(ImagineProvider):
    """Gemini Imagen backend — text-to-image + on-style variations."""

    name = "gemini"

    def is_available(self) -> bool:
        return bool(resolve_gemini_key())

    def capabilities(self) -> set[str]:
        # Honest: only the operations the public Imagen :predict surface does.
        return {"generate", "similar"}

    def generate(
        self,
        prompt: str,
        *,
        style: Optional[str] = None,
        aspect: str = "1:1",
        n: int = 1,
        allow_people: bool = False,
        refs: Optional[list[ImageInput]] = None,
    ) -> list[GeneratedImage]:
        from mediahub.media_ai.imagine import ImagineError, ProviderNotConfigured

        if not self.is_available():
            raise ProviderNotConfigured("Gemini API key not configured.")
        full = _compose_prompt(prompt, style)
        images = imagen_predict(
            full,
            aspect_ratio=aspect,
            sample_count=max(1, min(int(n), 4)),
            allow_people=allow_people,
        )
        if not images:
            raise ImagineError(
                "Imagen returned no image. The Gemini key may lack Imagen "
                "billing, or the prompt was refused by the safety filter."
            )
        return [GeneratedImage(data=b, mime="image/png") for b in images]

    def similar(
        self,
        image: ImageInput,
        *,
        prompt: str = "",
        n: int = 1,
        allow_people: bool = False,
    ) -> list[GeneratedImage]:
        # Imagen :predict is text-driven, so "similar" re-rolls the same brief.
        # A descriptive prompt is required to steer the variations honestly —
        # we do not pretend to condition on the reference pixels.
        from mediahub.media_ai.imagine import ImagineError

        if not (prompt or "").strip():
            raise ImagineError(
                "The Gemini provider needs a text description to make on-style "
                "variations (it cannot condition on the reference image's "
                "pixels). Provide a prompt, or use the local backend (P5.6)."
            )
        return self.generate(
            prompt, aspect="1:1", n=max(1, min(int(n), 4)), allow_people=allow_people
        )


# ---------------------------------------------------------------------------
# Style presets — curated sport-editorial looks (no "3D clay" gimmicks by default)
# ---------------------------------------------------------------------------

STYLE_PRESETS = {
    "editorial": (
        "premium sports-magazine editorial photography, cinematic lighting, "
        "high contrast, shallow depth of field, atmospheric"
    ),
    "abstract": (
        "abstract editorial sports background, dynamic geometric forms, "
        "gradient lighting, subtle motion blur, clean negative space"
    ),
    "poster": (
        "bold modern sports poster art, strong graphic shapes, flat colour "
        "blocking, screen-print texture"
    ),
    "duotone": ("high-contrast duotone treatment, two-colour gradient, editorial poster feel"),
    "line_art": (
        "clean black-and-white line art, printable colouring-page style, bold "
        "outlines, no shading, white background"
    ),
}

DEFAULT_STYLE = "editorial"


def _compose_prompt(prompt: str, style: Optional[str]) -> str:
    base = (prompt or "").strip()
    key = (style or "").strip().lower() or DEFAULT_STYLE
    suffix = STYLE_PRESETS.get(key)
    if not suffix:
        return base
    return f"{base}. Style: {suffix}." if base else suffix


__all__ = [
    "GeminiImagineProvider",
    "imagen_predict",
    "resolve_gemini_key",
    "STYLE_PRESETS",
    "DEFAULT_STYLE",
]
