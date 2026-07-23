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
- **Deterministic output.** Motion is pure arithmetic — a seed-chosen Ken
  Burns variant per beat (zoom in/out, four pans, two corner zooms, a 2.5D
  parallax composite, or an honest held frame), and per-join transitions
  that mirror the Remotion cuts (``MeetReel.tsx::transitionFor``): one
  earned, mood-chosen cut into the peak beat, a single quiet connective
  kind everywhere else. No easing RNG; the same inputs produce the same
  MP4, cached under ``DATA_DIR/motion_cache`` keyed by content hash +
  engine + motion revision.
- **Every cut, not just story.** Renders all four Remotion cuts — story
  (1080×1920, default), portrait (1080×1350), square (1080×1080) and
  landscape (1920×1080) — by rendering the card's still at the requested
  geometry and threading that ``(width, height)`` through every FFmpeg
  filter (Ken Burns, parallax, transitions). The cut is folded into the
  cache key; the story path stays byte-identical to the pre-multiformat era
  so existing caches survive.

FFmpeg binary resolution order:

1. ``MEDIAHUB_FFMPEG`` (explicit path, operator override)
2. ``ffmpeg`` on PATH
3. the static binary bundled by the ``imageio-ffmpeg`` wheel
"""

from __future__ import annotations

import json
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

# Fixed zoom held during a pan variant — enough crop margin to travel
# across the 2× pre-scaled frame without ever exposing an edge.
_PAN_ZOOM = 1.12

# 2.5D parallax variant: the still is composited over a blurred, drifting
# copy of itself, the sharp foreground riding slightly inset so the depth
# bleed reads at the border band. Same verified pixels on both planes —
# nothing about the card's facts or brand changes, only its apparent depth.
_PARALLAX_BG_BLUR = 20  # gblur sigma on the background plane
_PARALLAX_BG_ZOOM = 1.10  # background plane's fixed zoom while it drifts
_PARALLAX_FG_ZOOM = 1.05  # foreground plane's slow Ken Burns push
_PARALLAX_FG_SCALE = 0.90  # foreground inset as a fraction of the frame

# Motion revision — folded into the cache key so a motion-vocabulary change
# supersedes stale linear-zoom cache entries instead of serving them. Bump
# when the deterministic motion output changes for unchanged card inputs.
_MOTION_REV = 2

# The deterministic Ken Burns vocabulary, picked per beat from the card's
# variation seed (the same seed that drove its still graphic's look, so the
# motion stays correlated with the still). ``parallax`` and ``hold`` are
# reached through the director's motion_intent, not this rotation, so the
# seed pick stays a clean rotation of flat camera moves.
KEN_BURNS_VARIANTS: tuple[str, ...] = (
    "zoom_in",
    "zoom_out",
    "pan_left",
    "pan_right",
    "pan_up",
    "pan_down",
    "zoom_tl",
    "zoom_br",
)

# Reel beat transitions mirror the Remotion cuts in
# MeetReel.tsx::transitionFor — each kind maps to the closest frame-pure
# FFmpeg xfade so both engines cut a given beat the same way.
_XFADE_FOR_KIND: dict[str, str] = {
    "crossfade": "fade",
    "push": "slideup",
    "wipe": "wiperight",
    "blur": "hblur",
    "zoom": "zoomin",
    "whip": "slideleft",
    "iris": "circleopen",
    # R1.14 seed-alternated peak cuts (odd seeds) — closest frame-pure xfades.
    "glitch": "pixelize",
    "light-sweep": "radial",
    "slide-stack": "smoothup",
}


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def _supersample_requested() -> bool:
    """True when the Remotion-only motion supersample knob is set > 1. This free
    engine renders pre-baked Playwright stills and never invokes render.js, so it
    reports the knob as not-applied in its manifest rather than silently swallowing
    it (its stills already get their own DPR supersample upstream)."""
    raw = os.environ.get("MEDIAHUB_MOTION_SUPERSAMPLE", "").strip()
    try:
        return float(raw) > 1.0
    except ValueError:
        return False


def _photo_supersample_requested() -> bool:
    """True when the per-photo resample knob (``MEDIAHUB_PHOTO_SUPERSAMPLE``) is
    set. Unlike the Remotion best-effort CSS hint, this free engine ALREADY
    resamples every camera move from a genuine 2x Lanczos prescale (``scale=
    {w*2}:{h*2}:flags=lanczos`` at :440/:460 into the zoompan crop), so it reports
    the knob as natively satisfied — the honest truth — rather than claiming to
    honour an arbitrary caller factor it did not apply."""
    raw = os.environ.get("MEDIAHUB_PHOTO_SUPERSAMPLE", "").strip()
    try:
        return int(float(raw)) >= 2
    except ValueError:
        return False


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


def _ken_burns_filter(
    duration_sec: float,
    *,
    variant: str = "zoom_in",
    tag: str = "0",
    width: int = WIDTH,
    height: int = HEIGHT,
    fps: int = FPS,
) -> str:
    """One beat's motion sub-graph — a Ken Burns variant, the 2.5D parallax
    composite, or an honest held frame.

    Returns a bare filtergraph fragment with no boundary pads: the caller
    prefixes the input pad and appends ``setsar``/fades plus the output pad.
    The single-plane variants are one ``scale,zoompan`` chain; ``hold`` is a
    plain rescale; ``parallax`` is a multi-plane split/blur/overlay graph
    carrying its own ``tag``-suffixed internal pads (unique per beat) and
    ending on the ``overlay`` whose single output the caller chains onward —
    so the same wrapping works whether the host is a ``-vf`` (story) or a
    ``-filter_complex`` (reel) graph. Pure arithmetic, no easing RNG: the
    same inputs yield an identical fragment and a byte-identical MP4.
    """
    frames = max(1, round(duration_sec * fps))
    base = f"scale={width * 2}:{height * 2}:flags=lanczos"
    centre = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    tail = f":s={width}x{height}:fps={fps}"

    if variant == "hold":
        # Honest stillness for a `static` motion_intent — no camera move,
        # just the still rescaled to the beat geometry at the beat rate.
        return f"scale={width}:{height}:flags=lanczos,fps={fps}"

    if variant == "parallax":
        fg_w = int(round(width * _PARALLAX_FG_SCALE))
        fg_h = int(round(height * _PARALLAX_FG_SCALE))
        fg_rate = (_PARALLAX_FG_ZOOM - 1.0) / frames
        bg = (
            f"[pbg{tag}]scale={width}:{height},gblur=sigma={_PARALLAX_BG_BLUR},"
            f"zoompan=z='{_PARALLAX_BG_ZOOM}':d=1"
            f":x='(iw-iw/zoom)*(on/{frames})':y='ih/2-(ih/zoom/2)'"
            f":s={width}x{height}:fps={fps}[pbgz{tag}]"
        )
        fg = (
            f"[pfg{tag}]scale={fg_w * 2}:{fg_h * 2}:flags=lanczos,"
            f"zoompan=z='min(1.0+{fg_rate:.6f}*on,{_PARALLAX_FG_ZOOM})':d=1"
            f":{centre}:s={fg_w}x{fg_h}:fps={fps}[pfgz{tag}]"
        )
        return (
            f"split=2[pbg{tag}][pfg{tag}];{bg};{fg};"
            f"[pbgz{tag}][pfgz{tag}]overlay=x='(W-w)/2':y='(H-h)/2'"
        )

    if variant in ("pan_left", "pan_right", "pan_up", "pan_down"):
        # Fixed modest zoom, crop window tracking across the frame.
        z = f"z='{_PAN_ZOOM}'"
        if variant == "pan_left":
            pos = f"x='(iw-iw/zoom)*(1-on/{frames})':y='ih/2-(ih/zoom/2)'"
        elif variant == "pan_right":
            pos = f"x='(iw-iw/zoom)*(on/{frames})':y='ih/2-(ih/zoom/2)'"
        elif variant == "pan_up":
            pos = f"x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*(1-on/{frames})'"
        else:  # pan_down
            pos = f"x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*(on/{frames})'"
    elif variant in ("zoom_tl", "zoom_br"):
        # Zoom in while a corner stays pinned — the crop shrinks toward it.
        rate = (_MAX_ZOOM - 1.0) / frames
        z = f"z='min(1.0+{rate:.6f}*on,{_MAX_ZOOM})'"
        pos = "x='0':y='0'" if variant == "zoom_tl" else "x='(iw-iw/zoom)':y='(ih-ih/zoom)'"
    elif variant == "zoom_out":
        rate = (_MAX_ZOOM - 1.0) / frames
        z = f"z='max({_MAX_ZOOM}-{rate:.6f}*on,1.0)'"
        pos = centre
    else:  # "zoom_in" (default) — the historic centre push
        rate = (_MAX_ZOOM - 1.0) / frames
        z = f"z='min(1.0+{rate:.6f}*on,{_MAX_ZOOM})'"
        pos = centre

    return f"{base},zoompan={z}:d=1:{pos}{tail}"


def _write_caption_ass(
    caption_json: str,
    work_dir: Path,
    name: str,
    *,
    width: int = WIDTH,
    height: int = HEIGHT,
    fps: int = FPS,
) -> Optional[Path]:
    """Write a card's caption track (R1.3) as an ASS file for burn-in, or None.

    Best-effort: a malformed/empty track yields None and the frame renders
    without captions — an overlay never fails the render.
    """
    if not caption_json:
        return None
    try:
        from mediahub.visual import subtitle_burn

        track = json.loads(caption_json)
        if not isinstance(track, dict) or not track.get("cues"):
            return None
        doc = subtitle_burn.ass_document(track, width=width, height=height, fps=fps)
        path = work_dir / f"{name}.ass"
        path.write_text(doc, encoding="utf-8")
        return path
    except Exception:
        return None


def _ken_burns_variant_for(seed: int, *, motion_intent: str = "") -> str:
    """Pick a beat's Ken Burns programme deterministically.

    The director's ``motion_intent`` wins when it names a depth or hold
    treatment (mirroring the Remotion ``parallax`` / ``static`` intents);
    otherwise the card's own variation seed rotates through the flat Ken
    Burns vocabulary.
    """
    intent = (motion_intent or "").strip().lower()
    if intent == "parallax":
        return "parallax"
    if intent == "static":
        return "hold"
    return KEN_BURNS_VARIANTS[int(seed or 0) % len(KEN_BURNS_VARIANTS)]


# The vocabulary preset behind each shipped Ken Burns variant — the reverse of
# ``motion.vocabulary.KEN_BURNS_ALIASES``. Engine-only programmes (the corner
# zooms, the 2.5D parallax composite, the honest ``hold``) have no tokenised
# preset and keep the direct recipe.
_PRESET_FOR_KB_VARIANT: dict[str, str] = {
    "zoom_in": "ken_burns_in",
    "zoom_out": "ken_burns_out",
    "pan_left": "pan_left",
    "pan_right": "pan_right",
    "pan_up": "pan_up",
    "pan_down": "pan_down",
}


def _beat_motion_filter(
    duration_sec: float,
    *,
    variant: str,
    tag: str,
    width: int = WIDTH,
    height: int = HEIGHT,
    fps: int = FPS,
) -> str:
    """One beat's motion fragment, compiled from the brand motion vocabulary.

    When ``variant`` is a tokenised photo preset (``mediahub.motion`` — the
    same tokens the Remotion and CSS surfaces compile), the fragment comes via
    ``motion.compile_ffmpeg`` so the ffmpeg engine genuinely compiles the
    shared vocabulary (the ``/motion/vocabulary`` gallery's promise). The
    compiler delegates photo presets straight back to ``_ken_burns_filter``,
    so the fragment — and therefore every cache key — is byte-identical to the
    direct call; the tokens are simply the authoritative source. Engine-only
    variants (corner zooms / parallax / hold) keep the direct recipe.
    """
    preset_name = _PRESET_FOR_KB_VARIANT.get(variant)
    if preset_name:
        from mediahub.motion import vocabulary
        from mediahub.motion.compile_ffmpeg import compile_ffmpeg

        return compile_ffmpeg(
            vocabulary.get(preset_name),
            duration_sec=duration_sec,
            width=width,
            height=height,
            tag=tag,
            fps=fps,
        )
    return _ken_burns_filter(
        duration_sec, variant=variant, tag=tag, width=width, height=height, fps=fps
    )


def _transition_kind_for(seed: int, *, peak: bool = False, mood: str = "") -> str:
    """Port of ``MeetReel.tsx::transitionFor`` — the reel's deterministic cut
    picker, kept in lock-step so the FFmpeg engine cuts the way the Remotion
    reel would. Peak beats earn a mood-chosen bold cut; connective beats
    share one quiet kind spread only across reels.
    """
    if peak:
        m = (mood or "").lower()
        # Mirror the tsx's seed alternation between the two cuts that share a
        # mood's character, so both engines pick the same peak cut per seed.
        alt = ((int(seed or 0) % 2) + 2) % 2 == 1
        if any(k in m for k in ("calm", "stoic", "precise", "warm", "minimal")):
            return "blur"
        if any(k in m for k in ("explosive", "electric", "fierce")):
            return "glitch" if alt else "whip"
        if any(k in m for k in ("celebratory", "triumph", "medal")):
            return "light-sweep" if alt else "iris"
        return "slide-stack" if alt else "zoom"
    mode = (int(seed or 0) % 3 + 3) % 3
    if mode == 1:
        return "push"
    if mode == 2:
        return "wipe"
    return "crossfade"


def _xfade_for(kind: str) -> str:
    """Map a Remotion transition kind onto its closest FFmpeg xfade name."""
    return _XFADE_FOR_KIND.get(kind, "fade")


def _reel_kb_variants(cards_props: list[dict]) -> list[str]:
    """Per-beat Ken Burns variants: a steady centre zoom on the brand cover,
    then one seed/intent-chosen programme per card beat. Length is one per
    still (cover + one per card)."""
    variants = ["zoom_in"]  # cover — the reel's typical, brand-forward move
    for props in cards_props:
        variants.append(
            _ken_burns_variant_for(
                int(props.get("variationSeed") or 0),
                motion_intent=str(props.get("motionIntent") or ""),
            )
        )
    return variants


def _reel_transition_names(cards_props: list[dict]) -> list[str]:
    """Per-join xfade names mirroring ``MeetReel``: the cover→first-card
    handoff earns the bold, mood-chosen cut (only when there is more than one
    card), and every LATER handoff picks its OWN quiet connective kind from
    that card's seed (#1058) — so consecutive same-rank beats vary within the
    quiet trio instead of all cutting identically. A seedless lower beat falls
    back to the reel-level connective (the top card's seed). Length is one per
    beat join (= number of cards)."""
    if not cards_props:
        return []
    top = cards_props[0]
    seed = int(top.get("variationSeed") or 0)
    connective = _transition_kind_for(seed)
    peak = _transition_kind_for(seed, peak=True, mood=str(top.get("mood") or ""))
    n = len(cards_props)
    kinds: list[str] = []
    for j, props in enumerate(cards_props):
        if j == 0 and n > 1:
            kinds.append(peak)
            continue
        cseed = int(props.get("variationSeed") or 0)
        kinds.append(_transition_kind_for(cseed) if cseed else connective)
    return [_xfade_for(k) for k in kinds]


def story_ffmpeg_args(
    still: Path,
    out_path: Path,
    duration_sec: float,
    *,
    variant: str = "zoom_in",
    ass_path: Optional[Path] = None,
    width: int = WIDTH,
    height: int = HEIGHT,
    fps: int = FPS,
) -> list[str]:
    """Argument list (after the binary) for a single-card story MP4.

    ``variant`` selects the Ken Burns programme (or the 2.5D parallax /
    held-frame treatment); the default keeps the historic centre zoom-in, so
    a caller that passes no variant renders exactly as before. ``ass_path``
    (R1.3) burns the card's caption track onto the final frame via FFmpeg's
    ``ass`` filter — engine parity with the Remotion captions overlay.
    ``width``/``height`` select the cut (story / portrait / square /
    landscape); they default to the story geometry.
    """
    fade_out = max(0.0, duration_sec - 0.6)
    vf = (
        f"{_beat_motion_filter(duration_sec, variant=variant, tag='s', width=width, height=height, fps=fps)},"
        f"fade=t=in:st=0:d=0.4,fade=t=out:st={fade_out:.3f}:d=0.6,"
        f"format=yuv420p,setsar=1"
    )
    if ass_path is not None:
        from mediahub.visual.subtitle_burn import ass_filter

        vf = f"{vf},{ass_filter(str(ass_path))}"
    return [
        "-loop",
        "1",
        "-framerate",
        str(fps),
        "-t",
        f"{duration_sec:.3f}",
        "-i",
        str(still),
        "-vf",
        vf,
        "-r",
        str(fps),
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


def reel_segment_durations(
    n_cards: int, total_sec: float, *, rhythm: Optional[dict] = None
) -> list[float]:
    """Per-segment input durations (cover + one per card) whose xfade-chained
    total is exactly ``total_sec``.

    Beats follow motion.reel_duration_for's structure — a 2s cover, 4s per
    card, and a 1s outro tail absorbed by the last card — scaled
    proportionally when the caller overrides the total. Every segment except
    the last is extended by the crossfade it loses to the following overlap.

    R1.12 — when ``rhythm`` (a canonical dict from
    ``motion.normalise_reel_rhythm``) is supplied, the cover/outro seconds and
    the explicit per-card beat weights are mirrored from the Remotion carving
    so the free engine produces the same rhythm. ``None`` keeps the original
    flat-beat split byte-identical.
    """
    from mediahub.visual.motion import (
        REEL_COVER_SEC,
        REEL_OUTRO_SEC,
        REEL_PER_CARD_SEC,
        _fit_beat_weights,
        reel_duration_for,
    )

    n = max(1, int(n_cards))
    if rhythm:
        cover = float(rhythm.get("coverSec", REEL_COVER_SEC))
        outro = float(rhythm.get("outroSec", REEL_OUTRO_SEC))
        per_card = float(rhythm.get("perCardSec", REEL_PER_CARD_SEC))
        weights = list(rhythm.get("beatWeights") or [])
    else:
        cover, outro, per_card, weights = REEL_COVER_SEC, REEL_OUTRO_SEC, REEL_PER_CARD_SEC, []

    if weights:
        card_secs = [per_card * w for w in _fit_beat_weights(weights, n)]
    else:
        # No explicit weights → flat per-card beats (the free engine's original
        # carve; the Remotion path layers a top-card emphasis on top, a
        # long-standing per-engine nuance left untouched here).
        card_secs = [per_card] * n
    base = [cover] + card_secs
    base[-1] += outro
    ref_total = reel_duration_for(
        n,
        cover_sec=cover,
        outro_sec=outro,
        per_card_sec=per_card,
        beat_weights=(weights or None),
    )
    factor = float(total_sec) / ref_total if ref_total else 1.0
    visible = [b * factor for b in base]
    return [v + (CROSSFADE_SEC if i < len(visible) - 1 else 0.0) for i, v in enumerate(visible)]


def reel_ffmpeg_args(
    stills: list[Path],
    out_path: Path,
    segment_durations: list[float],
    *,
    kb_variants: Optional[list[str]] = None,
    transitions: Optional[list[str]] = None,
    width: int = WIDTH,
    height: int = HEIGHT,
    fps: int = FPS,
) -> list[str]:
    """Argument list (after the binary) for the multi-beat reel MP4.

    ``kb_variants`` is one Ken Burns variant per still (cover + one per card)
    and ``transitions`` one FFmpeg xfade name per beat join; both default to
    the historic alternating zoom / plain crossfade, so the bare builder
    stays stable for callers and tests that don't pass the richer programme.
    ``width``/``height`` select the cut (story / portrait / square /
    landscape); they default to the story geometry.
    """
    if len(stills) != len(segment_durations):
        raise ValueError("one segment duration per still is required")
    if kb_variants is None:
        kb_variants = ["zoom_out" if i % 2 else "zoom_in" for i in range(len(stills))]
    if transitions is None:
        transitions = ["fade"] * max(0, len(stills) - 1)
    if len(kb_variants) != len(stills):
        raise ValueError("one Ken Burns variant per still is required")
    if len(transitions) != max(0, len(stills) - 1):
        raise ValueError("one transition per beat join is required")
    args: list[str] = []
    for dur, still in zip(segment_durations, stills):
        args += [
            "-loop",
            "1",
            "-framerate",
            str(fps),
            "-t",
            f"{dur:.3f}",
            "-i",
            str(still),
        ]

    total = sum(segment_durations) - CROSSFADE_SEC * (len(stills) - 1)
    chains: list[str] = []
    for i, dur in enumerate(segment_durations):
        kb = _beat_motion_filter(
            dur, variant=kb_variants[i], tag=str(i), width=width, height=height, fps=fps
        )
        chains.append(f"[{i}:v]{kb},setsar=1[v{i}]")
    last = "v0"
    elapsed = 0.0
    for i in range(1, len(stills)):
        elapsed += segment_durations[i - 1]
        offset = elapsed - i * CROSSFADE_SEC
        nxt = f"x{i}"
        chains.append(
            f"[{last}][v{i}]xfade=transition={transitions[i - 1]}:duration={CROSSFADE_SEC}:"
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
        str(fps),
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
    try:
        proc = subprocess.run(
            [exe, "-hide_banner", "-i", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return None  # wedged probe on a malformed container — duration unknown
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
    n_cards: int = 0,
    manifest: Optional[dict] = None,
    rhythm: Optional[dict] = None,
    audio_notes: Optional[dict] = None,
) -> Path:
    if not tmp_mp4.exists() or tmp_mp4.stat().st_size < 1024:
        raise RuntimeError("FFmpeg reported success but the MP4 is missing or empty")
    cached.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(tmp_mp4), str(cached))
    # Same finishing pass as the Remotion engine: planned audio (honest
    # silent fallback, beat grid moved by any custom rhythm) + the
    # poster-frame sidecar, then the explainability manifest (M22 — the
    # ffmpeg engine writes the same sidecar shape the Remotion paths write,
    # so an ffmpeg MP4 is never an unexplained "legacy render"), then
    # publish (which ships the sidecars along).
    from mediahub.visual.audio_mux import poster_path_for
    from mediahub.visual.motion import _finish_cached_video, _publish, _write_render_manifest

    audio_rec = _finish_cached_video(
        cached,
        kind=kind,
        plan=audio_plan,
        duration_sec=duration_sec,
        n_cards=n_cards,
        rhythm=rhythm,
        audio_notes=audio_notes,
    )
    if manifest is not None:
        _write_render_manifest(
            cached,
            {
                **manifest,
                "audio": audio_rec,
                "poster": poster_path_for(cached).name if poster_path_for(cached).exists() else "",
            },
        )
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
    fps: int = FPS,
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
        "motion": _MOTION_REV,
        "brief": brief_dict or {},
    }
    if format_name != "story":
        cache_payload["format"] = format_name
    if audio_plan:
        cache_payload["audio"] = audio_plan
    # fps-option: fold the frame rate only for a non-default choice so the
    # default (30fps) ffmpeg-story cache key is byte-identical to before.
    if int(fps) != FPS:
        cache_payload["fps"] = int(fps)
    cache_key = _content_hash(cache_payload, kind="story")
    cached = _cache_dir() / f"{cache_key}.mp4"
    if cached.exists() and cached.stat().st_size > 1024:
        _finish_cached_video(cached, kind="story", plan=audio_plan, duration_sec=duration_sec)
        return _publish(cached, out_path)

    brief = _frame_brief(card_props, brand_dict, brand_kit, brief_dict, format_name=format_name)
    variant = _ken_burns_variant_for(
        int(card_props.get("variationSeed") or 0),
        motion_intent=str(card_props.get("motionIntent") or ""),
    )
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
        ass_path = _write_caption_ass(
            str(card_props.get("captionsJson") or ""),
            work,
            "story",
            width=width,
            height=height,
            fps=fps,
        )
        _run_ffmpeg(
            story_ffmpeg_args(
                still,
                tmp_mp4,
                duration_sec,
                variant=variant,
                ass_path=ass_path,
                width=width,
                height=height,
                fps=fps,
            )
        )
        # M22 — the same explainability shape the Remotion story path writes,
        # plus honest engine notes (a reduced-motion render must say so).
        from mediahub.visual.motion import _caption_manifest, _card_manifest_axes

        manifest = {
            "kind": "story",
            "engine": "ffmpeg",
            "format": format_name,
            "size": [width, height],
            "duration_sec": duration_sec,
            "fps": int(fps),
            "card": _card_manifest_axes(card_props),
            "kb_variant": variant,
            "captions": _caption_manifest(str(card_props.get("captionsJson") or "")),
            "notes": {
                **(
                    {"supersample": {"applied": False, "reason": "remotion-only"}}
                    if _supersample_requested()
                    else {}
                ),
                # transform-sampling: the per-photo resample knob maps to this
                # engine's NATIVE 2x Lanczos prescale (the zoompan crop already
                # samples a dense buffer), so it is satisfied natively rather than
                # faking a caller factor — the honest cross-engine parity note.
                **(
                    {
                        "photo_supersample": {
                            "applied": True,
                            "method": "native-2x-lanczos-prescale",
                        }
                    }
                    if _photo_supersample_requested()
                    else {}
                ),
                # M23: footage-backed beats need the Remotion engine (this
                # path animates the card's pre-baked still and cannot play a
                # video plane) — an honest capability note, never a fake beat.
                "footage": "unsupported-on-engine",
                # render-banding-dither: the ordered-dither debanding overlay is a
                # Remotion mix-blend layer (Dither.tsx); this engine animates the
                # card's pre-baked still and cannot composite it, so a dither-opted
                # STORY render honestly reports it absent — never a faked layer.
                # (The reel path composites the pre-baked still PNGs, which already
                # carry the still-side dither baked in, so it needs no such note.)
                "dither": "unsupported-on-engine",
                # blur-family: the develop-in directional/radial/lens focus blur
                # is a per-frame Remotion photo-element grade; this engine
                # composites the approved still unblurred, so the intro smear is
                # honestly absent — never a faked filter.
                "focus_blur": "unsupported-on-engine",
                # Per-glyph text reveal needs the DOM Remotion path; this engine
                # animates the pre-baked still, so any glyph-granularity request
                # degrades honestly to the whole-still render — never a faked
                # per-character animation.
                "text_granularity": "per-glyph-unsupported-on-engine",
                "engine_note": (
                    "Rendered by the reduced-motion FFmpeg engine: the card's own "
                    "approved still with a deterministic camera move — no text "
                    "choreography, count-up, or typewriter/scramble reveal."
                ),
            },
        }
        return _finalise(
            tmp_mp4,
            cached,
            out_path,
            kind="story",
            duration_sec=duration_sec,
            audio_plan=audio_plan,
            manifest=manifest,
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
    rhythm: Optional[dict] = None,
    audio_notes: Optional[dict] = None,
    fps: int = FPS,
) -> Path:
    """Render the meet reel (cover + one beat per card) via still+FFmpeg.

    ``duration_sec=None`` (the default) is data-driven — the same
    ``reel_duration_for`` arithmetic the Remotion path uses, folded with the
    optional ``rhythm`` (R1.12) so the free engine honours custom cover/outro
    seconds and per-card beat weights too. ``audio_plan`` behaves exactly as on
    the story path (cache-key folded; honest silent fallback).

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
        _reel_duration_kwargs,
        reel_duration_for,
    )

    _require_available()
    if not cards_props:
        raise ValueError("at least one card is required for a reel")
    if duration_sec is None:
        duration_sec = reel_duration_for(len(cards_props), **_reel_duration_kwargs(rhythm))
    out_path = Path(out_path)
    width, height = _format_size(format_name)
    briefs = list(brief_dicts or [])
    cache_payload = {
        "cards": cards_props,
        "brand": brand_dict,
        "meet": meet_name,
        "duration": duration_sec,
        "engine": "ffmpeg",
        "motion": _MOTION_REV,
        "briefs": [b or {} for b in briefs] or [{}] * len(cards_props),
    }
    if rhythm:
        cache_payload["rhythm"] = rhythm
    if format_name != "story":
        cache_payload["format"] = format_name
    if audio_plan:
        cache_payload["audio"] = audio_plan
    # fps-option: fold the frame rate only for a non-default choice so the
    # default (30fps) ffmpeg-reel cache key is byte-identical to before.
    if int(fps) != FPS:
        cache_payload["fps"] = int(fps)
    cache_key = _content_hash(cache_payload, kind="reel")
    cached = _cache_dir() / f"{cache_key}.mp4"
    if cached.exists() and cached.stat().st_size > 1024:
        _finish_cached_video(
            cached,
            kind="reel",
            plan=audio_plan,
            duration_sec=duration_sec,
            n_cards=len(cards_props),
            rhythm=rhythm,
            audio_notes=audio_notes,
        )
        return _publish(cached, out_path)

    with tempfile.TemporaryDirectory(prefix="mh_reel_ffmpeg_") as td:
        work = Path(td)
        # Build the beat list — the meet-name cover plus one still per card —
        # then render the stills concurrently. The beats are independent and
        # their Chromium renders dominate the reel's wall-clock cost;
        # render_beats preserves beat order, so the FFmpeg transition chain
        # still composites cover, card0, card1, … and the output bytes (and
        # cache key) are unchanged — only the wall-clock shrinks. (This extends
        # R1.28's parallel-composition win — which sped up the Remotion reel via
        # reel_parallel.py — to the free FFmpeg fallback engine, whose beats
        # still rendered serially.) Each closure binds its own brief/name via
        # default args so it doesn't capture the loop's final value.
        from mediahub.visual.reel_ffmpeg_parallel import Beat, render_beats

        cover_brief = _cover_brief(
            cards_props,
            brand_dict,
            brand_kit,
            meet_name,
            format_name=format_name,
        )
        beats: list[Beat] = [
            Beat(
                "cover",
                lambda b=cover_brief: _render_still(
                    b,
                    brand_kit,
                    work,
                    name="cover",
                    size=(width, height),
                    format_name=format_name,
                ),
            )
        ]
        for idx, props in enumerate(cards_props):
            bd = briefs[idx] if idx < len(briefs) else None
            brief = _frame_brief(props, brand_dict, brand_kit, bd, format_name=format_name)
            name = f"card{idx}"
            beats.append(
                Beat(
                    name,
                    lambda b=brief, n=name: _render_still(
                        b,
                        brand_kit,
                        work,
                        name=n,
                        size=(width, height),
                        format_name=format_name,
                    ),
                )
            )
        stills = render_beats(beats)

        seg_durations = reel_segment_durations(len(cards_props), duration_sec, rhythm=rhythm)
        tmp_mp4 = work / "reel.mp4"
        kb_variants = _reel_kb_variants(cards_props)
        transitions = _reel_transition_names(cards_props)
        _run_ffmpeg(
            reel_ffmpeg_args(
                stills,
                tmp_mp4,
                seg_durations,
                kb_variants=kb_variants,
                transitions=transitions,
                width=width,
                height=height,
                fps=fps,
            )
        )
        # M22 — the same explainability shape the Remotion reel path writes,
        # plus honest capability notes: this engine renders pre-baked stills,
        # so reel captions are unsupported and the cover's stat chips are
        # static (no count-up).
        from mediahub.visual.motion import _card_manifest_axes

        manifest = {
            "kind": "reel",
            "engine": "ffmpeg",
            "format": format_name,
            "size": [width, height],
            "duration_sec": duration_sec,
            "fps": int(fps),
            "meet_name": meet_name,
            "rhythm": rhythm or "default",
            "cards": [_card_manifest_axes(cp) for cp in cards_props],
            "kb_variants": kb_variants,
            "transitions": transitions,
            "captions": {"status": "unsupported-on-engine"},
            "notes": {
                **(
                    {"supersample": {"applied": False, "reason": "remotion-only"}}
                    if _supersample_requested()
                    else {}
                ),
                # transform-sampling: satisfied natively by this engine's fixed 2x
                # Lanczos prescale into every zoompan crop — honest parity note,
                # never a faked caller factor.
                **(
                    {
                        "photo_supersample": {
                            "applied": True,
                            "method": "native-2x-lanczos-prescale",
                        }
                    }
                    if _photo_supersample_requested()
                    else {}
                ),
                "captions": "unsupported-on-engine",
                "stat_chips": "static-cover",
                # varfont-animation: the Remotion engine blooms the supporting
                # weight registers' variable wght axis up to the still's target
                # over the first ~20% of the beat. This engine bakes the approved
                # still, which already carries that static register weight, so it
                # shows the terminal (parity) weight with no bloom — reported
                # truthfully, never a faked animation.
                "variable_axes": "static-weight",
                # M23: footage-backed beats need the Remotion engine (this
                # path animates pre-baked stills and cannot play a video
                # plane) — an honest capability note, never a fake beat.
                "footage": "unsupported-on-engine",
                # blur-family: the develop-in directional/radial/lens focus blur
                # is a per-frame Remotion photo-element grade; each beat here is
                # the approved still composited unblurred, so the intro smear is
                # honestly absent — never a faked filter.
                "focus_blur": "unsupported-on-engine",
                # Per-glyph text reveal needs the DOM Remotion path; each beat
                # here is the pre-baked still, so a glyph-granularity request
                # degrades honestly — never a faked per-character animation.
                "text_granularity": "per-glyph-unsupported-on-engine",
                "engine_note": (
                    "Rendered by the reduced-motion FFmpeg engine: each beat is "
                    "the card's own approved still with a deterministic camera "
                    "move — no text choreography, count-up, or burned captions."
                ),
            },
        }
        return _finalise(
            tmp_mp4,
            cached,
            out_path,
            kind="reel",
            duration_sec=duration_sec,
            audio_plan=audio_plan,
            n_cards=len(cards_props),
            manifest=manifest,
            rhythm=rhythm,
            audio_notes=audio_notes,
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
    "KEN_BURNS_VARIANTS",
    "CROSSFADE_SEC",
    "WIDTH",
    "HEIGHT",
    "FPS",
]
