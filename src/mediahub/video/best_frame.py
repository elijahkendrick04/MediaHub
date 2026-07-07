"""video/best_frame.py — deterministic best-frame still extraction (M25).

Most clubs have far more video than photos. This turns a footage clip's top
detected moment into a real ``athlete_action`` photo asset, so the whole still
pipeline (selector, saliency, cutouts, still↔motion parity) lights up for a
video-rich, photo-poor club — and (via M23's priority rule) the clip itself can
then back the motion render while the extracted frame carries the still.

Deterministic end to end: the moment ranking is :mod:`mediahub.video.moments`
(pure maths over FFmpeg measurement), the frame is the top moment's CENTRE
timestamp (fixed → reproducible), and the extraction is one ``ffmpeg -ss <t>
-frames:v 1``. No AI anywhere on this path.

Safeguarding: the new photo asset inherits the footage's links AND its
``permission_status`` verbatim — never wider. A frame lifted from a clip that
needs parental consent needs exactly that same consent.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from mediahub.media_library.models import MediaAsset

log = logging.getLogger(__name__)


class BestFrameUnavailable(RuntimeError):
    """Raised when a frame cannot be extracted (no FFmpeg / unmeasured clip)."""


def frame_timestamp_ms(moments: list) -> Optional[int]:
    """The centre of the top-scoring detected moment, in ms. Pure.

    Earliest wins a tie — the same chronological tiebreak the footage-beat
    picker uses, so "best frame" and "footage beat" agree on the moment.
    """
    if not moments:
        return None
    best = max(moments, key=lambda m: (m.score, -m.start_ms))
    return (best.start_ms + best.end_ms) // 2


def extract_best_frame(
    footage: MediaAsset,
    *,
    store: Any = None,
    detect_fn: Optional[Callable] = None,
    extract_fn: Optional[Callable] = None,
) -> MediaAsset:
    """Extract the footage clip's best frame as a linked photo asset.

    Returns the saved ``athlete_action`` MediaAsset. Raises
    :class:`BestFrameUnavailable` (honest, actionable) when the clip is
    unmeasured, missing on disk, or FFmpeg can't extract — never a fabricated
    or empty image. ``detect_fn`` / ``extract_fn`` are injection seams for
    tests (defaults: ``moments.detect_moments`` and the real ffmpeg grab).
    """
    if store is None:
        from mediahub.media_library.store import get_store

        store = get_store()

    src = Path(str(footage.path or ""))
    if not src.exists():
        raise BestFrameUnavailable("The clip's file is missing on disk.")
    meta = footage.media_meta if isinstance(footage.media_meta, dict) else {}
    duration_ms = int(meta.get("duration_ms") or 0)
    if duration_ms <= 0:
        raise BestFrameUnavailable(
            "This clip was stored unmeasured (no FFmpeg at upload time) — "
            "re-upload it once the video engine is available."
        )

    if detect_fn is None:
        from mediahub.video.moments import detect_moments as detect_fn  # type: ignore[no-redef]

    moments = detect_fn(
        src, duration_ms=duration_ms, target_len_ms=min(6000, duration_ms), max_moments=3
    )
    at_ms = frame_timestamp_ms(list(moments))
    if at_ms is None:
        at_ms = duration_ms // 2  # a flat clip still yields a deterministic frame

    if extract_fn is None:
        extract_fn = _ffmpeg_frame
    frame_bytes = extract_fn(src, at_ms)
    if not frame_bytes:
        raise BestFrameUnavailable(
            "Extracting the frame needs an FFmpeg binary (install imageio-ffmpeg, "
            "put ffmpeg on PATH, or set MEDIAHUB_FFMPEG)."
        )

    at_s = at_ms / 1000.0
    frame_name = f"{Path(footage.filename).stem or 'clip'}_frame_{at_ms}ms.jpg"
    blob_path = store.store_blob(frame_bytes, frame_name, footage.profile_id)

    asset = MediaAsset(
        id="",
        filename=frame_name,
        path=str(blob_path),
        type="athlete_action",
        description_raw=f"frame from {footage.filename} at {at_s:.1f}s",
        profile_id=footage.profile_id,
        linked_athlete_ids=list(footage.linked_athlete_ids or []),
        linked_athlete_names=list(footage.linked_athlete_names or []),
        linked_meet_ids=list(footage.linked_meet_ids or []),
        # Safeguarding: INHERITED from the footage, never wider. The clip's
        # approval state rides along too — a draft clip yields a draft frame.
        permission_status=footage.permission_status,
        approval_status=footage.approval_status,
        safe_for_minors=footage.safe_for_minors,
        uploaded_by=footage.uploaded_by,
        media_meta={
            "source_footage_id": footage.id,
            "frame_at_ms": at_ms,
        },
    )
    try:
        from mediahub.media_library.tagger import measure_asset

        measure_asset(asset)
    except Exception:
        pass  # an unmeasured frame is still a real frame
    return store.save(asset)


def _ffmpeg_frame(src: Path, at_ms: int) -> Optional[bytes]:
    """One JPEG frame at ``at_ms`` via FFmpeg, or None when unavailable."""
    from mediahub.visual.reel_ffmpeg import ffmpeg_exe

    exe = ffmpeg_exe()
    if not exe:
        return None
    with tempfile.TemporaryDirectory(prefix="mh_best_frame_") as td:
        out = Path(td) / "frame.jpg"
        try:
            proc = subprocess.run(
                [
                    exe,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    f"{at_ms / 1000.0:.3f}",
                    "-i",
                    str(src),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(out),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode != 0 or not out.exists() or out.stat().st_size == 0:
                return None
            return out.read_bytes()
        except Exception as e:
            log.warning("best-frame ffmpeg grab failed for %s: %s", src, e)
            return None


__all__ = ["BestFrameUnavailable", "frame_timestamp_ms", "extract_best_frame"]
