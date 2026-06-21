"""video/filler.py — deterministic filler-word detection for tightening (1.6).

"Remove the ums and uhs" (Descript, Gling, TimeBolt) — done the MediaHub way: a
fixed lexicon matched against the ASR transcript's word stamps, **not** an AI
judgement. The ASR (the one ML dependency) gives word-timed text; *which* words
are fillers is then pure string-matching, and the cut is deterministic timeline
maths — so the same clip + transcript always yields the same cuts.

The split:

* **Lexicon match (pure).** :func:`find_filler_spans` turns word stamps into the
  spans to cut. Two registers: a **safe** set of non-lexical disfluencies
  (``um``/``uh``/``erm``…) that are almost never meaningful, and an **aggressive**
  set (``like``/``you know``/``I mean``…) that is opt-in because those words *can*
  carry meaning — exactly the precision/recall tradeoff the tools wrestle with.
* **Inversion reuses ``silence``.** Filler spans are regions to remove just like
  dead air, so the keep-plan is built by the same :func:`silence.plan_keep_segments`
  — one inverter for both, and silence + filler cuts compose cleanly.
* **Orchestration honest-errors.** :func:`detect_filler_spans` needs the ASR seam;
  with no transcriber it returns ``[]`` (nothing cut) rather than guessing.
"""

from __future__ import annotations

import re
from pathlib import Path

from mediahub.video.silence import Span

# Safe register: non-lexical disfluencies that are essentially always filler.
FILLER_WORDS = frozenset(
    {"um", "uh", "uhh", "umm", "erm", "er", "ah", "hmm", "mm", "mhm", "uhm", "eh"}
)
# Aggressive register: discourse markers that *can* be meaningful — opt-in only.
AGGRESSIVE_WORDS = frozenset({"like", "basically", "literally", "actually", "honestly"})
AGGRESSIVE_PHRASES: tuple[tuple[str, ...], ...] = (
    ("you", "know", "what", "i", "mean"),
    ("you", "know"),
    ("i", "mean"),
    ("sort", "of"),
    ("kind", "of"),
)


def _norm(token: str) -> str:
    """Lowercase a token and strip surrounding punctuation (keep inner apostrophes)."""
    return re.sub(r"^[^a-z']+|[^a-z']+$", "", (token or "").lower())


def find_filler_spans(words: list[tuple[str, int, int]], *, aggressive: bool = False) -> list[Span]:
    """Find the ``(start_ms, end_ms)`` spans of filler words/phrases. Pure.

    ``words`` is ``[(text, start_ms, end_ms), …]``. The safe register always
    applies; ``aggressive`` adds the discourse-marker words and the multi-word
    phrases (longest phrase wins, matched greedily left-to-right). Phrases are
    checked before single words so "you know what I mean" cuts as one span.
    """
    toks = [(_norm(t), a, b) for (t, a, b) in words]
    fillers = set(FILLER_WORDS) | (AGGRESSIVE_WORDS if aggressive else set())
    phrases = AGGRESSIVE_PHRASES if aggressive else ()
    spans: list[Span] = []
    i = 0
    n = len(toks)
    while i < n:
        matched = False
        for ph in phrases:
            k = len(ph)
            if i + k <= n and tuple(toks[i + j][0] for j in range(k)) == ph:
                spans.append((toks[i][1], toks[i + k - 1][2]))
                i += k
                matched = True
                break
        if matched:
            continue
        if toks[i][0] in fillers:
            spans.append((toks[i][1], toks[i][2]))
        i += 1
    return spans


def detect_filler_spans(
    source: Path | str,
    *,
    in_ms: int = 0,
    out_ms: int = 0,
    aggressive: bool = False,
    language: str = "",
) -> list[Span]:
    """Transcribe a clip (window) and return its filler spans. Honest ``[]``.

    Returns spans rebased to the window origin (so they compose with the silence
    plan over the same trimmed clip). Returns ``[]`` — never raises — when ASR is
    unavailable or the clip is silent, so filler-trim is an enhancement, never a
    render-blocker.
    """
    p = Path(source)
    try:
        data = p.read_bytes()
    except OSError:
        return []
    if not data:
        return []
    try:
        from mediahub.visual import transcribe
    except Exception:
        return []
    ct = "video/mp4" if p.suffix.lower() in {".mp4", ".m4v", ".mov"} else ""
    try:
        tr = transcribe.transcribe_audio(data, content_type=ct, language=language)
    except Exception:
        return []
    words = tr.words() or []
    if not words:
        return []
    window = out_ms > in_ms
    kept: list[tuple[str, int, int]] = []
    for w in words:
        a, b = w.start_ms, w.end_ms
        if window and (b <= in_ms or a >= out_ms):
            continue
        base = in_ms if window else 0
        kept.append((w.text, max(0, a - base), max(1, b - base)))
    return find_filler_spans(kept, aggressive=aggressive)


__all__ = [
    "FILLER_WORDS",
    "AGGRESSIVE_WORDS",
    "AGGRESSIVE_PHRASES",
    "find_filler_spans",
    "detect_filler_spans",
]
