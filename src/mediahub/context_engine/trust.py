"""
context_engine/trust.py — Per-domain trust ledger.

The ledger is stored as append-only JSONL under the writable DATA_DIR tree at
discovered/discovered_sources.jsonl (see ``_ledger_path``).
Domains are scored using Laplace-smoothed success rate:
    score = (successes + 1) / (attempts + 2)

The ledger starts empty; the engine populates it as it processes pages.
No domains are hardcoded — trust is earned through empirical parse success.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path


# Serialises the ledger's read-modify-write so concurrent PB lookups (the
# pipeline now fans swimmers out across a thread pool) can't lose updates or
# read a half-written file. Intra-process only; cross-process safety rests on
# the atomic os.replace in _save_record.
_LEDGER_LOCK = threading.Lock()


def _ledger_path() -> Path:
    """Append-only trust ledger, stored beside the discovered-source caches
    under the writable ``DATA_DIR/discovered`` tree — never the read-only
    package source. On the hosted deployment DATA_DIR is the mounted disk, so
    this resolves to a writable path instead of ``/app/src/mediahub/data``
    (read-only), where the eager mkdir here used to raise PermissionError and
    abort every PB lookup.

    The directory is created best-effort by ``_save_record`` at write time, not
    here, so on a read-only disk a read simply finds no file (empty ledger) and
    a write fails soft — PB ranking degrades to the neutral prior rather than
    crashing the recognition run."""
    from mediahub.context_engine.cache import _data_root

    return _data_root() / "discovered" / "discovered_sources.jsonl"


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
    # Write to a sibling temp file then atomically rename, so a concurrent
    # reader (score_domain / rank_candidates) always sees a complete ledger,
    # never a truncated mid-write one.
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.tmp.{os.getpid()}.{threading.get_ident()}")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
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
    with _LEDGER_LOCK:
        ledger = _load_ledger()
        record = ledger.get(
            domain,
            {
                "domain": domain,
                "first_seen": _now(),
                "last_used": _now(),
                "parse_attempts": 0,
                "parse_successes": 0,
                "domains_observed_for": [],
            },
        )
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
        s = re.sub(r"^https?://", "", url)
        s = s.split("/")[0].split("?")[0].split("#")[0].split(":")[0]
        return s.lower()
    except Exception:
        return url


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
