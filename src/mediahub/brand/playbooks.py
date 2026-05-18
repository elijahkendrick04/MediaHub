"""brand/playbooks.py — Persistent learned scraping strategies (B11).

The user's directive: the AI should learn how to read each site (website,
Instagram, Facebook, etc.), remember what worked, and never forget. When
the site changes its bot defences or markup, the system should adapt
rather than silently degrade.

This module owns the persistent memory side of that pipeline. The
LLM-driven adaptation lives in ``link_learners/``; this module just
loads, saves, validates, and replays.

A playbook is one JSON file per host name under
``{DATA_DIR}/scraping_playbooks/<domain>.json``. Schema:

    {
      "domain": "instagram.com",
      "strategy": {
        "url_template": "https://www.instagram.com/{handle}/",
        "headers": {"User-Agent": "...", "Accept-Language": "..."},
        "parser": "html",                              # html|json|jsonld|oembed|rss
        "selectors_or_jsonpath": [".bio", "meta[name=description]"],
        "alt_endpoints": ["https://www.instagram.com/{handle}/embed/"],
        "notes": "Bio is in og:description; recent posts are blocked."
      },
      "success_count": 12,
      "fail_count": 1,
      "last_validated_at": "2026-05-17T10:30:00+00:00",
      "history": [
        {"ts": "...", "status": "real_content", "notes": "..."},
        ...
      ]
    }

The companion audit log at ``{DATA_DIR}/scraping_playbooks/audit.jsonl``
records every regeneration so an operator can answer "why did this
playbook change last Tuesday?" without spelunking through git.

This file never imports from link_handlers / link_learners — they
depend on it, not the other way round.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# How long a playbook is considered fresh before it must be re-validated
# against the live site. 7 days is a balance: long enough that the LLM
# isn't invoked on every form submission, short enough that a real
# Instagram markup change is caught within a week.
DEFAULT_MAX_AGE = timedelta(days=7)

# How much history to keep on the playbook. Older entries are pruned on
# every save so the file doesn't grow unbounded.
_MAX_HISTORY = 25


# ---------------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------------

def _root() -> Path:
    """Resolve the on-disk playbook directory. Honours DATA_DIR for
    parity with ClubProfile / brand-DNA caches; falls back to a
    source-relative dir for tests."""
    base = os.environ.get("DATA_DIR")
    if base:
        d = Path(base) / "scraping_playbooks"
    else:
        d = Path(__file__).resolve().parents[1] / "data" / "scraping_playbooks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def audit_log_path() -> Path:
    return _root() / "audit.jsonl"


def _path_for(domain: str) -> Path:
    safe = re.sub(r"[^a-z0-9._-]+", "_", domain.lower().strip())
    if not safe:
        safe = "_empty"
    return _root() / f"{safe}.json"


# ---------------------------------------------------------------------------
# Domain extraction
# ---------------------------------------------------------------------------

def domain_for(url: str) -> str:
    """Return the canonical host for a URL.

    Strips a leading "www." but preserves everything else. Returns
    empty string if the input isn't a parseable URL with a netloc.
    """
    if not url:
        return ""
    u = url.strip()
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    try:
        host = urlparse(u).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def empty_playbook(domain: str) -> dict:
    """A fresh, zero-history record for a new domain."""
    return {
        "domain": domain,
        "strategy": {},
        "success_count": 0,
        "fail_count": 0,
        "last_validated_at": "",
        "history": [],
    }


def load(domain: str) -> Optional[dict]:
    if not domain:
        return None
    p = _path_for(domain)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log.debug("playbook load failed for %s: %s", domain, e)
        return None
    if not isinstance(data, dict):
        return None
    # Defensive: missing keys default in.
    data.setdefault("domain", domain)
    data.setdefault("strategy", {})
    data.setdefault("success_count", 0)
    data.setdefault("fail_count", 0)
    data.setdefault("last_validated_at", "")
    data.setdefault("history", [])
    return data


def save(playbook: dict) -> Path:
    domain = (playbook.get("domain") or "").strip()
    if not domain:
        raise ValueError("playbook missing 'domain'")
    # Prune history
    hist = playbook.get("history") or []
    if isinstance(hist, list) and len(hist) > _MAX_HISTORY:
        playbook["history"] = hist[-_MAX_HISTORY:]
    p = _path_for(domain)
    p.write_text(json.dumps(playbook, indent=2, ensure_ascii=False),
                  encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Drift detection — continuous self-updating playbooks
# ---------------------------------------------------------------------------

def _parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def is_stale(playbook: dict, max_age: timedelta = DEFAULT_MAX_AGE) -> bool:
    """Return True when the playbook needs re-validation.

    Stale conditions:
      - no strategy ever recorded
      - last_validated_at older than ``max_age``
      - last_validated_at unparseable / missing
    """
    if not playbook:
        return True
    if not playbook.get("strategy"):
        return True
    last = _parse_iso(playbook.get("last_validated_at", ""))
    if last is None:
        return True
    age = datetime.now(timezone.utc) - last
    return age >= max_age


def needs_regeneration(playbook: dict, recent_failure_threshold: int = 3) -> bool:
    """Return True when the playbook's recent history suggests the
    current strategy has stopped working — e.g., the last 3 attempts
    all blocked/auth-walled. Independent of age-based staleness.
    """
    hist = playbook.get("history") or []
    if len(hist) < recent_failure_threshold:
        return False
    recent = hist[-recent_failure_threshold:]
    bad = {"hard_blocked", "auth_walled", "rate_limited",
           "fetch_failed", "unknown", "soft_blocked_spa"}
    return all(e.get("status") in bad for e in recent if isinstance(e, dict))


# ---------------------------------------------------------------------------
# Attempt recording — observable history for explainability + audit
# ---------------------------------------------------------------------------

def record_attempt(
    playbook: dict,
    *,
    status: str,
    notes: str = "",
    persist: bool = True,
) -> dict:
    """Append an attempt to the playbook's history and bump counters.

    The reason this returns the (possibly-mutated) playbook is so the
    caller can chain: ``pb = record_attempt(pb, status="real_content")``
    and keep working with the latest state.
    """
    if not isinstance(playbook, dict):
        return playbook
    hist = playbook.setdefault("history", [])
    hist.append({
        "ts": _now_iso(),
        "status": status,
        "notes": (notes or "")[:400],
    })
    bad = {"hard_blocked", "auth_walled", "rate_limited",
           "fetch_failed", "unknown"}
    if status in ("real_content", "ok"):
        playbook["success_count"] = int(playbook.get("success_count", 0)) + 1
        playbook["last_validated_at"] = _now_iso()
    elif status in bad:
        playbook["fail_count"] = int(playbook.get("fail_count", 0)) + 1
    if persist:
        try:
            save(playbook)
        except Exception as e:
            log.debug("playbook save failed: %s", e)
    return playbook


def record_audit(event: dict) -> None:
    """Append one event to the audit log. Best-effort; never raises.

    Events should carry: ``ts``, ``domain``, ``action`` (one of
    "load" / "regenerate" / "validate" / "stale_replay" / "fallback"),
    plus any free-form ``notes``.
    """
    event = dict(event or {})
    event.setdefault("ts", _now_iso())
    try:
        with audit_log_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug("audit log write failed: %s", e)


def audit_tail(limit: int = 50) -> list[dict]:
    """Return the last ``limit`` audit events. Read-only convenience for
    the audit-and-fix passes (E1, E5, E8) and any future health-check UI.
    """
    p = audit_log_path()
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out: list[dict] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# Convenience: list all known playbooks (for the audit UI / debug)
# ---------------------------------------------------------------------------

def list_all() -> list[dict]:
    out: list[dict] = []
    for f in sorted(_root().glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


__all__ = [
    "DEFAULT_MAX_AGE",
    "domain_for",
    "empty_playbook",
    "load",
    "save",
    "is_stale",
    "needs_regeneration",
    "record_attempt",
    "record_audit",
    "audit_tail",
    "audit_log_path",
    "list_all",
]
