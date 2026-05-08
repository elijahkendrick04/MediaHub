"""
ontology_loader.py — reads data/ontology/*.json files.

No domain vocabulary literals.  This module simply locates and loads JSON
files from the ontology directory; the content (swim terms, column labels,
etc.) lives entirely in those JSON files.
"""
from __future__ import annotations

import json
import logging
import pathlib
import re
from typing import Any

log = logging.getLogger(__name__)

# Default ontology directory — callers can override via OntologyLoader(root=…)
# In the V9 layout this file lives at src/mediahub/interpreter/, so we go up
# three levels to reach <repo_root>/ and then into data/ontology/.
_DEFAULT_ONTOLOGY_ROOT = pathlib.Path(__file__).resolve().parents[3] / "data" / "ontology"
if not _DEFAULT_ONTOLOGY_ROOT.exists():
    # Fallback for legacy layouts where data/ sits next to the package.
    _DEFAULT_ONTOLOGY_ROOT = pathlib.Path(__file__).resolve().parent.parent / "data" / "ontology"


class OntologyLoader:
    """
    Loads and caches every *.json file in the ontology directory.

    Access via:
        loader["strokes"]          → dict from strokes.json
        loader.aliases("strokes")  → flat list of all alias strings
        loader.canonical_map("strokes") → {"alias": "canonical", ...}
    """

    def __init__(self, root: pathlib.Path | str | None = None) -> None:
        self._root = pathlib.Path(root) if root else _DEFAULT_ONTOLOGY_ROOT
        self._cache: dict[str, Any] = {}
        self._load_all()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_all(self) -> None:
        if not self._root.exists():
            log.warning("Ontology root not found: %s", self._root)
            return
        for json_file in sorted(self._root.glob("*.json")):
            key = json_file.stem
            try:
                with json_file.open(encoding="utf-8") as fh:
                    self._cache[key] = json.load(fh)
            except Exception as exc:  # noqa: BLE001
                log.error("Failed to load ontology file %s: %s", json_file, exc)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def __getitem__(self, name: str) -> Any:
        return self._cache.get(name, {})

    def keys(self) -> list[str]:
        return list(self._cache.keys())

    def aliases(self, name: str) -> list[str]:
        """Return flat list of every alias for every canonical term."""
        data = self._cache.get(name, {})
        if isinstance(data, dict):
            result: list[str] = []
            for aliases in data.values():
                if isinstance(aliases, list):
                    result.extend(aliases)
            return result
        return []

    def canonical_map(self, name: str) -> dict[str, str]:
        """
        Returns {alias_lower: canonical} for fast lookup.
        Works for dict-valued ontology files where values are lists of aliases.
        """
        data = self._cache.get(name, {})
        mapping: dict[str, str] = {}
        if isinstance(data, dict):
            for canonical, aliases in data.items():
                if isinstance(aliases, list):
                    for alias in aliases:
                        mapping[alias.lower()] = canonical
        return mapping

    def build_regex(self, name: str, flags: int = re.IGNORECASE) -> re.Pattern | None:
        """
        Builds a single alternation regex from all aliases in an ontology file.
        Returns None if the file is empty or not found.
        """
        all_aliases = self.aliases(name)
        if not all_aliases:
            return None
        # Sort longest-first to avoid prefix-matching issues
        sorted_aliases = sorted(all_aliases, key=len, reverse=True)
        escaped = [re.escape(a) for a in sorted_aliases]
        pattern = r"\b(?:" + "|".join(escaped) + r")\b"
        return re.compile(pattern, flags)

    def reload(self) -> None:
        """Force reload of all files (useful after engine updates them)."""
        self._cache.clear()
        self._load_all()
