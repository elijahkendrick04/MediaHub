"""visual/subtitle_burn.py — subtitle / caption burn-in engine (roadmap R1.3).

Most feed video autoplays **muted**, so the words a reel speaks have to also be
*on the screen*. ``visual/voiceover.py`` already emits a deterministic ``.srt``
beside every synthesised caption (built from the TTS engine's word-boundary
timings); this module is the deferred "burn the SRT into the frames" half it was
always waiting for.

It turns a voiceover SRT — or, for surfaces without per-clip timings, a plain
fact-only line — into a **frame-timed, APCA-gated caption track** that the two
renderers burn onto the video:

  * **Remotion** (default engine): the track is JSON-encoded into the StoryCard
    props (``captionsJson``) and painted by
    ``remotion/.../sprint/layers/captions.tsx`` — a frame-pure overlay that
    composites the captions into the rendered pixels.
  * **FFmpeg** (free fallback engine): the same track is written as an ASS
    subtitle document and burned with FFmpeg's ``ass`` filter.

Everything here is **deterministic** and holds the renderer's honesty contract:

- *No LLM, no judgement.* The caption words are the verbatim voiceover
  transcript (itself the fact-only ``narration.py`` template) or a card's own
  verified facts — never invented copy.
- *Colour is colour-science, not taste.* The caption ink + scrim are chosen by
  the deterministic APCA maths in ``theming/contrast.py`` — the same model the
  still renderer trusts — so a caption is legible on its brand ground by
  construction, never a hard-coded white.
- *Honest, non-fatal.* A missing/blank SRT or a synthesis failure yields
  ``None`` and the caller renders the video **without** captions. A caption
  overlay must never fail a render or fabricate timings.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from mediahub.theming.contrast import apca, pick_ink

# The Remotion compositions (and the FFmpeg engine) run at 30fps; callers pass
# the real fps so nothing here hard-codes the cadence.
FPS_DEFAULT = 30

# Caption legibility floor. Captions are large display text painted over a dense
# brand-ground scrim, so the APCA headline / non-text "Bronze" level
# (|Lc| >= 45) is the threshold a role colour must clear; below it we fall back
# to the maximal #000 / #FFF ink so a caption is *never* shipped illegible.
CAPTION_APCA_MIN = 45.0

# Word-grouping windows mirror ``voiceover.build_srt`` so a caption cue and the
# SRT cue it came from carry the same boundaries.
MAX_CUE_WORDS = 7
MAX_CUE_MS = 3000

# Reading-speed floor for the synthetic (no-timings) path: never flash a cue
# faster than this. ~0.42s/word ≈ the 2.4 words/sec narration rate.
MS_PER_WORD = 420
MIN_CUE_MS = 900


@dataclass(frozen=True)
class Cue:
    """One subtitle cue: ``text`` shown from ``start_ms`` to ``end_ms``."""

    start_ms: int
    end_ms: int
    text: str


# ---------------------------------------------------------------------------
# Hex helpers
# ---------------------------------------------------------------------------


def _norm_hex(value: str) -> str:
    """Return an uppercase ``#RRGGBB`` for a 3/6-digit hex, else ``""``.

    Tolerant by design — an unparseable colour just drops out of the caption
    candidate list rather than raising mid-render.
    """
    h = (value or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) == 6:
        try:
            int(h, 16)
        except ValueError:
            return ""
        return "#" + h.upper()
    return ""


# ---------------------------------------------------------------------------
# Read the voiceover SRT
# ---------------------------------------------------------------------------

_SRT_TS = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")


def _ts_to_ms(h: str, m: str, s: str, frac: str) -> int:
    ms = int((frac + "000")[:3])  # pad/truncate fractional to milliseconds
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + ms


def parse_srt(srt: str) -> list[Cue]:
    """Parse SRT text into ordered cues. Blank/garbled input yields ``[]``.

    Deliberately lenient: any block whose middle line carries a
    ``HH:MM:SS,mmm --> HH:MM:SS,mmm`` range is taken; everything after that
    line in the block is the cue text (newlines flattened to spaces).
    """
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", (srt or "").strip()):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        ts_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), -1)
        if ts_idx < 0:
            continue
        left, _, right = lines[ts_idx].partition("-->")
        ml, mr = _SRT_TS.search(left), _SRT_TS.search(right)
        if not ml or not mr:
            continue
        start = _ts_to_ms(*ml.groups())
        end = _ts_to_ms(*mr.groups())
        text = " ".join(ln.strip() for ln in lines[ts_idx + 1 :]).strip()
        if text and end > start:
            cues.append(Cue(start, end, text))
    return cues


# ---------------------------------------------------------------------------
# Synthetic cues (text without per-clip timings — e.g. a reel beat's own line)
# ---------------------------------------------------------------------------


def cues_from_text(text: str, total_ms: int) -> list[Cue]:
    """Group ``text`` into cues spread evenly across ``total_ms``.

    Used where there is no synthesised SRT to read (the reel captions each beat
    from its own verified facts). Pure and deterministic: words are grouped
    into ``MAX_CUE_WORDS`` chunks and given a share of the window proportional
    to their length, never tighter than ``MIN_CUE_MS``.
    """
    words = (text or "").split()
    if not words or total_ms <= 0:
        return []
    groups = [words[i : i + MAX_CUE_WORDS] for i in range(0, len(words), MAX_CUE_WORDS)]
    total_words = len(words)
    cues: list[Cue] = []
    acc = 0
    for g in groups:
        if len(groups) == 1:
            dur = total_ms
        else:
            dur = max(MIN_CUE_MS, round(total_ms * (len(g) / total_words)))
        cues.append(Cue(acc, acc + dur, " ".join(g)))
        acc += dur
    # The MIN_CUE_MS floor can push the tail past the window; scale back so the
    # last cue still lands inside ``total_ms`` (captions never outlive the clip).
    if cues and cues[-1].end_ms > total_ms:
        scale = total_ms / cues[-1].end_ms
        cues = [Cue(round(c.start_ms * scale), round(c.end_ms * scale), c.text) for c in cues]
    return cues


def cues_from_stamps(stamps) -> list[Cue]:
    """Group timed word (or segment) stamps into readable caption cues.

    The ASR path (roadmap 1.4): each ``stamp`` carries real measured timing —
    either a ``WordStamp``-like object (``.text``/``.start_ms``/``.end_ms``) or a
    ``(text, start_ms, end_ms)`` tuple — so, unlike :func:`cues_from_text`, the
    cue boundaries are *observed*, not spread. Stamps are grouped into the same
    ``MAX_CUE_WORDS`` / ``MAX_CUE_MS`` windows the voiceover SRT uses, so an
    ASR-driven caption reads at the same rhythm as a TTS-driven one. Pure and
    deterministic; malformed/empty stamps drop out rather than raising.
    """
    items: list[tuple[int, int, str]] = []
    for s in stamps or []:
        if isinstance(s, (tuple, list)) and len(s) >= 3:
            text, start, end = str(s[0]), s[1], s[2]
        else:
            text = str(getattr(s, "text", ""))
            start, end = getattr(s, "start_ms", None), getattr(s, "end_ms", None)
        text = text.strip()
        if not text or start is None or end is None:
            continue
        try:
            a, b = int(start), int(end)
        except (TypeError, ValueError):
            continue
        items.append((a, max(a, b), text))

    cues: list[Cue] = []
    cur: list[tuple[int, int, str]] = []

    def _flush() -> None:
        if not cur:
            return
        start = cur[0][0]
        end = max(w[1] for w in cur)
        text = " ".join(w[2] for w in cur).strip()
        if text and end > start:
            cues.append(Cue(start, end, text))

    for a, b, t in items:
        if cur:
            span = b - cur[0][0]
            if len(cur) >= MAX_CUE_WORDS or span > MAX_CUE_MS:
                _flush()
                cur = []
        cur.append((a, b, t))
    _flush()
    return cues


# ---------------------------------------------------------------------------
# APCA-gated caption colour (deterministic colour-science)
# ---------------------------------------------------------------------------


def caption_colours(ground: str, onground: str = "", accent: str = "") -> tuple[str, str]:
    """Pick ``(text_colour, scrim_colour)`` for a caption over a brand ground.

    The scrim is the card's own ground colour (painted at high alpha by the
    renderer, so it reads as a band of the brand colour). The ink is the most
    legible of the brand-priority candidates — the resolved ``onGround`` role,
    then ``accent``, then pure white/black — measured by APCA against that
    ground; if none clears :data:`CAPTION_APCA_MIN` we return the maximal
    ``pick_ink`` choice. Reusing the already-APCA-gated ``onGround`` role means
    the common case needs no second guess, and the fallback guarantees a
    caption is never shipped below the legibility floor.
    """
    g = _norm_hex(ground) or "#0A0B11"
    best, best_lc = "", -1.0
    for cand in (onground, accent, "#FFFFFF", "#000000"):
        c = _norm_hex(cand)
        if not c:
            continue
        lc = abs(apca(c, g))
        if lc > best_lc:
            best, best_lc = c, lc
    if not best or best_lc < CAPTION_APCA_MIN:
        best = pick_ink(g)[0]
    return best, g


# ---------------------------------------------------------------------------
# Frame-timed caption track
# ---------------------------------------------------------------------------


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def cues_to_frames(cues: list[Cue], *, fps: int = FPS_DEFAULT, total_frames: int = 0) -> list[dict]:
    """Convert millisecond cues into ``{from, dur, text}`` frame windows.

    Windows are clamped to ``total_frames`` (when > 0) so a slightly-overrunning
    final cue can never exceed the clip; a cue that starts at/after the end is
    dropped. ``from`` and ``dur`` are integers (Remotion ``<Sequence>`` needs
    integral frames; ``dur`` is always >= 1).
    """
    out: list[dict] = []
    for c in cues:
        start = round(c.start_ms / 1000 * fps)
        end = round(c.end_ms / 1000 * fps)
        if total_frames > 0:
            if start >= total_frames:
                continue
            start = _clamp(start, 0, total_frames - 1)
            end = _clamp(end, start + 1, total_frames)
        dur = max(1, end - start)
        text = (c.text or "").strip()
        if text:
            out.append({"from": start, "dur": dur, "text": text})
    return out


def build_track(
    cues: list[Cue],
    *,
    fps: int = FPS_DEFAULT,
    total_frames: int = 0,
    ground: str = "",
    onground: str = "",
    accent: str = "",
) -> dict | None:
    """Assemble the renderer-ready caption track, or ``None`` when empty.

    Shape (consumed by ``captions.tsx`` and :func:`ass_document`)::

        {"color": "#FFFFFF", "scrim": "#0A2540",
         "cues": [{"from": 0, "dur": 45, "text": "New PB"}, ...]}
    """
    frames = cues_to_frames(cues, fps=fps, total_frames=total_frames)
    if not frames:
        return None
    color, scrim = caption_colours(ground, onground, accent)
    return {"color": color, "scrim": scrim, "cues": frames}


def track_json(track: dict | None) -> str:
    """Serialise a track to the compact JSON string the props field carries.

    ``None`` → ``""`` so the silent/captions-off path leaves the prop empty and
    the layer renders nothing (byte-identical to a render without captions).
    """
    if not track:
        return ""
    return json.dumps(track, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# Track builders for the two motion surfaces
# ---------------------------------------------------------------------------


def story_caption_track(
    script: str,
    *,
    voice: str,
    duration_sec: float,
    fps: int = FPS_DEFAULT,
    ground: str = "",
    onground: str = "",
    accent: str = "",
) -> dict | None:
    """Read the voiceover SRT for ``script`` and build its caption track.

    Synthesises (or reuses the cache for) the spoken caption with
    ``apply_pronunciation=False`` so the on-screen words are the *original*
    spelling — a phonetic override ("Siobhan" → "Shiv-awn") belongs in the
    TTS, never burned onto the screen. Returns ``None`` on any failure so a
    render proceeds silently rather than aborting over a caption.
    """
    script = (script or "").strip()
    if not script:
        return None
    try:
        from mediahub.visual import voiceover

        result = voiceover.synthesize(script, voice=voice, apply_pronunciation=False)
        srt_text = result.srt_path.read_text() if result.srt_path.exists() else ""
        cues = parse_srt(srt_text)
        if not cues:
            cues = parse_srt(voiceover.build_srt(result.word_boundaries))
    except Exception:
        return None
    total_frames = max(1, round(float(duration_sec) * fps))
    return build_track(
        cues, fps=fps, total_frames=total_frames, ground=ground, onground=onground, accent=accent
    )


def text_caption_track(
    text: str,
    *,
    total_frames: int,
    fps: int = FPS_DEFAULT,
    ground: str = "",
    onground: str = "",
    accent: str = "",
) -> dict | None:
    """Build a caption track from a plain line spread over ``total_frames``.

    The no-SRT path: used to caption each reel beat from that card's own
    verified line (no extra synthesis). Deterministic.
    """
    text = (text or "").strip()
    if not text or total_frames <= 0:
        return None
    total_ms = round(total_frames / fps * 1000)
    return build_track(
        cues_from_text(text, total_ms),
        fps=fps,
        total_frames=total_frames,
        ground=ground,
        onground=onground,
        accent=accent,
    )


# ---------------------------------------------------------------------------
# FFmpeg burn-in (ASS subtitle document + filter)
# ---------------------------------------------------------------------------


def _ass_colour(hex_str: str, opacity: float = 1.0) -> str:
    """``#RRGGBB`` → ASS ``&HAABBGGRR`` (alpha inverted: 00 opaque, FF clear)."""
    h = _norm_hex(hex_str).lstrip("#") or "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    a = round((1.0 - max(0.0, min(1.0, opacity))) * 255)
    return f"&H{a:02X}{b}{g}{r}"


def _ass_ts(ms: int) -> str:
    """Milliseconds → ASS ``H:MM:SS.cc`` (centisecond) timestamp."""
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, msec = divmod(rem, 1000)
    cs = min(99, round(msec / 10))
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_text(text: str) -> str:
    """Sanitise cue text for an ASS Dialogue line (no override-tag injection)."""
    return (
        (text or "")
        .replace("\\", "⧵")  # neutralise stray backslashes
        .replace("{", "(")
        .replace("}", ")")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
    )


def ass_document(track: dict, *, width: int, height: int, fps: int = FPS_DEFAULT) -> str:
    """Render a caption ``track`` as a self-contained ASS subtitle document.

    Bottom-centred, an opaque brand-ground box (``BorderStyle=4``) behind the
    APCA-gated ink, with the same lower-band placement the Remotion layer uses
    (a touch higher on tall cuts to clear platform chrome). Deterministic.
    """
    color = track.get("color") or "#FFFFFF"
    scrim = track.get("scrim") or "#000000"
    primary = _ass_colour(color, 1.0)
    box = _ass_colour(scrim, 0.82)
    fontsize = max(16, round(min(width, height) * 0.040))
    margin_v = round(height * (0.09 if width > height else 0.14))
    side = round(width * 0.09)
    head = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        f"PlayResX: {int(width)}",
        f"PlayResY: {int(height)}",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding"
        ),
        (
            f"Style: Caption,Inter,{fontsize},{primary},{primary},{box},{box},"
            f"-1,0,0,0,100,100,0,0,4,0,0,2,{side},{side},{margin_v},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events = [
        f"Dialogue: 0,{_ass_ts(round(c['from'] / fps * 1000))},"
        f"{_ass_ts(round((c['from'] + c['dur']) / fps * 1000))},Caption,,0,0,0,,"
        f"{_ass_text(c['text'])}"
        for c in track.get("cues", [])
    ]
    return "\n".join(head + events) + "\n"


def ass_filter(ass_path: str) -> str:
    """An FFmpeg ``-vf`` token that burns ``ass_path`` onto the video.

    Escapes the filtergraph metacharacters (``\\`` and ``:``) in the path so a
    normal temp path drops straight into a filter chain.
    """
    escaped = str(ass_path).replace("\\", "\\\\").replace(":", "\\:")
    return f"ass={escaped}"


# Title position → (ASS alignment numpad, vertical margin as a fraction of H).
# Burned via libass too (the deployment's FFmpeg has libass but not drawtext),
# so a title and a bottom caption don't collide: "lower-third" sits well above
# the caption band.
_TITLE_ALIGN: dict[str, tuple[int, float]] = {
    "top": (8, 0.10),
    "center": (5, 0.0),
    "bottom": (2, 0.16),
    "lower-third": (2, 0.30),
}


def titles_ass_document(
    overlays: list[dict],
    *,
    width: int,
    height: int,
    fps: int = FPS_DEFAULT,
    color: str = "#FFFFFF",
    scrim: str = "#0A0A0A",
) -> str:
    """Render positioned title overlays as a self-contained ASS document.

    Each overlay is ``{"text", "start_ms", "duration_ms", "position"}`` (the
    ``video.edl.TextOverlay`` shape). Titles are bolder than captions and sit at
    their requested position via the libass alignment; the brand ``scrim`` backs
    each line so it reads on any footage. Deterministic.
    """
    primary = _ass_colour(color, 1.0)
    box = _ass_colour(scrim, 0.78)
    fontsize = max(20, round(min(width, height) * 0.050))
    side = round(width * 0.08)
    head = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        f"PlayResX: {int(width)}",
        f"PlayResY: {int(height)}",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding"
        ),
    ]
    events = ["", "[Events]",
              "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    styles: list[str] = []
    seen_aligns: set[int] = set()
    for o in overlays:
        align, mv_frac = _TITLE_ALIGN.get(str(o.get("position", "lower-third")), (2, 0.30))
        margin_v = round(height * mv_frac)
        style_name = f"Title{align}"
        if align not in seen_aligns:
            styles.append(
                f"Style: {style_name},Inter,{fontsize},{primary},{primary},{box},{box},"
                f"-1,0,0,0,100,100,0,0,4,0,0,{align},{side},{side},{margin_v},1"
            )
            seen_aligns.add(align)
        start_ms = int(o.get("start_ms", 0))
        end_ms = start_ms + int(o.get("duration_ms", 2000))
        text = _ass_text(str(o.get("text", "")))
        if not text:
            continue
        events.append(
            f"Dialogue: 0,{_ass_ts(start_ms)},{_ass_ts(end_ms)},{style_name},,0,0,0,,{text}"
        )
    return "\n".join(head + styles + events) + "\n"


__all__ = [
    "Cue",
    "FPS_DEFAULT",
    "CAPTION_APCA_MIN",
    "parse_srt",
    "cues_from_text",
    "cues_from_stamps",
    "caption_colours",
    "cues_to_frames",
    "build_track",
    "track_json",
    "story_caption_track",
    "text_caption_track",
    "ass_document",
    "titles_ass_document",
    "ass_filter",
]
