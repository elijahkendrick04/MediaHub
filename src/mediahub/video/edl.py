"""video/edl.py — the Edit Decision List and its FFmpeg filter-graph compiler.

An **EDL** is the timeline: an ordered list of clips (each a trimmed,
optionally sped-up / reframed / muted slice of a source video), the joins
between them (a hard cut or a named transition), title overlays, and an
optional caption track — laid onto a fixed canvas (width/height/fps). It is the
data the footage path (roadmap 1.6) edits and renders, the equivalent of the
``CreativeBrief`` for the data-driven reels: **data, kept separate from
rendering.**

This module is the **deterministic engine** for that timeline. It validates an
EDL and compiles it to an FFmpeg ``-filter_complex`` graph. There is no AI and
no randomness here — the same EDL always compiles to the same graph, which is
what makes a render content-cacheable (``render.py``) and unit-testable with no
FFmpeg binary present (the compile is a pure function over the data).

Design choices that keep the graph correct *and* simple:

* **One running composite.** Clips are joined left-to-right onto a single
  running label: a *cut* concatenates (``concat=n=2``), a *transition*
  cross-fades (``xfade`` / ``acrossfade``) with the offset computed from the
  running duration. This chains correctly for any mix of cuts and transitions
  without the "all-or-nothing" restriction a single ``concat`` would impose.
* **Every clip is normalised to the canvas** (scale-to-fit + pad + ``fps`` +
  ``format``) *before* it is joined, so ``concat`` / ``xfade`` always see
  matching geometry — the usual cause of a broken filter graph.
* **Speed folds into one ``setpts``** for video and an ``atempo`` chain for
  audio (so a 4× or 0.25× clip stays in atempo's valid per-stage range).
* **Captions are not compiled here.** They are an overlay burned by
  ``render.py`` (it owns the temp ASS path); the EDL only *carries* the track.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

TRACK_KINDS = ("video", "audio", "caption", "graphic")

# Speed is bounded so a clip can be slowed for a race-finish or sped for a warm-up
# montage, but never to a degree that makes the atempo chain absurd or the PTS
# maths lose precision. Mirrors the spirit of the ranker's fixed, tuned weights.
MIN_SPEED = 0.25
MAX_SPEED = 4.0

# Transition name → FFmpeg xfade transition. "cut" is the hard join (concat),
# handled specially (it is not an xfade). The set is deliberately small and
# legible — a sport clip needs a few honest joins, not Premiere's catalogue.
TRANSITIONS: dict[str, str] = {
    "cut": "",  # hard join (concat); no xfade
    "fade": "fade",  # through black/blend
    "dissolve": "dissolve",
    "wipeleft": "wipeleft",
    "wiperight": "wiperight",
    "slideup": "slideup",
    "slidedown": "slidedown",
    "smoothleft": "smoothleft",
    "circleopen": "circleopen",
}

# Valid title-overlay positions. The position → on-screen placement mapping
# lives in ``subtitle_burn`` (titles are burned via libass/ASS, not drawtext,
# because the deployment's static FFmpeg ships libass but not the drawtext
# filter — the same proven path the caption track already uses).
OVERLAY_POSITIONS: tuple[str, ...] = ("top", "center", "bottom", "lower-third")

DEFAULT_TRANSITION_MS = 500


class EDLError(ValueError):
    """Raised when an EDL is structurally invalid (an honest, specific error)."""


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass
class Transition:
    """A join into a clip: a hard ``cut`` (default) or a named cross-fade."""

    kind: str = "cut"
    duration_ms: int = DEFAULT_TRANSITION_MS

    @property
    def is_cut(self) -> bool:
        return self.kind == "cut" or self.duration_ms <= 0

    def to_dict(self) -> dict:
        return {"kind": self.kind, "duration_ms": int(self.duration_ms)}

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "Transition":
        d = d or {}
        return cls(
            kind=str(d.get("kind", "cut")),
            duration_ms=int(d.get("duration_ms", DEFAULT_TRANSITION_MS)),
        )


@dataclass
class Clip:
    """One slice of a source video on the timeline.

    ``in_ms``/``out_ms`` are offsets *inside the source*; ``speed`` retimes it;
    ``mute`` drops its audio; ``crop`` is an optional reframe rectangle
    ``(x, y, w, h)`` in source pixels (from ``reframe.py``); ``transition_in``
    is the join from the previous clip.
    """

    source: str  # absolute path to the source clip on disk
    in_ms: int = 0
    out_ms: int = 0  # 0 → "to the end"; resolved against the probe at render time
    speed: float = 1.0
    mute: bool = False
    crop: Optional[tuple[int, int, int, int]] = None
    transition_in: Transition = field(default_factory=Transition)

    @property
    def source_span_ms(self) -> int:
        """Length taken from the source (before retiming). 0 ⇒ unresolved."""
        return max(0, self.out_ms - self.in_ms)

    @property
    def timeline_ms(self) -> int:
        """Length on the timeline after ``speed`` (before any transition overlap)."""
        span = self.source_span_ms
        return round(span / self.speed) if span and self.speed > 0 else 0

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "in_ms": int(self.in_ms),
            "out_ms": int(self.out_ms),
            "speed": float(self.speed),
            "mute": bool(self.mute),
            "crop": list(self.crop) if self.crop else None,
            "transition_in": self.transition_in.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Clip":
        crop = d.get("crop")
        return cls(
            source=str(d.get("source", "")),
            in_ms=int(d.get("in_ms", 0)),
            out_ms=int(d.get("out_ms", 0)),
            speed=float(d.get("speed", 1.0)),
            mute=bool(d.get("mute", False)),
            crop=tuple(int(v) for v in crop) if crop else None,  # type: ignore[arg-type]
            transition_in=Transition.from_dict(d.get("transition_in")),
        )


@dataclass
class TextOverlay:
    """A title/caption-free text layer drawn over the composite for a window."""

    text: str
    start_ms: int = 0
    duration_ms: int = 2000
    position: str = "lower-third"

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "start_ms": int(self.start_ms),
            "duration_ms": int(self.duration_ms),
            "position": self.position,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TextOverlay":
        return cls(
            text=str(d.get("text", "")),
            start_ms=int(d.get("start_ms", 0)),
            duration_ms=int(d.get("duration_ms", 2000)),
            position=str(d.get("position", "lower-third")),
        )


@dataclass
class EDL:
    """A full timeline: canvas + clip sequence + overlays + caption track."""

    width: int = 1080
    height: int = 1920
    fps: int = 30
    clips: list[Clip] = field(default_factory=list)
    overlays: list[TextOverlay] = field(default_factory=list)
    captions: Optional[dict] = None  # a subtitle_burn track dict, or None
    keep_audio: bool = True
    background: str = "#000000"  # pad colour for letter/pillar-boxed clips

    def total_timeline_ms(self) -> int:
        """Composite duration: sum of clip timelines minus transition overlaps."""
        total = 0
        for i, clip in enumerate(self.clips):
            total += clip.timeline_ms
            if i > 0 and not clip.transition_in.is_cut:
                total -= max(0, clip.transition_in.duration_ms)
        return max(0, total)

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "clips": [c.to_dict() for c in self.clips],
            "overlays": [o.to_dict() for o in self.overlays],
            "captions": self.captions,
            "keep_audio": self.keep_audio,
            "background": self.background,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EDL":
        return cls(
            width=int(d.get("width", 1080)),
            height=int(d.get("height", 1920)),
            fps=int(d.get("fps", 30)),
            clips=[Clip.from_dict(c) for c in (d.get("clips") or [])],
            overlays=[TextOverlay.from_dict(o) for o in (d.get("overlays") or [])],
            captions=d.get("captions"),
            keep_audio=bool(d.get("keep_audio", True)),
            background=str(d.get("background", "#000000")),
        )


@dataclass(frozen=True)
class CompiledGraph:
    """The pure product of :func:`compile_filtergraph`.

    ``inputs`` are the ordered source paths (each becomes one ``-i`` arg);
    ``filter_complex`` is the graph; ``vout``/``aout`` are the final labels to
    ``-map`` (``aout`` is ``None`` when the EDL carries no audio).
    """

    inputs: tuple[str, ...]
    filter_complex: str
    vout: str
    aout: Optional[str]


# --------------------------------------------------------------------------
# Validation (deterministic; raises EDLError)
# --------------------------------------------------------------------------


def validate(edl: EDL) -> None:
    """Raise :class:`EDLError` on any structurally invalid timeline.

    Pure and total: never touches disk (a missing source file is the renderer's
    concern, not the timeline's shape). Checks canvas sanity, ≥1 clip, per-clip
    in<out / speed bounds / crop positivity, and known transition + overlay
    names — the invariants the compiler relies on.
    """
    if edl.width <= 0 or edl.height <= 0:
        raise EDLError(f"canvas must be positive, got {edl.width}x{edl.height}")
    if not (1 <= edl.fps <= 120):
        raise EDLError(f"fps out of range (1..120): {edl.fps}")
    if not edl.clips:
        raise EDLError("an EDL needs at least one clip")
    for i, c in enumerate(edl.clips):
        if not c.source:
            raise EDLError(f"clip {i} has no source")
        if c.in_ms < 0 or c.out_ms < 0:
            raise EDLError(f"clip {i} has a negative in/out point")
        if c.out_ms and c.out_ms <= c.in_ms:
            raise EDLError(f"clip {i}: out_ms ({c.out_ms}) must exceed in_ms ({c.in_ms})")
        if not (MIN_SPEED <= c.speed <= MAX_SPEED):
            raise EDLError(f"clip {i}: speed {c.speed} outside [{MIN_SPEED}, {MAX_SPEED}]")
        if c.crop is not None:
            if len(c.crop) != 4 or any(v < 0 for v in c.crop) or c.crop[2] <= 0 or c.crop[3] <= 0:
                raise EDLError(f"clip {i}: crop must be (x,y,w,h) with w,h>0, got {c.crop}")
        t = c.transition_in
        if t.kind not in TRANSITIONS:
            raise EDLError(f"clip {i}: unknown transition {t.kind!r}; valid: {sorted(TRANSITIONS)}")
        if i == 0 and not t.is_cut:
            raise EDLError("the first clip cannot have a transition_in (nothing precedes it)")
    for j, o in enumerate(edl.overlays):
        if o.position not in OVERLAY_POSITIONS:
            raise EDLError(
                f"overlay {j}: unknown position {o.position!r}; valid: {sorted(OVERLAY_POSITIONS)}"
            )


# --------------------------------------------------------------------------
# Pure FFmpeg-fragment builders (each unit-tested without a binary)
# --------------------------------------------------------------------------


def _ms_to_s(ms: int) -> str:
    """Milliseconds → a fixed-precision seconds literal (stable, locale-free)."""
    return f"{max(0, int(ms)) / 1000:.3f}"


def atempo_chain(speed: float) -> str:
    """Decompose ``speed`` into a chain of atempo stages each within [0.5, 2.0].

    FFmpeg's ``atempo`` only accepts 0.5–2.0 per stage, so 4× becomes
    ``atempo=2.0,atempo=2.0`` and 0.25× becomes ``atempo=0.5,atempo=0.5``.
    Deterministic; returns ``""`` for unit speed.
    """
    if abs(speed - 1.0) < 1e-6 or speed <= 0:
        return ""
    stages: list[float] = []
    remaining = speed
    while remaining > 2.0 + 1e-9:
        stages.append(2.0)
        remaining /= 2.0
    while remaining < 0.5 - 1e-9:
        stages.append(0.5)
        remaining /= 0.5
    stages.append(round(remaining, 6))
    return ",".join(f"atempo={s:g}" for s in stages)


def video_clip_chain(
    idx: int, clip: Clip, *, width: int, height: int, fps: int, background: str
) -> str:
    """The filter chain that turns input ``idx``'s video into a canvas-fit clip.

    trim → reset PTS (folding in speed) → optional reframe crop → scale-to-fit →
    pad to canvas → fps → format. Ends with the ``[v{idx}]`` label.
    """
    parts = [f"[{idx}:v]"]
    if clip.out_ms:
        parts.append(f"trim=start={_ms_to_s(clip.in_ms)}:end={_ms_to_s(clip.out_ms)}")
    elif clip.in_ms:
        parts.append(f"trim=start={_ms_to_s(clip.in_ms)}")
    # Reset the timestamp origin and fold speed into one setpts (speed>1 ⇒ /speed).
    if abs(clip.speed - 1.0) < 1e-6:
        parts.append("setpts=PTS-STARTPTS")
    else:
        parts.append(f"setpts=(PTS-STARTPTS)/{clip.speed:g}")
    if clip.crop:
        x, y, w, h = clip.crop
        parts.append(f"crop={w}:{h}:{x}:{y}")
    parts.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease")
    parts.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={_pad_colour(background)}")
    parts.append("setsar=1")
    parts.append(f"fps={fps}")
    parts.append("format=yuv420p")
    chain = parts[0] + ",".join(parts[1:]) if len(parts) > 1 else parts[0]
    return f"{chain}[v{idx}]"


def audio_clip_chain(idx: int, clip: Clip, *, keep_audio: bool, has_audio: bool) -> str:
    """The audio chain for input ``idx``, or a silent source when muted/absent.

    A muted clip, a clip on a silent source, or a globally audio-free EDL gets a
    real silence segment of the right *timeline* length, so the audio
    concat/cross-fade stays sample-aligned with the video. Ends with ``[a{idx}]``.
    """
    silent = (not keep_audio) or clip.mute or (not has_audio)
    if silent:
        dur = _ms_to_s(clip.timeline_ms or clip.source_span_ms or 1000)
        return (
            f"anullsrc=channel_layout=stereo:sample_rate=44100,"
            f"atrim=duration={dur},asetpts=PTS-STARTPTS[a{idx}]"
        )
    parts = [f"[{idx}:a]"]
    if clip.out_ms:
        parts.append(f"atrim=start={_ms_to_s(clip.in_ms)}:end={_ms_to_s(clip.out_ms)}")
    elif clip.in_ms:
        parts.append(f"atrim=start={_ms_to_s(clip.in_ms)}")
    parts.append("asetpts=PTS-STARTPTS")
    tempo = atempo_chain(clip.speed)
    if tempo:
        parts.append(tempo)
    parts.append("aresample=44100")
    chain = parts[0] + ",".join(parts[1:])
    return f"{chain}[a{idx}]"


def _pad_colour(background: str) -> str:
    """A pad-safe colour token (``#RRGGBB`` → ``0xRRGGBB``; else as-is)."""
    b = (background or "").strip()
    if b.startswith("#") and len(b) == 7:
        return "0x" + b[1:]
    return b or "black"


# --------------------------------------------------------------------------
# The compiler
# --------------------------------------------------------------------------


def compile_filtergraph(
    edl: EDL,
    *,
    probes: Optional[dict[str, int]] = None,
    audio: Optional[dict[str, bool]] = None,
) -> CompiledGraph:
    """Compile a validated ``edl`` to a :class:`CompiledGraph` (pure, no I/O).

    Compiles the **structural timeline** — per-clip normalisation, speed, reframe
    crop, and the cut/transition joins — into one composite video + audio pair.
    Burned text (captions and title overlays) is *not* in this graph: it is
    layered on by ``render.py`` via libass/ASS (the path the deployment's FFmpeg
    actually supports). So a compiled graph's ``vout`` is the clip composite.

    ``probes`` optionally maps a clip ``source`` → its true duration in ms, used
    only to resolve a clip whose ``out_ms`` is 0 ("to the end") so the timeline
    maths and transition offsets are exact; absent, an open-ended clip is
    treated as 0-span (the caller is expected to resolve out points first, which
    ``clip_maker`` / the render path do).

    ``audio`` optionally maps a clip ``source`` → whether it carries an audio
    stream. A source with **no** audio gets a silence segment of the right length
    (so the audio concat/cross-fade stays aligned) instead of a dangling
    ``[i:a]`` reference that would crash FFmpeg. Unknown ⇒ assume present (the
    render path always supplies an accurate map from the probe).
    """
    validate(edl)
    probes = probes or {}
    audio = audio if audio is not None else {}

    # Resolve open-ended out points against probe durations so timeline maths is
    # exact. We work on shallow copies so the caller's EDL is never mutated.
    resolved: list[Clip] = []
    for c in edl.clips:
        out_ms = c.out_ms
        if not out_ms and c.source in probes:
            out_ms = probes[c.source]
        resolved.append(
            Clip(
                source=c.source,
                in_ms=c.in_ms,
                out_ms=out_ms,
                speed=c.speed,
                mute=c.mute,
                crop=c.crop,
                transition_in=c.transition_in,
            )
        )

    inputs = [c.source for c in resolved]
    lines: list[str] = []

    # 1) Per-clip normalisation chains.
    for i, c in enumerate(resolved):
        lines.append(
            video_clip_chain(
                i, c, width=edl.width, height=edl.height, fps=edl.fps, background=edl.background
            )
        )
        # Accurate audio-stream presence from the probe; unknown ⇒ assume present.
        has_audio = audio.get(c.source, True)
        lines.append(audio_clip_chain(i, c, keep_audio=edl.keep_audio, has_audio=has_audio))

    # 2) Join clips onto one running composite (cut → concat, else xfade).
    if len(resolved) == 1:
        vout, aout = "v0", "a0"
    else:
        vacc, aacc = "v0", "a0"
        running_ms = resolved[0].timeline_ms
        for i in range(1, len(resolved)):
            c = resolved[i]
            v_next, a_next = f"v{i}", f"a{i}"
            v_label, a_label = f"vx{i}", f"ax{i}"
            if c.transition_in.is_cut:
                lines.append(f"[{vacc}][{v_next}]concat=n=2:v=1:a=0[{v_label}]")
                lines.append(f"[{aacc}][{a_next}]concat=n=2:v=0:a=1[{a_label}]")
                running_ms += c.timeline_ms
            else:
                xname = TRANSITIONS[c.transition_in.kind] or "fade"
                dur_s = _ms_to_s(c.transition_in.duration_ms)
                offset_ms = max(0, running_ms - c.transition_in.duration_ms)
                lines.append(
                    f"[{vacc}][{v_next}]xfade=transition={xname}:"
                    f"duration={dur_s}:offset={_ms_to_s(offset_ms)}[{v_label}]"
                )
                lines.append(f"[{aacc}][{a_next}]acrossfade=d={dur_s}[{a_label}]")
                running_ms += c.timeline_ms - c.transition_in.duration_ms
            vacc, aacc = v_label, a_label
        vout, aout = vacc, aacc

    return CompiledGraph(
        inputs=tuple(inputs),
        filter_complex=";".join(lines),
        vout=vout,
        aout=aout,
    )


__all__ = [
    "TRACK_KINDS",
    "TRANSITIONS",
    "OVERLAY_POSITIONS",
    "MIN_SPEED",
    "MAX_SPEED",
    "EDLError",
    "Transition",
    "Clip",
    "TextOverlay",
    "EDL",
    "CompiledGraph",
    "validate",
    "atempo_chain",
    "video_clip_chain",
    "audio_clip_chain",
    "compile_filtergraph",
]
