"""brand/dna_capture.py — Capture a structured brand profile from a website.

Given a URL, fetch the page, extract visual identity and voice signals
deterministically (title, headings, og:image, theme-color, inline-style
colours, likely logo image), then ask the LLM for the structured voice
fields (50-word voice summary, 8-12 keywords, 3-5 phrases to use,
3-5 phrases to avoid, palette in hex, typography hint).

Public surface:
    capture_brand_dna(website_url: str, *, force: bool = False) -> dict

The returned dict has the same keys as the ClubProfile brand_* fields:
    brand_voice_summary, brand_keywords, brand_palette_extracted,
    brand_logo_url, brand_typography_hint, brand_phrases_to_avoid,
    brand_phrases_to_use, brand_source_url, brand_captured_at,
    brand_capture_status

Graceful failure: every failure mode (unreachable URL, malformed HTML,
LLM unavailable) returns a dict with brand_capture_status set to a
clear error string and the other fields populated with whatever could
be extracted. Never raises.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urljoin

log = logging.getLogger(__name__)

_USER_AGENT = "MediaHubBrandDNA/1.0 (+https://mediahub.example/about)"
_FETCH_TIMEOUT = 15
_MAX_HTML_BYTES = 2_000_000  # 2 MB cap to avoid runaway pages


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _cache_dir() -> Path:
    """Return the brand-DNA cache directory. DATA_DIR-aware."""
    base = os.environ.get("DATA_DIR")
    if base:
        d = Path(base) / "brand_dna_cache"
    else:
        # Fallback to source-relative when DATA_DIR not set
        d = Path(__file__).resolve().parents[1] / "data" / "brand_dna_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(url: str) -> str:
    """Stable cache key based on the domain (one cache entry per domain)."""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        host = ""
    if not host:
        host = re.sub(r"[^a-z0-9.-]+", "-", url.lower())[:80] or "unknown"
    return re.sub(r"[^a-z0-9.-]+", "-", host)


def _cache_path(url: str) -> Path:
    return _cache_dir() / f"{_cache_key(url)}.json"


def _load_cache(url: str) -> Optional[dict]:
    p = _cache_path(url)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_cache(url: str, payload: dict) -> None:
    try:
        p = _cache_path(url)
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as e:
        log.debug("brand-dna cache write failed: %s", e)


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------

def _fetch(url: str) -> Optional[str]:
    """Fetch a URL with a sane UA, size cap, and timeout. Returns text or None."""
    try:
        import requests  # already a project dep
    except Exception:
        log.debug("requests not installed")
        return None
    try:
        r = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
            timeout=_FETCH_TIMEOUT,
            allow_redirects=True,
        )
    except Exception as e:
        log.debug("brand-dna fetch failed for %s: %s", url, e)
        return None
    if r.status_code != 200:
        log.debug("brand-dna non-200 (%s) for %s", r.status_code, url)
        return None
    text = r.text or ""
    if len(text) > _MAX_HTML_BYTES:
        text = text[:_MAX_HTML_BYTES]
    return text


# ---------------------------------------------------------------------------
# Deterministic extraction
# ---------------------------------------------------------------------------

_COLOUR_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")


def _normalise_hex(c: str) -> str:
    c = c.lower()
    if len(c) == 4:  # #abc -> #aabbcc
        c = "#" + "".join(ch * 2 for ch in c[1:])
    return c


def _extract_colours_from_html(html: str) -> list[str]:
    """Find all #hex colours in the HTML and return frequency-ranked, normalised."""
    matches = _COLOUR_RE.findall(html or "")
    if not matches:
        return []
    counts: dict[str, int] = {}
    for m in matches:
        norm = _normalise_hex(m)
        # Skip pure white/black noise so we surface brand colours first
        if norm in ("#ffffff", "#000000"):
            counts[norm] = counts.get(norm, 0) + 1
            continue
        counts[norm] = counts.get(norm, 0) + 1
    # Sort by frequency, prefer non-greyscale
    def _key(item):
        hexv, n = item
        r, g, b = int(hexv[1:3], 16), int(hexv[3:5], 16), int(hexv[5:7], 16)
        is_greyscale = abs(r - g) < 8 and abs(g - b) < 8
        return (is_greyscale, -n)
    return [c for c, _ in sorted(counts.items(), key=_key)]


def _extract_signals(html: str, url: str) -> dict:
    """Pull deterministic signals from the HTML — title, headings, image,
    theme-color, colour palette. Uses BeautifulSoup if present, else regex.
    """
    signals: dict = {
        "title": "",
        "meta_description": "",
        "headings": [],
        "og_image": "",
        "theme_color": "",
        "colours": [],
        "logo_url": "",
        "language_hints": [],
    }
    if not html:
        return signals

    # Colours — always do the regex sweep
    signals["colours"] = _extract_colours_from_html(html)

    try:
        from bs4 import BeautifulSoup  # already a project dep
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        soup = None

    if soup is not None:
        if soup.title and soup.title.string:
            signals["title"] = soup.title.string.strip()[:300]

        md = soup.find("meta", attrs={"name": "description"}) or \
             soup.find("meta", attrs={"property": "og:description"})
        if md and md.get("content"):
            signals["meta_description"] = md["content"].strip()[:600]

        og = soup.find("meta", attrs={"property": "og:image"})
        if og and og.get("content"):
            signals["og_image"] = urljoin(url, og["content"].strip())

        tc = soup.find("meta", attrs={"name": "theme-color"})
        if tc and tc.get("content"):
            val = tc["content"].strip()
            if val.startswith("#"):
                signals["theme_color"] = _normalise_hex(val)

        # Headings (up to 6 of h1/h2)
        for tag in soup.find_all(["h1", "h2"])[:6]:
            text = (tag.get_text() or "").strip()
            if text:
                signals["headings"].append(text[:200])

        # Logo: largest <img> in <header>/<nav> or one whose src/alt
        # contains "logo".
        logo_candidates: list[tuple[int, str]] = []
        for img in soup.find_all("img"):
            src = (img.get("src") or "").strip()
            alt = (img.get("alt") or "").strip().lower()
            if not src:
                continue
            score = 0
            if "logo" in src.lower() or "logo" in alt:
                score += 10
            parent_names = []
            p = img.parent
            depth = 0
            while p is not None and depth < 5:
                parent_names.append(getattr(p, "name", "") or "")
                p = getattr(p, "parent", None)
                depth += 1
            if any(n in ("header", "nav") for n in parent_names):
                score += 5
            if score > 0:
                logo_candidates.append((score, urljoin(url, src)))
        if logo_candidates:
            logo_candidates.sort(key=lambda x: -x[0])
            signals["logo_url"] = logo_candidates[0][1]
        elif signals["og_image"]:
            signals["logo_url"] = signals["og_image"]

        # Quick language signal: html[lang]
        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            signals["language_hints"].append(html_tag["lang"][:8])
    else:
        # Fallback regex extraction when BS4 isn't available
        m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I | re.S)
        if m:
            signals["title"] = m.group(1).strip()[:300]
        m = re.search(r'name=["\']description["\']\s+content=["\']([^"\']+)', html, re.I)
        if m:
            signals["meta_description"] = m.group(1).strip()[:600]

    return signals


# ---------------------------------------------------------------------------
# LLM step
# ---------------------------------------------------------------------------

_LLM_SYSTEM = (
    "You analyse a club, society or sports team's website signals and "
    "return a structured brand profile as JSON. Be factual, terse and "
    "concrete. Do not invent details that aren't supported by the signals."
)


def _build_llm_prompt(signals: dict, url: str) -> str:
    lines = [
        f"Website URL: {url}",
        f"Page title: {signals.get('title','')}",
        f"Meta description: {signals.get('meta_description','')}",
    ]
    headings = signals.get("headings") or []
    if headings:
        lines.append("Headings: " + " | ".join(headings[:6]))
    colours = signals.get("colours") or []
    if colours:
        lines.append("Most-used colours (frequency-ranked): " + ", ".join(colours[:10]))
    theme = signals.get("theme_color")
    if theme:
        lines.append(f"theme-color meta: {theme}")
    if signals.get("logo_url"):
        lines.append(f"Detected logo URL: {signals['logo_url']}")
    lines.append("")
    lines.append(
        "Return a single JSON object with EXACTLY these keys:\n"
        "  voice_summary: string, 30-50 words describing this organisation's voice\n"
        "  keywords: array of 8-12 short keywords this org would use about itself\n"
        "  phrases_to_use: array of 3-5 short phrases that sound like this org\n"
        "  phrases_to_avoid: array of 3-5 short phrases this org would NOT use\n"
        '  palette: object {"primary":"#rrggbb","secondary":"#rrggbb","accent":"#rrggbb"}\n'
        "  typography_hint: one of \"serif\", \"sans\", \"display\", \"mono\"\n"
        "No prose, no fences, no commentary — only the JSON object."
    )
    return "\n".join(lines)


def _is_valid_hex(c: str) -> bool:
    return isinstance(c, str) and bool(re.match(r"^#[0-9a-fA-F]{6}$", c))




def _call_llm(signals: dict, url: str) -> Optional[dict]:
    """Ask the LLM for the structured profile. Returns dict or None on failure."""
    try:
        from mediahub.media_ai.llm import generate_json, is_available
    except Exception as e:
        log.debug("llm import failed: %s", e)
        return None
    if not is_available():
        return None
    prompt = _build_llm_prompt(signals, url)
    try:
        data = generate_json(prompt, system=_LLM_SYSTEM, max_tokens=900,
                             fallback={})
    except Exception as e:
        log.debug("llm generate_json raised: %s", e)
        return None
    if not isinstance(data, dict) or not data:
        return None
    return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty_result(url: str, status: str) -> dict:
    return {
        "brand_voice_summary": "",
        "brand_keywords": [],
        "brand_palette_extracted": {},
        "brand_logo_url": "",
        "brand_typography_hint": "",
        "brand_phrases_to_avoid": [],
        "brand_phrases_to_use": [],
        "brand_source_url": url,
        "brand_captured_at": _now_iso(),
        "brand_capture_status": status,
    }


def _merge_llm_into_result(base: dict, llm: dict, signals: dict) -> dict:
    """Apply the LLM-returned dict to the base result, with type guards.

    Never raises — bad LLM output is replaced with safe defaults.
    """
    out = dict(base)

    summary = llm.get("voice_summary")
    if isinstance(summary, str) and summary.strip():
        out["brand_voice_summary"] = summary.strip()[:600]

    kw = llm.get("keywords")
    if isinstance(kw, list):
        out["brand_keywords"] = [str(k).strip() for k in kw if str(k).strip()][:12]

    ptu = llm.get("phrases_to_use")
    if isinstance(ptu, list):
        out["brand_phrases_to_use"] = [str(p).strip() for p in ptu if str(p).strip()][:5]

    pta = llm.get("phrases_to_avoid")
    if isinstance(pta, list):
        out["brand_phrases_to_avoid"] = [str(p).strip() for p in pta if str(p).strip()][:5]

    palette = llm.get("palette")
    if isinstance(palette, dict):
        clean: dict[str, str] = {}
        for k in ("primary", "secondary", "accent"):
            v = palette.get(k)
            if isinstance(v, str):
                v_norm = _normalise_hex(v) if v.startswith("#") else v
                if _is_valid_hex(v_norm):
                    clean[k] = v_norm
        # Fill any missing palette slot from extracted colours
        colours = signals.get("colours") or []
        if "primary" not in clean and colours:
            clean["primary"] = colours[0]
        if "secondary" not in clean and len(colours) > 1:
            clean["secondary"] = colours[1]
        if "accent" not in clean and len(colours) > 2:
            clean["accent"] = colours[2]
        if clean:
            out["brand_palette_extracted"] = clean

    typo = llm.get("typography_hint")
    if isinstance(typo, str) and typo.strip().lower() in ("serif", "sans", "display", "mono"):
        out["brand_typography_hint"] = typo.strip().lower()

    return out


def capture_brand_dna(website_url: str, *, force: bool = False) -> dict:
    """Capture a structured brand profile from a website URL.

    Args:
        website_url: the URL to analyse. http:// prefix added if missing.
        force: ignore the on-disk cache and re-fetch.

    Returns:
        A dict with the ClubProfile brand_* keys. Always returns — never
        raises. On hard failure, brand_capture_status describes why.
    """
    if not website_url or not isinstance(website_url, str):
        return _empty_result("", "missing_url")
    url = website_url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url

    # Cache hit?
    if not force:
        cached = _load_cache(url)
        if cached and isinstance(cached, dict) and cached.get("brand_capture_status") == "ok":
            return cached

    html = _fetch(url)
    if not html:
        return _empty_result(url, "fetch_failed")

    signals = _extract_signals(html, url)

    # Build the deterministic base result so we always have something
    base = _empty_result(url, "extracted")
    if signals.get("logo_url"):
        base["brand_logo_url"] = signals["logo_url"]
    colours = signals.get("colours") or []
    if colours or signals.get("theme_color"):
        base["brand_palette_extracted"] = {}
        if signals.get("theme_color"):
            base["brand_palette_extracted"]["primary"] = signals["theme_color"]
        if colours:
            slots = ["primary", "secondary", "accent"]
            for i, c in enumerate(colours[:3]):
                slot = slots[i]
                base["brand_palette_extracted"].setdefault(slot, c)

    llm_out = _call_llm(signals, url)
    if llm_out:
        out = _merge_llm_into_result(base, llm_out, signals)
        out["brand_capture_status"] = "ok"
    else:
        # No cloud LLM available — preserve the deterministic palette /
        # logo signals we extracted from the HTML, but do NOT invent
        # voice / keywords / phrases. Status "no_provider" tells the UI
        # to surface an honest "configure an AI provider" message.
        out = dict(base)
        out["brand_capture_status"] = "no_provider"

    out["brand_captured_at"] = _now_iso()

    _save_cache(url, out)
    return out


__all__ = ["capture_brand_dna"]
