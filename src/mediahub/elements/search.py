"""elements.search — find the right element for a moment (roadmap 1.10, build 2).

Two layers, honest about what's configured:

  1. **Semantic search** — embeds each element's description with the *same*
     cloud embedding infra the caption memory uses (``mediahub.memory.embedder``)
     and ranks the catalogue by cosine similarity to the query. "something for a
     relay", "a fast feel", "celebration" all land on the right elements even
     when the words don't match a tag.
  2. **Keyword fallback** — when no embedding provider is configured, search
     degrades *honestly* to the deterministic substring/tag filter
     (``catalog.filter_elements``). Browse always works with no AI key — it just
     loses the fuzzy understanding. No fabricated relevance, ever.

Why not the caption ``memory.store`` tables? Those are tenant-scoped caption
vectors; mixing element vectors in would pollute caption recall. The catalogue is
small and global, so we keep a tiny dedicated vector cache and do exact
brute-force cosine — the same algorithm sqlite-vec runs, without the per-tenant
table coupling. Contextual *choice* (which element fits this card) is AI
territory; the deterministic tag map is the explainable backbone underneath.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import catalog as _catalog
from .models import Element

_lock = threading.Lock()


@dataclass(frozen=True)
class ElementHit:
    element: Element
    score: float  # 0..1 (cosine for semantic; heuristic for keyword)
    method: str  # "semantic" | "keyword"


# --------------------------------------------------------------------------- #
# availability
# --------------------------------------------------------------------------- #
def is_semantic_available() -> bool:
    """True when a cloud embedding provider is configured (honest gate)."""
    try:
        from mediahub.memory import embedder

        return bool(embedder.is_configured())
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# vector cache (tiny, dedicated, content-keyed)
# --------------------------------------------------------------------------- #
def _index_dir() -> Path:
    data_dir = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[2])))
    d = data_dir / "element_index"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_path(profile_id: Optional[str], model_id: str) -> Path:
    key = f"{profile_id or 'global'}.{_safe(model_id)}"
    return _index_dir() / f"{key}.json"


def _safe(s: str) -> str:
    return "".join(ch for ch in str(s) if ch.isalnum() or ch in "-_.") or "model"


def _content_sig(element: Element) -> str:
    """A short hash of an element's search text — re-embed only when it changes."""
    return hashlib.blake2b(element.search_text().encode("utf-8"), digest_size=8).hexdigest()


def _load_cache(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("vectors"), dict):
            return raw
    except (OSError, ValueError):
        pass
    return {"model_id": "", "vectors": {}, "sigs": {}}


def _save_cache(path: Path, cache: dict) -> None:
    try:
        path.write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass


def _ensure_vectors(
    elements: list[Element], profile_id: Optional[str]
) -> Optional[tuple[str, dict[str, list[float]]]]:
    """Return (model_id, {element_id: vector}) embedding the catalogue, or None.

    Only embeds elements that are new or whose description changed since last run
    (the redundancy guard, mirroring memory.learning.capture). Returns ``None``
    when the embedder is unconfigured or the embed call fails — the caller then
    falls back to keyword search.
    """
    try:
        from mediahub.memory import embedder
    except Exception:
        return None
    if not embedder.is_configured():
        return None

    model_id = embedder.embed_model() or ""
    with _lock:
        path = _cache_path(profile_id, model_id)
        cache = _load_cache(path)
        if cache.get("model_id") != model_id:
            cache = {"model_id": model_id, "vectors": {}, "sigs": {}}

        vectors: dict[str, list[float]] = dict(cache.get("vectors", {}))
        sigs: dict[str, str] = dict(cache.get("sigs", {}))

        to_embed: list[Element] = []
        for el in elements:
            sig = _content_sig(el)
            if el.id not in vectors or sigs.get(el.id) != sig:
                to_embed.append(el)

        if to_embed:
            try:
                result = embedder.embed([el.search_text() for el in to_embed])
            except Exception:
                # embed failed mid-flight: use whatever we already cached, else None
                return (model_id, vectors) if vectors else None
            for el, vec in zip(to_embed, result.vectors):
                vectors[el.id] = list(vec)
                sigs[el.id] = _content_sig(el)
            _save_cache(path, {"model_id": model_id, "vectors": vectors, "sigs": sigs})

        if not vectors:
            return None
        return model_id, vectors


def _embed_query(text: str) -> Optional[list[float]]:
    try:
        from mediahub.memory import embedder

        if not embedder.is_configured():
            return None
        return list(embedder.embed_one(text).vectors[0])
    except Exception:
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


# --------------------------------------------------------------------------- #
# search
# --------------------------------------------------------------------------- #
def search(
    query: str,
    *,
    profile_id: Optional[str] = None,
    kind: Optional[str] = None,
    sport: Optional[str] = None,
    limit: int = 24,
) -> list[ElementHit]:
    """Rank the catalogue for ``query``. Semantic when configured, else keyword.

    ``kind``/``sport`` pre-filter the candidate set (cheap, deterministic) before
    ranking. An empty query returns the natural catalogue order (browse mode).
    """
    candidates = _catalog.filter_elements(profile_id=profile_id, kind=kind, sport=sport)
    q = (query or "").strip()
    if not q:
        return [ElementHit(el, 1.0, "keyword") for el in candidates][:limit]

    ensured = _ensure_vectors(candidates, profile_id)
    qvec = _embed_query(q) if ensured else None
    if ensured and qvec:
        _model_id, vectors = ensured
        scored: list[ElementHit] = []
        for el in candidates:
            vec = vectors.get(el.id)
            if vec is None:
                continue
            scored.append(ElementHit(el, max(0.0, _cosine(qvec, vec)), "semantic"))
        if scored:
            scored.sort(key=lambda h: h.score, reverse=True)
            return scored[:limit]

    return _keyword_rank(q, candidates, limit)


def _keyword_rank(query: str, candidates: list[Element], limit: int) -> list[ElementHit]:
    """Deterministic relevance: token overlap over name/tags/keywords."""
    tokens = [t for t in _tokenise(query) if t]
    if not tokens:
        return [ElementHit(el, 1.0, "keyword") for el in candidates][:limit]
    scored: list[ElementHit] = []
    for el in candidates:
        hay = el.search_text().lower()
        hay_tokens = set(_tokenise(hay))
        name = el.name.lower()
        hits = 0.0
        for tok in tokens:
            if tok in hay_tokens:
                hits += 1.0
            elif tok in hay:  # substring (e.g. "free" in "freestyle")
                hits += 0.6
            if tok in name:
                hits += 0.5  # name matches weigh more
        if hits > 0:
            scored.append(ElementHit(el, min(1.0, hits / (len(tokens) + 1)), "keyword"))
    scored.sort(key=lambda h: h.score, reverse=True)
    return scored[:limit]


def _tokenise(text: str) -> list[str]:
    out: list[str] = []
    word = []
    for ch in str(text).lower():
        if ch.isalnum():
            word.append(ch)
        elif word:
            out.append("".join(word))
            word = []
    if word:
        out.append("".join(word))
    return out


# --------------------------------------------------------------------------- #
# contextual suggestions (from a card's achievement facts)
# --------------------------------------------------------------------------- #
# Deterministic signal → tag map: the explainable backbone. A gold medal should
# always surface the trophy / rosette / podium; a PB the stopwatch / PB chip.
_CONTEXT_TAGS: dict[str, tuple[str, ...]] = {
    "gold": ("trophy", "winner", "first", "gold", "rosette"),
    "silver": ("medal", "podium", "ranking"),
    "bronze": ("medal", "podium", "ranking"),
    "pb": ("pb", "personal-best", "time", "stopwatch"),
    "record": ("trophy", "winner", "first", "star"),
    "relay": ("podium", "team", "ranking"),
    "freestyle": ("freestyle", "stroke", "speed"),
    "butterfly": ("butterfly", "stroke"),
    "backstroke": ("backstroke", "stroke"),
    "breaststroke": ("breaststroke", "stroke"),
}


def context_query(context: dict) -> str:
    """Build a natural-language query from a card's achievement facts."""
    if not isinstance(context, dict):
        return ""
    bits: list[str] = []
    for key in ("achievement_label", "post_angle", "event_name", "stroke", "headline", "tone"):
        v = context.get(key)
        if isinstance(v, str) and v.strip():
            bits.append(v.strip())
    medal = str(context.get("medal_tier") or "").strip()
    if medal:
        bits.append(f"{medal} medal")
    if context.get("is_pb"):
        bits.append("personal best")
    return " ".join(bits).strip()


def _context_tags(context: dict) -> list[str]:
    blob = " ".join(
        str(v) for v in (context or {}).values() if isinstance(v, (str, int, float))
    ).lower()
    medal = str((context or {}).get("medal_tier") or "").lower()
    if medal:
        blob += " " + medal
    if (context or {}).get("is_pb"):
        blob += " pb personal best"
    tags: list[str] = []
    for signal, mapped in _CONTEXT_TAGS.items():
        if signal in blob:
            for t in mapped:
                if t not in tags:
                    tags.append(t)
    return tags


def suggest_for_context(
    context: dict, *, profile_id: Optional[str] = None, limit: int = 8
) -> list[Element]:
    """Suggest elements that fit a card's moment.

    Deterministic tag mapping first (explainable, works with no AI key), then —
    when an embedding provider is configured — blended with semantic search over a
    query built from the same facts. Always returns *something* useful.
    """
    tags = _context_tags(context)
    ranked: list[Element] = []
    seen: set[str] = set()

    # 1) deterministic tag matches (the backbone)
    if tags:
        for el in _catalog.filter_elements(profile_id=profile_id, tags=tags):
            if el.id not in seen:
                ranked.append(el)
                seen.add(el.id)

    # 2) semantic blend (only adds; never replaces the explainable matches)
    q = context_query(context)
    if q and is_semantic_available():
        for hit in search(q, profile_id=profile_id, limit=limit):
            if hit.element.id not in seen:
                ranked.append(hit.element)
                seen.add(hit.element.id)

    return ranked[:limit]


__all__ = [
    "ElementHit",
    "search",
    "suggest_for_context",
    "context_query",
    "is_semantic_available",
]
