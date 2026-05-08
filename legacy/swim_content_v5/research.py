"""
ResearchClient — source-grounded live web research for the V5 achievement layer.

Uses pplx CLI via subprocess. Falls back gracefully if unavailable.
Total research budget: 60 seconds wall-clock enforced via threading.Timer.

Cache: .cache/research/<hash>.json (disk-based, per-query).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from swim_content_v4.canonical import Meet


RESEARCH_TIMEOUT_SEC = 55   # per-query subprocess timeout
TOTAL_BUDGET_SEC = 60       # total research budget per pipeline run


def _hash_key(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResearchClient:
    """
    Wraps pplx CLI subprocess for web search with disk caching.

    All methods fail-safe: if pplx is unavailable, missing, or times out,
    they return {"ok": False, "error": ..., "sources": []} and never raise.
    """

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._budget_remaining = TOTAL_BUDGET_SEC
        self._budget_lock = threading.Lock()

    def _consume_budget(self, seconds: float) -> bool:
        """Attempt to consume budget. Returns False if budget exhausted."""
        with self._budget_lock:
            if self._budget_remaining <= 0:
                return False
            self._budget_remaining -= seconds
            return True

    def _cached_or_fetch(self, key: str, fetch_fn: Callable) -> dict:
        cache_path = self.cache_dir / f"{key}.json"
        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text())
            except Exception:
                pass

        if not self._consume_budget(RESEARCH_TIMEOUT_SEC):
            return {"ok": False, "error": "research budget exhausted", "sources": []}

        try:
            start = time.time()
            result = fetch_fn()
            elapsed = time.time() - start
            # Refund unused budget
            with self._budget_lock:
                self._budget_remaining += max(0, RESEARCH_TIMEOUT_SEC - elapsed)
            if result.get("ok", True) is not False:
                try:
                    cache_path.write_text(json.dumps(result))
                except Exception:
                    pass
            return result
        except Exception as e:
            return {"ok": False, "error": str(e), "sources": []}

    def _run_pplx_search(self, query: str) -> dict:
        """
        Run `pplx search web <query>` as a subprocess.
        Falls back to DuckDuckGo HTML search (V7.4) when pplx is unavailable.
        Returns parsed JSON or error dict.
        """
        # Try pplx first
        try:
            env = os.environ.copy()
            result = subprocess.run(
                ["pplx", "search", "web", query],
                capture_output=True,
                text=True,
                timeout=RESEARCH_TIMEOUT_SEC,
                env=env,
            )
            if result.returncode == 0:
                try:
                    data = json.loads(result.stdout)
                    sources = []
                    for hit in (data.get("hits") or [])[:5]:
                        sources.append({
                            "url": hit.get("url", ""),
                            "name": hit.get("title", hit.get("domain", "")),
                            "snippet": hit.get("snippet", hit.get("summary", ""))[:200],
                            "fetched_at": _now_iso(),
                            "source_backend": "pplx",
                        })
                    return {"ok": True, "sources": sources, "raw": data, "research_available": True}
                except json.JSONDecodeError:
                    pass
        except FileNotFoundError:
            pass
        except (subprocess.TimeoutExpired, Exception):
            pass

        # V7.4: Fallback to DuckDuckGo via WebResearcher
        try:
            from web_research.search import WebResearcher
            researcher = WebResearcher()
            hits = researcher.search(query, num=5)
            if hits:
                sources = []
                for h in hits:
                    sources.append({
                        "url": h.url,
                        "name": h.title,
                        "snippet": h.snippet[:200],
                        "fetched_at": _now_iso(),
                        "source_backend": "duckduckgo",
                    })
                return {"ok": True, "sources": sources, "research_available": True}
        except Exception as e:
            return {"ok": False, "error": f"DuckDuckGo fallback failed: {e}", "sources": [],
                    "research_available": False}

        return {"ok": False, "error": "No search backend available", "sources": [],
                "research_available": False}

    def search_meet_context(self, meet) -> dict:
        """
        Query: meet name + venue + year.
        Returns: {meet_level, has_finals, has_age_groups, governing_body,
                  qualifying_standards_url, sources: [...]}
        """
        name = getattr(meet, "name", "") or ""
        venue = getattr(meet, "venue", "") or ""
        year = ""
        if getattr(meet, "start_date", None):
            year = str(meet.start_date)[:4]

        query_parts = [p for p in [name, venue, year, "swim meet"] if p]
        query = " ".join(query_parts[:4])

        key = _hash_key(f"meet_ctx:{query}")

        def fetch():
            result = self._run_pplx_search(query)
            if not result.get("ok"):
                return result

            # Extract structured info from snippets
            sources = result.get("sources", [])
            combined_text = " ".join(
                s.get("snippet", "") for s in sources
            ).lower()

            meet_level = "open"
            if any(k in combined_text for k in ["national championship", "british swimming", "national record"]):
                meet_level = "national"
            elif any(k in combined_text for k in ["bucs", "university", "student"]):
                meet_level = "university"
            elif any(k in combined_text for k in ["county", "regional"]):
                meet_level = "county"

            has_finals = any(k in combined_text for k in ["a final", "b final", "finals"])
            governing_body = None
            if "swim england" in combined_text or "asa" in combined_text:
                governing_body = "Swim England"
            elif "swim wales" in combined_text:
                governing_body = "Swim Wales"
            elif "swim ireland" in combined_text:
                governing_body = "Swim Ireland"
            elif "scottish swimming" in combined_text:
                governing_body = "Scottish Swimming"

            return {
                "ok": True,
                "meet_level": meet_level,
                "has_finals": has_finals,
                "governing_body": governing_body,
                "research_available": True,
                "sources": [{"url": s["url"], "name": s["name"],
                              "used_for": "meet_context",
                              "fetched_at": s.get("fetched_at"),
                              "source_backend": s.get("source_backend", "unknown")}
                             for s in sources],
            }

        return self._cached_or_fetch(key, fetch)

    def search_swimmer_context(self, swimmer_name: str, club: str, asa_id: Optional[str] = None) -> dict:
        """
        Search for recent context about a swimmer.
        Returns: {recent_meets, ranking_context, sources: [...]}
        Only called for top-N swimmers after initial ranking.
        """
        parts = [swimmer_name, club, "swimmer", "swim"]
        if asa_id:
            parts.insert(0, asa_id)
        query = " ".join(parts[:4])
        key = _hash_key(f"swimmer_ctx:{swimmer_name}:{club}")

        def fetch():
            result = self._run_pplx_search(query)
            if not result.get("ok"):
                return result
            sources = result.get("sources", [])
            return {
                "ok": True,
                "swimmer_name": swimmer_name,
                "sources": [{"url": s["url"], "name": s["name"],
                              "used_for": "swimmer_context", "fetched_at": s.get("fetched_at")}
                             for s in sources],
            }

        return self._cached_or_fetch(key, fetch)


def build_research_client(data_dir: Optional[Path] = None) -> ResearchClient:
    """Factory function. data_dir defaults to project root .cache/research/."""
    if data_dir is None:
        # Find project root relative to this file
        here = Path(__file__).resolve()
        root = here.parents[1]
        data_dir = root / ".cache" / "research"
    return ResearchClient(cache_dir=data_dir)
