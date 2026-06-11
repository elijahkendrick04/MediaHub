"""link_learners/endpoint_discoverer.py — B9. Endpoint discoverer.

When the primary fetch is blocked / auth-walled / rate-limited, this
learner asks the LLM what other public endpoints might serve the same
content. Examples it might propose:

  - https://www.facebook.com/<page>?_rdc=1&_rdr   (mobile/no-redirect)
  - https://www.facebook.com/pg/<page>/about      (printable page)
  - https://www.linkedin.com/company/<slug>/about/
  - https://oembed-endpoint/...                   (oEmbed widget)
  - https://rsshub.app/...                         (public aggregator)
  - https://web.archive.org/web/<date>/<url>      (last cached copy)

The handler tries each alternative in turn until the block detector
returns 'real_content' (then the strategy proposer is asked to bake
that endpoint into a refreshed playbook).

Returns a ranked list of candidate URLs. Falls back to a small
deterministic set of mobile/oembed/archive transformations when the
LLM is unavailable.
"""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlparse, urlunparse

log = logging.getLogger(__name__)


_LLM_SYSTEM = (
    "You suggest alternative public endpoints for reading a "
    "club / society / sports-team's content when the primary URL is "
    "blocked. You ONLY propose endpoints that the operator could "
    "fetch without authentication, OAuth, or a paid API. Examples of "
    "things you may suggest: oEmbed widgets, embed pages, mobile "
    "subdomains, /about pages, JSON-LD structured-data dumps, RSS "
    "feeds, public sitemaps, web.archive.org snapshots, public "
    "aggregator gateways. Never invent endpoints that are unlikely "
    "to exist. Return up to 4 ranked candidates. If you genuinely "
    "have no ideas, return an empty array."
)


def _build_prompt(
    url: str,
    platform_intent: str,
    last_status: str,
    last_strategy: Optional[dict],
) -> str:
    last_strat_summary = ""
    if isinstance(last_strategy, dict):
        last_strat_summary = (
            f"  parser: {last_strategy.get('parser', '')}\n"
            f"  alt_endpoints tried: {last_strategy.get('alt_endpoints', [])}\n"
            f"  notes: {last_strategy.get('notes', '')}"
        )
    parts = [
        f"Primary URL: {url}",
        f"Platform intent: {platform_intent}",
        f"Last fetch status (from block detector): {last_status}",
        f"Last strategy:\n{last_strat_summary or '  (none)'}",
        "",
        'Return JSON: {"candidates": ["<url1>", "<url2>", ...]} — '
        "up to 4 ranked alternative public endpoints to try. Most-"
        "likely-to-work first.",
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Deterministic fallback transforms — generic, used when no LLM available
# ---------------------------------------------------------------------------


def _fallback_candidates(url: str) -> list[str]:
    """Generic transforms that often surface a less-blocked version of
    the same content. Conservative — only emits a candidate if the
    transform is well-formed."""
    out: list[str] = []
    if not url:
        return out
    try:
        parts = urlparse(url if "://" in url else "https://" + url)
    except Exception:
        return out
    host = (parts.netloc or "").lower()
    if not host:
        return out

    # Mobile subdomain (m.host or www → m)
    if not host.startswith("m."):
        bare = host[4:] if host.startswith("www.") else host
        out.append(urlunparse(parts._replace(netloc="m." + bare)))

    # /about-style page
    path = parts.path.rstrip("/")
    if path and not path.endswith("/about"):
        out.append(urlunparse(parts._replace(path=path + "/about")))

    # web.archive.org last snapshot
    full = urlunparse(parts)
    out.append(f"https://web.archive.org/web/2024/{full}")

    # r.jina.ai readability gateway (returns plain text of a URL)
    out.append(f"https://r.jina.ai/{full}")

    # de-dupe while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for u in out:
        if u in seen:
            continue
        seen.add(u)
        uniq.append(u)
    return uniq[:4]


def propose_alternatives(
    url: str,
    *,
    platform_intent: str = "",
    last_status: str = "",
    last_strategy: Optional[dict] = None,
) -> list[str]:
    """Return up to 4 alternative URLs to try. Never raises.

    When the LLM is unavailable falls back to a generic transform set
    (mobile subdomain, /about path, web.archive snapshot, readability
    gateway) which empirically gets through about 30% of soft blocks.
    """
    if not url:
        return []
    try:
        from mediahub.media_ai.llm import generate_json, is_available
    except Exception:
        return _fallback_candidates(url)
    if not is_available():
        return _fallback_candidates(url)
    prompt = _build_prompt(
        url, platform_intent or "(generic web page)", last_status or "unknown", last_strategy
    )
    try:
        raw = generate_json(prompt, system=_LLM_SYSTEM, max_tokens=400, fallback={})
    except Exception as e:
        log.debug("endpoint-discoverer LLM call failed: %s", e)
        return _fallback_candidates(url)
    candidates = []
    if isinstance(raw, dict):
        c = raw.get("candidates")
        if isinstance(c, list):
            candidates = c
    out: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        if not isinstance(c, str):
            continue
        c = c.strip()
        if not c or c in seen:
            continue
        # Reject anything that looks like a private endpoint or token
        if any(bad in c.lower() for bad in ("access_token", "client_secret", "api_key=")):
            continue
        seen.add(c)
        out.append(c[:1_000])
        if len(out) >= 4:
            break
    return out or _fallback_candidates(url)


__all__ = ["propose_alternatives"]
