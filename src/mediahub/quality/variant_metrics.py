"""Deterministic distinctiveness metrics for the generative content engine.

These power the §8C "success metrics" of the generative-AI thesis
(``docs/research/mediahub-generative-ai-thesis.md``) — the measurable signals
that tell us the generation surgery actually made output less "samey":

  - ``archetype_diversity(specs)``   — structural variety across a candidate
    pool: distinct layout archetypes / candidates.
  - ``perceptual_spread(png_paths)`` — how visually different the *rendered*
    candidates are, via a cheap perceptual (difference) hash.
  - ``caption_repetition(captions)`` — worst-case n-gram overlap between
    captions, used to gate caption non-repetition.

All three are pure, deterministic, and fully offline — no LLM, no network, no
heavy ML. They read generation *outputs* and score them; they never make a
creative judgement (which would belong in ``media_ai.llm`` / ``ai_core.llm``).

§8C targets these feed:
  - a 5-candidate pool for one card spans ≥4 archetypes → ``archetype_diversity`` ≥ 0.8
  - a pack of 10 cards uses ≥6 distinct archetypes      → ``archetype_diversity`` ≥ 0.6
  - consecutive captions for a card stay below a repetition threshold
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Union

import numpy as np
from PIL import Image


# --------------------------------------------------------------------------- #
# 1. Archetype diversity
# --------------------------------------------------------------------------- #

# Fields a design-spec / creative brief may carry the structural archetype on.
# ``archetype`` is the gen-v2 design-spec name (thesis §5.4); ``layout_family``
# is the current ``VariationProfile`` / ``CreativeBrief`` field it supersedes.
_ARCHETYPE_KEYS = ("archetype", "layout_family")


def _archetype_label(spec: Any) -> str:
    """Pull a normalised archetype label out of one spec.

    Accepts a mapping (a design-spec JSON), an object exposing an ``archetype``
    or ``layout_family`` attribute (e.g. a ``CreativeBrief``), or a plain
    string. Returns ``""`` when no archetype is present.
    """
    if spec is None:
        return ""
    if isinstance(spec, str):
        return spec.strip().lower()
    if isinstance(spec, Mapping):
        for key in _ARCHETYPE_KEYS:
            val = spec.get(key)
            if val:
                return str(val).strip().lower()
        return ""
    for key in _ARCHETYPE_KEYS:
        val = getattr(spec, key, None)
        if val:
            return str(val).strip().lower()
    return ""


def archetype_diversity(specs: Sequence[Any]) -> float:
    """Fraction of the candidate pool that is structurally distinct.

    ``distinct archetypes / candidates`` — the headline structural-distinctiveness
    metric (thesis §8C). ``1.0`` means every candidate uses a different
    archetype; a low value means the pool is reskins of the same skeleton
    ("today this is ~1–2" distinct → ~0.1–0.4 for a 5–10 candidate pool).

    Candidates that carry no archetype label still count toward the denominator
    (they are candidates) but add nothing to the distinct count, so missing data
    lowers the score honestly rather than inflating it. A single candidate is
    trivially "diverse" (``1.0``); the metric is meaningful for pools of several.

    Returns ``0.0`` for an empty pool.
    """
    specs = list(specs)
    if not specs:
        return 0.0
    distinct = {label for label in (_archetype_label(s) for s in specs) if label}
    return len(distinct) / len(specs)


# --------------------------------------------------------------------------- #
# 2. Perceptual spread
# --------------------------------------------------------------------------- #

# Difference-hash grid edge (bits = _HASH_SIZE²). 16 → 256 bits: fine enough to
# separate card layouts while staying microseconds per image.
_HASH_SIZE = 16


def _difference_hash(path: Union[str, Path]) -> np.ndarray:
    """Difference hash (dHash) of one image, as a flat boolean bit array.

    The image is reduced to luminance and downscaled, then each pixel is
    compared with its right-hand neighbour. The result captures *structure*
    (edges, mass, composition) and is deliberately blind to flat recolouring —
    rotating which brand colour fills a shape is "cosmetic, not structural"
    (thesis §2.2), so it must not register as perceptual spread.
    """
    with Image.open(path) as img:
        small = img.convert("L").resize(
            (_HASH_SIZE + 1, _HASH_SIZE), Image.Resampling.LANCZOS
        )
    grid = np.asarray(small, dtype=np.int16)
    return (grid[:, 1:] > grid[:, :-1]).flatten()


def perceptual_spread(png_paths: Sequence[Union[str, Path]]) -> float:
    """Mean pairwise perceptual distance across rendered candidate PNGs.

    Each image is reduced to a difference hash; the distance between two images
    is the normalised Hamming distance between their hashes (fraction of
    differing bits, in ``[0, 1]``); the score is the mean over all unordered
    pairs.

    ``0.0`` means the renders are structurally identical (the "samey" failure);
    higher means the pool looks genuinely different. Fewer than two paths →
    ``0.0`` (nothing to compare). Accepts ``str`` or ``Path``; a missing file
    raises (an honest error, never a silent zero).
    """
    paths = list(png_paths)
    if len(paths) < 2:
        return 0.0
    hashes = [_difference_hash(p) for p in paths]
    total = 0.0
    pairs = 0
    for i in range(len(hashes)):
        for j in range(i + 1, len(hashes)):
            total += float(np.mean(hashes[i] != hashes[j]))
            pairs += 1
    return total / pairs


# --------------------------------------------------------------------------- #
# 3. Caption repetition
# --------------------------------------------------------------------------- #

_WORD_RE = re.compile(r"\w+")


def _word_ngrams(text: str, n: int) -> set:
    """Word n-gram set for one caption (lower-cased, punctuation stripped).

    A caption shorter than ``n`` words collapses to a single n-gram of all its
    words, so two short captions stay comparable ("big win" vs "big win" →
    identical) instead of both vanishing into the empty set.
    """
    tokens = _WORD_RE.findall(text.lower())
    if not tokens:
        return set()
    if len(tokens) < n:
        return {tuple(tokens)}
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def caption_repetition(captions: Sequence[str], n: int = 3) -> float:
    """Worst-case n-gram overlap between any two captions, in ``[0, 1]``.

    Returns the maximum Jaccard overlap of word ``n``-gram sets over all caption
    pairs — the signal behind §8C's "caption non-repetition" target, where
    consecutive captions for a card must stay *below* a threshold. ``1.0`` means
    two captions are word-for-word the same; ``0.0`` means no shared phrasing.

    Fewer than two captions → ``0.0``. ``n`` is the n-gram width (default 3,
    trigrams) and must be ≥ 1.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    grams = [_word_ngrams(c, n) for c in captions]
    if len(grams) < 2:
        return 0.0
    best = 0.0
    for i in range(len(grams)):
        for j in range(i + 1, len(grams)):
            best = max(best, _jaccard(grams[i], grams[j]))
    return best
