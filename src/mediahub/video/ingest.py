"""video/ingest.py — bring uploaded/recorded footage into the media library (1.6).

A footage clip is just another media asset — so it lives in the **same**
``media_library`` as photos, inheriting the per-profile isolation, the
permission/approval machinery, and (crucially for race footage of minors) the
safeguarding posture. Ingest stores the bytes, measures the clip
(``video.probe``), and records the measurement in the asset's ``media_meta``
(duration, fps, audio presence, frame shape) so Clip-Maker and the EDL compiler
never have to re-probe.

Two deliberate defaults:

* **Type ``footage``** — the asset type added for the video suite, so the
  library can list and filter clips distinctly from photos.
* **``permission_status="needs_approval"``** — footage is more sensitive than a
  crest, and a human approves before any export (rule 6). The caller can
  override for, say, a coach's own talking-head, but the safe default is
  review-first.

Probing needs FFmpeg; when it is unavailable the clip is still stored honestly
(``media_meta={}``) rather than rejected — Clip-Maker will surface the missing
measurement later rather than ingest guessing a duration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from mediahub.media_library.models import MediaAsset

# Container extensions we accept as footage (validated on the way in).
VIDEO_EXTS = frozenset({".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".3gp"})


def is_video_filename(filename: str) -> bool:
    """True when ``filename``'s extension is a recognised video container."""
    return Path(filename or "").suffix.lower() in VIDEO_EXTS


def ingest_footage(
    file_bytes: bytes,
    filename: str,
    *,
    profile_id: Optional[str],
    description: str = "",
    uploaded_by: Optional[str] = None,
    permission_status: str = "needs_approval",
    store=None,
    probe_fn: Optional[Callable] = None,
) -> MediaAsset:
    """Store a footage clip as a ``footage`` MediaAsset and measure it.

    ``store``/``probe_fn`` are injectable for testing (defaults: the media-library
    singleton and ``video.probe.probe_clip``). Raises ``ValueError`` on empty
    bytes or an unrecognised container — an honest rejection beats a stored file
    nothing can read.
    """
    if not file_bytes:
        raise ValueError("footage is empty")
    if not is_video_filename(filename):
        raise ValueError(
            f"{filename!r} is not a recognised video file (accepted: "
            f"{sorted(VIDEO_EXTS)})"
        )

    if store is None:
        from mediahub.media_library.store import get_store

        store = get_store()

    blob_path = store.store_blob(file_bytes, filename, profile_id)

    media_meta: dict = {}
    width = height = 0
    orientation = "unknown"
    if probe_fn is None:
        from mediahub.video.probe import probe_clip as probe_fn  # type: ignore[no-redef]
    try:
        probe = probe_fn(blob_path)
        dw, dh = probe.display_size
        width, height = dw, dh
        orientation = probe.orientation
        media_meta = {
            "duration_ms": probe.duration_ms,
            "fps": probe.fps,
            "has_audio": probe.has_audio,
            "has_video": probe.has_video,
            "video_codec": probe.video_codec,
            "audio_codec": probe.audio_codec,
            "rotation": probe.rotation,
        }
    except Exception:
        # FFmpeg unavailable / unprobeable → store honestly, unmeasured.
        media_meta = {}

    asset = MediaAsset(
        id="",
        filename=Path(filename).name,
        path=str(blob_path),
        type="footage",
        description_raw=description,
        profile_id=profile_id,
        permission_status=permission_status,
        approval_status="draft",
        width=width,
        height=height,
        orientation=orientation,
        uploaded_by=uploaded_by,
        media_meta=media_meta,
    )
    return store.save(asset)


__all__ = ["VIDEO_EXTS", "is_video_filename", "ingest_footage"]
