"""video/reel_builder.py — assemble a branded reel from many clips (1.6).

``clip_maker`` turns *one* clip into one cut. ``reel_builder`` is the multi-clip
sibling: hand it several footage clips and it produces one branded vertical
**reel** — the highlights from across a meet, ordered, graded, captioned, and
scored to music, with a human approving before export.

It is an **assembler over the engine pieces plus the AI director**:

    probe + detect moments (deterministic, per clip)
      → director plans the order/look/mood/hook (AI judgement, honest default)
      → reframe each chosen moment (deterministic saliency)
      → caption the lead beat (verbatim ASR)
      → resolve a music bed for the mood (deterministic library pick)
      → assemble a branded EDL (deterministic) → render (server-side, cached)

The only judgement is the director's (and it only *orders/selects* facts — it
never invents one). Everything else is the same deterministic machinery the
single-clip path uses, so the reel is reproducible and explainable. The split
that keeps it testable: :func:`build_reel_edl` is a **pure function** (sources +
chosen beats + crops + caption track + plan → EDL); :func:`make_reel` is the
impure orchestrator with every engine piece injectable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from mediahub.video import director as _director
from mediahub.video import moments as _moments
from mediahub.video import reframe as _reframe
from mediahub.video.clip_maker import BrandColours, canvas_for
from mediahub.video.director import ReelPlan
from mediahub.video.edl import EDL, AudioPlan, Clip, TextOverlay, Transition
from mediahub.video.moments import Moment
from mediahub.video.probe import ClipProbe

DEFAULT_FORMAT = "story"
DEFAULT_TRANSITION = "dissolve"
DEFAULT_TRANSITION_MS = 320
MIN_WEIGHTED_BEAT_MS = 900  # a weighted beat never tightens below ~0.9s (readable)


@dataclass
class ReelResult:
    """The product: the timeline, the director's plan, and an explainability map."""

    edl: EDL
    plan: ReelPlan = field(default_factory=ReelPlan)
    moments_by_clip: list[list[Moment]] = field(default_factory=list)
    manifest: dict = field(default_factory=dict)


def resolve_music(
    mood: str,
    *,
    platform: str = "instagram",
    content_key: str = "",
) -> Optional[str]:
    """Pick a music bed path for a mood from the library (deterministic floor).

    The *mood* is the director's AI judgement; the *pick* is the library's honest
    content-hash floor over the tracks that match it (same key → same track).
    Falls back to any music track when the mood has no match, and returns ``None``
    when the library is empty — the reel then carries voice-only, honestly.
    """
    try:
        from mediahub.audio.library import AudioLibrary

        lib = AudioLibrary.load()
    except Exception:
        return None
    key = content_key or f"reel:{mood}"
    track = lib.pick(key, kind="music", mood=mood, platform=platform)
    if track is None:
        track = lib.pick(key, kind="music", platform=platform)
    if track is None:
        return None
    try:
        return str(Path(track.path))
    except Exception:
        return None


def snap_to_beats(length_ms: int, beat_ms: float, *, min_beats: int = 2) -> int:
    """Round a clip length to a whole number of musical beats. Pure + deterministic.

    A reel feels tighter when its cuts land on the beat: a 1.7s window at 120 BPM
    (500ms/beat) snaps to 4 beats = 2.0s. ``min_beats`` keeps a beat from being
    too short to read. ``beat_ms <= 0`` (no/unknown tempo) is a no-op.
    """
    if beat_ms <= 0 or length_ms <= 0:
        return length_ms
    beats = max(min_beats, round(length_ms / beat_ms))
    return round(beats * beat_ms)


def build_reel_edl(
    sources: list[str],
    beats: list[_director.ClipBeat],
    moments_by_clip: list[list[Moment]],
    *,
    format_name: str = DEFAULT_FORMAT,
    crops: Optional[list] = None,
    caption_track: Optional[dict] = None,
    plan: Optional[ReelPlan] = None,
    colours: Optional[BrandColours] = None,
    audio_plan: Optional[AudioPlan] = None,
    transition_kind: str = DEFAULT_TRANSITION,
    transition_ms: int = DEFAULT_TRANSITION_MS,
    beat_ms: float = 0.0,
    fps: int = 30,
) -> EDL:
    """Assemble a reel EDL from chosen beats + per-beat crops + a caption track.

    Pure and deterministic. Each beat becomes one clip on the target canvas (the
    first joins with a hard cut, the rest with the chosen transition); the
    director's hook rides as an opening title; the lead beat's captions and the
    named look + audio plan ride on top. When ``beat_ms`` is given each clip's
    length is snapped to a whole number of musical beats so the cuts land on the
    beat. No FFmpeg, no transcription here — those happen in :func:`make_reel`.
    """
    colours = colours or BrandColours()
    plan = plan or ReelPlan()
    width, height = canvas_for(format_name)
    crops = crops or []

    clips: list[Clip] = []
    for i, beat in enumerate(beats):
        try:
            m = moments_by_clip[beat.asset_index][beat.moment_index]
            src = sources[beat.asset_index]
        except (IndexError, KeyError):
            continue
        crop = crops[i] if i < len(crops) and crops[i] else None
        trans = Transition("cut") if not clips else Transition(transition_kind, transition_ms)
        # The director's per-beat weight scales the moment's screen time. An even
        # 1.0 weight leaves the span exactly as before (byte-identical render and
        # cache key); a weighted beat is floored so it never tightens below the
        # readable minimum.
        weight = getattr(beat, "weight", 1.0) or 1.0
        base_span = m.end_ms - m.start_ms
        span = base_span if weight == 1.0 else max(MIN_WEIGHTED_BEAT_MS, round(base_span * weight))
        out_ms = m.start_ms + snap_to_beats(span, beat_ms)
        clips.append(
            Clip(
                source=src,
                in_ms=m.start_ms,
                out_ms=out_ms,
                crop=tuple(crop) if crop else None,  # type: ignore[arg-type]
                transition_in=trans,
            )
        )
    if not clips:
        # Degenerate input (no usable beats): keep the opening of the first source.
        src = sources[0] if sources else ""
        clips = [Clip(source=src, in_ms=0, out_ms=6000)]

    overlays: list[TextOverlay] = []
    if plan.hook.strip():
        overlays.append(
            TextOverlay(
                text=plan.hook.strip(), start_ms=0, duration_ms=2400, position="lower-third"
            )
        )

    track = caption_track
    if track and (colours.ground or colours.accent):
        from mediahub.video import captions as _captions

        track = _captions.restyle(
            track, ground=colours.ground, onground=colours.onground, accent=colours.accent
        )

    return EDL(
        width=width,
        height=height,
        fps=fps,
        clips=clips,
        overlays=overlays,
        captions=track,
        keep_audio=True,
        background=colours.background or "#0A0A0A",
        look=plan.look or "none",
        audio=audio_plan if (audio_plan and not audio_plan.is_empty()) else None,
    )


def make_reel(
    asset_paths: list[Path | str],
    *,
    format_name: str = DEFAULT_FORMAT,
    per_clip_moments: int = 2,
    max_beats: int = 5,
    with_captions: bool = True,
    caption_style: str = "karaoke",
    caption_beats: int = 1,
    with_reframe: bool = True,
    with_music: bool = True,
    beat_sync: bool = True,
    enhance_audio: bool = True,
    loudness: str = "social",
    brief_context: str = "",
    colours: Optional[BrandColours] = None,
    music_platform: str = "instagram",
    fps: int = 30,
    # Injection seams (default to the real engine pieces):
    probe_fn: Optional[Callable] = None,
    detect_fn: Optional[Callable] = None,
    reframe_fn: Optional[Callable] = None,
    caption_fn: Optional[Callable] = None,
    plan_fn: Optional[Callable] = None,
    music_fn: Optional[Callable] = None,
) -> ReelResult:
    """Turn several footage clips into one branded reel :class:`ReelResult`.

    Deterministic where it matters (moments, crops, the timeline, the music pick);
    the one judgement is the director's order/look/mood/hook, which only arranges
    the detected facts and falls back to a deterministic plan with no AI provider.
    """
    sources = [str(p) for p in asset_paths]
    colours = colours or BrandColours()
    width, height = canvas_for(format_name)
    fps = max(1, fps)
    probe = probe_fn or _default_probe
    detect = detect_fn or _moments.detect_moments
    plan_reel = plan_fn or _director.plan_reel

    # 1) Probe + detect moments per clip (deterministic).
    probes: list[ClipProbe] = []
    moments_by_clip: list[list[Moment]] = []
    clips_meta: list[dict] = []
    for src in sources:
        p = probe(src)
        probes.append(p)
        ms = list(
            detect(src, duration_ms=p.duration_ms, target_len_ms=4500, max_moments=per_clip_moments)
        )
        moments_by_clip.append(ms)
        clips_meta.append(
            {
                "name": Path(src).stem,
                "orientation": p.orientation,
                "moments": [m.to_dict() for m in ms],
            }
        )

    # 2) Director plans the reel (AI judgement; honest default).
    plan = plan_reel(clips_meta, brief_context=brief_context, max_beats=max_beats)
    beats = list(plan.order)

    # 3) Reframe each chosen beat (deterministic saliency), when shapes differ.
    crops: list = []
    reframed = False
    rf = reframe_fn or _reframe.reframe_clip_crop
    for beat in beats:
        crop = None
        try:
            p = probes[beat.asset_index]
            m = moments_by_clip[beat.asset_index][beat.moment_index]
        except (IndexError, KeyError):
            crops.append(None)
            continue
        dw, dh = p.display_size
        if with_reframe and _reframe.needs_reframe(dw, dh, width, height):
            crop = rf(
                sources[beat.asset_index],
                in_ms=m.start_ms,
                out_ms=m.end_ms,
                dst_w=width,
                dst_h=height,
            )
            reframed = reframed or bool(crop)
        crops.append(crop)

    # 4) Captions. The lead beat always carries verbatim captions; the director
    #    can caption more of the montage (``caption_beats`` > 1), each window
    #    offset to its place on the assembled timeline (assembled after the EDL is
    #    built, below, so beat-sync + weights are reflected).
    cap = caption_fn or (
        _default_karaoke_caption if caption_style == "karaoke" else _default_caption
    )
    n_caption = max(1, min(int(caption_beats), len(beats))) if (with_captions and beats) else 0
    caption_track: Optional[dict] = None
    captions_note = "off"
    if n_caption == 1:
        lead = beats[0]
        try:
            m = moments_by_clip[lead.asset_index][lead.moment_index]
            caption_track = cap(
                sources[lead.asset_index],
                in_ms=m.start_ms,
                out_ms=m.end_ms,
                fps=fps,
                ground=colours.ground,
                onground=colours.onground,
                accent=colours.accent,
            )
            note = "burned-lead-karaoke" if caption_style == "karaoke" else "burned-lead"
            captions_note = note if caption_track else "no-speech-or-asr-off"
        except (IndexError, KeyError):
            captions_note = "off"

    # 5) Resolve a music bed for the director's mood (deterministic floor).
    music_path: Optional[str] = None
    if with_music:
        resolver = music_fn or resolve_music
        music_path = resolver(
            plan.music_mood, platform=music_platform, content_key=":".join(sources)
        )

    audio_plan = AudioPlan(
        music=music_path or "",
        enhance_voice=bool(enhance_audio),
        loudness=loudness or "",
        duck=True,
    )

    # 6) Beat-sync: when there's a music bed, snap the cuts to its tempo.
    beat_ms = 0.0
    if music_path and beat_sync:
        try:
            from mediahub.visual.audio_mux import track_bpm

            bpm = track_bpm(music_path)
            if bpm and bpm > 0:
                beat_ms = 60000.0 / bpm
        except Exception:
            beat_ms = 0.0

    edl = build_reel_edl(
        sources,
        beats,
        moments_by_clip,
        format_name=format_name,
        crops=crops,
        caption_track=caption_track,
        plan=plan,
        colours=colours,
        audio_plan=audio_plan,
        beat_ms=beat_ms,
        fps=fps,
    )

    # Multi-beat captions are assembled here, once the timeline (with beat-sync
    # and per-beat weights) is final, so each cue is offset under its own clip.
    captioned_beats = 1 if (n_caption == 1 and caption_track) else 0
    if n_caption > 1:
        merged, captioned_beats = _assemble_reel_captions(
            edl, beats, sources, cap, fps=fps, colours=colours, n=n_caption
        )
        edl.captions = merged
        if captioned_beats:
            base = "karaoke" if caption_style == "karaoke" else "static"
            captions_note = f"burned-{captioned_beats}beats-{base}"
        else:
            captions_note = "no-speech-or-asr-off"

    manifest = {
        "kind": "reel",
        "format": format_name,
        "canvas": [width, height],
        "sources": [Path(s).name for s in sources],
        "plan": plan.to_dict(),
        "beats": [b.to_dict() for b in beats],
        "reframed": reframed,
        "captions": captions_note,
        "captioned_beats": captioned_beats,
        "music": Path(music_path).name if music_path else "",
        "beat_synced": round(60000.0 / beat_ms, 1) if beat_ms else False,
        "timeline_ms": edl.total_timeline_ms(),
    }
    return ReelResult(edl=edl, plan=plan, moments_by_clip=moments_by_clip, manifest=manifest)


def _assemble_reel_captions(
    edl: EDL,
    beats: list[_director.ClipBeat],
    sources: list[str],
    cap_fn: Callable,
    *,
    fps: int,
    colours: BrandColours,
    n: int,
) -> tuple[Optional[dict], int]:
    """Caption the first ``n`` beats, each offset to its place on the timeline.

    Builds each caption over the *actual EDL clip window* (so beat-sync and
    per-beat weights are reflected), rebases it to that clip's dominant-start
    frame (:meth:`EDL.clip_start_offsets_ms`), and merges them into one track.
    Beats with no speech (or ASR off) are skipped honestly. Returns
    ``(merged_track_or_None, count_actually_captioned)``.
    """
    from mediahub.video import captions as _captions

    offsets = edl.clip_start_offsets_ms()
    tracks: list[Optional[dict]] = []
    captioned = 0
    for i in range(min(n, len(beats), len(edl.clips))):
        beat = beats[i]
        clip = edl.clips[i]
        try:
            src = sources[beat.asset_index]
        except (IndexError, KeyError):
            continue
        track = cap_fn(
            src,
            in_ms=clip.in_ms,
            out_ms=clip.out_ms,
            fps=fps,
            ground=colours.ground,
            onground=colours.onground,
            accent=colours.accent,
        )
        if not track:
            continue
        off_frames = round(offsets[i] / 1000 * fps)
        tracks.append(_captions.offset_track(track, off_frames))
        captioned += 1
    merged = _captions.merge_tracks(tracks)
    if merged and (colours.ground or colours.accent):
        merged = _captions.restyle(
            merged, ground=colours.ground, onground=colours.onground, accent=colours.accent
        )
    return merged, captioned


def _default_probe(source: str) -> ClipProbe:
    from mediahub.video.probe import probe_clip

    return probe_clip(source)


def _default_caption(source: str, **kw) -> Optional[dict]:
    from mediahub.video import captions as _captions

    return _captions.windowed_caption_track(source, **kw)


def _default_karaoke_caption(source: str, **kw) -> Optional[dict]:
    from mediahub.video import captions as _captions

    return _captions.windowed_karaoke_track(source, **kw)


__all__ = [
    "DEFAULT_FORMAT",
    "ReelResult",
    "resolve_music",
    "build_reel_edl",
    "make_reel",
]
