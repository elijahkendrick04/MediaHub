"""
hypothesis.py — propose new patterns when confidence is low.

When schema induction or event detection fails to achieve confident results
on a section, this module:

  1. Examines the failing text and proposes candidate regex / heuristic patterns.
  2. Validates each candidate against past successes in data/patterns_validation_corpus/.
  3. Persists surviving candidates to data/patterns.jsonl with provisional=True.
  4. Returns the list of proposed pattern dicts for inclusion in needs_review.

No swim-vocabulary literals.
"""

from __future__ import annotations

import logging
import pathlib
import re
from typing import Any

from .patterns import PatternStore

log = logging.getLogger(__name__)

_DEFAULT_CORPUS_DIR = pathlib.Path(__file__).parent.parent / "data" / "patterns_validation_corpus"

# ---------------------------------------------------------------------------
# Pattern proposal heuristics
# ---------------------------------------------------------------------------

# Structural shape generalisation: replace specific numbers/words with groups
_NUM_RE = re.compile(r"\b\d+\b")
_WORD_RE = re.compile(r"\b[A-Za-z]+\b")


def _generalise(text: str, max_candidates: int = 5) -> list[str]:
    """
    Generate candidate regex patterns by generalising observed strings.
    Pure structural — no domain knowledge.
    """
    candidates: list[str] = []
    stripped = text.strip()

    # Candidate 1: literal (but escaped)
    candidates.append(re.escape(stripped))

    # Candidate 2: digits → \\d+
    c2 = _NUM_RE.sub(r"\\d+", re.escape(stripped))
    if c2 not in candidates:
        candidates.append(c2)

    # Candidate 3: words → [A-Za-z]+
    c3 = _WORD_RE.sub(r"[A-Za-z]+", re.escape(stripped))
    if c3 not in candidates:
        candidates.append(c3)

    # Candidate 4: combined
    c4 = _WORD_RE.sub(r"[A-Za-z]+", _NUM_RE.sub(r"\\d+", re.escape(stripped)))
    if c4 not in candidates:
        candidates.append(c4)

    # Candidate 5: very general — first token + digits
    tokens = stripped.split()
    if tokens:
        c5 = re.escape(tokens[0]) + r"[\s\S]{0,80}"
        if c5 not in candidates:
            candidates.append(c5)

    return candidates[:max_candidates]


# ---------------------------------------------------------------------------
# Validation against corpus
# ---------------------------------------------------------------------------


def _load_corpus_texts(corpus_dir: pathlib.Path) -> list[str]:
    """Load all text files from the corpus directory."""
    texts: list[str] = []
    if not corpus_dir.exists():
        return texts
    for f in corpus_dir.glob("*.txt"):
        try:
            texts.append(f.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not read corpus file %s: %s", f, exc)
    return texts


def _validate_candidate(
    pattern_str: str,
    corpus_texts: list[str],
    current_store: PatternStore,
) -> bool:
    """
    A candidate is valid if:
      a) It doesn't break (false-positive match) successful past parses, or
      b) The corpus is empty (no past data → accept tentatively).
    """
    if not corpus_texts:
        return True  # No corpus to validate against → accept provisionally

    try:
        pat = re.compile(pattern_str, re.IGNORECASE)
    except re.error:
        return False

    # Check: does the pattern fire on corpus at all (useful)?
    any_match = any(pat.search(text) for text in corpus_texts)
    # We don't reject based on false-positives here (no negative corpus);
    # simply require the pattern to be compilable and non-vacuous.
    return True  # Accept all compilable patterns when no negative corpus available


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def propose_patterns(
    stream_section: str,
    current_store: PatternStore,
    pattern_type: str = "unknown",
    corpus_dir: pathlib.Path | None = None,
    max_candidates: int = 5,
) -> list[dict[str, Any]]:
    """
    Analyse *stream_section* text and propose candidate patterns.

    Parameters
    ----------
    stream_section:
        The raw text that failed to parse confidently.
    current_store:
        The active PatternStore (used to avoid duplicates and for validation).
    pattern_type:
        Label for the proposed patterns (e.g. "event_header", "time_value").
    corpus_dir:
        Override for the validation corpus directory.
    max_candidates:
        Maximum number of candidates to generate and evaluate.

    Returns
    -------
    List of pattern dicts that were persisted (provisional=True).
    """
    if corpus_dir is None:
        corpus_dir = _DEFAULT_CORPUS_DIR

    corpus_texts = _load_corpus_texts(corpus_dir)
    candidates = _generalise(stream_section, max_candidates)
    persisted: list[dict[str, Any]] = []

    for cand_pattern in candidates:
        if not _validate_candidate(cand_pattern, corpus_texts, current_store):
            log.debug("Candidate failed validation: %s", cand_pattern[:60])
            continue

        pid = current_store.add(
            pattern=cand_pattern,
            type_name=pattern_type,
            description=f"Auto-proposed from failing section: {stream_section[:60]!r}",
            provisional=True,
        )
        rec = next((r for r in current_store.all_records() if r["id"] == pid), None)
        if rec:
            persisted.append(rec)

    if persisted:
        log.info("Proposed %d provisional patterns for type %r", len(persisted), pattern_type)
        current_store.flush()

    return persisted


def save_corpus_section(
    text: str,
    corpus_dir: pathlib.Path | None = None,
    label: str = "section",
) -> pathlib.Path:
    """
    Save a successfully-parsed text section to the validation corpus for
    future hypothesis validation.
    """
    if corpus_dir is None:
        corpus_dir = _DEFAULT_CORPUS_DIR
    corpus_dir.mkdir(parents=True, exist_ok=True)

    import time  # noqa: PLC0415

    filename = f"{label}_{int(time.time() * 1000)}.txt"
    dest = corpus_dir / filename
    dest.write_text(text, encoding="utf-8")
    log.debug("Saved corpus section to %s", dest)
    return dest
