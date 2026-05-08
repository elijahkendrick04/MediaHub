"""
Qualification standards updater (auto-search + confirm).

When the registry is stale, this module proposes refreshed sources for human
confirmation. We do NOT auto-mutate the registry. The flow is:

  1. registry has 'stale' standards (older than FRESHNESS_DAYS)
  2. updater runs `pplx search web` for canonical PDFs of those standards
  3. updater returns a list of proposed updates [{standard_id, candidate_url, title, snippet, retrieved_at}]
  4. The Flask UI shows these to the user as a confirmation panel.
  5. On confirm, we record the new source_url + retrieved_at against the standard;
     manually editing the times themselves remains a deliberate user action.

This is intentionally small: the value is in surfacing freshness checks and
prompting human review, not in autonomously rewriting standards.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .quals_registry import Standard, DEFAULT_REGISTRY_PATH, load_registry, stale_standards


@dataclass
class UpdateProposal:
    standard_id: str
    competition: str
    season: str
    candidate_url: str
    candidate_title: str
    candidate_snippet: str
    retrieved_at: str


# Search hints per standard family. Keep these short and keyword-driven.
_SEARCH_HINTS = {
    "BUCS_LC":      "BUCS Long Course Championships entry times qualifying consideration",
    "BUCS_SC":      "BUCS Short Course Championships entry times qualifying consideration",
    "AGB_CHAMPS":   "Aquatics GB Swimming Championships consideration times",
    "SE_SUMMER":    "Swim England National Summer Meet consideration times",
    "SE_WINTER":    "Swim England Winter Nationals qualifying times",
    "SW_NATIONAL":  "Swim Wales National Championships qualifying times",
    "WELSH_CHAMPS": "Welsh Championships swimming qualifying times",
}


def _hint_for(standard_id: str) -> str:
    for key, hint in _SEARCH_HINTS.items():
        if standard_id.upper().startswith(key):
            return hint
    return ""


def _run_pplx_search(query: str, *, timeout_sec: int = 30) -> list[dict]:
    """Run `pplx search web` and return the parsed hits list. Empty on any failure."""
    pplx = shutil.which("pplx")
    if not pplx:
        return []
    try:
        proc = subprocess.run(
            [pplx, "search", "web", query],
            capture_output=True, text=True, timeout=timeout_sec,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return []
        data = json.loads(proc.stdout)
        return data.get("hits", []) or []
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return []


def propose_updates(
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    only_stale: bool = True,
) -> list[UpdateProposal]:
    """For each (stale) standard, search for a candidate refreshed source URL."""
    standards = load_registry(registry_path)
    targets = stale_standards(standards) if only_stale else standards
    proposals: list[UpdateProposal] = []
    now = datetime.now(timezone.utc).isoformat()
    for s in targets:
        hint = _hint_for(s.standard_id)
        if not hint:
            continue
        query = f"{hint} {s.season} PDF"
        hits = _run_pplx_search(query)
        if not hits:
            continue
        # Prefer PDFs from the canonical body's domain
        best = None
        for h in hits[:8]:
            url = h.get("url", "")
            domain = h.get("domain", "")
            if url.lower().endswith(".pdf"):
                best = h
                # Prefer same body/domain when possible
                if any(tok in domain for tok in ["bucs.org", "aquaticsgb", "swimming.org",
                                                 "swimwales", "britishswimming"]):
                    break
        if best is None:
            best = hits[0]
        proposals.append(UpdateProposal(
            standard_id=s.standard_id,
            competition=s.competition,
            season=s.season,
            candidate_url=best.get("url", ""),
            candidate_title=best.get("title", "")[:200],
            candidate_snippet=(best.get("summary") or "")[:400],
            retrieved_at=now,
        ))
    return proposals


def apply_source_refresh(
    proposals: list[UpdateProposal],
    accepted_ids: list[str],
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> int:
    """
    Update only the source_url + retrieved_at on accepted proposals.

    Times remain frozen — the user must manually edit them if values changed.
    Returns the count of standards updated.
    """
    if not accepted_ids:
        return 0
    data = json.loads(Path(registry_path).read_text())
    accepted_set = set(accepted_ids)
    by_id = {p.standard_id: p for p in proposals}
    n = 0
    for s in data.get("standards", []):
        if s.get("id") in accepted_set and s["id"] in by_id:
            p = by_id[s["id"]]
            s["source_url"] = p.candidate_url
            s["retrieved_at"] = p.retrieved_at
            n += 1
    Path(registry_path).write_text(json.dumps(data, indent=2))
    return n
