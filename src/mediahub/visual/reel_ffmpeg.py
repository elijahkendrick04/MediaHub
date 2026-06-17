"""Free reel fallback — card stills + FFmpeg motion (roadmap P0.1).

The ``ffmpeg`` reel engine renders the same MP4 surfaces as the Remotion
pipeline (story cards and meet reels) with **zero licensing cost**: each
beat is the card's own still graphic — produced by the existing
``graphic_renderer`` (Playwright/Chromium, already a hard dependency of
the deployment) — animated and stitched by FFmpeg (LGPL/GPL, invoked as
a separate process). No Node, no Remotion Company License.

Selected via ``MEDIAHUB_REEL_ENGINE=ffmpeg`` (see
:mod:`mediahub.visual.reel_engine`); the default engine remains Remotion
and that path is untouched.

Design rules
------------
- **Brand parity by construction.** When the card has a persisted
  CreativeBrief (the AI-directed design used for its still graphic), the
  story frame is rendered from that exact brief at story size — the reel
  literally animates the card's own approved design. Without a brief, a
  deterministic minimal brief (``story_card`` layout, BrandKit palette)
  is built from the card facts. No AI call is made in this module and no
  judgement is faked — frame content is the same verified card data the
  Remotion compositions receive.
- **Honest errors.** A missing FFmpeg binary or still renderer raises
  :exc:`ReelEngineUnavailable`; render failures raise ``RuntimeError``
  with the FFmpeg stderr tail. Never a placeholder asset.
- **Deterministic output.** Motion is pure arithmetic (linear Ken Burns
  zoom, fixed crossfades); the same inputs produce the same MP4, cached
  under ``DATA_DIR/motion_cache`` keyed by content hash + engine.
- **Every cut, not just story.** Renders all four Remotion cuts — story
  (1080×1920, default), portrait (1080×1350), square (1080×1080) and
  landscape (1920×1080) — by rendering the card's still at the requested
  geometry and threading that ``(width, height)`` through every FFmpeg
  filter. The cut is folded into the cache key; the story path stays
  byte-identical to the pre-multiformat era so existing caches survive.

FFmpeg binary resolution order:

1. ``MEDIAHUB_FFMPEG`` (explicit path, operator override)
2. ``ffmpeg`` on PATH
3. the static binary bundled by the ``imageio-ffmpeg`` wheel
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from mediahub.visual.reel_engine import ReelEngineUnavailable

# Default output geometry — the canonical 9:16 story cut, matching the
# Remotion compositions exactly. WIDTH/HEIGHT are the story defaults every
# builder falls back to; the public renders resolve the caller's chosen cut
# (story / portrait / square / landscape) via _format_size and thread its
# (width, height) through every filter, so the FFmpeg fallback mirrors the
# four Remotion cuts one-for-one.
WIDTH = 1080
HEIGHT = 1920
FPS = 30

# Crossfade between reel beats. Folded into segment lengths so the
# advertised total duration (motion.reel_duration_for) is hit exactly.
CROSSFADE_SEC = 0.5

# Maximum Ken Burns zoom; reached linearly across each beat.
_MAX_ZOOM = 1.08


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def ffmpeg_exe() -> Optional[str]:
    """Resolve the FFmpeg binary, or None when no source provides one."""
    env = os.environ.get("MEDIAHUB_FFMPEG", "").strip()
    if env:
        return env if Path(env).exists() else None
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _still_renderer_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:
        return False
    return True


def available() -> bool:
    """True when the free fallback can render right now."""
    return ffmpeg_exe() is not None and _still_renderer_available()


def _require_available() -> str:
    exe = ffmpeg_exe()
    if not exe:
        raise ReelEngineUnavailable(
            "The 'ffmpeg' reel engine needs an FFmpeg binary: install the "
            "imageio-ffmpeg package (bundled static build), put ffmpeg on "
            "PATH, or point MEDIAHUB_FFMPEG at a binary."
        )
    if not _still_renderer_available():
        raise ReelEngineUnavailable(
            "The 'ffmpeg' reel engine renders frames with Playwright/"
            "Chromium (the same renderer the still graphics use) and "
            "Playwright is not importable on this deployment."
        )
    return exe


# ---------------------------------------------------------------------------
# Output geometry — single source of truth is motion.MOTION_FORMATS
# ---------------------------------------------------------------------------


def _format_size(format_name: str) -> tuple[int, int]:
    """Resolve a motion format name to ``(width, height)``.

    Delegates to :func:`mediahub.visual.motion.motion_format_size` so the
    four cuts (``story`` / ``portrait`` / ``square`` / ``landscape``) have a
    single source of truth shared with the Remotion path. Imported lazily
    because ``motion`` imports this module on its ffmpeg dispatch path, and
    an unknown name raises ``ValueError`` there — an honest config error
    rather than a silently wrong aspect ratio.
    """
    from mediahub.visual.motion import motion_format_size

    return motion_format_size(format_name)


# ---------------------------------------------------------------------------
# Frame briefs — rehydrate the card's persisted brief, or build a
# deterministic minimal one from the card facts (no AI involved).
# ---------------------------------------------------------------------------


def _props_text_layers(props: dict) -> dict[str, str]:
    """Map the Remotion-shaped card props onto renderer text-layer keys."""
    return {
        "athlete_full_name": str(props.get("athleteFullName") or ""),
        "athlete_first_name": str(props.get("athleteFirstName") or ""),
        "athlete_surname": str(props.get("athleteSurname") or ""),
        "event_name": str(props.get("eventName") or ""),
        "result_value": str(props.get("resultValue") or ""),
        "achievement_label": str(props.get("achievementLabel") or ""),
        "meet_name": str(props.get("meetName") or ""),
        "place": str(props.get("place") or ""),
    }


def _palette_from_brand(brand_dict: dict) -> dict[str, str]:
    return {
        "primary": str(brand_dict.get("primary") or "#0A2540"),
        "secondary": str(brand_dict.get("secondary") or "#000000"),
        "accent": str(brand_dict.get("accent") or "#FFFFFF"),
    }


def _minimal_brief(
    props: dict,
    brand_dict: dict,
    *,
    profile_id: str,
    layout_template: str = "story_card",
    text_layers: Optional[dict[str, str]] = None,
    confidence_label: Optional[str] = None,
    format_name: str = "story",
):
    """A fully-deterministic CreativeBrief for one frame.

    This is data plumbing, not creative judgement: every field is a
    verified card fact or a fixed structural default, the same contract
    the Remotion compositions consume.
    """
    from mediahub.creative_brief.generator import CreativeBrief

    layers = text_layers if text_layers is not None else _props_text_layers(props)
    label = (
        confidence_label if confidence_label is not None else layers.get("achievement_label", "")
    )
    return CreativeBrief(
        id="ffr_" + (str(props.get("variationSeed") or 0)),
        content_item_id=str(props.get("athleteFullName") or "") or "ffmpeg_frame",
        profile_id=profile_id,
        achievement_summary=layers.get("event_name", ""),
        objective="reel_frame",
        primary_hook=layers.get("athlete_full_name") or layers.get("meet_name") or "",
        confidence_label=label,
        tone="data_led",
        layout_template=layout_template,
        inspiration_pattern_id="",
        image_treatment="none",
        text_hierarchy=["athlete_full_name", "result_value", "event_name"],
        brand_instructions="",
        sponsor_instructions=None,
        sourced_asset_ids=[],
        safety_notes=[],
        why_this_design=(
            "Deterministic frame for the FFmpeg reel engine: the card's "
            "verified facts on the brand palette (no AI direction here)."
        ),
        text_layers=layers,
        palette=_palette_from_brand(brand_dict),
        format_priority=[format_name],
    )


def _rehydrate_brief(brief_dict: dict):
    """Rebuild a CreativeBrief from its persisted ``to_dict()`` form.

    Returns None when the dict is missing required fields — the caller
    falls back to the deterministic minimal brief.
    """
    from mediahub.creative_brief.generator import CreativeBrief

    return CreativeBrief.from_dict(brief_dict)


def _frame_brief(
    props: dict,
    brand_dict: dict,
    brand_kit: Any,
    brief_dict: Optional[dict],
    *,
    format_name: str = "story",
):
    profile_id = ""
    if brand_kit is not None:
        profile_id = str(
            getattr(brand_kit, "profile_id", "")
            or (brand_kit.get("profile_id", "") if isinstance(brand_kit, dict) else "")
        )
    if isinstance(brief_dict, dict) and brief_dict:
        brief = _rehydrate_brief(brief_dict)
        if brief is not None:
            # The frame renders at the requested cut's geometry; tag the
            # brief with it and make sure it carries a palette (legacy
            # briefs may have lost it).
            if not brief.palette:
                brief.palette = _palette_from_brand(brand_dict)
            brief.format_priority = [format_name]
            return brief
    return _minimal_brief(props, brand_dict, profile_id=profile_id, format_name=format_name)


def _cover_brief(
    cards_props: list[dict],
    brand_dict: dict,
    brand_kit: Any,
    meet_name: str,
    *,
    format_name: str = "story",
):
    """The reel's opening frame: meet name on the brand, ``reel_cover`` layout."""
    profile_id = ""
    if brand_kit is not None:
        profile_id = str(
            getattr(brand_kit, "profile_id", "")
            or (brand_kit.get("profile_id", "") if isinstance(brand_kit, dict) else "")
        )
    first = cards_props[0] if cards_props else {}
    title = (
        meet_name or str(first.get("meetName") or "") or str(brand_dict.get("displayName") or "")
    )
    layers = {
        # The reel_cover layout's text-led path uses athlete_full_name as
        # the mega headline; for a meet-level cover that headline is the
        # meet itself. The bottom meet strip is left empty so the title
        # never appears twice on one frame.
        "athlete_full_name": title,
        "athlete_first_name": "",
        "athlete_surname": "",
        "event_name": "",
        "result_value": "",
        "achievement_label": "MEET RECAP",
        "meet_name": "",
        "place": "",
    }
    return _minimal_brief(
        first,
        brand_dict,
        profile_id=profile_id,
        layout_template="reel_cover",
        text_layers=layers,
        confidence_label="MEET RECAP",
        format_name=format_name,
    )


# ---------------------------------------------------------------------------
# Still rendering (graphic_renderer — Playwright/Chromium)
# ---------------------------------------------------------------------------


def _render_still(
    brief,
    brand_kit: Any,
    out_dir: Path,
    *,
    name: str,
    size: tuple[int, int] = (WIDTH, HEIGHT),
    format_name: str = "story",
) -> Path:
    """Render one frame PNG for ``brief`` at ``size`` into ``out_dir``.

    ``size`` is the resolved ``(width, height)`` of the requested cut; the
    still layouts scale every dimension proportionally from it, so one brief
    serves every aspect. ``format_name`` only labels the emitted PNG.
    """
    from mediahub.graphic_renderer.render import render_brief

    frame_dir = out_dir / name
    frame_dir.mkdir(parents=True, exist_ok=True)
    result = render_brief(
        brief,
        output_dir=frame_dir,
        size=size,
        format_name=format_name,
        brand_kit=brand_kit,
        skip_cutout=True,
    )
    png = Path(result.visual.file_path)
    if not png.exists() or png.stat().st_size == 0:
        raise RuntimeError(f"still render produced no PNG for frame {name!r}")
    return png


# ---------------------------------------------------------------------------
# FFmpeg assembly (pure command builders + one subprocess runner)
# ---------------------------------------------------------------------------


def _zoom_filter(
    duration_sec: float,
    *,
    zoom_out: bool = False,
    width: int = WIDTH,
    height: int = HEIGHT,
) -> str:
    """Linear Ken Burns over the whole beat; deterministic, no easing RNG.

    ``width``/``height`` are the resolved geometry of the requested cut, so
    the upscale-and-pan maths produces a frame at the exact aspect ratio.
    """
    frames = max(1, round(duration_sec * FPS))
    rate = (_MAX_ZOOM - 1.0) / frames
    if zoom_out:
        z = f"'max({_MAX_ZOOM}-{rate:.6f}*on,1.0)'"
    else:
        z = f"'min(1.0+{rate:.6f}*on,{_MAX_ZOOM})'"
    return (
        f"scale={width * 2}:{height * 2}:flags=lanczos,"
        f"zoompan=z={z}:d=1"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":s={width}x{height}:fps={FPS}"
    )


def story_ffmpeg_args(
    still: Path,
    out_path: Path,
    duration_sec: float,
    *,
    width: int = WIDTH,
    height: int = HEIGHT,
) -> list[str]:
    """Argument list (after the binary) for a single-card story MP4.

    ``width``/``height`` select the cut (story / portrait / square /
    landscape); they default to the story geometry.
    """
    fade_out = max(0.0, duration_sec - 0.6)
    vf = (
        f"{_zoom_filter(duration_sec, width=width, height=height)},"
        f"fade=t=in:st=0:d=0.4,fade=t=out:st={fade_out:.3f}:d=0.6,"
        f"format=yuv420p,setsar=1"
    )
    return [
        "-loop",
        "1",
        "-framerate",
        str(FPS),
        "-t",
        f"{duration_sec:.3f}",
        "-i",
        str(still),
        "-vf",
        vf,
        "-r",
        str(FPS),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "19",
        "-movflags",
        "+faststart",
        "-an",
        str(out_path),
    ]


def reel_segment_durations(n_cards: int, total_sec: float) -> list[float]:
    """Per-segment input durations (cover + one per card) whose xfade-chained
    total is exactly ``total_sec``.

    Beats follow motion.reel_duration_for's structure — a 2s cover, 4s per
    card, and a 1s outro tail absorbed by the last card — scaled
    proportionally when the caller overrides the total. Every segment except
    the last is extended by the crossfade it loses to the following overlap.
    """
    from mediahub.visual.motion import (
        REEL_COVER_SEC,
        REEL_OUTRO_SEC,
        REEL_PER_CARD_SEC,
        reel_duration_for,
    )

    n = max(1, int(n_cards))
    base = [REEL_COVER_SEC] + [REEL_PER_CARD_SEC] * n
    base[-1] += REEL_OUTRO_SEC
    factor = float(total_sec) / reel_duration_for(n)
    visible = [b * factor for b in base]
    return [v + (CROSSFADE_SEC if i < len(visible) - 1 else 0.0) for i, v in enumerate(visible)]


def reel_ffmpeg_args(
    stills: list[Path],
    out_path: Path,
    segment_durations: list[float],
    *,
    width: int = WIDTH,
    height: int = HEIGHT,
) -> list[str]:
    """Argument list (after the binary) for the multi-beat reel MP4.

    ``width``/``height`` select the cut (story / portrait / square /
    landscape); they default to the story geometry.
    """
    if len(stills) != len(segment_durations):
        raise ValueError("one segment duration per still is required")
    args: list[str] = []
    for dur, still in zip(segment_durations, stills):
        args += [
            "-loop",
            "1",
            "-framerate",
            str(FPS),
            "-t",
            f"{dur:.3f}",
            "-i",
            str(still),
        ]

    total = sum(segment_durations) - CROSSFADE_SEC * (len(stills) - 1)
    chains: list[str] = []
    for i, dur in enumerate(segment_durations):
        chains.append(
            f"[{i}:v]{_zoom_filter(dur, zoom_out=bool(i % 2), width=width, height=height)},"
            f"setsar=1[v{i}]"
        )
    last = "v0"
    elapsed = 0.0
    for i in range(1, len(stills)):
        elapsed += segment_durations[i - 1]
        offset = elapsed - i * CROSSFADE_SEC
        nxt = f"x{i}"
        chains.append(
            f"[{last}][v{i}]xfade=transition=fade:duration={CROSSFADE_SEC}:"
            f"offset={offset:.3f}[{nxt}]"
        )
        last = nxt
    fade_out = max(0.0, total - 1.0)
    chains.append(
        f"[{last}]fade=t=in:st=0:d=0.4,fade=t=out:st={fade_out:.3f}:d=1.0,format=yuv420p[vout]"
    )
    args += [
        "-filter_complex",
        ";".join(chains),
        "-map",
        "[vout]",
        "-r",
        str(FPS),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "19",
        "-movflags",
        "+faststart",
        "-an",
        str(out_path),
    ]
    return args


def _run_ffmpeg(args: list[str], *, timeout: int = 600) -> None:
    exe = _require_available()
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"FFmpeg render timed out after {timeout}s") from e
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip().splitlines()
        tail = "\n".join(stderr[-12:]) if stderr else "(no stderr)"
        raise RuntimeError(f"FFmpeg render failed (exit {proc.returncode}):\n{tail}")


def media_duration_seconds(path: Path) -> Optional[float]:
    """Container duration via ``ffmpeg -i`` (no ffprobe in the static wheel)."""
    exe = ffmpeg_exe()
    if not exe:
        return None
    proc = subprocess.run([exe, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr or "")
    if not m:
        return None
    h, mnt, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mnt * 60 + s


# ---------------------------------------------------------------------------
# Public renders (called from mediahub.visual.motion's engine dispatch)
# ---------------------------------------------------------------------------


def _finalise(
    tmp_mp4: Path,
    cached: Path,
    out_path: Path,
    *,
    kind: str = "story",
    duration_sec: float = 6.0,
    audio_plan: Optional[dict] = None,
) -> Path:
    if not tmp_mp4.exists() or tmp_mp4.stat().st_size < 1024:
        raise RuntimeError("FFmpeg reported success but the MP4 is missing or empty")
    cached.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(tmp_mp4), str(cached))
    # Same finishing pass as the Remotion engine: planned audio (honest
    # silent fallback) + the poster-frame sidecar, then publish.
    from mediahub.visual.motion import _finish_cached_video, _publish

    _finish_cached_video(cached, kind=kind, plan=audio_plan, duration_sec=duration_sec)
    return _publish(cached, out_path)


def render_story_card_from_props(
    card_props: dict,
    brand_dict: dict,
    brand_kit: Any,
    out_path: Path,
    *,
    duration_sec: float = 6.0,
    brief_dict: Optional[dict] = None,
    audio_plan: Optional[dict] = None,
    format_name: str = "story",
) -> Path:
    """Render one card's story MP4 via the still+FFmpeg path.

    ``card_props`` / ``brand_dict`` are the exact prop dicts the Remotion
    composition would receive (built by motion's shapers), so both engines
    are fed identical card facts by construction. ``audio_plan`` (built by
    motion's audio helpers) is folded into the cache key when present and
    mixed onto the finished MP4 — None keeps the silent path's cache keys
    byte-identical to before.

    ``format_name`` picks the cut — ``story`` (1080×1920, default),
    ``portrait`` (1080×1350), ``square`` (1080×1080) or ``landscape``
    (1920×1080). Only the non-story cuts fold the format into the cache key,
    so a cached story render is never evicted or mis-served by a sibling cut.
    """
    from mediahub.visual.motion import (
        _cache_dir,
        _content_hash,
        _finish_cached_video,
        _publish,
    )

    _require_available()
    out_path = Path(out_path)
    width, height = _format_size(format_name)
    cache_payload = {
        "card": card_props,
        "brand": brand_dict,
        "duration": duration_sec,
        "engine": "ffmpeg",
        "brief": brief_dict or {},
    }
    if format_name != "story":
        cache_payload["format"] = format_name
    if audio_plan:
        cache_payload["audio"] = audio_plan
    cache_key = _content_hash(cache_payload, kind="story")
    cached = _cache_dir() / f"{cache_key}.mp4"
    if cached.exists() and cached.stat().st_size > 1024:
        _finish_cached_video(cached, kind="story", plan=audio_plan, duration_sec=duration_sec)
        return _publish(cached, out_path)

    brief = _frame_brief(card_props, brand_dict, brand_kit, brief_dict, format_name=format_name)
    with tempfile.TemporaryDirectory(prefix="mh_reel_ffmpeg_") as td:
        work = Path(td)
        still = _render_still(
            brief,
            brand_kit,
            work,
            name="story",
            size=(width, height),
            format_name=format_name,
        )
        tmp_mp4 = work / "story.mp4"
        _run_ffmpeg(story_ffmpeg_args(still, tmp_mp4, duration_sec, width=width, height=height))
        return _finalise(
            tmp_mp4,
            cached,
            out_path,
            kind="story",
            duration_sec=duration_sec,
            audio_plan=audio_plan,
        )


def render_meet_reel_from_props(
    cards_props: list[dict],
    brand_dict: dict,
    brand_kit: Any,
    out_path: Path,
    *,
    meet_name: str = "",
    duration_sec: Optional[float] = None,
    brief_dicts: Optional[list[Optional[dict]]] = None,
    audio_plan: Optional[dict] = None,
    format_name: str = "story",
) -> Path:
    """Render the meet reel (cover + one beat per card) via still+FFmpeg.

    ``duration_sec=None`` (the default) is data-driven — the same
    ``reel_duration_for`` arithmetic the Remotion path uses. ``audio_plan``
    behaves exactly as on the story path (cache-key folded; honest silent
    fallback).

    ``format_name`` picks the cut — ``story`` (default), ``portrait``,
    ``square`` or ``landscape``; every beat (cover + cards) renders at that
    geometry. Only the non-story cuts fold the format into the cache key, so
    a cached story reel is never evicted or mis-served by a sibling cut.
    """
    from mediahub.visual.motion import (
        _cache_dir,
        _content_hash,
        _finish_cached_video,
        _publish,
        reel_duration_for,
    )

    _require_available()
    if not cards_props:
        raise ValueError("at least one card is required for a reel")
    if duration_sec is None:
        duration_sec = reel_duration_for(len(cards_props))
    out_path = Path(out_path)
    width, height = _format_size(format_name)
    briefs = list(brief_dicts or [])
    cache_payload = {
        "cards": cards_props,
        "brand": brand_dict,
        "meet": meet_name,
        "duration": duration_sec,
        "engine": "ffmpeg",
        "briefs": [b or {} for b in briefs] or [{}] * len(cards_props),
    }
    if format_name != "story":
        cache_payload["format"] = format_name
    if audio_plan:
        cache_payload["audio"] = audio_plan
    cache_key = _content_hash(cache_payload, kind="reel")
    cached = _cache_dir() / f"{cache_key}.mp4"
    if cached.exists() and cached.stat().st_size > 1024:
        _finish_cached_video(cached, kind="reel", plan=audio_plan, duration_sec=duration_sec)
        return _publish(cached, out_path)

    with tempfile.TemporaryDirectory(prefix="mh_reel_ffmpeg_") as td:
        work = Path(td)
        stills: list[Path] = [
            _render_still(
                _cover_brief(
                    cards_props,
                    brand_dict,
                    brand_kit,
                    meet_name,
                    format_name=format_name,
                ),
                brand_kit,
                work,
                name="cover",
                size=(width, height),
                format_name=format_name,
            )
        ]
        for idx, props in enumerate(cards_props):
            bd = briefs[idx] if idx < len(briefs) else None
            brief = _frame_brief(props, brand_dict, brand_kit, bd, format_name=format_name)
            stills.append(
                _render_still(
                    brief,
                    brand_kit,
                    work,
                    name=f"card{idx}",
                    size=(width, height),
                    format_name=format_name,
                )
            )

        seg_durations = reel_segment_durations(len(cards_props), duration_sec)
        tmp_mp4 = work / "reel.mp4"
        _run_ffmpeg(reel_ffmpeg_args(stills, tmp_mp4, seg_durations, width=width, height=height))
        return _finalise(
            tmp_mp4,
            cached,
            out_path,
            kind="reel",
            duration_sec=duration_sec,
            audio_plan=audio_plan,
        )


__all__ = [
    "available",
    "ffmpeg_exe",
    "media_duration_seconds",
    "render_story_card_from_props",
    "render_meet_reel_from_props",
    "reel_segment_durations",
    "story_ffmpeg_args",
    "reel_ffmpeg_args",
    "CROSSFADE_SEC",
    "WIDTH",
    "HEIGHT",
    "FPS",
]
