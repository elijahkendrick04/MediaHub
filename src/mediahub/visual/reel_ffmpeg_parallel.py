"""visual/reel_ffmpeg_parallel.py — concurrent beat rendering for the free
FFmpeg reel engine.

The free FFmpeg reel engine (:mod:`mediahub.visual.reel_ffmpeg`) builds a meet
reel from *beats*: a meet-name cover frame plus one frame per ranked card. Each
beat's frame is an independent still graphic rendered by ``graphic_renderer``
(Playwright/Chromium) before FFmpeg stitches the beats together with the
engine's Ken-Burns + transition chain. Those still renders are the reel's
dominant wall-clock cost and they share nothing, so rendering them
concurrently — exactly what ``graphic_renderer.variants.render_all_formats``
already does for format variants — turns the cover+N-card render phase from
Σ(beat) into roughly max(beat) **without changing a single output pixel**.

Relationship to :mod:`mediahub.visual.reel_parallel`
----------------------------------------------------
That module is R1.28's accelerator for the **Remotion** reel: it splits one
frame-pure Remotion timeline into contiguous frame ranges, renders the ranges
concurrently, and concats them. This module is its counterpart for the **free
FFmpeg fallback** engine, which composes the reel from *separate per-beat
still graphics* rather than one continuous timeline — so the unit of
parallelism here is the beat still, not a frame range. Two engines, two
mechanisms; neither changes what the reel looks like, only how fast it renders.

This helper is engine-agnostic and owns no rendering or FFmpeg knowledge: a
caller hands it a list of :class:`Beat` records (a stable name + a zero-argument
callable that renders that beat's still and returns its ``Path``) and gets the
rendered paths back **in the caller's original beat order**. Determinism is
preserved by construction — only wall-clock changes, never the bytes:

* the result list is ordered by beat order, never by completion order, so the
  FFmpeg transition chain always composites ``cover, card0, card1, …``;
* each beat still is itself deterministic (same brief → same PNG); and
* the first beat to raise aborts the batch and its exception propagates
  unchanged — the engine surfaces an honest error and never stitches a partial
  reel or a placeholder frame.

Concurrency is bounded and reuses the still renderer's existing knobs, so an
operator who already tuned graphic rendering gets the same behaviour on reels:

``MEDIAHUB_RENDER_PARALLEL``
    ``"0"`` forces fully-sequential rendering (less RAM, easier debugging). Any
    other value (the default) enables the bounded thread pool.
``MEDIAHUB_RENDER_WORKERS``
    Maximum concurrent Chromium renders (default ``3``). Each headless Chromium
    holds ~150 MB, so the default keeps a six-beat reel (cover + five cards)
    inside a 1 GB worker by rendering three beats at a time.
``MEDIAHUB_REEL_RENDER_WORKERS``
    Optional reel-specific override of the worker cap (reel beats are full-size
    cut frames, heavier than the format-variant renders the shared cap was
    sized for); falls back to ``MEDIAHUB_RENDER_WORKERS``.

(These are the still-render knobs shared with ``render_all_formats`` — distinct
from ``reel_parallel.py``'s ``MEDIAHUB_REEL_PARALLEL`` /
``MEDIAHUB_REEL_PARALLEL_WORKERS``, which gate the Remotion segment split.)

The pool is created only when it helps: a single beat, a worker cap of one, or
``MEDIAHUB_RENDER_PARALLEL=0`` all render inline on the calling thread, so the
sequential path is byte-for-byte the pre-parallel behaviour.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

# Matches graphic_renderer.variants.render_all_formats: ~150 MB per headless
# Chromium, so three concurrent renders fit a 1 GB worker.
DEFAULT_MAX_WORKERS = 3


@dataclass(frozen=True)
class Beat:
    """One reel beat to render.

    ``name``    A stable, human-readable beat id (``"cover"``, ``"card0"`` …)
                used for the working sub-directory and for diagnostics; it does
                not affect ordering — the result list follows submission order.
    ``render``  A zero-argument callable that renders the beat's still and
                returns its on-disk ``Path``. Bind per-beat inputs with default
                arguments at the call site so each closure captures its own
                brief/name rather than the loop's final value.
    """

    name: str
    render: Callable[[], Path]


def parallel_enabled() -> bool:
    """True unless ``MEDIAHUB_RENDER_PARALLEL`` is explicitly ``"0"``."""
    return os.environ.get("MEDIAHUB_RENDER_PARALLEL", "1") != "0"


def max_workers() -> int:
    """Resolve the concurrent-render cap (always ``>= 1``).

    Prefers the reel-specific ``MEDIAHUB_REEL_RENDER_WORKERS``, then the shared
    ``MEDIAHUB_RENDER_WORKERS``, then :data:`DEFAULT_MAX_WORKERS`. A non-integer
    or sub-1 value falls back to the default rather than failing a render over a
    typo'd env var.
    """
    raw = (
        os.environ.get("MEDIAHUB_REEL_RENDER_WORKERS")
        or os.environ.get("MEDIAHUB_RENDER_WORKERS")
        or ""
    ).strip()
    if not raw:
        return DEFAULT_MAX_WORKERS
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_MAX_WORKERS
    return n if n >= 1 else DEFAULT_MAX_WORKERS


def render_beats(beats: Sequence[Beat]) -> list[Path]:
    """Render every beat's still and return the paths in beat order.

    Concurrent by default via a bounded thread pool — the still renderer
    launches its own Chromium per call, so threads parallelise the
    subprocess-bound work cleanly (the same model ``render_all_formats`` uses).
    Renders inline on the calling thread when there is a single beat, when the
    worker cap resolves to one, or when ``MEDIAHUB_RENDER_PARALLEL=0``; those
    paths are byte-identical to the pre-parallel sequential loop.

    The returned list always follows the input order regardless of which beat
    finishes first. The first beat to raise aborts the batch and its exception
    propagates unchanged (no placeholder frame, no partial reel), honouring the
    engine's "never a fake asset" contract.
    """
    beats = list(beats)
    if not beats:
        return []
    workers = min(max_workers(), len(beats))
    if workers <= 1 or not parallel_enabled():
        return [beat.render() for beat in beats]

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mh-reel-beat") as pool:
        # Submission order == beat order, so reading the futures back in that
        # order both preserves output order and re-raises the first beat's
        # error (the pool's context-manager exit then waits for any still-live
        # renders, so no Chromium is orphaned).
        futures = [pool.submit(beat.render) for beat in beats]
        return [fut.result() for fut in futures]


__all__ = [
    "Beat",
    "render_beats",
    "parallel_enabled",
    "max_workers",
    "DEFAULT_MAX_WORKERS",
]
