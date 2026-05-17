"""brand/social_dna.py — Capture an organisation's brand DNA from social links.

This is the AI-first ingestion path used by the first-run organisation
setup. The user pastes one or more URLs (website + up to five social
profiles); per-platform fetchers grab whatever raw text is publicly
reachable, and then a single LLM call interprets *all* of it together
to produce a unified brand+voice profile.

The interpretation layer is intentionally LLM-driven — there are no
hardcoded "if instagram then friendly" heuristics here. The fetchers
are deliberately small and graceful: any link that is rate-limited,
auth-walled, or 4xx is recorded with a status and skipped, never
failing the whole capture.

Public surface:
    capture_from_socials(social_links: dict[str, str],
                         website_url: str = "",
                         *,
                         force: bool = False) -> dict

Returned dict shape:
    {
        # Same keys as brand.dna_capture.capture_brand_dna():
        "brand_voice_summary": str,
        "brand_keywords": list[str],
        "brand_palette_extracted": dict,
        "brand_logo_url": str,
        "brand_typography_hint": str,
        "brand_phrases_to_avoid": list[str],
        "brand_phrases_to_use": list[str],
        "brand_source_url": str,           # website if provided, else first social
        "brand_captured_at": str,
        "brand_capture_status": str,       # "ok" | "ok_heuristic" | "no_sources" | ...

        # New social-specific outputs:
        "voice_profile": dict,             # same schema as brand.voice_imitation
        "social_links_status": dict,       # {platform: "ok" | "blocked" | "fetch_failed" | ...}
        "captions_captured": int,          # how many captions the LLM saw
    }

Graceful failure: every failure mode returns a dict with status set.
Never raises.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (compatible; MediaHubBrandDNA/1.0; "
    "+https://mediahub.example/about)"
)
_FETCH_TIMEOUT = 15
_MAX_HTML_BYTES = 2_000_000

# Platforms we recognise — order matters only for display.
SUPPORTED_PLATFORMS: tuple[str, ...] = (
    "instagram",
    "facebook",
    "twitter",
    "tiktok",
    "linkedin",
)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _cache_dir() -> Path:
    base = os.environ.get("DATA_DIR")
    if base:
        d = Path(base) / "social_dna_cache"
    else:
        d = Path(__file__).resolve().parents[1] / "data" / "social_dna_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(website_url: str, social_links: dict[str, str]) -> str:
    """Stable key for the full set of inputs."""
    parts = [(website_url or "").strip().lower()]
    for k in sorted(social_links or {}):
        v = (social_links.get(k) or "").strip().lower()
        if v:
            parts.append(f"{k}|{v}")
    blob = "::".join(parts) or "empty"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _cache_path(website_url: str, social_links: dict[str, str]) -> Path:
    return _cache_dir() / f"{_cache_key(website_url, social_links)}.json"


def _load_cache(website_url: str, social_links: dict[str, str]) -> Optional[dict]:
    p = _cache_path(website_url, social_links)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_cache(website_url: str, social_links: dict[str, str], payload: dict) -> None:
    try:
        p = _cache_path(website_url, social_links)
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as e:
        log.debug("social-dna cache write failed: %s", e)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _fetch(url: str) -> tuple[Optional[str], int]:
    """Fetch a URL. Returns (text_or_None, status_code).

    status_code is 0 on connection failure, the HTTP status on a real
    response. We need the code so the analyser can tell the LLM
    "this link 403'd, treat it as unknown" rather than silently dropping it.
    """
    try:
        import requests
    except Exception:
        return None, 0
    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "en-GB,en;q=0.9",
            },
            timeout=_FETCH_TIMEOUT,
            allow_redirects=True,
        )
    except Exception as e:
        log.debug("social-dna fetch failed for %s: %s", url, e)
        return None, 0
    if r.status_code != 200:
        return None, r.status_code
    text = r.text or ""
    if len(text) > _MAX_HTML_BYTES:
        text = text[:_MAX_HTML_BYTES]
    return text, 200


# ---------------------------------------------------------------------------
# Per-platform text extraction
#
# Each extractor's job is to pull text the LLM can read — *not* to
# interpret it. We grab title, meta description, og:* tags, visible
# captions/bio when easily reachable, and hand the lot to the LLM.
# Anything platform-specific (e.g. "instagram captions live in this JSON
# blob") is a fetching detail, not an interpretation rule.
# ---------------------------------------------------------------------------

_BS4_AVAILABLE: Optional[bool] = None


def _get_soup(html: str):
    global _BS4_AVAILABLE
    if not html:
        return None
    try:
        from bs4 import BeautifulSoup
        _BS4_AVAILABLE = True
        return BeautifulSoup(html, "html.parser")
    except Exception:
        _BS4_AVAILABLE = False
        return None


def _meta_block(soup) -> dict:
    """Pull og:title, og:description, og:image, description, theme-color."""
    out = {"title": "", "description": "", "og_image": "", "theme_color": ""}
    if soup is None:
        return out
    if soup.title and soup.title.string:
        out["title"] = soup.title.string.strip()[:400]
    md = soup.find("meta", attrs={"name": "description"}) or \
         soup.find("meta", attrs={"property": "og:description"})
    if md and md.get("content"):
        out["description"] = md["content"].strip()[:1200]
    og = soup.find("meta", attrs={"property": "og:image"})
    if og and og.get("content"):
        out["og_image"] = og["content"].strip()
    tc = soup.find("meta", attrs={"name": "theme-color"})
    if tc and tc.get("content"):
        out["theme_color"] = tc["content"].strip()
    return out


_HASHTAG_RE = re.compile(r"#[A-Za-z][A-Za-z0-9_]{1,40}")


def _extract_visible_text(soup, *, limit_chars: int = 8000) -> str:
    """Strip scripts/styles, collapse whitespace, return up to ``limit_chars``."""
    if soup is None:
        return ""
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text[:limit_chars]


def _extract_captions_from_text(text: str) -> list[str]:
    """Best-effort: split on sentence-like boundaries, keep things that look
    like captions (contain a hashtag, an emoji-ish character, or are 30+ chars).
    The LLM does the real interpretation; this is just to seed it with
    candidates.
    """
    if not text:
        return []
    # Split on common social-style separators
    chunks = re.split(r"(?:\s•\s|\s\|\s|\n+|(?<=[.!?])\s+)", text)
    out: list[str] = []
    for ch in chunks:
        ch = ch.strip()
        if 20 <= len(ch) <= 400:
            out.append(ch)
        if len(out) >= 30:
            break
    return out


def _fetch_platform(platform: str, url: str) -> dict:
    """Return a normalised payload for one platform link.

    Schema:
        {
            "platform": "instagram",
            "url": "...",
            "status": "ok" | "blocked" | "fetch_failed" | "auth_walled" | "http_<n>",
            "title": str,
            "description": str,
            "text_excerpt": str,        # visible text, trimmed
            "candidate_captions": list[str],
            "hashtags": list[str],
            "og_image": str,
        }
    """
    payload = {
        "platform": platform,
        "url": url,
        "status": "fetch_failed",
        "title": "",
        "description": "",
        "text_excerpt": "",
        "candidate_captions": [],
        "hashtags": [],
        "og_image": "",
    }
    if not url:
        payload["status"] = "missing_url"
        return payload
    html, code = _fetch(url)
    if html is None:
        payload["status"] = f"http_{code}" if code else "fetch_failed"
        # Many social platforms answer 401/403/429 to bots — record honestly
        # so the LLM is told "we couldn't read this one".
        if code in (401, 403):
            payload["status"] = "auth_walled"
        elif code == 404:
            payload["status"] = "not_found"
        elif code == 429:
            payload["status"] = "rate_limited"
        return payload

    soup = _get_soup(html)
    meta = _meta_block(soup)
    payload["title"] = meta.get("title", "")
    payload["description"] = meta.get("description", "")
    payload["og_image"] = meta.get("og_image", "")
    visible = _extract_visible_text(soup) if soup is not None else ""
    payload["text_excerpt"] = visible
    payload["candidate_captions"] = _extract_captions_from_text(
        visible or meta.get("description", "")
    )
    tags = _HASHTAG_RE.findall(visible or "")
    # de-dupe preserving order
    seen: set[str] = set()
    unique_tags: list[str] = []
    for t in tags:
        tl = t.lower()
        if tl not in seen:
            seen.add(tl)
            unique_tags.append(t)
    payload["hashtags"] = unique_tags[:25]

    # Did we actually get anything useful? If the page rendered but had
    # nothing readable (common for JS-only SPAs like instagram.com), call
    # it "blocked" so the LLM knows.
    has_signal = bool(
        payload["title"]
        or payload["description"]
        or payload["candidate_captions"]
        or payload["hashtags"]
    )
    payload["status"] = "ok" if has_signal else "blocked"
    return payload


def _fetch_website(url: str) -> dict:
    """Website fetcher: returns the same shape as a platform payload, with
    one extra key — ``palette_hints`` (frequency-ranked hex colours from
    inline CSS/style attrs).
    """
    payload = _fetch_platform("website", url)
    if payload["status"] != "ok" and payload["status"] != "blocked":
        return payload | {"palette_hints": []}
    html, _ = _fetch(url)
    colours: list[str] = []
    if html:
        # Frequency-ranked hex colour sweep, skipping pure black/white
        matches = re.findall(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b", html)
        counts: dict[str, int] = {}
        for m in matches:
            c = m.lower()
            if len(c) == 4:
                c = "#" + "".join(ch * 2 for ch in c[1:])
            counts[c] = counts.get(c, 0) + 1
        def _key(item: tuple[str, int]) -> tuple[bool, int]:
            hexv, n = item
            r, g, b = int(hexv[1:3], 16), int(hexv[3:5], 16), int(hexv[5:7], 16)
            is_grey = abs(r - g) < 8 and abs(g - b) < 8
            return (is_grey, -n)
        colours = [c for c, _ in sorted(counts.items(), key=_key)][:8]
    payload["palette_hints"] = colours
    return payload


# ---------------------------------------------------------------------------
# LLM interpretation — one call, everything together
# ---------------------------------------------------------------------------

_LLM_SYSTEM = (
    "You analyse a club, society, sports team or organisation's online "
    "presence and return a structured brand+voice profile as JSON. You "
    "will be given raw text excerpts from the organisation's website and "
    "social profiles (some links may have been blocked or auth-walled — "
    "those will be flagged so you can ignore them). Be factual, terse, "
    "and concrete. Do not invent details that aren't supported by the "
    "evidence you are given. Where evidence is thin, leave fields empty "
    "rather than guessing."
)


def _build_llm_prompt(payloads: list[dict], website_payload: Optional[dict]) -> str:
    """Assemble one prompt that hands the LLM everything we collected."""
    lines: list[str] = []
    if website_payload:
        lines.append(f"### WEBSITE: {website_payload.get('url','')}")
        lines.append(f"  status: {website_payload.get('status','')}")
        if website_payload.get("title"):
            lines.append(f"  title: {website_payload['title']}")
        if website_payload.get("description"):
            lines.append(f"  meta description: {website_payload['description']}")
        excerpt = (website_payload.get("text_excerpt") or "")[:1800]
        if excerpt:
            lines.append(f"  visible text excerpt: {excerpt}")
        hints = website_payload.get("palette_hints") or []
        if hints:
            lines.append(f"  most-used hex colours: {', '.join(hints)}")
        if website_payload.get("og_image"):
            lines.append(f"  og:image: {website_payload['og_image']}")
        lines.append("")
    for p in payloads:
        lines.append(f"### {p.get('platform','').upper()}: {p.get('url','')}")
        lines.append(f"  status: {p.get('status','')}")
        if p.get("status") != "ok" and p.get("status") != "blocked":
            lines.append("  (no readable text — treat as unknown for this platform)")
            lines.append("")
            continue
        if p.get("title"):
            lines.append(f"  page title: {p['title']}")
        if p.get("description"):
            lines.append(f"  description / bio: {p['description']}")
        caps = p.get("candidate_captions") or []
        if caps:
            lines.append("  candidate caption fragments:")
            for c in caps[:10]:
                lines.append(f"    - {c}")
        tags = p.get("hashtags") or []
        if tags:
            lines.append(f"  hashtags seen: {', '.join(tags[:15])}")
        lines.append("")

    lines.append(
        "Return a SINGLE JSON object with EXACTLY these keys (no prose, no "
        "fences, no commentary):\n"
        "  voice_summary: string, 30-60 words on this organisation's voice "
        "and what they're about\n"
        "  keywords: array of 6-12 short keywords this organisation would "
        "use about itself\n"
        "  phrases_to_use: array of 3-6 short phrases that sound like them "
        "(draw from the captions if possible)\n"
        "  phrases_to_avoid: array of 3-5 short phrases that would feel "
        "off-brand for them\n"
        '  palette: object {"primary":"#rrggbb","secondary":"#rrggbb",'
        '"accent":"#rrggbb"} — use the website hex hints if present, '
        "otherwise infer from descriptions; leave a key out if you have "
        "no evidence\n"
        '  typography_hint: one of "serif", "sans", "display", "mono"\n'
        "  voice_profile: object with these keys describing how they "
        "actually write captions (infer from candidate captions where you "
        "can; use null when evidence is too thin):\n"
        "    sentence_length_avg: number\n"
        "    sentence_length_p90: number\n"
        "    emoji_rate_per_caption: number\n"
        "    hashtag_count_avg: number\n"
        "    characteristic_openers: array of up to 4 short opener phrases\n"
        "    characteristic_closers: array of up to 4 short closer phrases\n"
        "    forbidden_phrases: array of up to 5 short phrases that would "
        "feel wrong from this org\n"
        "    preferred_swimmer_address: one of \"first_name\", \"last_name\", "
        "\"surname_only\", \"nickname\"\n"
        "    common_hashtags: array of up to 8 hashtags they use\n"
        "    capitalisation_style: one of \"sentence\", \"title\", \"shouty\", "
        "\"lower\"\n"
    )
    return "\n".join(lines)


def _call_llm(prompt: str) -> Optional[dict]:
    try:
        from mediahub.media_ai.llm import generate_json, is_available
    except Exception:
        return None
    if not is_available():
        return None
    try:
        data = generate_json(
            prompt,
            system=_LLM_SYSTEM,
            max_tokens=1400,
            fallback={},
        )
    except Exception as e:
        log.debug("social-dna LLM call failed: %s", e)
        return None
    if not isinstance(data, dict) or not data:
        return None
    return data


# ---------------------------------------------------------------------------
# Result assembly
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _normalise_hex(c: str) -> str:
    c = (c or "").lower()
    if len(c) == 4 and c.startswith("#"):
        c = "#" + "".join(ch * 2 for ch in c[1:])
    return c


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty_result(primary_url: str, status: str) -> dict:
    return {
        "brand_voice_summary": "",
        "brand_keywords": [],
        "brand_palette_extracted": {},
        "brand_logo_url": "",
        "brand_typography_hint": "",
        "brand_phrases_to_avoid": [],
        "brand_phrases_to_use": [],
        "brand_source_url": primary_url,
        "brand_captured_at": _now_iso(),
        "brand_capture_status": status,
        "voice_profile": {},
        "social_links_status": {},
        "captions_captured": 0,
    }


def _merge_llm_into_result(
    base: dict,
    llm: dict,
    website_payload: Optional[dict],
) -> dict:
    out = dict(base)
    summary = llm.get("voice_summary")
    if isinstance(summary, str) and summary.strip():
        out["brand_voice_summary"] = summary.strip()[:800]
    kw = llm.get("keywords")
    if isinstance(kw, list):
        out["brand_keywords"] = [str(k).strip() for k in kw if str(k).strip()][:12]
    ptu = llm.get("phrases_to_use")
    if isinstance(ptu, list):
        out["brand_phrases_to_use"] = [str(p).strip() for p in ptu if str(p).strip()][:6]
    pta = llm.get("phrases_to_avoid")
    if isinstance(pta, list):
        out["brand_phrases_to_avoid"] = [str(p).strip() for p in pta if str(p).strip()][:5]

    palette = llm.get("palette")
    clean_pal: dict[str, str] = {}
    if isinstance(palette, dict):
        for slot in ("primary", "secondary", "accent"):
            v = palette.get(slot)
            if isinstance(v, str):
                v_norm = _normalise_hex(v) if v.startswith("#") else v
                if _HEX_RE.match(v_norm):
                    clean_pal[slot] = v_norm
    # Fill from website palette hints if the LLM left slots blank
    hints = (website_payload or {}).get("palette_hints") or []
    if "primary" not in clean_pal and hints:
        clean_pal["primary"] = hints[0]
    if "secondary" not in clean_pal and len(hints) > 1:
        clean_pal["secondary"] = hints[1]
    if "accent" not in clean_pal and len(hints) > 2:
        clean_pal["accent"] = hints[2]
    if clean_pal:
        out["brand_palette_extracted"] = clean_pal

    typo = llm.get("typography_hint")
    if isinstance(typo, str) and typo.strip().lower() in ("serif", "sans", "display", "mono"):
        out["brand_typography_hint"] = typo.strip().lower()

    # Logo — prefer the website's og:image; the LLM doesn't see images.
    if website_payload and website_payload.get("og_image"):
        out["brand_logo_url"] = website_payload["og_image"]

    # Voice profile
    vp = llm.get("voice_profile")
    if isinstance(vp, dict):
        cleaned_vp: dict = {}
        for numeric in (
            "sentence_length_avg",
            "sentence_length_p90",
            "emoji_rate_per_caption",
            "hashtag_count_avg",
        ):
            v = vp.get(numeric)
            if v is None:
                continue
            try:
                cleaned_vp[numeric] = float(v)
            except (TypeError, ValueError):
                continue
        for list_key in (
            "characteristic_openers",
            "characteristic_closers",
            "forbidden_phrases",
            "common_hashtags",
        ):
            v = vp.get(list_key)
            if isinstance(v, list):
                cleaned_vp[list_key] = [str(x).strip() for x in v if str(x).strip()][:8]
        addr = vp.get("preferred_swimmer_address")
        if isinstance(addr, str) and addr in (
            "first_name", "last_name", "surname_only", "nickname",
        ):
            cleaned_vp["preferred_swimmer_address"] = addr
        cap_style = vp.get("capitalisation_style")
        if isinstance(cap_style, str) and cap_style in (
            "sentence", "title", "shouty", "lower",
        ):
            cleaned_vp["capitalisation_style"] = cap_style
        if cleaned_vp:
            out["voice_profile"] = cleaned_vp

    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def capture_from_socials(
    social_links: Optional[dict[str, str]] = None,
    website_url: str = "",
    *,
    force: bool = False,
) -> dict:
    """Build a unified brand+voice profile from a website + social links.

    Args:
        social_links: dict mapping platform name to URL. Recognised keys:
            ``instagram``, ``facebook``, ``twitter``, ``tiktok``, ``linkedin``.
            Unknown keys are still fetched (status recorded), but the
            LLM is told what platform they are.
        website_url: optional canonical site URL.
        force: bypass the on-disk cache.

    Returns: dict — see module docstring. Always returns; never raises.
    """
    social_links = {k.lower(): (v or "").strip() for k, v in (social_links or {}).items() if v}
    website_url = (website_url or "").strip()
    if website_url and not re.match(r"^https?://", website_url, re.I):
        website_url = "https://" + website_url
    for k in list(social_links):
        u = social_links[k]
        if u and not re.match(r"^https?://", u, re.I):
            social_links[k] = "https://" + u

    primary = website_url or next(iter(social_links.values()), "")
    if not primary:
        return _empty_result("", "no_sources")

    if not force:
        cached = _load_cache(website_url, social_links)
        if (
            cached
            and isinstance(cached, dict)
            and cached.get("brand_capture_status") in ("ok", "ok_heuristic")
        ):
            return cached

    # ---- Fetch ----
    website_payload = _fetch_website(website_url) if website_url else None
    platform_payloads: list[dict] = []
    for platform, url in social_links.items():
        platform_payloads.append(_fetch_platform(platform, url))

    # If literally nothing fetched, bail honestly.
    any_signal = bool(website_payload and website_payload.get("status") == "ok") or any(
        p.get("status") == "ok" for p in platform_payloads
    )
    if not any_signal:
        out = _empty_result(primary, "fetch_failed_all")
        out["social_links_status"] = {p["platform"]: p["status"] for p in platform_payloads}
        if website_payload:
            out["social_links_status"]["website"] = website_payload.get("status", "")
        return out

    # ---- LLM interpretation ----
    prompt = _build_llm_prompt(platform_payloads, website_payload)
    llm_out = _call_llm(prompt)

    base = _empty_result(primary, "extracted")
    # Carry forward palette hints + logo even before merging
    if website_payload:
        hints = website_payload.get("palette_hints") or []
        if hints:
            base["brand_palette_extracted"] = {}
            slots = ["primary", "secondary", "accent"]
            for i, c in enumerate(hints[:3]):
                base["brand_palette_extracted"].setdefault(slots[i], c)
        if website_payload.get("og_image"):
            base["brand_logo_url"] = website_payload["og_image"]

    captions_seen = sum(len(p.get("candidate_captions") or []) for p in platform_payloads)
    if website_payload:
        captions_seen += len(website_payload.get("candidate_captions") or [])

    if llm_out:
        out = _merge_llm_into_result(base, llm_out, website_payload)
        out["brand_capture_status"] = "ok"
    else:
        # No LLM available — return whatever the fetchers extracted.
        # Build a minimal voice_summary from titles + descriptions so the
        # caller still has something useful to show.
        bits: list[str] = []
        if website_payload and website_payload.get("title"):
            bits.append(website_payload["title"])
        if website_payload and website_payload.get("description"):
            bits.append(website_payload["description"])
        for p in platform_payloads:
            if p.get("description"):
                bits.append(p["description"])
                break
        if bits:
            base["brand_voice_summary"] = " ".join(bits)[:400]
        base["brand_capture_status"] = "ok_heuristic"
        out = base

    out["social_links_status"] = {p["platform"]: p["status"] for p in platform_payloads}
    if website_payload:
        out["social_links_status"]["website"] = website_payload.get("status", "")
    out["captions_captured"] = captions_seen
    out["brand_captured_at"] = _now_iso()

    _save_cache(website_url, social_links, out)
    return out


__all__ = ["capture_from_socials", "SUPPORTED_PLATFORMS"]
