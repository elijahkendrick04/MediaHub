"""
context_engine/ontology.py — Load and extend ontology data from research.

Ontology files live under data/ontology/*.json.
Each file is a dict mapping canonical term -> list of aliases.

note_new_term() appends a newly-discovered alias to the appropriate category file.
This allows the engine to grow its vocabulary from live documents.

No aliases are hardcoded here — they come from data files and live research.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def _ontology_root() -> Path:
    here = Path(__file__).resolve().parent.parent
    root = here / "data" / "ontology"
    root.mkdir(parents=True, exist_ok=True)
    return root


def load_ontology(category: str) -> dict[str, list[str]]:
    """
    Load an ontology category from data/ontology/<category>.json.

    Returns dict mapping canonical term -> list of aliases.
    Returns empty dict if the file does not exist.
    """
    p = _ontology_root() / f"{category}.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def note_new_term(category: str, term: str, source: str, parent: str | None = None) -> None:
    """
    Record a newly-discovered term/alias in the ontology.

    If `parent` is given, the term is added as an alias of that canonical.
    Otherwise it is added as a new top-level entry with itself as its only alias.

    Thread-safe via module-level lock.
    """
    with _LOCK:
        p = _ontology_root() / f"{category}.json"
        data: dict[str, list[str]] = {}
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}

        if parent and parent in data:
            aliases = data[parent]
            if term not in aliases:
                aliases.append(term)
                data[parent] = aliases
        else:
            # Check if it's already an alias under another canonical
            for canonical, aliases in data.items():
                if term in aliases:
                    return  # already known
            # Add as new entry
            if term not in data:
                data[term] = [term]

        try:
            p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass


def lookup_canonical(category: str, raw_term: str) -> str | None:
    """
    Look up the canonical form of a raw term within a category.

    Returns the canonical string if found, else None.
    """
    data = load_ontology(category)
    raw_lower = raw_term.lower().strip()
    for canonical, aliases in data.items():
        for alias in aliases:
            if alias.lower() == raw_lower:
                return canonical
    return None
