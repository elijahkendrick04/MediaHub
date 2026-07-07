"""video/caption_render.py — animated (karaoke) caption burning for footage (1.6).

Static captions (one box per line) are burned by the shared
``visual.subtitle_burn.ass_document``. Modern short-form reels also want the
**word-by-word "active word" caption** (the Submagic/Captions.ai look): the line
shows and the highlight sweeps across each word as it is spoken. That is the
signature reel caption style, and it is **deterministic** — ASS karaoke (``\\kf``)
tags over the *verbatim* word timings the ASR already produced, no AI writing.

This lives in the **video package**, not in the shared ``subtitle_burn``, so the
data-driven reel engine's caption output stays byte-for-byte identical — the
footage path simply chooses the karaoke renderer when its track carries
``style="karaoke"`` and word stamps; otherwise it falls back to the shared static
renderer unchanged.

The document builder is a pure function (unit-tested with no FFmpeg); only the
caller (``render.py``) writes it to disk and burns it via libass.
"""

from __future__ import annotations

from mediahub.video.caption_fonts import ass_font_family
from mediahub.visual.subtitle_burn import (
    FPS_DEFAULT,
    _ass_colour,
    _ass_text,
    _ass_ts,
    ass_document,
)


def is_karaoke(track: dict | None) -> bool:
    """True when a caption track asks for the animated (karaoke) style."""
    return bool(track) and str(track.get("style") or "").lower() == "karaoke"


def ass_for_track(track: dict, *, width: int, height: int, fps: int = FPS_DEFAULT) -> str:
    """Render a caption ``track`` to ASS, picking the karaoke or static builder.

    The single entry point ``render.py`` uses: an animated track routes to
    :func:`karaoke_ass_document`; everything else falls through to the shared,
    unchanged ``subtitle_burn.ass_document`` so the static path is identical.
    """
    if is_karaoke(track):
        return karaoke_ass_document(track, width=width, height=height, fps=fps)
    return ass_document(track, width=width, height=height, fps=fps)


def _karaoke_line(cue: dict, *, fps: int) -> str:
    """The ``{\\kf}``-tagged text for one cue (a continuous word-fill sweep).

    Each word carries a frame ``dur``; ``\\kf`` takes centiseconds, so the
    sweep highlights word N over its own duration. A cue with no word stamps
    falls back to its plain text (a still line), so karaoke never *loses* a
    caption just because the ASR gave only segment timing.
    """
    words = cue.get("words") or []
    if not words:
        return _ass_text(cue.get("text", ""))
    parts: list[str] = []
    for w in words:
        cs = max(1, round(int(w.get("dur", 1)) / fps * 100))
        parts.append(f"{{\\kf{cs}}}{_ass_text(w.get('text', ''))} ")
    return "".join(parts).rstrip()


def karaoke_ass_document(track: dict, *, width: int, height: int, fps: int = FPS_DEFAULT) -> str:
    """Render a word-timed caption ``track`` as an animated ASS document.

    Same bottom-centred, brand-ground-box placement as the static captions, but
    the line's words fill from the base ink (``SecondaryColour``) to the brand
    accent (``PrimaryColour``) in time with the speech — the "active word" sweep.
    Deterministic: the same track always compiles to the same document.
    """
    base = track.get("color") or "#FFFFFF"
    accent = track.get("accent") or base  # no accent ⇒ no visible sweep (still legible)
    scrim = track.get("scrim") or "#000000"
    primary = _ass_colour(accent, 1.0)  # post-sweep highlight
    secondary = _ass_colour(base, 1.0)  # pre-sweep base ink
    box = _ass_colour(scrim, 0.82)
    fontsize = max(16, round(min(width, height) * 0.042))
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
            # M28: the family must be one of the six self-hosted brand faces —
            # render.py provisions the ttf + FONTCONFIG_FILE so libass resolves
            # it to the repo's own bytes, never a substituted system font.
            f"Style: Caption,{ass_font_family(track.get('font_family'))},{fontsize},"
            f"{primary},{secondary},{box},{box},"
            f"-1,0,0,0,100,100,0,0,4,0,0,2,{side},{side},{margin_v},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events = [
        f"Dialogue: 0,{_ass_ts(round(c['from'] / fps * 1000))},"
        f"{_ass_ts(round((c['from'] + c['dur']) / fps * 1000))},Caption,,0,0,0,,"
        f"{_karaoke_line(c, fps=fps)}"
        for c in track.get("cues", [])
    ]
    return "\n".join(head + events) + "\n"


__all__ = ["is_karaoke", "ass_for_track", "karaoke_ass_document"]
