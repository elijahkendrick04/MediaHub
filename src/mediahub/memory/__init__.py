"""mediahub.memory — cloud-embedding semantic memory (Capability 2).

Foundation modules (PR 2a):
    embedder — cloud text embeddings via Capability 1's OpenAI-compatible
               transport (no local model; cloud-only by design).
    store    — sqlite-vec vector store in ``DATA_DIR/memory.db`` with
               tenant- and embedding-model-scoped exact KNN.

The wiring that *uses* this (capture on card approval + caption-exemplar
retrieval) lands in PR 2b.

Off-by-default: with no ``MEDIAHUB_EMBED_*`` configured,
``embedder.is_configured()`` is False and nothing is embedded, stored, or
queried — the rest of MediaHub behaves exactly as before. There is no
keyword/heuristic fallback: when embeddings are unavailable, semantic memory is
simply unavailable (honest error), per CLAUDE.md.
"""
