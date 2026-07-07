"""brand/dna_capture.py — Capture a structured brand profile from a website.

Given a URL, fetch the page (SSRF-safe — public hosts only, re-validated on
every redirect hop), extract visual identity and voice signals
deterministically (title, headings, og:image, theme-color, site-wide
colour-usage frequencies incl. linked CSS, likely logo image, and — P1.5 —
`materialyoucolor`-quantized candidates from the logo/og-image **pixels**),
then ask the LLM for the structured voice fields (50-word voice summary,
8-12 keywords, 3-5 phrases to use, 3-5 phrases to avoid, palette in hex,
typography hint).

The whole flow runs with no paid API: the scrape is local, the colour
science is local (Apache-2.0 material-color-utilities, the same maths the
theming engine uses), and the one judgement step rides ``media_ai.llm`` —
which serves local OpenAI-compatible endpoints (Ollama, llama.cpp, vLLM via
``MEDIAHUB_LLM_ENDPOINTS``) exactly like the hosted providers. The LLM's
palette picks are validated against the gathered evidence universe — a hex
the site never exhibited is dropped, never trusted (the standing
anti-hallucination guard for brand-from-URL extraction).

Public surface:
    capture_brand_dna(website_url: str, *, force: bool = False) -> dict

The returned dict has the same keys as the ClubProfile brand_* fields:
    brand_voice_summary, brand_keywords, brand_palette_extracted,
    brand_logo_url, brand_typography_hint, brand_phrases_to_avoid,
    brand_phrases_to_use, brand_source_url, brand_captured_at,
    brand_capture_status, brand_palette_sources, brand_palette_reasoning

Graceful failure: every failure mode (unreachable or unsafe URL, malformed
HTML, LLM unavailable) returns a dict with brand_capture_status set to a
clear error string and the other fields populated with whatever could be
extracted. With no provider configured the deterministic palette evidence
is preserved but voice fields stay empty (status ``no_provider``) — an
honest gap, never an invented voice. Never raises.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urljoin

log = logging.getLogger(__name__)

_USER_AGENT = "MediaHubBrandDNA/1.0 (+https://mediahub.example/about)"
_FETCH_TIMEOUT = 15
_MAX_HTML_BYTES = 2_000_000  # 2 MB cap to avoid runaway pages

# Bounds for the best-effort linked-stylesheet fetch that enriches the
# colour-usage evidence. Real brand colours live in external CSS, not the
# page HTML; we pull a few stylesheets so the AI sees full-site usage.
_CSS_FETCH_MAX = 3  # at most N stylesheets per page
_CSS_FETCH_BYTES = 512_000  # ~512 KB cap per stylesheet
_CSS_FETCH_TIMEOUT = 6  # seconds, per stylesheet
_COLOUR_USAGE_TOP = 24  # top-N chromatic colours returned as evidence


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


_FETCH_MAX_HOPS = 4


def _url_is_safe(url: str) -> bool:
    """Public-host gate shared with the research fetcher. Fail-closed."""
    try:
        from mediahub.web_research.safe_fetch import is_url_safe

        return is_url_safe(url)
    except Exception:  # pragma: no cover - safe_fetch is a core module
        return False


def _read_text_capped(r, cap: int) -> Optional[str]:
    """Stream a response body up to ``cap`` bytes, then decode.

    The cap is enforced WHILE downloading (``iter_content``), so a huge
    or decompression-bomb body from a user-supplied URL never fully
    buffers in worker memory — the old ``r.text``-then-truncate approach
    materialised the whole response first. Charset: the header-declared
    encoding wins; otherwise the capped bytes are sniffed locally
    (``r.apparent_encoding`` is avoided on purpose — it reads
    ``r.content`` and would consume the rest of the stream).
    """
    chunks: list[bytes] = []
    total = 0
    try:
        for chunk in r.iter_content(64 * 1024):
            if not chunk:
                continue
            chunks.append(chunk)
            total += len(chunk)
            if total >= cap:
                break
    except Exception as e:
        log.debug("capped body read failed: %s", e)
        return None
    finally:
        try:
            r.close()
        except Exception:
            pass
    data = b"".join(chunks)[:cap]
    if not data:
        return ""
    enc = r.encoding
    if not enc:
        try:  # requests' own charset detector, run on the capped bytes only
            from charset_normalizer import from_bytes

            best = from_bytes(data).best()
            enc = best.encoding if best else None
        except Exception:
            enc = None
    try:
        return data.decode(enc or "utf-8", errors="replace")
    except (LookupError, TypeError):
        return data.decode("utf-8", errors="replace")


def _fetch(url: str) -> Optional[str]:
    """Fetch a URL with a sane UA, size cap, and timeout. Returns text or None.

    SSRF-safe: the host must resolve to public IPs, and redirects are
    followed manually so every hop is re-validated — a public URL can never
    302 the capture into a private/loopback address. The body is streamed
    against the byte cap, never fully buffered.
    """
    try:
        import requests  # already a project dep
    except Exception:
        log.debug("requests not installed")
        return None
    current = url
    for _ in range(_FETCH_MAX_HOPS):
        if not _url_is_safe(current):
            log.debug("brand-dna fetch blocked (unsafe host): %s", current)
            return None
        try:
            r = requests.get(
                current,
                headers={"User-Agent": _USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
                timeout=_FETCH_TIMEOUT,
                allow_redirects=False,
                stream=True,
            )
        except Exception as e:
            log.debug("brand-dna fetch failed for %s: %s", current, e)
            return None
        if r.status_code in (301, 302, 303, 307, 308):
            try:
                r.close()
            except Exception:
                pass
            nxt = r.headers.get("Location", "")
            if not nxt:
                return None
            current = urljoin(current, nxt)
            continue
        if r.status_code != 200:
            log.debug("brand-dna non-200 (%s) for %s", r.status_code, current)
            try:
                r.close()
            except Exception:
                pass
            return None
        return _read_text_capped(r, _MAX_HTML_BYTES)
    return None


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


# ---------------------------------------------------------------------------
# Colour-USAGE evidence (with frequency), incl. linked stylesheets
# ---------------------------------------------------------------------------
#
# The brand-palette decision is made by the cloud LLM, but it can only be
# as good as the evidence it sees. A flat list of "every hex on the page"
# surfaces the unused DEFAULT swatches that WordPress / Divi / Elementor /
# Material / Bootstrap inline on every site — and the LLM, given no other
# signal, picks them. The decisive signal is how OFTEN each colour is
# actually used across the full CSS: the real brand navy turns up dozens of
# times; a stray builder default turns up once or twice.
#
# These helpers gather that evidence (a [(hex, count), ...] map) — they do
# NOT choose the palette. The white/black/near-grey filter below is data
# hygiene (UI tokens flood the count), not a brand decision.

_LINK_CSS_RE = re.compile(
    r"<link\b[^>]*?>",
    re.IGNORECASE | re.DOTALL,
)
_REL_ATTR_RE = re.compile(r"""rel\s*=\s*["']?([^"'>]+)""", re.IGNORECASE)
_HREF_ATTR_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


def _usage_is_chromatic(r: int, g: int, b: int) -> bool:
    """Data hygiene: reject pure white/black and near-grey UI tokens.

    Mirrors the filter used by the legacy first-appearance scan. A colour
    is kept when it carries real hue — the spread between the max and min
    RGB channel is >= 8 — UNLESS it is an extreme (very-near white/black),
    which page chrome dumps in bulk. This is evidence hygiene; the AI still
    decides which of the surviving chromatic colours are the brand.
    """
    if max(r, g, b) - min(r, g, b) < 8:
        # near-grey: keep only the extremes are still noise, drop mid-greys
        if max(r, g, b) < 240 and min(r, g, b) > 15:
            return False
    return True


def build_colour_usage_map(
    text: str,
    *,
    top: int = _COLOUR_USAGE_TOP,
) -> list[tuple[str, int]]:
    """Count every distinct chromatic ``#rrggbb`` in ``text`` by frequency.

    ``text`` is the combined (page HTML + any fetched stylesheet) blob.
    Returns ``[(hex, count), ...]`` sorted by count desc (ties broken by
    hex for determinism), capped at ``top``. Pure white, pure black and
    near-grey are dropped as data hygiene (see ``_usage_is_chromatic``);
    this is evidence-gathering for the AI, NOT a brand decision.
    """
    if not text:
        return []
    counts: dict[str, int] = {}
    for m in _COLOUR_RE.findall(text):
        norm = _normalise_hex(m)
        if len(norm) != 7:  # only count full #rrggbb (3-digit expanded above)
            continue
        if norm in ("#ffffff", "#000000"):
            continue
        try:
            r, g, b = int(norm[1:3], 16), int(norm[3:5], 16), int(norm[5:7], 16)
        except ValueError:
            continue
        if not _usage_is_chromatic(r, g, b):
            continue
        counts[norm] = counts.get(norm, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[:top]


def _stylesheet_hrefs(html: str) -> list[str]:
    """Extract ``href`` of every ``<link rel="stylesheet">`` in the HTML."""
    hrefs: list[str] = []
    for tag in _LINK_CSS_RE.findall(html or ""):
        rel_m = _REL_ATTR_RE.search(tag)
        if not rel_m or "stylesheet" not in rel_m.group(1).lower():
            continue
        href_m = _HREF_ATTR_RE.search(tag)
        if not href_m:
            continue
        href = href_m.group(1).strip()
        if href and href not in hrefs:
            hrefs.append(href)
    return hrefs


def _default_css_fetcher(css_url: str) -> Optional[str]:
    """Best-effort GET of one stylesheet. Returns text or None. Never raises.

    SSRF-safe: same public-host gate as the page fetch; redirects are not
    followed (a stylesheet that redirects is simply skipped).
    """
    try:
        import requests
    except Exception:
        return None
    if not _url_is_safe(css_url):
        log.debug("css fetch blocked (unsafe host): %s", css_url)
        return None
    try:
        r = requests.get(
            css_url,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/css,*/*;q=0.1"},
            timeout=_CSS_FETCH_TIMEOUT,
            allow_redirects=False,
            stream=True,
        )
    except Exception as e:
        log.debug("css fetch failed for %s: %s", css_url, e)
        return None
    if r.status_code != 200:
        try:
            r.close()
        except Exception:
            pass
        return None
    return _read_text_capped(r, _CSS_FETCH_BYTES)


def fetch_linked_css(
    html: str,
    base_url: str,
    *,
    fetcher=None,
    max_sheets: int = _CSS_FETCH_MAX,
) -> str:
    """Best-effort fetch of up to ``max_sheets`` linked stylesheets.

    Parses ``<link rel="stylesheet" href=...>`` from ``html``, resolves
    each href against ``base_url``, and fetches it (same-origin first,
    then obvious CDNs). Returns the concatenated CSS text. Any failure on
    any sheet is silently ignored — this NEVER raises and NEVER blocks the
    crawl; missing CSS simply means thinner colour evidence.

    ``fetcher`` is injectable for tests: a callable ``(url) -> str|None``.
    """
    if not html:
        return ""
    fetch = fetcher or _default_css_fetcher
    try:
        base_host = urlparse(base_url).netloc.lower()
    except Exception:
        base_host = ""
    pieces: list[str] = []
    fetched = 0
    for href in _stylesheet_hrefs(html):
        if fetched >= max_sheets:
            break
        try:
            abs_url = urljoin(base_url, href)
        except Exception:
            continue
        if not abs_url.lower().startswith(("http://", "https://")):
            continue
        # Prefer same-origin; allow obvious CDN hosts (they serve the
        # builder/theme CSS where real usage lives).
        try:
            host = urlparse(abs_url).netloc.lower()
        except Exception:
            continue
        same_origin = host == base_host
        looks_cdn = any(
            tok in host
            for tok in (
                "cdn",
                "jsdelivr",
                "unpkg",
                "cloudflare",
                "cloudfront",
                "fonts.googleapis",
                "bootstrapcdn",
                "staticfile",
            )
        )
        if not (same_origin or looks_cdn):
            continue
        css = None
        try:
            css = fetch(abs_url)
        except Exception as e:
            log.debug("css fetcher raised for %s: %s", abs_url, e)
            css = None
        if css:
            pieces.append(css)
            fetched += 1
    return "\n".join(pieces)


def colour_usage_evidence(
    html: str,
    url: str,
    *,
    css_fetcher=None,
) -> list[tuple[str, int]]:
    """End-to-end colour-usage evidence for one page.

    Combines the page HTML with up to ``_CSS_FETCH_MAX`` linked
    stylesheets and returns the frequency-ranked chromatic colour map.
    Best-effort: a CSS fetch failure just yields HTML-only evidence.
    """
    css = fetch_linked_css(html, url, fetcher=css_fetcher)
    combined = (html or "") + ("\n" + css if css else "")
    return build_colour_usage_map(combined)


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

        md = soup.find("meta", attrs={"name": "description"}) or soup.find(
            "meta", attrs={"property": "og:description"}
        )
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
# Palette evidence — usage frequencies + image pixels (P1.5)
# ---------------------------------------------------------------------------


def gather_palette_evidence(
    html: str,
    url: str,
    signals: dict,
    *,
    css_fetcher=None,
    image_fetcher=None,
) -> dict:
    """All the deterministic colour evidence for one site, with provenance.

    Combines (a) the site-wide colour-USAGE map (page HTML + linked CSS),
    (b) `materialyoucolor`-quantized candidates from the detected logo and
    og:image pixels, and (c) the declared theme-color. Returns::

        {
          "usage":   [(hex, count), ...],
          "images":  {"logo": [...], "og_image": [...]},
          "sources": {hex: provenance_string},   # strongest source wins
          "ordered": [hex, ...],                 # evidence-strength order
        }

    Evidence-gathering only — semantic role assignment stays with the LLM.
    """
    usage = colour_usage_evidence(html, url, css_fetcher=css_fetcher)

    try:
        from mediahub.brand.palette_evidence import gather_image_evidence

        images = gather_image_evidence(
            logo_url=signals.get("logo_url") or "",
            og_image_url=signals.get("og_image") or "",
            image_fetcher=image_fetcher,
        )
    except Exception as e:
        log.debug("image evidence unavailable: %s", e)
        images = {"logo": [], "og_image": []}

    sources: dict[str, str] = {}
    ordered: list[str] = []

    def _add(hex_value: str, provenance: str) -> None:
        h = _normalise_hex(hex_value)
        if not _is_valid_hex(h):
            return
        if h not in sources:
            sources[h] = provenance
            ordered.append(h)

    # Strongest first: real logo pixels → declared theme-color → og-image
    # pixels → site-wide CSS usage → raw HTML scan.
    for cand in images.get("logo") or []:
        _add(
            cand["hex"],
            f"logo pixels (material score rank {cand['rank']}, "
            f"{cand['population_share']:.0%} of pixels)",
        )
    if signals.get("theme_color"):
        _add(signals["theme_color"], "declared <meta name=theme-color>")
    for cand in images.get("og_image") or []:
        _add(cand["hex"], f"og:image pixels (material score rank {cand['rank']})")
    for hex_value, count in usage:
        _add(hex_value, f"used {count}× across page + linked CSS")
    for hex_value in signals.get("colours") or []:
        _add(hex_value, "found in page HTML")

    return {"usage": usage, "images": images, "sources": sources, "ordered": ordered}


def _palette_from_evidence(evidence: dict) -> tuple[dict, dict, str]:
    """Deterministic palette fill from the evidence-strength order.

    Returns ``(palette, per_slot_sources, reasoning)``. This is a *real*
    deterministic path — every hex comes from the club's own site/assets —
    used to fill slots when no provider is configured or an LLM pick fails
    validation. It assigns by evidence strength, not by judgement.
    """
    ordered: list[str] = evidence.get("ordered") or []
    sources: dict[str, str] = evidence.get("sources") or {}
    palette: dict[str, str] = {}
    slot_sources: dict[str, str] = {}
    for slot, hex_value in zip(("primary", "secondary", "accent"), ordered):
        palette[slot] = hex_value
        slot_sources[slot] = f"evidence: {sources.get(hex_value, 'site evidence')}"
    reasoning = (
        "Deterministic fill in evidence-strength order (logo pixels → theme-color → "
        "og:image pixels → CSS usage)."
        if palette
        else "No colour evidence found on the site."
    )
    return palette, slot_sources, reasoning


# ---------------------------------------------------------------------------
# LLM step
# ---------------------------------------------------------------------------

_LLM_SYSTEM = (
    "You analyse a club, society or sports team's website signals and "
    "return a structured brand profile as JSON. Be factual, terse and "
    "concrete. Do not invent details that aren't supported by the signals. "
    "Palette colours MUST be chosen verbatim from the evidence list given."
)


def _build_llm_prompt(signals: dict, url: str, evidence: Optional[dict] = None) -> str:
    lines = [
        f"Website URL: {url}",
        f"Page title: {signals.get('title','')}",
        f"Meta description: {signals.get('meta_description','')}",
    ]
    headings = signals.get("headings") or []
    if headings:
        lines.append("Headings: " + " | ".join(headings[:6]))

    ev = evidence or {}
    ordered = ev.get("ordered") or []
    sources = ev.get("sources") or {}
    if ordered:
        lines.append("Colour evidence (strongest first — pick palette ONLY from these):")
        for hex_value in ordered[:14]:
            lines.append(f"  - {hex_value} — {sources.get(hex_value, 'site evidence')}")
    else:
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
        '  palette: object {"primary":"#rrggbb","secondary":"#rrggbb","accent":"#rrggbb"} — '
        "every value MUST appear verbatim in the colour evidence above\n"
        '  typography_hint: one of "serif", "sans", "display", "mono"\n'
        "No prose, no fences, no commentary — only the JSON object."
    )
    return "\n".join(lines)


def _is_valid_hex(c: str) -> bool:
    return isinstance(c, str) and bool(re.match(r"^#[0-9a-fA-F]{6}$", c))


def _call_llm(signals: dict, url: str, evidence: Optional[dict] = None) -> Optional[dict]:
    """Ask the LLM for the structured profile. Returns dict or None on failure.

    Rides ``media_ai.llm`` so the same call serves Gemini, Anthropic, or a
    local OpenAI-compatible endpoint (Ollama et al. via
    ``MEDIAHUB_LLM_ENDPOINTS``) — no paid API is required for this step.
    """
    try:
        from mediahub.media_ai.llm import generate_json, is_available
    except Exception as e:
        log.debug("llm import failed: %s", e)
        return None
    if not is_available():
        return None
    prompt = _build_llm_prompt(signals, url, evidence)
    try:
        data = generate_json(prompt, system=_LLM_SYSTEM, max_tokens=900, fallback={})
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
        "brand_palette_sources": {},
        "brand_palette_reasoning": "",
    }


def _merge_llm_into_result(
    base: dict, llm: dict, signals: dict, evidence: Optional[dict] = None
) -> dict:
    """Apply the LLM-returned dict to the base result, with type guards.

    Never raises — bad LLM output is replaced with safe defaults. Palette
    picks are validated against the evidence universe: a hex the site never
    exhibited is dropped (anti-hallucination) and the slot falls back to the
    deterministic evidence fill, with per-slot provenance recorded in
    ``brand_palette_sources``.
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

    ev = evidence or {}
    universe: dict[str, str] = ev.get("sources") or {}
    ordered: list[str] = ev.get("ordered") or []

    palette = llm.get("palette")
    clean: dict[str, str] = {}
    slot_sources: dict[str, str] = {}
    dropped: list[str] = []
    if isinstance(palette, dict):
        for k in ("primary", "secondary", "accent"):
            v = palette.get(k)
            if not isinstance(v, str):
                continue
            v_norm = _normalise_hex(v) if v.startswith("#") else v
            if not _is_valid_hex(v_norm):
                continue
            if universe and v_norm not in universe:
                # The model invented a colour the site never exhibited.
                dropped.append(f"{k}={v_norm}")
                continue
            clean[k] = v_norm
            slot_sources[k] = f"ai pick (from {universe.get(v_norm, 'site evidence')})"
    # Fill any missing palette slot deterministically: walk the evidence in
    # strength order and take the next colour the AI hasn't already placed.
    used = set(clean.values())
    for k in ("primary", "secondary", "accent"):
        if k in clean:
            continue
        candidate = next((h for h in ordered if h not in used), None)
        if candidate:
            clean[k] = candidate
            slot_sources[k] = f"evidence: {universe.get(candidate, 'site evidence')}"
            used.add(candidate)
    if clean:
        out["brand_palette_extracted"] = clean
        out["brand_palette_sources"] = slot_sources
        reasoning = llm.get("palette_reasoning")
        out["brand_palette_reasoning"] = (
            str(reasoning).strip()[:300]
            if isinstance(reasoning, str) and str(reasoning).strip()
            else "AI role assignment over deterministic site evidence "
            "(logo pixels, theme-color, CSS usage)."
        )
        if dropped:
            out["brand_palette_reasoning"] += (
                " Dropped invented colour(s) not present in the evidence: "
                + ", ".join(dropped)
                + "."
            )

    typo = llm.get("typography_hint")
    if isinstance(typo, str) and typo.strip().lower() in ("serif", "sans", "display", "mono"):
        out["brand_typography_hint"] = typo.strip().lower()

    return out


def capture_brand_dna(
    website_url: str,
    *,
    force: bool = False,
    css_fetcher=None,
    image_fetcher=None,
) -> dict:
    """Capture a structured brand profile from a website URL.

    Args:
        website_url: the URL to analyse. http:// prefix added if missing.
        force: ignore the on-disk cache and re-fetch.
        css_fetcher / image_fetcher: injectable fetchers (tests); the
            defaults are the SSRF-safe HTTP fetchers.

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
    evidence = gather_palette_evidence(
        html, url, signals, css_fetcher=css_fetcher, image_fetcher=image_fetcher
    )

    # Build the deterministic base result so we always have something:
    # palette slots filled in evidence-strength order (logo pixels →
    # theme-color → og:image pixels → CSS usage), each with provenance.
    base = _empty_result(url, "extracted")
    if signals.get("logo_url"):
        base["brand_logo_url"] = signals["logo_url"]
    ev_palette, ev_sources, ev_reasoning = _palette_from_evidence(evidence)
    if ev_palette:
        base["brand_palette_extracted"] = ev_palette
        base["brand_palette_sources"] = ev_sources
        base["brand_palette_reasoning"] = ev_reasoning

    llm_out = _call_llm(signals, url, evidence)
    if llm_out:
        out = _merge_llm_into_result(base, llm_out, signals, evidence)
        out["brand_capture_status"] = "ok"
    else:
        # No LLM provider reachable (hosted or local) — preserve the
        # deterministic, evidence-grounded palette / logo signals, but do
        # NOT invent voice / keywords / phrases. Status "no_provider"
        # tells the UI to surface an honest "configure an AI provider"
        # message (a local MEDIAHUB_LLM_ENDPOINTS endpoint counts).
        out = dict(base)
        out["brand_capture_status"] = "no_provider"

    out["brand_captured_at"] = _now_iso()

    _save_cache(url, out)
    return out


__all__ = [
    "capture_brand_dna",
    "build_colour_usage_map",
    "fetch_linked_css",
    "colour_usage_evidence",
    "gather_palette_evidence",
]
