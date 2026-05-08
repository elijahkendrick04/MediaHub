"""
context_engine/trust.py — Per-domain trust ledger.

The ledger is stored as append-only JSONL at data/discovered_sources.jsonl.
Domains are scored using Laplace-smoothed success rate:
    score = (successes + 1) / (attempts + 2)

The ledger starts empty; the engine populates it as it processes pages.
No domains are hardcoded — trust is earned through empirical parse success.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional


def _ledger_path() -> Path:
    here = Path(__file__).resolve().parent.parent
    p = here / "data" / "discovered_sources.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_ledger() -> dict[str, dict]:
    """Load domain records from the JSONL ledger. Returns {domain: record}."""
    ledger: dict[str, dict] = {}
    p = _ledger_path()
    if not p.exists():
        return ledger
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                domain = record.get("domain", "")
                if domain:
                    ledger[domain] = record
            except json.JSONDecodeError:
                continue
    except Exception:
        pass
    return ledger


def _save_record(record: dict) -> None:
    """Append or update a domain record in the ledger."""
    p = _ledger_path()
    # Read existing lines, update or append
    lines: list[str] = []
    domain = record["domain"]
    updated = False
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                existing = json.loads(line)
                if existing.get("domain") == domain:
                    lines.append(json.dumps(record))
                    updated = True
                else:
                    lines.append(line)
            except json.JSONDecodeError:
                lines.append(line)
    if not updated:
        lines.append(json.dumps(record))
    try:
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass


def score_domain(domain: str) -> float:
    """
    Return Laplace-smoothed trust score for a domain.
    score = (parse_successes + 1) / (parse_attempts + 2)

    New / unknown domains score 0.5 (neutral prior).
    """
    ledger = _load_ledger()
    record = ledger.get(domain)
    if record is None:
        return 0.5  # neutral prior for unknown domains
    attempts = record.get("parse_attempts", 0)
    successes = record.get("parse_successes", 0)
    return (successes + 1) / (attempts + 2)


def rank_candidates(urls: list[str]) -> list[str]:
    """
    Order URLs by domain trust score (descending), then by position (stable).

    Higher-trust domains float to the top so the engine tries them first.
    """
    def _key(url: str) -> float:
        domain = _domain_from_url(url)
        return -score_domain(domain)  # negative so sort ascending = highest first

    # Python's sort is stable by definition, so no extra argument needed
    return sorted(urls, key=_key)


def record_attempt(domain: str, success: bool, purpose: str = "") -> None:
    """
    Record a parse attempt against a domain.

    Called after trying to extract structured data from a page.
    Updates parse_attempts / parse_successes in the trust ledger.
    """
    ledger = _load_ledger()
    record = ledger.get(domain, {
        "domain": domain,
        "first_seen": _now(),
        "last_used": _now(),
        "parse_attempts": 0,
        "parse_successes": 0,
        "domains_observed_for": [],
    })
    record["parse_attempts"] = record.get("parse_attempts", 0) + 1
    if success:
        record["parse_successes"] = record.get("parse_successes", 0) + 1
    record["last_used"] = _now()
    observed = record.get("domains_observed_for", [])
    if purpose and purpose not in observed:
        observed.append(purpose)
    record["domains_observed_for"] = observed
    _save_record(record)


def _domain_from_url(url: str) -> str:
    import re
    try:
        s = re.sub(r'^https?://', '', url)
        s = s.split('/')[0].split('?')[0].split('#')[0].split(':')[0]
        return s.lower()
    except Exception:
        return url


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
