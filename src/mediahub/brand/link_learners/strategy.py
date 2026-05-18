"""link_learners/strategy.py — B7. Strategy proposer learner.

Given a URL and a sample fetch attempt (status code, response headers,
first 8 KB of body), the LLM proposes the next scraping strategy as
structured JSON. The handler then executes that strategy via the
shared HTTP fetcher (brand.social_dna._fetch).

This is the place we teach the system "how to read this kind of link".
The strategy is then persisted by brand.playbooks so it's replayed on
subsequent runs without re-asking the LLM.

Output schema (the only contract any caller relies on):

    {
      "url_template": "https://www.instagram.com/{handle}/embed/",
      "headers": {
        "User-Agent": "Mozilla/5.0 ...",
        "Accept": "text/html,...",
        "Accept-Language": "en-GB,en;q=0.9"
      },
      "parser": "html",                            # html|json|jsonld|oembed|rss
      "selectors_or_jsonpath": ["meta[property='og:description']",
                                "meta[property='og:image']",
                                "script[type='application/ld+json']"],
      "alt_endpoints": [
        "https://www.instagram.com/{handle}/?__a=1",
        "https://r.jina.ai/https://www.instagram.com/{handle}/"
      ],
      "notes": "Instagram blocks unauth requests for /username; the
                /embed/ variant returns og: meta consistently."
    }

If the LLM is unavailable the function returns a generic strategy
(plain HTML fetch, no special headers) so the system still functions
end-to-end on offline deployments.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)


_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; MediaHubBrandDNA/1.0; "
        "+https://mediahub.example/about)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


_LLM_SYSTEM = (
    "You design web-scraping strategies for a brand-intelligence "
    "system that needs to read the publicly-visible parts of "
    "club / society / sports-team websites and social profiles. "
    "You are given a URL, what we know about the platform, and a "
    "sample fetch attempt (status code, key response headers, body "
    "excerpt). You propose a SINGLE next strategy as JSON. Prefer "
    "endpoints that return rich metadata without authentication: "
    "oEmbed, embed pages, public JSON-LD blocks, RSS, mobile sites, "
    "sitemap.xml, og: meta tags. Avoid anything that would require an "
    "account, an OAuth token, or that would be considered abusive. Be "
    "conservative with rate."
)


def _build_prompt(
    url: str,
    platform_intent: str,
    sample: Optional[dict],
) -> str:
    sample = sample or {}
    body_excerpt = (sample.get("body_excerpt") or "")[:8_000]
    headers = sample.get("response_headers") or {}
    status = sample.get("status_code", "")
    header_summary = "; ".join(f"{k}: {v}" for k, v in headers.items() if k.lower() in (
        "content-type", "server", "x-frame-options", "content-security-policy",
        "set-cookie", "x-powered-by",
    ))
    parts = [
        f"URL: {url}",
        f"Platform intent: {platform_intent}",
        f"Sample fetch status: {status}",
        f"Key response headers: {header_summary or '(none captured)'}",
        f"Body excerpt (first ~8 KB):\n{body_excerpt or '(empty)'}",
        "",
        "Return a SINGLE JSON object with EXACTLY these keys:",
        "  url_template: string — the URL you propose to fetch. May "
        "use {handle} or {slug} placeholders if the input URL implies "
        "one. If the input URL is already correct, return it verbatim.",
        "  headers: object — request headers to send. At minimum include "
        "a sensible User-Agent and Accept-Language.",
        "  parser: one of \"html\", \"json\", \"jsonld\", \"oembed\", \"rss\".",
        "  selectors_or_jsonpath: array of CSS selectors (for html) or "
        "JSONPath expressions (for json/jsonld/oembed/rss) you expect "
        "to contain useful brand text. Empty array if not applicable.",
        "  alt_endpoints: array of up to 4 alternative URLs to try if "
        "the primary fetch returns a block / auth wall / 404. Same "
        "{handle}/{slug} placeholders allowed.",
        "  notes: short string explaining why this strategy should "
        "work. Useful for the operator and for future LLM calls when "
        "the strategy drifts.",
    ]
    return "\n".join(parts)


def _normalise(raw: object, fallback_url: str) -> dict:
    out = {
        "url_template": fallback_url or "",
        "headers": dict(_DEFAULT_HEADERS),
        "parser": "html",
        "selectors_or_jsonpath": [],
        "alt_endpoints": [],
        "notes": "",
    }
    if not isinstance(raw, dict):
        return out
    if isinstance(raw.get("url_template"), str) and raw["url_template"].strip():
        out["url_template"] = raw["url_template"].strip()[:1_000]
    hdrs = raw.get("headers")
    if isinstance(hdrs, dict):
        clean: dict[str, str] = {}
        for k, v in hdrs.items():
            if not isinstance(k, str) or not isinstance(v, str):
                continue
            k = k.strip()[:80]
            v = v.strip()[:400]
            if k and v:
                clean[k] = v
            if len(clean) >= 12:
                break
        # Always retain a sane UA + accept-language if the LLM omitted them.
        for k, v in _DEFAULT_HEADERS.items():
            clean.setdefault(k, v)
        out["headers"] = clean
    parser = raw.get("parser")
    if isinstance(parser, str) and parser.lower() in ("html", "json", "jsonld", "oembed", "rss"):
        out["parser"] = parser.lower()
    sel = raw.get("selectors_or_jsonpath")
    if isinstance(sel, list):
        out["selectors_or_jsonpath"] = [
            str(s).strip()[:240] for s in sel if str(s).strip()
        ][:12]
    alt = raw.get("alt_endpoints")
    if isinstance(alt, list):
        out["alt_endpoints"] = [
            str(a).strip()[:1_000] for a in alt if str(a).strip()
        ][:6]
    notes = raw.get("notes")
    if isinstance(notes, str):
        out["notes"] = notes.strip()[:600]
    return out


def default_strategy(url: str) -> dict:
    """The conservative fallback used when no LLM is available or every
    LLM attempt fails. Plain GET with a sensible UA, parse as HTML."""
    return {
        "url_template": url or "",
        "headers": dict(_DEFAULT_HEADERS),
        "parser": "html",
        "selectors_or_jsonpath": [
            "meta[property='og:description']",
            "meta[property='og:image']",
            "meta[name='description']",
            "title",
            "script[type='application/ld+json']",
        ],
        "alt_endpoints": [],
        "notes": "Fallback strategy: no LLM, plain HTML scrape.",
    }


def propose_strategy(
    url: str,
    *,
    platform_intent: str = "",
    sample: Optional[dict] = None,
) -> dict:
    """Ask the LLM for a scraping strategy. Returns a normalised dict;
    never raises. Falls back to ``default_strategy(url)`` if the LLM
    isn't reachable.
    """
    if not url:
        return default_strategy("")
    try:
        from mediahub.media_ai.llm import generate_json, is_available
    except Exception:
        return default_strategy(url)
    if not is_available():
        return default_strategy(url)
    prompt = _build_prompt(url, platform_intent or "(generic web page)", sample)
    try:
        raw = generate_json(prompt, system=_LLM_SYSTEM, max_tokens=900, fallback={})
    except Exception as e:
        log.debug("strategy LLM call failed: %s", e)
        return default_strategy(url)
    return _normalise(raw, fallback_url=url)


__all__ = ["propose_strategy", "default_strategy"]
