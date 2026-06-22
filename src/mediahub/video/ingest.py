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
from typing import BinaryIO, Callable, Optional

from mediahub.media_library.models import MediaAsset

# Container extensions we accept as footage (validated on the way in).
VIDEO_EXTS = frozenset({".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".3gp"})


def is_video_filename(filename: str) -> bool:
    """True when ``filename``'s extension is a recognised video container."""
    return Path(filename or "").suffix.lower() in VIDEO_EXTS


def _require_video(filename: str) -> None:
    if not is_video_filename(filename):
        raise ValueError(
            f"{filename!r} is not a recognised video file (accepted: {sorted(VIDEO_EXTS)})"
        )


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
    """Store a footage clip (from bytes) as a ``footage`` MediaAsset and measure it.

    ``store``/``probe_fn`` are injectable for testing (defaults: the media-library
    singleton and ``video.probe.probe_clip``). Raises ``ValueError`` on empty
    bytes or an unrecognised container — an honest rejection beats a stored file
    nothing can read. For large uploads prefer :func:`ingest_footage_stream`,
    which never holds the whole clip in memory.
    """
    if not file_bytes:
        raise ValueError("footage is empty")
    _require_video(filename)
    store = store or _default_store()
    blob_path = store.store_blob(file_bytes, filename, profile_id)
    return _finalise_footage_asset(
        store,
        blob_path,
        filename,
        profile_id=profile_id,
        description=description,
        uploaded_by=uploaded_by,
        permission_status=permission_status,
        probe_fn=probe_fn,
    )


def ingest_footage_stream(
    fileobj: BinaryIO,
    filename: str,
    *,
    profile_id: Optional[str],
    description: str = "",
    uploaded_by: Optional[str] = None,
    permission_status: str = "needs_approval",
    store=None,
    probe_fn: Optional[Callable] = None,
) -> MediaAsset:
    """Like :func:`ingest_footage` but **streams** the upload straight to disk.

    The clip is copied to its blob path in fixed-size chunks (no full-file bytes
    object in memory), so a 500 MB upload costs the copy buffer, not 500 MB of
    RAM. Emptiness can't be checked before the copy, so an empty upload is
    rejected *after* it (and the zero-byte file is cleaned up). Same honest
    ``ValueError`` on a non-video container.
    """
    _require_video(filename)
    store = store or _default_store()
    blob_path = Path(store.store_blob_stream(fileobj, filename, profile_id))
    try:
        empty = blob_path.stat().st_size == 0
    except OSError:
        empty = True
    if empty:
        try:
            blob_path.unlink()
        except OSError:
            pass
        raise ValueError("footage is empty")
    return _finalise_footage_asset(
        store,
        blob_path,
        filename,
        profile_id=profile_id,
        description=description,
        uploaded_by=uploaded_by,
        permission_status=permission_status,
        probe_fn=probe_fn,
    )


def _default_store():
    from mediahub.media_library.store import get_store

    return get_store()


def _finalise_footage_asset(
    store,
    blob_path,
    filename: str,
    *,
    profile_id: Optional[str],
    description: str,
    uploaded_by: Optional[str],
    permission_status: str,
    probe_fn: Optional[Callable],
) -> MediaAsset:
    """Probe a stored blob, build the ``footage`` MediaAsset, and persist it.

    Shared tail of both ingest paths. Probing needs FFmpeg; when it is
    unavailable the clip is still stored honestly (``media_meta={}``) rather than
    rejected — Clip-Maker surfaces the missing measurement later.
    """
    if probe_fn is None:
        from mediahub.video.probe import probe_clip as probe_fn  # type: ignore[no-redef]

    media_meta: dict = {}
    width = height = 0
    orientation = "unknown"
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


__all__ = ["VIDEO_EXTS", "is_video_filename", "ingest_footage", "ingest_footage_stream"]
