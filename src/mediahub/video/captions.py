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


def windowed_karaoke_track(
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
    """Build an **animated (karaoke) caption track** for a clip window.

    Like :func:`windowed_caption_track`, but each line keeps its constituent
    **word stamps** so ``video.caption_render`` can burn the word-by-word
    highlight sweep (the signature reel caption look). The on-screen words are
    the *verbatim* transcript — there is no AI writing here, only word timing the
    ASR already produced. Honest ``None`` when ASR is unavailable or the window
    has no speech, so a render proceeds without it.
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
    if not words:
        # No word-level timing → karaoke would have nothing to sweep; fall back to
        # the static track so captions still appear (honest, never empty-faked).
        return windowed_caption_track(
            source,
            in_ms=in_ms,
            out_ms=out_ms,
            fps=fps,
            ground=ground,
            onground=onground,
            accent=accent,
            language=language,
        )

    # Keep words overlapping the window, rebased to a zero origin.
    kept: list[tuple[str, int, int]] = []
    for w in words:
        a, b = w.start_ms, w.end_ms
        if b <= in_ms or a >= out_ms:
            continue
        kept.append((w.text, max(0, a - in_ms), max(1, min(b, out_ms) - in_ms)))
    if not kept:
        return None

    total_frames = max(1, round((out_ms - in_ms) / 1000 * fps))
    cues = subtitle_burn.cues_from_stamps(kept)  # group words into lines
    color, scrim = subtitle_burn.caption_colours(ground, onground, accent)

    def _f(ms: int) -> int:
        return max(0, min(total_frames - 1, round(ms / 1000 * fps)))

    out_cues: list[dict] = []
    for cue in cues:
        line_words = [w for w in kept if cue.start_ms <= w[1] < cue.end_ms]
        if not line_words:
            continue
        c_from = _f(cue.start_ms)
        c_dur = max(1, min(total_frames - c_from, _f(cue.end_ms) - c_from + 1))
        wf: list[dict] = []
        for i, (text, a, _b) in enumerate(line_words):
            start_f = _f(a)
            # Gap-absorbing duration so the sweep is continuous across the line.
            nxt = _f(line_words[i + 1][1]) if i + 1 < len(line_words) else c_from + c_dur
            wf.append({"from": start_f, "dur": max(1, nxt - start_f), "text": text})
        out_cues.append(
            {
                "from": c_from,
                "dur": c_dur,
                "text": " ".join(t for t, _a, _b in line_words),
                "words": wf,
            }
        )
    if not out_cues:
        return None
    return {
        "color": color,
        "scrim": scrim,
        "accent": accent or "",
        "style": "karaoke",
        "cues": out_cues,
    }


# --------------------------------------------------------------------------
# Deterministic edit transforms (pure; return a new track)
# --------------------------------------------------------------------------


def _cues(track: Optional[dict]) -> list[dict]:
    return list((track or {}).get("cues") or [])


def cue_count(track: Optional[dict]) -> int:
    return len(_cues(track))


def edit_cue_text(track: dict, index: int, text: str) -> dict:
    """Replace cue ``index``'s text (the verbatim transcript can be corrected).

    On an animated (karaoke) cue the burned words come from the per-word ``words``
    stamps, not the line ``text`` — so a text edit that left those stamps in place
    would silently show the *old* words on screen. The edited cue drops its stale
    ``words``; ``caption_render`` renders a word-less cue as a still line of the new
    text, so the correction actually appears. A static cue has no ``words`` and is
    unchanged.
    """
    out = copy.deepcopy(track)
    cues = out.get("cues") or []
    if 0 <= index < len(cues):
        cues[index] = {k: v for k, v in cues[index].items() if k != "words"}
        cues[index]["text"] = str(text)
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


def offset_track(track: dict, delta_frames: int) -> dict:
    """Shift a whole track by ``delta_frames`` — **karaoke-aware**. Pure.

    Like :func:`shift_track` but also nudges each cue's per-word ``words`` stamps,
    so an animated (karaoke) track stays in sync when it is placed later on a reel
    timeline. Frames clamp at 0. Returns a new track.
    """
    out = copy.deepcopy(track)
    d = int(delta_frames)
    for c in out.get("cues") or []:
        c["from"] = max(0, int(c.get("from", 0)) + d)
        for w in c.get("words") or []:
            w["from"] = max(0, int(w.get("from", 0)) + d)
    return out


def merge_tracks(tracks: list[Optional[dict]]) -> Optional[dict]:
    """Concatenate several (already frame-offset) caption tracks into one. Pure.

    The footage reel captions more than its lead beat: each captioned beat's track
    is built over its own window, offset to its place on the timeline
    (:func:`offset_track`), then merged here. Cues are concatenated in order with
    their karaoke ``words`` preserved; the style (colour/scrim/accent/style) comes
    from the first non-empty track. Returns ``None`` when nothing has cues, so the
    reel's captions stay honestly optional.
    """
    base: Optional[dict] = None
    cues: list[dict] = []
    for t in tracks:
        if not t:
            continue
        if base is None:
            base = {k: v for k, v in t.items() if k != "cues"}
        cues.extend(copy.deepcopy(c) for c in (t.get("cues") or []))
    if base is None or not cues:
        return None
    return {**base, "cues": cues}


def _frame(ms: int, fps: int) -> int:
    return int(round(int(ms) / 1000 * max(1, int(fps))))


def retime_track_for_edit(
    track: Optional[dict],
    old_clips: list[dict],
    new_clips: list[dict],
    *,
    fps: int,
) -> Optional[dict]:
    """Re-time a burned caption track after the timeline's clips were
    reordered / trimmed / deleted in the editor.

    ``old_clips`` / ``new_clips`` are ordered, one dict per clip, each
    ``{"source", "offset_ms", "in_ms", "out_ms"}`` where ``offset_ms`` is the
    clip's dominant start on the assembled timeline
    (:meth:`~mediahub.video.edl.EDL.clip_start_offsets_ms`). A captioned clip
    always runs at ~1× (slow-mo skips captions), so a timeline frame maps 1:1 to
    a source frame and a head-trim shift is exact.

    Each cue (and its karaoke ``words``) is bucketed into the old clip whose
    window holds it, matched to the new clip carrying the same source (the k-th
    occurrence of a source maps to the k-th occurrence), and re-placed at the new
    offset — shifted by any head-trim and clamped to the new window. A cue whose
    clip was deleted, or whose word was trimmed away, is dropped rather than left
    to drift onto the wrong moment. Pure; returns a new track, or ``None`` when
    nothing survives. Callers should only invoke this when the clip structure
    actually changed — an identity mapping re-emits the track unchanged.
    """
    cues = _cues(track)
    if not cues or not old_clips:
        return track
    fps = max(1, int(fps))
    # An open-ended window (out ≤ in) can't be placed in frames without a probe;
    # leave the track untouched rather than guess (no worse than before).
    if any(int(c.get("out_ms", 0)) <= int(c.get("in_ms", 0)) for c in old_clips + new_clips):
        return track

    old_starts = [_frame(c["offset_ms"], fps) for c in old_clips]

    # Map each old clip to the new clip carrying the same source, matching k-th
    # occurrence to k-th occurrence so a repeated source stays in order.
    new_by_source: dict[str, list[int]] = {}
    for j, c in enumerate(new_clips):
        new_by_source.setdefault(str(c["source"]), []).append(j)
    seen: dict[str, int] = {}
    old_to_new: dict[int, Optional[int]] = {}
    for i, c in enumerate(old_clips):
        src = str(c["source"])
        k = seen.get(src, 0)
        seen[src] = k + 1
        lst = new_by_source.get(src, [])
        old_to_new[i] = lst[k] if k < len(lst) else None

    def _owning_old_clip(frame: int) -> int:
        # The last clip that starts at/before this frame owns it (an xfade lets a
        # cue sit in the incoming clip's lead-in; nearest start is the right home).
        idx = 0
        for i, s in enumerate(old_starts):
            if s <= frame:
                idx = i
            else:
                break
        return idx

    out_cues: list[dict] = []
    for cue in cues:
        oi = _owning_old_clip(int(cue.get("from", 0)))
        nj = old_to_new.get(oi)
        if nj is None:
            continue  # the owning clip was deleted
        old_c, new_c = old_clips[oi], new_clips[nj]
        head_shift = _frame(int(new_c["in_ms"]) - int(old_c["in_ms"]), fps)
        new_start = _frame(new_c["offset_ms"], fps)
        new_len = max(1, _frame(int(new_c["out_ms"]) - int(new_c["in_ms"]), fps))

        def _place(frame: int) -> Optional[int]:
            local = frame - old_starts[oi] - head_shift
            if local < 0 or local >= new_len:
                return None
            return new_start + local

        nf = _place(int(cue.get("from", 0)))
        if nf is None:
            continue  # trimmed off this clip's head or tail
        local = nf - new_start
        new_cue = {**cue, "from": nf, "dur": max(1, min(int(cue.get("dur", 1)), new_len - local))}
        if cue.get("words"):
            words: list[dict] = []
            for w in cue["words"]:
                wf = _place(int(w.get("from", 0)))
                if wf is None:
                    continue
                wl = wf - new_start
                words.append(
                    {**w, "from": wf, "dur": max(1, min(int(w.get("dur", 1)), new_len - wl))}
                )
            new_cue["words"] = words
        out_cues.append(new_cue)

    if not out_cues:
        return None
    out_cues.sort(key=lambda c: int(c.get("from", 0)))
    return {**{k: v for k, v in track.items() if k != "cues"}, "cues": out_cues}


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
    "windowed_karaoke_track",
    "cue_count",
    "edit_cue_text",
    "retime_cue",
    "delete_cue",
    "shift_track",
    "offset_track",
    "merge_tracks",
    "restyle",
    "retime_track_for_edit",
    "clamp_to_frames",
]
