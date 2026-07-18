"""Finding #74 — the motion cache key folds in a renderer-source fingerprint.

The per-composition revisions (STORY/REEL_COMPOSITION_REVISION) must be bumped by
hand when a composition changes. A change to SHARED renderer code (render.js,
Root.tsx, shared components, fonts.ts) or a Remotion version bump that nobody
remembered to bump the revision for would otherwise keep serving a stale cached
MP4. ``renderer_generation()`` content-hashes the renderer sources and
``_content_hash`` folds it into every key, so any renderer change invalidates the
whole motion cache automatically — while an unchanged renderer keeps stable keys
across redeploys (content hash, not mtime).
"""

from __future__ import annotations

from mediahub.visual import motion


def test_renderer_generation_is_stable_nonempty_hex():
    g1 = motion.renderer_generation()
    g2 = motion.renderer_generation()
    assert g1 == g2, "must be stable within a process (memoised)"
    assert g1 and all(c in "0123456789abcdef" for c in g1), f"expected hex token, got {g1!r}"
    # Real Remotion sources exist in the tree, so this is a real fingerprint,
    # not the read-failure fallback token.
    assert g1 != "r0"


def test_renderer_generation_is_memoised():
    motion.renderer_generation()
    assert motion._RENDERER_GENERATION is not None


def test_content_hash_depends_on_renderer_generation(monkeypatch):
    """The discriminator: two identical payloads hashed under different renderer
    generations must produce DIFFERENT keys. Fails on the pre-fix _content_hash
    (which ignored the renderer generation entirely)."""
    payload = {"card": {"swimmer": "A"}, "duration": 6.0}

    monkeypatch.setattr(motion, "renderer_generation", lambda: "gen-aaaa")
    k_a = motion._content_hash(payload, kind="story")

    monkeypatch.setattr(motion, "renderer_generation", lambda: "gen-bbbb")
    k_b = motion._content_hash(payload, kind="story")

    assert k_a != k_b, "a renderer-generation change must bust the cache key"


def test_same_renderer_generation_keeps_key_stable(monkeypatch):
    payload = {"card": {"swimmer": "A"}, "duration": 6.0}
    monkeypatch.setattr(motion, "renderer_generation", lambda: "gen-fixed")
    assert motion._content_hash(payload, kind="story") == motion._content_hash(
        payload, kind="story"
    )
    # Kind sensitivity is preserved.
    assert motion._content_hash(payload, kind="story") != motion._content_hash(
        payload, kind="reel"
    )
