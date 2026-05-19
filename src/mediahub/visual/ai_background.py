"""AI-generated brand-aware backgrounds via Replicate SDXL.

Adds a Holo/Predis-style "original imagery" layer to MediaHub renders.
Generates a brand-coloured abstract background image per card, cached by
content hash so repeats are free.

Activation
----------
Requires ``REPLICATE_API_TOKEN`` env var or secret. When unset, this module
is a no-op and the renderer uses the built-in procedural water-pattern +
noise overlay — that overlay is a primary first-class visual element, not
a heuristic stand-in for the AI background. Operators who want generated
backgrounds must configure the Replicate token.

Cost
----
SDXL on Replicate is ~$0.012 per image at 1024x1024. With caching, the
amortised cost across a content pack is well under $0.10.

Public API
----------
- ``is_available() -> bool``
- ``background_data_uri_for(brief, *, format_name="feed_portrait") -> Optional[str]``
  Returns a ``data:image/jpeg;base64,...`` URI or None if generation fails.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


_REPLICATE_MODEL = os.environ.get(
    "MEDIAHUB_SDXL_MODEL",
    # SDXL 1.0 — the default Replicate version. Override via env if a newer
    # model proves cheaper / faster.
    "stability-ai/sdxl:7762fd07cf82c948538e41f63f77d685e02b063e37e496e96eefd46c929f9bdc",
)
_REPLICATE_TIMEOUT = int(os.environ.get("MEDIAHUB_SDXL_TIMEOUT", "60"))


def _data_dir() -> Path:
    env = os.environ.get("DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1]


def _cache_dir() -> Path:
    p = _data_dir() / "ai_bg_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_token() -> Optional[str]:
    env = os.environ.get("REPLICATE_API_TOKEN")
    if env:
        return env
    try:
        from mediahub.web.secrets_store import get_secret  # type: ignore
        return get_secret("replicate_api_token") or None
    except Exception:
        return None


def is_available() -> bool:
    """True when an SDXL run can plausibly succeed (token configured)."""
    return bool(_resolve_token())


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------

def _palette_words(palette: dict) -> str:
    """Describe the palette so SDXL outputs colour-matched imagery."""
    primary = palette.get("primary") or "navy"
    secondary = palette.get("secondary") or "black"
    accent = palette.get("accent") or "gold"
    return f"hex {primary}, {secondary} and {accent}"


def _build_prompt(brief, palette: dict, format_name: str) -> str:
    """Brand-aware prompt for the background image.

    We deliberately keep the prompt abstract and non-figurative — we want
    a brand-coloured backdrop the renderer can overlay text on, NOT a
    photo that competes with the typography.
    """
    layers = (brief.text_layers or {}) if brief is not None else {}
    sport_hint = layers.get("event_name") or "swimming"
    palette_str = _palette_words(palette)
    return (
        f"Abstract editorial sports background, {sport_hint} themed, "
        f"dynamic geometric forms, gradient lighting, subtle motion blur, "
        f"colour palette {palette_str}, no people, no text, no logos, "
        f"clean negative space in the centre for typography overlay, "
        f"premium magazine aesthetic, depth, atmospheric"
    )


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _hash_key(prompt: str, format_name: str) -> str:
    h = hashlib.sha256(f"{prompt}|{format_name}".encode("utf-8")).hexdigest()
    return h[:16]


def _cached(key: str) -> Optional[bytes]:
    p = _cache_dir() / f"{key}.jpg"
    if p.exists():
        try:
            return p.read_bytes()
        except Exception:
            return None
    return None


def _cache_put(key: str, data: bytes) -> None:
    try:
        (_cache_dir() / f"{key}.jpg").write_bytes(data)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Replicate call
# ---------------------------------------------------------------------------

def _call_replicate(prompt: str, width: int, height: int) -> Optional[bytes]:
    """POST to Replicate, poll until done, return raw JPEG bytes."""
    token = _resolve_token()
    if not token:
        return None
    try:
        import requests  # type: ignore
    except Exception:
        return None

    # Replicate sizes must be multiples of 8 and divisible by 64 for best
    # results. Clamp to model's safe range (1024 max each side for SDXL).
    def _clamp(n: int) -> int:
        n = min(max(int(n), 512), 1024)
        return (n // 64) * 64

    payload = {
        "version": _REPLICATE_MODEL.split(":", 1)[1] if ":" in _REPLICATE_MODEL else _REPLICATE_MODEL,
        "input": {
            "prompt": prompt,
            "negative_prompt": "text, watermark, signature, faces, people, logos, blurry, low-quality",
            "width": _clamp(width),
            "height": _clamp(height),
            "num_inference_steps": 25,
            "guidance_scale": 7.0,
            "scheduler": "K_EULER",
        },
    }
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(
            "https://api.replicate.com/v1/predictions",
            headers=headers,
            data=json.dumps(payload),
            timeout=10,
        )
    except Exception as e:
        log.debug("ai_background: replicate POST failed: %s", e)
        return None
    if r.status_code not in (200, 201):
        log.debug("ai_background: replicate non-2xx: %s %s", r.status_code, r.text[:200])
        return None

    data = r.json()
    pred_url = (data.get("urls") or {}).get("get")
    if not pred_url:
        return None

    # Poll for completion (max 60s).
    import time as _time
    deadline = _time.time() + _REPLICATE_TIMEOUT
    output_url = None
    while _time.time() < deadline:
        try:
            poll = requests.get(pred_url, headers=headers, timeout=10).json()
        except Exception:
            return None
        status = poll.get("status")
        if status == "succeeded":
            out = poll.get("output")
            if isinstance(out, list) and out:
                output_url = out[0]
            elif isinstance(out, str):
                output_url = out
            break
        if status in ("failed", "canceled"):
            return None
        _time.sleep(1.5)

    if not output_url:
        return None

    try:
        img = requests.get(output_url, timeout=20)
    except Exception:
        return None
    if img.status_code != 200 or not img.content:
        return None
    return img.content


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

_FORMAT_SIZES = {
    "feed_square":   (1024, 1024),
    "feed_portrait": (832, 1024),
    "story":         (576, 1024),
    "reel_cover":    (576, 1024),
}


def background_data_uri_for(brief, *, format_name: str = "feed_portrait") -> Optional[str]:
    """Return an SDXL-generated background as a data URI, or None.

    Cached by (prompt, format) hash so repeated renders are free.
    Returns None when the API token isn't configured, when Replicate fails,
    or when any network/parsing error happens — the renderer's standard
    water-pattern + noise fallback handles the None case gracefully.
    """
    if not is_available():
        return None
    palette = (brief.palette or {}) if brief is not None else {}
    prompt = _build_prompt(brief, palette, format_name)
    key = _hash_key(prompt, format_name)

    cached = _cached(key)
    if cached:
        b64 = base64.b64encode(cached).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"

    w, h = _FORMAT_SIZES.get(format_name, (832, 1024))
    data = _call_replicate(prompt, w, h)
    if not data:
        return None
    _cache_put(key, data)
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


__all__ = ["is_available", "background_data_uri_for"]
