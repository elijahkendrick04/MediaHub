"""video/end_card.py — branded club end-card for Video Studio renders (M28).

The data-driven meet reel closes on a branded club outro; the footage path
ended mid-clip. This appends the same brand close to a project render: a club
outro frame rendered by the EXISTING still renderer (``reel_ffmpeg``'s
minimal-brief + Playwright path — APCA-gated roles, self-hosted fonts, logo
chip), looped into a short muted H.264 clip and appended to the timeline as a
final EDL clip joined with a dissolve.

Cache honesty: the end-card MP4 is a normal EDL clip source, so
``video/render.py``'s cache key folds its ``size:mtime`` fingerprint exactly
like music beds — a re-branded club produces a new end-card file and therefore
a fresh render, while an unchanged brand is a cache hit. The end-card file
itself is content-addressed by (palette + club name + canvas + seconds), so
repeat renders reuse one conversion.

Honest fallback: no brand kit, no still renderer (Playwright), or no FFmpeg →
the timeline renders exactly as before, with the reason returned for the
route's response. Never a half-branded or fabricated close.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Any, Optional

from mediahub.video.edl import EDL, Clip, Transition

log = logging.getLogger(__name__)

END_CARD_SECONDS = 2.2
END_CARD_DISSOLVE_MS = 500
_END_CARD_VERSION = "v1"  # bump when the end-card frame or encode changes


def _cache_dir() -> Path:
    from mediahub.video.render import cache_dir

    d = cache_dir() / "endcards"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _brand_fingerprint(brand_dict: dict, *, width: int, height: int, fps: int) -> str:
    blob = "|".join(
        [
            _END_CARD_VERSION,
            str(brand_dict.get("primary") or ""),
            str(brand_dict.get("secondary") or ""),
            str(brand_dict.get("accent") or ""),
            str(brand_dict.get("displayName") or ""),
            str(brand_dict.get("shortName") or ""),
            str(bool(brand_dict.get("logoDataUri"))),
            f"{width}x{height}@{fps}",
            f"{END_CARD_SECONDS:g}s",
        ]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]


def _outro_png(brand_kit: Any, brand_dict: dict, out_dir: Path, *, width: int, height: int) -> Path:
    """Render the club outro frame via the existing still renderer."""
    from mediahub.visual.reel_ffmpeg import _minimal_brief, _render_still

    profile_id = ""
    if brand_kit is not None:
        profile_id = str(
            getattr(brand_kit, "profile_id", "")
            or (brand_kit.get("profile_id", "") if isinstance(brand_kit, dict) else "")
        )
    club = str(brand_dict.get("displayName") or brand_dict.get("shortName") or "").strip()
    layers = {
        # Mirror the Remotion reel outro's follow-the-club close: the club
        # name is the headline, the eyebrow is the CTA. No invented facts.
        "athlete_full_name": club,
        "athlete_first_name": "",
        "athlete_surname": "",
        "event_name": "",
        "result_value": "",
        "achievement_label": "FOLLOW US",
        "meet_name": "",
        "place": "",
    }
    brief = _minimal_brief(
        {"variationSeed": 0},
        brand_dict,
        profile_id=profile_id,
        layout_template="reel_cover",
        text_layers=layers,
        confidence_label="FOLLOW US",
    )
    return _render_still(brief, brand_kit, out_dir, name="endcard", size=(width, height))


def _png_to_clip(png: Path, out_mp4: Path, *, width: int, height: int, fps: int) -> bool:
    """Loop the outro PNG into a short muted H.264 clip. False on any failure."""
    from mediahub.visual.reel_ffmpeg import ffmpeg_exe

    exe = ffmpeg_exe()
    if not exe:
        return False
    tmp = out_mp4.with_name(out_mp4.name + ".part.mp4")
    cmd = [
        exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-loop",
        "1",
        "-t",
        f"{END_CARD_SECONDS:.3f}",
        "-i",
        str(png),
        "-an",
        "-vf",
        f"scale={width}:{height},format=yuv420p",
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-movflags",
        "+faststart",
        str(tmp),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 1024:
            raise RuntimeError((proc.stderr or "empty end-card clip").strip()[:200])
        tmp.replace(out_mp4)
        return True
    except Exception as e:
        log.warning("end-card encode failed: %s", e)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def end_card_clip_path(brand_kit: Any, *, width: int, height: int, fps: int = 30) -> Optional[Path]:
    """The content-addressed end-card MP4 for this brand + canvas, or None.

    Builds it on first use (still render → PNG → looped clip); every miss —
    no brand, no Playwright, no FFmpeg — returns None so the caller renders
    the un-appended timeline exactly as before.
    """
    if brand_kit is None:
        return None
    try:
        from mediahub.visual.motion import _brand_to_dict

        brand_dict = _brand_to_dict(brand_kit)
    except Exception:
        return None
    if not (brand_dict.get("displayName") or brand_dict.get("shortName")):
        return None  # nothing honest to close on
    key = _brand_fingerprint(brand_dict, width=width, height=height, fps=fps)
    out_mp4 = _cache_dir() / f"{key}.mp4"
    if out_mp4.exists() and out_mp4.stat().st_size > 1024:
        return out_mp4
    try:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="mh_endcard_") as td:
            png = _outro_png(brand_kit, brand_dict, Path(td), width=width, height=height)
            if not _png_to_clip(png, out_mp4, width=width, height=height, fps=fps):
                return None
    except Exception as e:
        log.warning("end-card still render failed: %s", e)
        return None
    return out_mp4


def append_end_card(edl: EDL, brand_kit: Any) -> tuple[EDL, str]:
    """A copy of ``edl`` with the branded end-card appended, plus a note.

    The end-card joins with a dissolve and is muted; a soundtrack plan and
    captions ride through unchanged. Returns ``(edl, "")`` untouched with the
    honest reason when the card can't be built.
    """
    if not edl.clips:
        return edl, "empty timeline"
    clip_path = end_card_clip_path(brand_kit, width=edl.width, height=edl.height, fps=edl.fps)
    if clip_path is None:
        return edl, "end-card unavailable (no brand kit, still renderer, or FFmpeg)"
    appended = EDL.from_dict(edl.to_dict())  # deep copy — never mutate the project
    appended.clips.append(
        Clip(
            source=str(clip_path),
            in_ms=0,
            out_ms=round(END_CARD_SECONDS * 1000),
            mute=True,
            transition_in=Transition("dissolve", END_CARD_DISSOLVE_MS),
        )
    )
    return appended, ""


__all__ = [
    "END_CARD_SECONDS",
    "END_CARD_DISSOLVE_MS",
    "end_card_clip_path",
    "append_end_card",
]
