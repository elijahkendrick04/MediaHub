"""
visual/pronunciation.py — deterministic pronunciation overrides for voiceover.

Swimmer names are the part a text-to-speech engine most often gets wrong, and a
club's video that mispronounces its own swimmer's name reads as "they don't know
their members" — the exact trust failure MediaHub exists to avoid. Fixing that is
a *data* problem, not a judgement problem, so it stays deterministic: the operator
supplies a plain map of word -> phonetic respelling, and we substitute it into the
caption text **before** synthesis. No AI guesses a pronunciation.

The map lives in an optional JSON file under DATA_DIR (`pronunciations.json`), with
an optional per-run override file (`runs_v4/<run_id>__pronunciations.json`). Both are
plain `{ "written": "spoken" }` dicts. Absent files mean "no overrides" — never an
error, never a fabricated guess.

Substitution rules (deliberately boring and predictable):
  - whole-word only (word boundaries), so "Lee" never rewrites "Leeds";
  - case-insensitive match, but the replacement is emitted verbatim;
  - longest key first, so a multi-word key ("Mary Anne") wins over its parts;
  - the original text is otherwise passed through unchanged (verbatim guarantee).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


def _data_dir() -> Path:
    """DATA_DIR root, mirroring visual/motion.py's resolution."""
    env = os.environ.get("DATA_DIR")
    if env:
        return Path(env)
    # src/mediahub/visual/pronunciation.py -> repo `src` root fallback.
    return Path(__file__).resolve().parents[2]


def _runs_dir() -> Path:
    env = os.environ.get("RUNS_DIR")
    if env:
        return Path(env)
    return _data_dir() / "runs_v4"


def _read_map(path: Path) -> dict[str, str]:
    """Read a `{written: spoken}` JSON map, tolerating absence/corruption.

    A missing file is the normal case (most clubs need no overrides) and returns
    an empty map. A malformed file is also treated as "no overrides" rather than
    raising — a broken pronunciation hint must never block the voiceover.
    """
    try:
        if not path.exists():
            return {}
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip():
            out[k] = v
    return out


def load_overrides(run_id: str | None = None) -> dict[str, str]:
    """Merge the global pronunciation map with an optional per-run map.

    Per-run entries win over global ones. Returns `{}` when nothing is configured.
    """
    merged = _read_map(_data_dir() / "pronunciations.json")
    if run_id:
        merged.update(_read_map(_runs_dir() / f"{run_id}__pronunciations.json"))
    return merged


def apply_overrides(text: str, overrides: dict[str, str]) -> str:
    """Substitute pronunciation overrides into `text`, whole-word & case-insensitive.

    Deterministic and done in a **single pass**: all keys are compiled into one
    alternation, longest-first, so a multi-word key ("Mary Anne") wins over its
    parts and — crucially — a replacement is never re-scanned by a shorter rule
    (otherwise "Mary Anne"→"Mary-Ann" could then be mangled by a "Mary" rule).
    Each key matches on word boundaries so we never rewrite a substring of a
    larger word. With an empty map the text is returned unchanged.
    """
    if not text or not overrides:
        return text
    # Longest first so the alternation prefers multi-word / longer keys.
    keys = sorted(overrides, key=len, reverse=True)
    lookup = {k.lower(): v for k, v in overrides.items()}
    pattern = re.compile(
        r"\b(?:" + "|".join(re.escape(k) for k in keys) + r")\b",
        re.IGNORECASE,
    )
    return pattern.sub(lambda m: lookup.get(m.group(0).lower(), m.group(0)), text)


def pronounce(text: str, run_id: str | None = None) -> str:
    """Convenience: load the configured overrides for a run and apply them."""
    return apply_overrides(text, load_overrides(run_id))
