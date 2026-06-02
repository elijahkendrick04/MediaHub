"""mediahub/web_research/verify.py — structural verification primitives.

Capability 3b. The council was emphatic: what reaches MediaHub's trust / PB
layer must be decided by DETERMINISTIC code, not the model's say-so. These are
those primitives.

MediaHub's V7.5 contract is equally emphatic — and takes precedence over the
council's "hardcode the authority domain" suggestion: trust/authority is LEARNED
at runtime (``context_engine.trust`` scores domains by empirical parse success)
and operator-configured, NEVER hardcoded. So an "authority" source here is one
the operator has explicitly declared (``MEDIAHUB_RESEARCH_AUTHORITY_DOMAINS``)
OR one that has EARNED a high trust score in the ledger. No domain is baked in
(``tests/test_no_hardcode_in_live_paths.py`` enforces this).

The deep-research engine uses these only to ANNOTATE a result (which of its
sources are authoritative); the actual gate — "only persist a finding backed by
an authority source" — lives where research is consumed (a later step). This is
the shared, testable building block for that gate.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

# A domain counts as authoritative once it has EARNED at least this trust score
# in the learned ledger (context_engine.trust). Nothing is hardcoded.
_LEARNED_TRUST_THRESHOLD = 0.8


def configured_domains() -> tuple[str, ...]:
    """Operator-declared authoritative domains (runtime config, not hardcoded)."""
    raw = os.environ.get("MEDIAHUB_RESEARCH_AUTHORITY_DOMAINS", "").strip()
    return tuple(d.strip().lower() for d in raw.split(",") if d.strip())


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _matches(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def _learned_score(host: str) -> float:
    """Empirical trust score for this host from the learned ledger (0.0 on any
    error or when the ledger is unavailable)."""
    try:
        from mediahub.context_engine import trust

        return float(trust.score_domain(host))
    except Exception:
        return 0.0


def is_authority_source(url: str, domains: tuple[str, ...] | None = None) -> bool:
    """True if ``url``'s host is operator-declared authoritative OR has earned a
    high trust score in the learned ledger. No domains are hardcoded."""
    host = _host(url)
    if not host:
        return False
    doms = domains if domains is not None else configured_domains()
    if doms and _matches(host, doms):
        return True
    return _learned_score(host) >= _LEARNED_TRUST_THRESHOLD


def authority_sources(urls, domains: tuple[str, ...] | None = None) -> list[str]:
    """Return the subset of ``urls`` on an authoritative domain."""
    return [u for u in (urls or []) if is_authority_source(u, domains)]


__all__ = ["is_authority_source", "authority_sources", "configured_domains"]
