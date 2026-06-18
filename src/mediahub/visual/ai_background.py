"""AI-generated brand-aware backgrounds via Google Imagen 4.

Adds a Holo/Predis-style "original imagery" layer to MediaHub renders.
Generates a brand-coloured abstract background image per card, cached
by content hash so repeats are free.

Activation
----------
Requires a Gemini API key (``GEMINI_API_KEY`` or ``GOOGLE_API_KEY``).
This is the SAME key MediaHub already uses for caption/brand AI — no
separate Replicate token needed. When unset, the module is a no-op and
the renderer uses the built-in procedural water-pattern + noise overlay
(itself a primary first-class visual element, not a heuristic stand-in
for the AI background).

Note: Imagen image generation is a billed feature of the Gemini API.
A bare AI Studio free-tier key may return 403 on Imagen requests even
when text generation works. Operators who want generated backgrounds
need a key on a Google Cloud project with billing enabled.

Cost
----
Imagen 4 generation is roughly $0.03–0.04 per 1024×1024 image at
list price. With per-prompt caching, the amortised cost across a
content pack is well below $0.10. Fast and Ultra tiers are
overridable via ``MEDIAHUB_IMAGEN_MODEL``.

Public API
----------
- ``is_available() -> bool``
- ``background_data_uri_for(brief, *, format_name="feed_portrait") -> Optional[str]``
  Returns a ``data:image/png;base64,...`` URI or None if generation fails.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# Imagen model published through the Gemini ``generativelanguage`` API.
# Default to the production Imagen 4 model. Operators can override to a
# fast/ultra tier or pin a specific snapshot via env.
_IMAGEN_MODEL = os.environ.get(
    "MEDIAHUB_IMAGEN_MODEL",
    "imagen-4.0-generate-001",
)
_IMAGEN_TIMEOUT = int(os.environ.get("MEDIAHUB_IMAGEN_TIMEOUT", "60"))
_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _data_dir() -> Path:
    env = os.environ.get("DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1]


def _cache_dir() -> Path:
    p = _data_dir() / "ai_bg_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_key() -> Optional[str]:
    """Reuse the same Gemini key the rest of MediaHub uses."""
    try:
        from mediahub.media_ai.llm import _resolve_gemini_key

        return _resolve_gemini_key()
    except Exception:
        # Fall back to env-only resolution if the import isn't available
        # (early-bootstrap paths, isolated tests).
        for env_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            v = os.environ.get(env_name)
            if v:
                return v
        return None


def is_available() -> bool:
    """True when an Imagen run can plausibly succeed (key configured)."""
    return bool(_resolve_key())


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------


def _palette_words(palette: dict) -> str:
    """Describe the palette so Imagen outputs colour-matched imagery."""
    primary = palette.get("primary") or "navy"
    secondary = palette.get("secondary") or "black"
    accent = palette.get("accent") or "gold"
    return f"hex {primary}, {secondary}, and {accent}"


def _build_prompt(brief, palette: dict, format_name: str) -> str:
    """Brand-aware prompt for the background image.

    We deliberately keep the prompt abstract and non-figurative — we want
    a brand-coloured backdrop the renderer can overlay text on, NOT a
    photo that competes with the typography. Imagen 4 follows
    instructional language closely, so we lean into explicit
    constraints (no people, no text, central negative space).
    """
    layers = (brief.text_layers or {}) if brief is not None else {}
    sport_hint = layers.get("event_name") or "swimming"
    palette_str = _palette_words(palette)
    return (
        f"Abstract editorial sports background, {sport_hint} themed. "
        f"Dynamic geometric forms with gradient lighting and subtle "
        f"motion blur. Colour palette {palette_str}. "
        f"No people, no faces, no text, no logos, no watermarks. "
        f"Clean negative space in the centre for typography overlay. "
        f"Premium magazine aesthetic with depth and atmosphere. "
        f"Cinematic, high contrast, editorial photography style."
    )


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _hash_key(prompt: str, format_name: str) -> str:
    # Include the model so switching tiers (fast / ultra) invalidates
    # cached results from the previous tier.
    h = hashlib.sha256(f"{_IMAGEN_MODEL}|{prompt}|{format_name}".encode("utf-8")).hexdigest()
    return h[:16]


def _cached(key: str) -> Optional[bytes]:
    p = _cache_dir() / f"{key}.png"
    if p.exists():
        try:
            return p.read_bytes()
        except Exception:
            return None
    # Backwards compatibility: jpeg cached from the previous SDXL provider
    # is still a valid image source; serve it if present.
    p_jpg = _cache_dir() / f"{key}.jpg"
    if p_jpg.exists():
        try:
            return p_jpg.read_bytes()
        except Exception:
            return None
    return None


def _cache_put(key: str, data: bytes) -> None:
    try:
        (_cache_dir() / f"{key}.png").write_bytes(data)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Imagen call
# ---------------------------------------------------------------------------

# Map MediaHub format names to Imagen's supported aspectRatio enum.
# Imagen 4 supports: "1:1", "9:16", "16:9", "3:4", "4:3".
_FORMAT_ASPECT = {
    "feed_square": "1:1",
    "feed_portrait": "3:4",
    "story": "9:16",
    "reel_cover": "9:16",
}


def _call_imagen(prompt: str, aspect_ratio: str) -> Optional[bytes]:
    """Generate one background image via the shared Imagen ``:predict`` client.

    Delegates to :func:`mediahub.media_ai.imagine_providers.gemini_imagine.imagen_predict`
    — the one place the Imagen HTTP shape lives, since P6.3 generalised this
    single-purpose call behind the ``imagine`` seam. The request is byte-for-byte
    the historic one (same model, aspect, ``sampleCount=1``,
    ``personGeneration=dont_allow``, ``safetySetting=block_only_high``), so a
    given prompt still yields the same cached bytes under the same cache key.

    Returns raw image bytes on success, ``None`` on any failure (no key, Imagen
    billing disabled → 403, network/parse error) — the renderer's procedural
    water+noise backdrop handles the ``None`` case.
    """
    try:
        from mediahub.media_ai.imagine_providers.gemini_imagine import imagen_predict
    except Exception:  # pragma: no cover - import guard
        return None
    images = imagen_predict(
        prompt,
        aspect_ratio=aspect_ratio,
        sample_count=1,
        model=_IMAGEN_MODEL,
        timeout=_IMAGEN_TIMEOUT,
        allow_people=False,
        safety="block_only_high",
    )
    return images[0] if images else None


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def background_data_uri_for(brief, *, format_name: str = "feed_portrait") -> Optional[str]:
    """Return an Imagen-generated background as a data URI, or None.

    Cached by (model, prompt, format) hash so repeated renders are
    free. Returns None when the Gemini key isn't configured, when the
    Imagen endpoint errors out, or when any network/parsing error
    happens — the renderer's standard water-pattern + noise overlay
    handles the None case gracefully.
    """
    if not is_available():
        return None
    palette = (brief.palette or {}) if brief is not None else {}
    prompt = _build_prompt(brief, palette, format_name)
    key = _hash_key(prompt, format_name)

    cached = _cached(key)
    if cached:
        b64 = base64.b64encode(cached).decode("ascii")
        # Cache may hold legacy .jpg from the previous SDXL provider;
        # we still return image/png because most browsers handle the
        # mismatch fine and downstream HTML doesn't introspect mime.
        return f"data:image/png;base64,{b64}"

    aspect = _FORMAT_ASPECT.get(format_name, "3:4")
    data = _call_imagen(prompt, aspect)
    if not data:
        return None
    _cache_put(key, data)
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{b64}"


__all__ = ["is_available", "background_data_uri_for"]
