"""video/captions.py — the editable styled caption layer on footage (1.6).

Most feed video autoplays muted, so the words spoken in a club's clip have to be
*on screen*. The ASR seam (roadmap 1.4, ``visual.transcribe``) already turns a
clip's audio into a word-timed, APCA-legible caption track; this module is the
thin **footage-facing** layer over it:

* :func:`caption_track_from_footage` — transcribe a clip and build its track
  (honest ``None`` when ASR isn't configured; captions are an overlay, never
  load-bearing — a render proceeds without them).
* **Deterministic edit transforms** over a track dict — retime, shift, edit
  text, delete, restyle — the operations the timeline's caption editor needs.
  These are pure functions returning a *new* track (never mutating the input),
  so they are trivially unit-tested and undo/redo-friendly.

The track shape is exactly ``subtitle_burn``'s:
``{"color": "#FFF", "scrim": "#0A2540", "cues": [{"from": f, "dur": d, "text": t}]}``
— frame-indexed cues, which ``render.py`` burns via ``subtitle_burn.ass_document``.
The on-screen words are the *verbatim* transcript; there is no AI writing here.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Optional


def caption_track_from_footage(
    source: Path | str,
    *,
    fps: int = 30,
    total_frames: int = 0,
    ground: str = "",
    onground: str = "",
    accent: str = "",
    language: str = "",
) -> Optional[dict]:
    """Transcribe a footage clip and build its APCA-gated caption track.

    Reads the file bytes and hands them to ``transcribe.caption_track_for_audio``
    (which decodes the video's audio). Returns ``None`` — never raises — when ASR
    is unavailable, the clip is silent, or anything else goes wrong, so a caption
    is always optional over the render.
    """
    p = Path(source)
    try:
        data = p.read_bytes()
    except OSError:
        return None
    if not data:
        return None
    try:
        from mediahub.visual.transcribe import caption_track_for_audio
    except Exception:
        return None
    ct = "video/mp4" if p.suffix.lower() in {".mp4", ".m4v", ".mov"} else ""
    try:
        return caption_track_for_audio(
            data,
            fps=fps,
            total_frames=total_frames,
            ground=ground,
            onground=onground,
            accent=accent,
            language=language,
            content_type=ct,
        )
    except Exception:
        return None


def windowed_caption_track(
    source: Path | str,
    *,
    in_ms: int,
    out_ms: int,
    fps: int = 30,
    ground: str = "",
    onground: str = "",
    accent: str = "",
    language: str = "",
) -> Optional[dict]:
    """Build a caption track for just the ``[in_ms, out_ms]`` window of a clip.

    Clip-Maker trims a long clip to one moment; its captions must be the words
    spoken *in that window*, rebased so the window starts at frame 0. Transcribes
    the whole source (cached), keeps the word stamps overlapping the window,
    shifts them to a zero origin, and styles them APCA-legibly. Honest ``None``
    when ASR is unavailable or no words fall in the window.
    """
    p = Path(source)
    try:
        data = p.read_bytes()
    except OSError:
        return None
    if not data or out_ms <= in_ms:
        return None
    try:
        from mediahub.visual import subtitle_burn, transcribe
    except Exception:
        return None
    ct = "video/mp4" if p.suffix.lower() in {".mp4", ".m4v", ".mov"} else ""
    try:
        tr = transcribe.transcribe_audio(data, content_type=ct, language=language)
    except Exception:
        return None

    words = tr.words() or []
    stamps: list[tuple[str, int, int]]
    if words:
        src = [(w.text, w.start_ms, w.end_ms) for w in words]
    else:
        src = [(s.text, s.start_ms, s.end_ms) for s in tr.segments]
    # Keep anything that overlaps the window, rebased to the window origin.
    kept: list[tuple[str, int, int]] = []
    for text, a, b in src:
        if b <= in_ms or a >= out_ms:
            continue
        kept.append((text, max(0, a - in_ms), max(1, min(b, out_ms) - in_ms)))
    if not kept:
        return None
    cues = subtitle_burn.cues_from_stamps(kept)
    total_frames = max(1, round((out_ms - in_ms) / 1000 * fps))
    return subtitle_burn.build_track(
        cues, fps=fps, total_frames=total_frames, ground=ground, onground=onground, accent=accent
    )


# --------------------------------------------------------------------------
# Deterministic edit transforms (pure; return a new track)
# --------------------------------------------------------------------------


def _cues(track: Optional[dict]) -> list[dict]:
    return list((track or {}).get("cues") or [])


def cue_count(track: Optional[dict]) -> int:
    return len(_cues(track))


def edit_cue_text(track: dict, index: int, text: str) -> dict:
    """Replace cue ``index``'s text (the verbatim transcript can be corrected)."""
    out = copy.deepcopy(track)
    cues = out.get("cues") or []
    if 0 <= index < len(cues):
        cues[index] = {**cues[index], "text": str(text)}
    return out


def retime_cue(track: dict, index: int, *, from_frame: int, dur_frames: int) -> dict:
    """Set cue ``index``'s start frame and duration (manual timing)."""
    out = copy.deepcopy(track)
    cues = out.get("cues") or []
    if 0 <= index < len(cues):
        cues[index] = {
            **cues[index],
            "from": max(0, int(from_frame)),
            "dur": max(1, int(dur_frames)),
        }
    return out


def delete_cue(track: dict, index: int) -> dict:
    """Drop cue ``index`` (e.g. a filler 'um' the ASR caught)."""
    out = copy.deepcopy(track)
    cues = out.get("cues") or []
    if 0 <= index < len(cues):
        cues.pop(index)
    return out


def shift_track(track: dict, delta_frames: int) -> dict:
    """Nudge every cue by ``delta_frames`` (sync the whole caption track).

    Frames are clamped at 0 so a negative nudge can never produce a cue that
    starts before the clip.
    """
    out = copy.deepcopy(track)
    for c in out.get("cues") or []:
        c["from"] = max(0, int(c.get("from", 0)) + int(delta_frames))
    return out


def restyle(track: dict, *, ground: str = "", onground: str = "", accent: str = "") -> dict:
    """Recompute the caption colour/scrim for a (new) brand ground. Deterministic.

    Reuses ``subtitle_burn.caption_colours`` so the styled layer stays APCA-legible
    on whatever ground it is composited over — the same colour-science the still
    renderer uses.
    """
    out = copy.deepcopy(track)
    try:
        from mediahub.visual.subtitle_burn import caption_colours

        color, scrim = caption_colours(ground, onground, accent)
        out["color"] = color
        out["scrim"] = scrim
    except Exception:
        pass
    return out


def clamp_to_frames(track: dict, total_frames: int) -> dict:
    """Drop/clip cues that fall outside ``[0, total_frames)`` (timeline trim).

    Keeps a re-trimmed clip's captions inside the new length so a burned cue can
    never run past the end of the video.
    """
    out = copy.deepcopy(track)
    if total_frames <= 0:
        return out
    kept: list[dict] = []
    for c in out.get("cues") or []:
        start = int(c.get("from", 0))
        if start >= total_frames:
            continue
        dur = max(1, min(int(c.get("dur", 1)), total_frames - start))
        kept.append({**c, "from": start, "dur": dur})
    out["cues"] = kept
    return out


__all__ = [
    "caption_track_from_footage",
    "windowed_caption_track",
    "cue_count",
    "edit_cue_text",
    "retime_cue",
    "delete_cue",
    "shift_track",
    "restyle",
    "clamp_to_frames",
]
