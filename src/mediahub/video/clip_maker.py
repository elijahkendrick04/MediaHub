"""video/clip_maker.py — Clip-Maker-for-sport: footage → branded cut (1.6).

This is the centrepiece of the video suite. A club uploads a two-minute phone
clip of a race; Clip-Maker turns it into a short, vertical, captioned, branded
highlight with the same approval flow as everything else:

    probe → detect the moment(s) (deterministic) → reframe to the target shape
    (saliency) → caption from the transcript (ASR) → assemble a branded EDL

It is an **assembler over the engine pieces**, not new intelligence: the moment
detection (``moments``), the reframe maths (``reframe``), the caption track
(``captions``/``transcribe``) and the timeline compiler (``edl``) each own their
own correctness. The only judgement here — optionally naming a moment — is the
AI label, kept off the deterministic path.

The split that keeps this testable: :func:`build_clip_edl` is a **pure
function** (probe + chosen moments + crops + caption track → EDL), unit-tested
with no FFmpeg; :func:`clip_maker` is the impure orchestrator that gathers those
inputs from the (FFmpeg-backed) engine pieces and is injectable end-to-end for
tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from mediahub.video import captions as _captions
from mediahub.video import moments as _moments
from mediahub.video import reframe as _reframe
from mediahub.video.edl import EDL, Clip, TextOverlay, Transition
from mediahub.video.moments import Moment
from mediahub.video.probe import ClipProbe

# Canvas sizes — single source of truth is visual.motion.MOTION_FORMATS.
try:
    from mediahub.visual.motion import MOTION_FORMATS as _MOTION_FORMATS
except Exception:  # pragma: no cover - motion always imports in practice
    _MOTION_FORMATS = {
        "story": (1080, 1920),
        "portrait": (1080, 1350),
        "square": (1080, 1080),
        "landscape": (1920, 1080),
    }

DEFAULT_FORMAT = "story"
DEFAULT_BACKGROUND = "#0A0A0A"


@dataclass(frozen=True)
class BrandColours:
    """The colours Clip-Maker styles captions + padding with (caller-resolved)."""

    ground: str = ""
    onground: str = ""
    accent: str = ""
    background: str = DEFAULT_BACKGROUND


@dataclass
class ClipMakerResult:
    """The product: the timeline, the moments behind it, and an explainability map."""

    edl: EDL
    moments: list[Moment] = field(default_factory=list)
    manifest: dict = field(default_factory=dict)


def canvas_for(format_name: str) -> tuple[int, int]:
    """The (width, height) for a motion format, defaulting to story."""
    return _MOTION_FORMATS.get(format_name, _MOTION_FORMATS[DEFAULT_FORMAT])


def build_clip_edl(
    source: str,
    probe: ClipProbe,
    chosen: list[Moment],
    *,
    format_name: str = DEFAULT_FORMAT,
    crops: Optional[list] = None,
    caption_track: Optional[dict] = None,
    title: str = "",
    colours: Optional[BrandColours] = None,
    transition_kind: str = "cut",
    transition_ms: int = 400,
    fps: int = 30,
) -> EDL:
    """Assemble an EDL from chosen moments + per-moment crops + a caption track.

    Pure and deterministic: no FFmpeg, no transcription — those happen in
    :func:`clip_maker` and are passed in. Each moment becomes one clip on the
    target canvas; the first joins with a hard cut, the rest with the chosen
    transition. The caption track and an optional brand title ride on top.
    """
    colours = colours or BrandColours()
    width, height = canvas_for(format_name)
    crops = crops or []

    clips: list[Clip] = []
    for i, m in enumerate(chosen):
        crop = crops[i] if i < len(crops) and crops[i] else None
        trans = Transition("cut") if i == 0 else Transition(transition_kind, transition_ms)
        clips.append(
            Clip(
                source=source,
                in_ms=m.start_ms,
                out_ms=m.end_ms,
                crop=tuple(crop) if crop else None,  # type: ignore[arg-type]
                transition_in=trans,
            )
        )
    if not clips:
        # No moment at all (degenerate input): keep the opening few seconds.
        end = min(probe.duration_ms or 6000, 6000)
        clips = [Clip(source=source, in_ms=0, out_ms=end)]

    overlays: list[TextOverlay] = []
    if title.strip():
        overlays.append(
            TextOverlay(text=title.strip(), start_ms=0, duration_ms=2200, position="lower-third")
        )

    # Restyle the caption track to the brand ground (deterministic colour-science).
    track = caption_track
    if track and (colours.ground or colours.accent):
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
        background=colours.background or DEFAULT_BACKGROUND,
    )


def clip_maker(
    source: Path | str,
    *,
    format_name: str = DEFAULT_FORMAT,
    target_moments: int = 1,
    target_len_ms: int = 6000,
    with_captions: bool = True,
    with_reframe: bool = True,
    title: str = "",
    colours: Optional[BrandColours] = None,
    transition_kind: str = "cut",
    transition_ms: int = 400,
    label_moments: bool = False,
    fps: int = 30,
    # Injection seams (default to the real, FFmpeg-backed engine pieces):
    probe_fn: Optional[Callable] = None,
    detect_fn: Optional[Callable] = None,
    reframe_fn: Optional[Callable] = None,
    caption_fn: Optional[Callable] = None,
) -> ClipMakerResult:
    """Turn a footage clip into a branded :class:`ClipMakerResult`.

    Deterministic where it matters: the same clip yields the same moments,
    crops, and timeline. Captions ride only on the single-moment cut (a
    multi-moment montage has no single transcript timeline — honest gap, noted
    in the manifest). The optional ``label_moments`` adds AI moment names, which
    never change which moments were detected.
    """
    source = str(source)
    colours = colours or BrandColours()
    width, height = canvas_for(format_name)
    fps = max(1, fps)

    probe = (probe_fn or _default_probe)(source)
    duration_ms = probe.duration_ms

    detect = detect_fn or _moments.detect_moments
    chosen = detect(
        source, duration_ms=duration_ms, target_len_ms=target_len_ms, max_moments=target_moments
    )
    chosen = list(chosen)[:target_moments]

    if label_moments:
        labelled: list[Moment] = []
        for m in chosen:
            name = _moments.label_moment(m.reason, context=title)
            labelled.append(Moment(m.start_ms, m.end_ms, m.score, m.kind, m.reason, label=name))
        chosen = labelled

    # Reframe (saliency) — only when the source shape differs from the canvas.
    crops: list = []
    dw, dh = probe.display_size
    reframed = False
    if with_reframe and _reframe.needs_reframe(dw, dh, width, height):
        rf = reframe_fn or _reframe.reframe_clip_crop
        for m in chosen:
            crop = rf(source, in_ms=m.start_ms, out_ms=m.end_ms, dst_w=width, dst_h=height)
            crops.append(crop)
            reframed = reframed or bool(crop)

    # Captions — single-moment only (verbatim transcript over that window).
    caption_track: Optional[dict] = None
    captions_note = "off"
    if with_captions and chosen:
        if target_moments == 1:
            cap = caption_fn or _captions.windowed_caption_track
            caption_track = cap(
                source,
                in_ms=chosen[0].start_ms,
                out_ms=chosen[0].end_ms,
                fps=fps,
                ground=colours.ground,
                onground=colours.onground,
                accent=colours.accent,
            )
            captions_note = "burned" if caption_track else "no-speech-or-asr-off"
        else:
            captions_note = "skipped-multimoment"

    edl = build_clip_edl(
        source,
        probe,
        chosen,
        format_name=format_name,
        crops=crops,
        caption_track=caption_track,
        title=title,
        colours=colours,
        transition_kind=transition_kind,
        transition_ms=transition_ms,
        fps=fps,
    )

    manifest = {
        "source": Path(source).name,
        "format": format_name,
        "canvas": [width, height],
        "source_duration_ms": duration_ms,
        "source_orientation": probe.orientation,
        "moments": [m.to_dict() for m in chosen],
        "reframed": reframed,
        "captions": captions_note,
        "timeline_ms": edl.total_timeline_ms(),
    }
    return ClipMakerResult(edl=edl, moments=chosen, manifest=manifest)


def _default_probe(source: str) -> ClipProbe:
    from mediahub.video.probe import probe_clip

    return probe_clip(source)


__all__ = [
    "BrandColours",
    "ClipMakerResult",
    "DEFAULT_FORMAT",
    "canvas_for",
    "build_clip_edl",
    "clip_maker",
]
