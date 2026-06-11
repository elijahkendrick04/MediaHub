"""brand/palette_evidence.py — pixel-grounded palette evidence (P1.5).

The brand-DNA-from-URL flow needs palette **evidence** that is grounded in
the club's real assets, not just regex hits in HTML. This module supplies
the deterministic half of that flow, all local and free of paid APIs:

* **SSRF-safe image fetch** — downloads the detected logo / og:image with
  the same public-host validation the research fetcher uses
  (``web_research.safe_fetch.is_url_safe``), re-validated on every redirect
  hop, size-capped, image-content only.
* **Material quantize + score** — the downloaded pixels run through
  `materialyoucolor` (Apache-2.0) ``QuantizeCelebi`` → ``Score.score`` —
  the same colour science the Adaptive Theming Engine's seed extraction
  uses (``theming/seed_extract.py``) — yielding ranked, deterministic
  brand-colour candidates with population shares.

Division of labour (the standing doctrine, see ``brand/bootstrap_extract``):
extracting candidates is mechanical colour science and lives here; deciding
*which* candidate is primary vs accent is a judgement call that stays with
``media_ai.llm`` — this module never assigns semantic roles.
"""

from __future__ import annotations

import io
import logging
from typing import Callable, Optional

log = logging.getLogger(__name__)

_IMAGE_TIMEOUT = 10
_IMAGE_MAX_BYTES = 4_000_000  # 4 MB cap per image
_IMAGE_MAX_HOPS = 4
_THUMB_SIZE = 128  # quantize at ≤128×128 — plenty for palette work
_QUANTIZE_COLOURS = 128
_USER_AGENT = "MediaHubBrandDNA/1.0 (+https://mediahub.example/about)"

ImageFetcher = Callable[[str], Optional[bytes]]


def _argb_to_hex(argb: int) -> str:
    return f"#{(argb >> 16) & 0xFF:02x}{(argb >> 8) & 0xFF:02x}{argb & 0xFF:02x}"


# ---------------------------------------------------------------------------
# SSRF-safe image fetch
# ---------------------------------------------------------------------------


def fetch_image_bytes(url: str) -> Optional[bytes]:
    """Download one image with public-host validation on every hop.

    Returns the raw bytes, or None when the URL is unsafe (private /
    loopback / non-http), unreachable, non-image, or oversized. Never
    raises — missing image evidence just means thinner candidates.
    """
    try:
        import requests

        from mediahub.web_research.safe_fetch import is_url_safe
    except Exception:  # pragma: no cover - both are hard deps
        return None

    current = (url or "").strip()
    for _ in range(_IMAGE_MAX_HOPS):
        if not is_url_safe(current):
            log.debug("image fetch blocked (unsafe host): %s", current)
            return None
        try:
            r = requests.get(
                current,
                headers={"User-Agent": _USER_AGENT, "Accept": "image/*,*/*;q=0.5"},
                timeout=_IMAGE_TIMEOUT,
                allow_redirects=False,
                stream=True,
            )
        except Exception as e:
            log.debug("image fetch failed for %s: %s", current, e)
            return None
        if r.status_code in (301, 302, 303, 307, 308):
            nxt = r.headers.get("Location", "")
            if not nxt:
                return None
            from urllib.parse import urljoin

            current = urljoin(current, nxt)
            continue
        if r.status_code != 200:
            return None
        ctype = (r.headers.get("Content-Type") or "").lower()
        if ctype and not (ctype.startswith("image/") or "svg" in ctype):
            log.debug("image fetch skipped non-image content-type %r for %s", ctype, current)
            return None
        data = r.content or b""
        if not data or len(data) > _IMAGE_MAX_BYTES:
            return None
        return data
    return None


# ---------------------------------------------------------------------------
# Material quantize + score — deterministic candidates from real pixels
# ---------------------------------------------------------------------------


def image_colour_candidates(payload: bytes, *, top: int = 6) -> list[dict]:
    """Ranked brand-colour candidates from one image's pixels.

    Returns ``[{"hex", "rank", "population_share"}, ...]`` (rank 1 = the
    Material Score pick, the same algorithm Android uses for wallpaper
    seeds). Deterministic for fixed bytes. Empty list when the image can't
    be decoded — never raises, never guesses.
    """
    if not payload:
        return []

    if payload.lstrip()[:5].lower() in (b"<svg ", b"<?xml"):
        try:
            import cairosvg  # type: ignore

            payload = cairosvg.svg2png(
                bytestring=payload, output_width=_THUMB_SIZE, output_height=_THUMB_SIZE
            )
        except Exception as e:
            log.debug("svg rasterisation unavailable/failed: %s", e)
            return []

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(payload)).convert("RGBA")
        img.thumbnail((_THUMB_SIZE, _THUMB_SIZE))
    except Exception as e:
        log.debug("image decode failed: %s", e)
        return []

    pixels: list[list[int]] = []
    total = 0
    for x in range(img.width):
        for y in range(img.height):
            r, g, b, a = img.getpixel((x, y))
            total += 1
            if a < 16:
                continue  # transparent → not brand material
            pixels.append([r, g, b])
    if not pixels:
        return []

    try:
        from materialyoucolor.quantize import QuantizeCelebi
        from materialyoucolor.score.score import Score, ScoreOptions

        clusters = QuantizeCelebi(pixels, _QUANTIZE_COLOURS)  # {argb: population}
        if not clusters:
            return []
        try:
            ranked = Score.score(clusters, ScoreOptions(desired=max(1, top), filter=True))
        except Exception:
            ranked = [max(clusters, key=clusters.get)]
    except Exception as e:
        log.debug("materialyoucolor quantize/score failed: %s", e)
        return []

    population = sum(clusters.values()) or 1
    out: list[dict] = []
    for rank, argb in enumerate(ranked[:top], start=1):
        out.append(
            {
                "hex": _argb_to_hex(argb),
                "rank": rank,
                "population_share": round(clusters.get(argb, 0) / population, 4),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Combined evidence for one site
# ---------------------------------------------------------------------------


def gather_image_evidence(
    *,
    logo_url: str = "",
    og_image_url: str = "",
    image_fetcher: Optional[ImageFetcher] = None,
    top: int = 6,
) -> dict:
    """Quantized candidates for the detected logo and og:image.

    Returns ``{"logo": [...], "og_image": [...]}`` (either may be empty).
    The og:image is skipped when identical to the logo URL. ``image_fetcher``
    is injectable for tests.
    """
    fetch = image_fetcher or fetch_image_bytes
    out: dict[str, list[dict]] = {"logo": [], "og_image": []}
    seen: set[str] = set()
    for key, url in (("logo", logo_url), ("og_image", og_image_url)):
        u = (url or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        try:
            payload = fetch(u)
        except Exception as e:
            log.debug("image fetcher raised for %s: %s", u, e)
            payload = None
        if payload:
            out[key] = image_colour_candidates(payload, top=top)
    return out


__all__ = [
    "fetch_image_bytes",
    "gather_image_evidence",
    "image_colour_candidates",
]
