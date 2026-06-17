"""Motion-graphic + short-form video output via Remotion.

Public API
----------
- ``render_story_card(card_payload, brand_kit, out_path, *, variation_seed=0,
                       duration_sec=6.0) -> Path``
- ``render_meet_reel(top_cards, brand_kit, out_path, *, meet_name="",
                     duration_sec=15.0) -> Path``

Both helpers shell out to ``src/mediahub/remotion/render.js`` via Node and
cache the resulting MP4 by a deterministic content hash. Cached outputs
live under ``DATA_DIR / "motion_cache" / <hash>.mp4``; cache hits avoid
the Node bundling/rendering cost entirely.

Design notes
------------
- Node is an optional dependency. ``node_available()`` exposes a fast
  check so the web layer can degrade gracefully if Node is missing.
- The variation seed from ``mediahub.creative_brief.generator`` is woven
  into the cache key and forwarded to the Remotion composition so the
  motion render of a given card stays visually identical across calls.
- Brand-kit ingest accepts either a ``BrandKit`` dataclass or a plain dict
  (so the renderer doesn't have to import the brand package).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import is_dataclass, asdict
from pathlib import Path
from typing import Any, Optional


from mediahub.visual.reel_engine import (
    ReelEngineUnavailable,
    select_reel_engine,
)

REMOTION_DIR = Path(__file__).resolve().parents[1] / "remotion"
RENDER_SCRIPT = REMOTION_DIR / "render.js"

# Composition ids declared in src/mediahub/remotion/src/Root.tsx
COMP_STORY = "StoryCard"
COMP_REEL = "MeetReel"

# Output formats (platform comprehensiveness): the canonical 9:16 story plus
# the 4:5 portrait feed cut, the 1:1 feed square and 16:9 landscape cuts.
# The TSX compositions lay out responsively from useVideoConfig(), so one
# composition serves every size. "story" is the default and keeps every
# pre-format cache key and output filename byte-identical.
MOTION_FORMATS: dict[str, tuple[int, int]] = {
    "story": (1080, 1920),
    "portrait": (1080, 1350),
    "square": (1080, 1080),
    "landscape": (1920, 1080),
}
DEFAULT_MOTION_FORMAT = "story"


def motion_format_size(format_name: str) -> tuple[int, int]:
    """Resolve a motion format name to ``(width, height)``.

    Unknown names raise ``ValueError`` — an honest configuration error
    beats silently rendering the wrong aspect ratio.
    """
    key = (format_name or DEFAULT_MOTION_FORMAT).strip().lower()
    if key not in MOTION_FORMATS:
        raise ValueError(f"unknown motion format {format_name!r}; valid: {sorted(MOTION_FORMATS)}")
    return MOTION_FORMATS[key]


def _data_dir() -> Path:
    """Resolve the DATA_DIR at call time so tests can monkeypatch it."""
    src_root = Path(__file__).resolve().parents[1]
    return Path(os.environ.get("DATA_DIR", str(src_root)))


def _cache_dir() -> Path:
    d = _data_dir() / "motion_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def node_available() -> bool:
    """Return True if a `node` binary is on PATH."""
    return shutil.which("node") is not None


def remotion_installed() -> bool:
    """Return True if the Remotion deps appear to be installed locally."""
    return (REMOTION_DIR / "node_modules" / "remotion").exists()


def _logo_to_data_uri(logo_svg: Optional[str]) -> str:
    """Return a base64 SVG data URI for an inline logo string, or "".

    Mirrors the static graphic renderer's _build_logo_block: only accepts
    raw SVG markup (must start with "<"), so callers can't accidentally
    inject a stale text mark and we don't have to fetch remote logos.
    """
    if not logo_svg or not isinstance(logo_svg, str):
        return ""
    s = logo_svg.strip()
    if not s.startswith("<"):
        return ""
    encoded = base64.b64encode(s.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _brand_to_dict(brand_kit: Any) -> dict[str, str]:
    """Normalise a BrandKit dataclass / dict / object into the shape the
    Remotion compositions expect.

    Phase 1.6 Stage G: when ``brand_kit.profile_id`` resolves to a
    theme in the on-disk store, prefer the theme-store palette over
    the BrandKit's flat ``primary_colour``/``secondary_colour``/
    ``accent_colour`` fields. Motion videos consume the DARK scheme's
    roles (video-grade saturation; see palette_for_motion docstring).
    Falls back to the legacy path when no theme is on disk — every
    existing render keeps working.
    """
    if brand_kit is None:
        src: dict[str, Any] = {}
    elif isinstance(brand_kit, dict):
        src = brand_kit
    elif is_dataclass(brand_kit):
        src = asdict(brand_kit)
    else:
        src = {
            "profile_id": getattr(brand_kit, "profile_id", ""),
            "display_name": getattr(brand_kit, "display_name", ""),
            "short_name": getattr(brand_kit, "short_name", ""),
            "primary_colour": getattr(brand_kit, "primary_colour", ""),
            "secondary_colour": getattr(brand_kit, "secondary_colour", ""),
            "accent_colour": getattr(brand_kit, "accent_colour", ""),
            "logo_svg": getattr(brand_kit, "logo_svg", ""),
        }

    # Stage G's theme_store integration mapped motion to MD3's
    # dark.primary / dark.secondary_container / dark.tertiary roles.
    # In practice those are tonal-palette tokens designed for UI
    # surfaces (buttons, containers), not full-bleed brand colour
    # ground/surface fills — they produced washed-out low-contrast
    # output in production (live verification 2026-05-19 showed
    # pink-on-pink renders for a #FFD86E/#A30D2D/#000000 BrandKit).
    # We now prefer the BrandKit's flat primary/secondary/accent
    # fields (the same ones the static renderer's brief.palette
    # carries) and only fall back to the theme store when the
    # BrandKit is incomplete. This keeps motion and static visually
    # aligned and restores the punch the brand was designed for.
    theme_palette: Optional[dict[str, str]] = None
    pid = src.get("profile_id") or src.get("profileId")
    if pid:
        try:
            from mediahub.theming.theme_store import read_theme, palette_for_motion

            theme_json = read_theme(pid)
            if theme_json:
                theme_palette = palette_for_motion(theme_json)
        except Exception as e:
            # Don't fail the render — fall through to the BrandKit
            # palette — but surface the cause in logs so a broken
            # theme_store integration is visible.
            import logging as _log

            _log.getLogger(__name__).warning(
                "motion: theme_store lookup failed for profile_id=%r: %s",
                pid,
                e,
            )
            theme_palette = None

    brand_primary = src.get("primary_colour") or src.get("primary")
    brand_secondary = src.get("secondary_colour") or src.get("secondary")
    brand_accent = src.get("accent_colour") or src.get("accent")
    used_brand_kit = bool(brand_primary or brand_secondary or brand_accent)

    primary = brand_primary or (theme_palette or {}).get("primary") or "#0A2540"
    secondary = brand_secondary or (theme_palette or {}).get("secondary") or "#000000"
    accent = brand_accent or (theme_palette or {}).get("accent") or "#FFFFFF"

    return {
        "primary": primary,
        "secondary": secondary,
        "accent": accent,
        "displayName": src.get("display_name") or src.get("displayName") or "",
        "shortName": src.get("short_name") or src.get("shortName") or "",
        "logoDataUri": _logo_to_data_uri(
            src.get("logo_svg") or src.get("logoSvg") or src.get("logoDataUri")
        ),
        "themeSource": "brand-kit"
        if used_brand_kit
        else ("theme-store" if theme_palette else "brand-kit"),
    }


_PHOTO_MAX_EDGE = 1280
_PHOTO_MAX_BYTES = 12_000_000  # refuse to embed originals beyond this raw size


def _photo_asset_path_for_brief(brief: Optional[dict]) -> Optional[Path]:
    """Resolve the on-disk path of the photo a brief sourced, or ``None``.

    Mirrors the sourcing rules of the still renderer: skips "no-photo"
    treatments, the synthetic ``_brand_logo_`` id, missing files, and
    oversized originals. Never raises.
    """
    b = brief if isinstance(brief, dict) else {}
    if not b or str(b.get("photo_treatment") or "") == "no-photo":
        return None
    asset_ids = [str(a) for a in (b.get("sourced_asset_ids") or []) if a and a != "_brand_logo_"]
    if not asset_ids:
        return None
    try:
        from mediahub.media_library.store import get_store

        store = get_store()
    except Exception:
        return None
    for aid in asset_ids:
        try:
            asset = store.get(aid)
        except Exception:
            continue
        if asset is None:
            continue
        p = Path(getattr(asset, "path", "") or "")
        try:
            if p.exists() and p.stat().st_size <= _PHOTO_MAX_BYTES:
                return p
        except OSError:
            continue
    return None


def _photo_data_uri_for_brief(brief: Optional[dict]) -> str:
    """Resolve the photo a brief sourced into an embeddable JPEG data URI.

    Remotion's headless Chromium only sees what the props carry, so the
    user's chosen photo is downscaled and inlined. Empty string on any
    miss (no brief, "no-photo" treatment, asset gone, decode failure) —
    a missing photo must never fail a motion render.
    """
    p = _photo_asset_path_for_brief(brief)
    if p is None:
        return ""
    try:
        import base64
        import io

        from PIL import Image

        with Image.open(p) as im:
            im = im.convert("RGB")
            im.thumbnail((_PHOTO_MAX_EDGE, _PHOTO_MAX_EDGE))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=82)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


def _photo_focus_for_brief(brief: Optional[dict], format_name: str = DEFAULT_MOTION_FORMAT) -> str:
    """Saliency ``object-position`` for the brief's photo, steered per cut.

    Reuses the still renderer's deterministic saliency maths so a face the
    still keeps in frame stays in frame on the video too — now resolved for
    the requested output cut. The 9:16 story, 4:5 portrait, 1:1 square and
    16:9 landscape crops of the same photo slide along different axes, so a
    subject framed for the tall story can sit off-centre in the wide
    landscape; computing the focus per format keeps it centred in each.
    ``""`` when the brief sourced no photo (the TSX then uses its own
    neutral default). The ``story`` default resolves to the 9:16 ratio, so a
    default-cut render is byte-identical to the pre-format behaviour.
    """
    p = _photo_asset_path_for_brief(brief)
    if p is None:
        return ""
    try:
        from mediahub.graphic_renderer.saliency import focus_position_for_format

        return focus_position_for_format(p, format_name)
    except Exception:
        return ""


def _resolved_motion_roles(brief: Optional[dict], brand_kit: Any) -> dict[str, str]:
    """The exact colour roles the card's STILL graphic paints, for motion.

    Rehydrates the persisted brief and runs the still renderer's single
    role resolver (Tier A brand baseline → the director's APCA-gated
    colour-role assignment → medal tint), then maps the ``--mh-*`` vars
    onto the motion prop names. Empty dict on any miss — the TSX then
    falls back to its seed-permutation roles, exactly the pre-parity
    behaviour.
    """
    if not isinstance(brief, dict) or not brief:
        return {}
    try:
        from mediahub.creative_brief.generator import CreativeBrief
        from mediahub.graphic_renderer.render import resolved_role_vars_for_brief

        b = CreativeBrief.from_dict(brief)
        if b is None:
            return {}
        root_vars = resolved_role_vars_for_brief(b, brand_kit)
        return {
            "roleGround": str(root_vars.get("--mh-primary") or ""),
            "roleSurface": str(root_vars.get("--mh-surface") or ""),
            "roleAccent": str(root_vars.get("--mh-accent") or ""),
            "roleOnGround": str(root_vars.get("--mh-on-primary") or ""),
        }
    except Exception:
        return {}


def _card_to_props(
    card: dict,
    *,
    variation_seed: int = 0,
    brief: Optional[dict] = None,
    brand_kit: Any = None,
    format_name: str = DEFAULT_MOTION_FORMAT,
) -> dict[str, Any]:
    """Coerce one content-pack card payload into the StoryCard props shape.

    Accepts either a flat dict ({"swimmer_name": ..., "event": ...}) or the
    nested {"achievement": {...}} variant emitted by the recognition layer.

    When ``brief`` is supplied (the AI-directed CreativeBrief for this
    card, as a dict via ``brief.to_dict()``), the variation axes the
    director picked — layout family, typography pair, composition,
    background style, accent style, mood, photo treatment, motion intent —
    are forwarded to Remotion. The TypeScript StoryCard composition uses
    those axes to vary fonts, layout, animation programme, background
    pattern, and accent decoration, so a Gemini-directed run produces
    visually distinct motion for every card instead of just rotating
    palette roles.

    When ``brand_kit`` is also supplied, the card's resolved colour roles
    (the exact APCA-gated set the still graphic painted, medal tint
    included) ride along as ``roleGround``/``roleSurface``/``roleAccent``/
    ``roleOnGround`` so the motion render and the approved still can never
    disagree on colour. Empty strings keep the seed-permutation fallback.

    ``format_name`` is the output cut (story / portrait / square / landscape);
    it steers the saliency ``photoPos`` so the photo's focal point is resolved
    for that frame's aspect ratio. The ``story`` default keeps ``photoPos``
    byte-identical to the pre-format behaviour.
    """
    ach = card.get("achievement") if isinstance(card, dict) else None
    if not isinstance(ach, dict):
        ach = card or {}
    layers = card.get("text_layers") if isinstance(card, dict) else None
    if not isinstance(layers, dict):
        layers = {}
    raw_facts = ach.get("raw_facts") if isinstance(ach, dict) else None
    if not isinstance(raw_facts, dict):
        raw_facts = {}

    athlete = (
        layers.get("athlete_full_name")
        or ach.get("swimmer_name")
        or ach.get("athlete_name")
        or card.get("swimmer_name")
        or card.get("athlete_name")
        or ""
    )
    first = layers.get("athlete_first_name") or (athlete.split()[0] if athlete else "")
    surname = layers.get("athlete_surname") or (athlete.split()[-1] if athlete else "")
    event = (
        layers.get("event_name")
        or ach.get("event_name")
        or ach.get("event")
        or card.get("event")
        or card.get("event_name")
        or ""
    )
    result = (
        layers.get("result_value")
        or ach.get("result_time")
        or ach.get("time")
        or raw_facts.get("time_str")
        or raw_facts.get("result")
        or card.get("result_time")
        or card.get("time")
        or ""
    )
    label = (
        layers.get("achievement_label")
        or ach.get("achievement_label")
        or ach.get("type")
        or card.get("confidence_label")
        or "STRONG SWIM"
    )
    meet_name = layers.get("meet_name") or card.get("meet_name") or ach.get("meet_name") or ""
    place = layers.get("place") or ach.get("place") or raw_facts.get("place") or ""

    # Pull variation axes from the brief (when supplied). Every field
    # is optional — empty strings tell the TSX composition to fall
    # back to its variationSeed-driven defaults.
    b = brief if isinstance(brief, dict) else {}
    # Gen v2 (SEQ-4): forward the still graphic's archetype + measured
    # emphasis line so the motion render of a card visually matches its
    # still. ``layout_template`` carries a v2 archetype name when the v2
    # engine produced the brief (a v1 family name otherwise — the TSX
    # treats unknown names as "no archetype treatment").
    brief_layers = b.get("text_layers") if isinstance(b.get("text_layers"), dict) else {}
    roles = _resolved_motion_roles(b, brand_kit)
    return {
        "athleteFullName": str(athlete),
        "athleteFirstName": str(first),
        "athleteSurname": str(surname),
        "eventName": str(event),
        "resultValue": str(result),
        "achievementLabel": str(label).upper(),
        "meetName": str(meet_name),
        "place": str(place),
        "variationSeed": int(variation_seed or 0),
        "backgroundStyle": str(b.get("background_style") or ""),
        "composition": str(b.get("composition") or ""),
        "typographyPair": str(b.get("typography_pair") or ""),
        "accentStyle": str(b.get("accent_style") or ""),
        "mood": str(b.get("mood") or ""),
        "photoTreatment": str(b.get("photo_treatment") or ""),
        "photoSrc": _photo_data_uri_for_brief(b),
        "photoPos": _photo_focus_for_brief(b, format_name),
        "archetype": str(b.get("layout_template") or ""),
        # The still's style pack id (graphic_renderer.style_packs): the motion
        # render layers the same ground/texture/accent-geometry overlay so a
        # card's video carries the still's exact decorative treatment. Folds
        # into the cache key via the card payload; "" = the bare (undecorated)
        # card, byte-equivalent to the pre-pack render.
        "stylePack": str(b.get("style_pack") or ""),
        "heroStat": str(brief_layers.get("hero_stat") or ""),
        # The director's motion language for this card (design_spec
        # MOTION_INTENTS). "" = the composition's mood/seed default.
        "motionIntent": str(b.get("motion_intent") or ""),
        # Resolved still-parity colour roles ("" = seed-permutation fallback).
        "roleGround": roles.get("roleGround", ""),
        "roleSurface": roles.get("roleSurface", ""),
        "roleAccent": roles.get("roleAccent", ""),
        "roleOnGround": roles.get("roleOnGround", ""),
    }


def _content_hash(payload: dict, *, kind: str) -> str:
    """Stable hash for the cache key. Serialises with sort_keys so call-site
    ordering doesn't bust the cache."""
    blob = json.dumps({"kind": kind, **payload}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _write_render_manifest(cached: Path, manifest: dict) -> None:
    """Persist the explainability record for one motion render.

    A small JSON sidecar next to the cached MP4 answering "why does this
    video look like this?" — archetype, motion intent, where the colours
    came from, the seed, format, and durations. Best-effort: a manifest
    failure must never fail (or follow) a successful render.
    """
    try:
        sidecar = cached.with_suffix(".json")
        sidecar.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
    except Exception:
        pass


def _publish_sidecar(cached: Path, out_path: Path) -> None:
    """Ship the explainability manifest with the MP4 it explains. Cache hits
    carry the sidecar from the original render; best-effort like the write."""
    try:
        src = cached.with_suffix(".json")
        dst = out_path.with_suffix(".json")
        if src.exists() and src.resolve() != dst.resolve():
            shutil.copyfile(src, dst)
    except Exception:
        pass


def _card_manifest_axes(card_props: dict) -> dict:
    """The per-card explainability axes worth recording (no photo bytes)."""
    return {
        "archetype": card_props.get("archetype") or "",
        "style_pack": card_props.get("stylePack") or "",
        "motion_intent": card_props.get("motionIntent") or "",
        "mood": card_props.get("mood") or "",
        "variation_seed": card_props.get("variationSeed") or 0,
        "colour_source": "still-parity-roles"
        if card_props.get("roleGround")
        else "seed-permutation",
        "has_photo": bool(card_props.get("photoSrc")),
        "photo_focus": card_props.get("photoPos") or "",
        "hero_stat": card_props.get("heroStat") or "",
    }


# ---------------------------------------------------------------------------
# Audio + poster finishing (engine-agnostic; see visual/audio_mux.py)
# ---------------------------------------------------------------------------


def _story_audio_plan(card_props: dict, brand_dict: dict):
    """The audio plan for one story render, or None for today's silent path.

    Built from the same props the composition displays (zero invention; see
    visual/narration.py). None when no audio source is configured — which
    also keeps the cache payload, and therefore every existing cache key,
    byte-identical to the pre-audio behaviour. The story line is one
    sentence; the mux's trim-to-video-length is the overrun guarantee.
    """
    try:
        from mediahub.visual import audio_mux, narration

        if not audio_mux.audio_active():
            return None
        script = ""
        if audio_mux.voice_active():
            script = narration.story_script(card_props, brand_dict)
        key = "story:{}:{}:{}".format(
            card_props.get("athleteFullName") or "",
            card_props.get("eventName") or "",
            card_props.get("resultValue") or "",
        )
        return audio_mux.build_audio_plan(script=script, content_key=key)
    except Exception:
        return None


def _reel_audio_plan(
    cards_props: list[dict], brand_dict: dict, meet_name: str, *, duration_sec: float
):
    """The audio plan for a reel render, or None for today's silent path."""
    try:
        from mediahub.visual import audio_mux, narration

        if not audio_mux.audio_active():
            return None
        script = ""
        if audio_mux.voice_active():
            script = narration.reel_script(
                cards_props, brand_dict, meet_name, max_seconds=duration_sec
            )
        first = cards_props[0] if cards_props else {}
        key = "reel:{}:{}:{}".format(
            meet_name or "", len(cards_props), first.get("athleteFullName") or ""
        )
        return audio_mux.build_audio_plan(script=script, content_key=key)
    except Exception:
        return None


def _audio_record_path(cached: Path) -> Path:
    """Sidecar recording whether the planned audio was attached to this MP4.

    A container probe can't answer that — Remotion's encoder emits a silent
    AAC track on every render, so "has an audio stream" does not mean "has
    the narration/music we planned". The record is written by the finishing
    pass itself and is the only thing trusted on a cache hit.
    """
    return Path(cached).with_suffix(".audio.json")


def _finish_cached_video(cached: Path, *, kind: str, plan, duration_sec: float) -> dict:
    """Idempotent finishing pass on the cached MP4: attach the planned audio
    (honest silent fallback on failure; retried on the next request) and
    ensure the poster-frame sidecar exists. Returns the manifest-ready
    audio record.
    """
    try:
        from mediahub.visual import audio_mux

        if plan:
            record_path = _audio_record_path(cached)
            audio_rec: dict = {}
            if record_path.exists():
                try:
                    prior = json.loads(record_path.read_text(encoding="utf-8"))
                    if isinstance(prior, dict) and prior.get("status") == "mixed":
                        audio_rec = prior
                except (OSError, ValueError):
                    audio_rec = {}
            if not audio_rec:
                audio_rec = audio_mux.apply_audio(cached, plan, duration_sec=duration_sec)
                try:
                    record_path.write_text(
                        json.dumps(audio_rec, indent=2, sort_keys=True, default=str),
                        encoding="utf-8",
                    )
                except OSError:
                    pass
        else:
            audio_rec = {"status": "off"}
        poster = audio_mux.poster_path_for(cached)
        if not poster.exists():
            audio_mux.write_poster(
                cached, poster, at_sec=audio_mux.poster_time_for(kind, duration_sec)
            )
        return audio_rec
    except Exception as e:
        return {"status": "silent_fallback", "reason": str(e)}


def _publish(cached: Path, out_path: Path) -> Path:
    """Copy the cached MP4 — plus its explainability manifest and poster
    sidecars, when present — to the caller-requested path. No-op when they
    are the same file."""
    from mediahub.visual.audio_mux import poster_path_for

    cached = Path(cached)
    out_path = Path(out_path)
    if cached.resolve() == out_path.resolve():
        return cached
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cached, out_path)
    _publish_sidecar(cached, out_path)
    cached_poster = poster_path_for(cached)
    if cached_poster.exists():
        try:
            shutil.copyfile(cached_poster, poster_path_for(out_path))
        except OSError:
            pass
    return out_path


def _update_manifest_audio(cached: Path, audio_rec: dict) -> None:
    """Refresh the manifest's audio record after a late audio attach (a
    cache hit whose earlier audio attempt fell back to silent). Best-effort."""
    try:
        sidecar = Path(cached).with_suffix(".json")
        if not sidecar.exists():
            return
        manifest = json.loads(sidecar.read_text(encoding="utf-8"))
        if manifest.get("audio") == audio_rec:
            return
        manifest["audio"] = audio_rec
        sidecar.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )
    except Exception:
        pass


def _run_remotion(
    *,
    composition_id: str,
    props: dict,
    out_path: Path,
    duration_sec: Optional[float] = None,
    size: Optional[tuple[int, int]] = None,
    timeout: int = 600,
) -> Path:
    """Invoke the Node render script. Raises RuntimeError on failure."""
    if not node_available():
        raise RuntimeError(
            "Node is not installed; install Node 18+ to render motion graphics. "
            "See CLAUDE.md → 'Remotion / motion graphics setup'."
        )
    if not RENDER_SCRIPT.exists():
        raise RuntimeError(f"Remotion render script missing at {RENDER_SCRIPT}")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Write props to a temp file alongside the cache; cheap and lets us tail
    # the JSON if a render fails.
    props_dir = _cache_dir() / "props"
    props_dir.mkdir(parents=True, exist_ok=True)
    props_path = props_dir / f"{out_path.stem}.json"
    props_path.write_text(json.dumps(props, indent=2), encoding="utf-8")

    cmd = [
        "node",
        str(RENDER_SCRIPT),
        "--composition",
        composition_id,
        "--props",
        str(props_path),
        "--output",
        str(out_path),
    ]
    if duration_sec is not None:
        cmd.extend(["--duration", str(duration_sec)])
    if size is not None:
        cmd.extend(["--width", str(int(size[0])), "--height", str(int(size[1]))])

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REMOTION_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Remotion render timed out after {timeout}s") from e

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip().splitlines()
        tail = "\n".join(stderr[-15:]) if stderr else "(no stderr)"
        raise RuntimeError(f"Remotion render failed (exit {proc.returncode}):\n{tail}")
    if not out_path.exists() or out_path.stat().st_size < 1024:
        raise RuntimeError(f"Remotion reported success but {out_path} is missing or empty")
    return out_path


# ---------------------------------------------------------------------------
# Engine dispatch
# ---------------------------------------------------------------------------


def _dispatch_engine() -> str:
    """Resolve and validate the configured engine; return its name.

    Called at the entry of each public render function.  When the engine
    resolves to 'remotion' (the default) the existing _run_remotion path
    continues completely unchanged.  'ffmpeg' routes to the free fallback
    in :mod:`mediahub.visual.reel_ffmpeg` (roadmap P0.1).
    """
    return select_reel_engine()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_story_card(
    card_payload: dict,
    brand_kit: Any,
    out_path: Path,
    *,
    variation_seed: int = 0,
    duration_sec: float = 6.0,
    brief: Optional[dict] = None,
    format_name: str = DEFAULT_MOTION_FORMAT,
) -> Path:
    """Render a single content-pack card to an MP4 story.

    Returns the path to the rendered MP4. Cached by content hash so
    repeated calls with the same card + brand + seed + brief + format
    reuse the existing file.

    Pass ``brief`` (as ``CreativeBrief.to_dict()``) to forward the
    Gemini-directed variation axes (layout/typography/background/
    accent/mood/motion intent) to the TSX composition. Without a brief
    the render falls back to variationSeed-only behaviour for backwards
    compat.

    ``format_name`` picks the output cut: ``story`` (1080×1920, default),
    ``portrait`` (1080×1350), ``square`` (1080×1080) or ``landscape``
    (1920×1080).

    When audio is configured (``MEDIAHUB_VOICEOVER=1`` narration and/or an
    operator ``MEDIAHUB_REEL_MUSIC_DIR`` bed), the finished MP4 carries the
    mixed track and the audio plan is folded into the cache key; otherwise
    the silent path's cache keys stay byte-identical to the pre-audio era.
    A poster-frame PNG sidecar is written beside the MP4 either way.
    """
    engine = _dispatch_engine()
    size = motion_format_size(format_name)
    out_path = Path(out_path)
    brand_dict = _brand_to_dict(brand_kit)
    card_dict = _card_to_props(
        card_payload,
        variation_seed=variation_seed,
        brief=brief,
        brand_kit=brand_kit,
        format_name=format_name,
    )
    audio_plan = _story_audio_plan(card_dict, brand_dict)

    if engine == "ffmpeg":
        if size != MOTION_FORMATS[DEFAULT_MOTION_FORMAT]:
            raise ReelEngineUnavailable(
                "The 'ffmpeg' reel engine currently renders the story "
                "(1080×1920) format only. Use the Remotion engine for "
                f"the {format_name!r} cut, or request format=story."
            )
        from mediahub.visual import reel_ffmpeg

        return reel_ffmpeg.render_story_card_from_props(
            card_dict,
            brand_dict,
            brand_kit,
            out_path,
            duration_sec=duration_sec,
            brief_dict=brief,
            audio_plan=audio_plan,
        )

    cache_payload = {
        "card": card_dict,
        "brand": brand_dict,
        "duration": duration_sec,
        "size": list(size),
    }
    if audio_plan:
        cache_payload["audio"] = audio_plan
    cache_key = _content_hash(cache_payload, kind="story")
    cached = _cache_dir() / f"{cache_key}.mp4"
    if cached.exists() and cached.stat().st_size > 1024:
        # Re-publish the cached MP4 at the caller-requested path. The
        # finishing pass is idempotent: it retries a previously-failed
        # audio attach and backfills a missing poster sidecar.
        audio_rec = _finish_cached_video(
            cached, kind="story", plan=audio_plan, duration_sec=duration_sec
        )
        if audio_plan:
            _update_manifest_audio(cached, audio_rec)
        return _publish(cached, out_path)

    # Render into the cache first so partial failures don't leave a half-
    # written file at the user-visible out_path.
    _run_remotion(
        composition_id=COMP_STORY,
        props={"card": card_dict, "brand": brand_dict},
        out_path=cached,
        duration_sec=duration_sec,
        size=size,
    )
    audio_rec = _finish_cached_video(
        cached, kind="story", plan=audio_plan, duration_sec=duration_sec
    )
    from mediahub.visual.audio_mux import poster_path_for

    _write_render_manifest(
        cached,
        {
            "kind": "story",
            "engine": engine,
            "format": format_name,
            "size": list(size),
            "duration_sec": duration_sec,
            "card": _card_manifest_axes(card_dict),
            "audio": audio_rec,
            "poster": poster_path_for(cached).name if poster_path_for(cached).exists() else "",
        },
    )
    published = _publish(cached, out_path)
    return published if published.exists() else cached


# Data-driven reel allocation (SEQ-4): the reel's length follows the number
# of ranked moments instead of a fixed 15s — a one-medal weekend is a tight
# 7s, a five-PB weekend a 23s recap. Mirrors MeetReel.tsx's scene layout
# (cover + N card scenes + outro beat).
REEL_COVER_SEC = 2.0
REEL_PER_CARD_SEC = 4.0
REEL_OUTRO_SEC = 1.0


def reel_duration_for(n_cards: int) -> float:
    """Total reel seconds for ``n_cards`` ranked moments.

    Deterministic structure maths (cover + per-card beats + outro), capped to
    the same 1..5 card range the route and the TSX composition enforce. Three
    cards land on the historic 15s default, so existing three-card reels keep
    their cached duration.
    """
    n = max(1, min(int(n_cards or 1), 5))
    return REEL_COVER_SEC + REEL_PER_CARD_SEC * n + REEL_OUTRO_SEC


def render_meet_reel(
    top_cards: list[dict],
    brand_kit: Any,
    out_path: Path,
    *,
    meet_name: str = "",
    duration_sec: Optional[float] = None,
    briefs: Optional[list[Optional[dict]]] = None,
    format_name: str = DEFAULT_MOTION_FORMAT,
) -> Path:
    """Render a multi-card reel from the top cards for a meet.

    Inputs:
      top_cards   list of card dicts (typically the top 3 from the content
                  pack). Each card is shaped via ``_card_to_props``.
      brand_kit   BrandKit or dict; applies palette, club name, logo hint.
      out_path    where the final MP4 should land. Cached results may be
                  copied here from the motion cache.
      meet_name   meet headline used on the reel cover. Defaults to the
                  first card's ``meet_name`` if blank.
      duration_sec explicit total reel duration. Default ``None`` =
                  data-driven: ``reel_duration_for(len(top_cards))``, so the
                  reel's structure follows the number of ranked moments
                  (1 card → 7s … 5 cards → 23s; 3 cards keep the historic 15s).
      format_name  output cut: ``story`` (default) / ``portrait`` /
                  ``square`` / ``landscape``.

    Audio + poster behaviour matches ``render_story_card``: opt-in narration
    (built only from the cards' own facts) and/or the operator's music bed
    are mixed in when configured, with an honest silent fallback, and a
    poster-frame PNG sidecar lands beside the MP4.
    """
    engine = _dispatch_engine()
    size = motion_format_size(format_name)
    out_path = Path(out_path)
    brand_dict = _brand_to_dict(brand_kit)

    cards_props: list[dict] = []
    briefs_list = list(briefs or [])
    for idx, c in enumerate(top_cards or []):
        # variation seed per card — caller may pass via {"variation_seed": N}
        seed = 0
        if isinstance(c, dict):
            seed = int(c.get("variation_seed") or 0)
            if not seed:
                # Derive a stable seed from the card id so re-renders are
                # deterministic per card without the caller having to
                # pre-compute it.
                cid = (
                    c.get("id")
                    or c.get("swim_id")
                    or (c.get("achievement") or {}).get("swim_id")
                    or ""
                )
                if cid:
                    try:
                        from mediahub.creative_brief.generator import (
                            auto_variation_seed_for,
                        )

                        seed = auto_variation_seed_for(str(cid))
                    except Exception:
                        seed = 1
        brief = briefs_list[idx] if idx < len(briefs_list) else None
        cards_props.append(
            _card_to_props(
                c, variation_seed=seed, brief=brief, brand_kit=brand_kit, format_name=format_name
            ),
        )

    if not meet_name:
        for cp in cards_props:
            if cp.get("meetName"):
                meet_name = cp["meetName"]
                break

    if duration_sec is None:
        duration_sec = reel_duration_for(len(cards_props))

    audio_plan = _reel_audio_plan(cards_props, brand_dict, meet_name, duration_sec=duration_sec)

    if engine == "ffmpeg":
        if size != MOTION_FORMATS[DEFAULT_MOTION_FORMAT]:
            raise ReelEngineUnavailable(
                "The 'ffmpeg' reel engine currently renders the story "
                "(1080×1920) format only. Use the Remotion engine for "
                f"the {format_name!r} cut, or request format=story."
            )
        from mediahub.visual import reel_ffmpeg

        return reel_ffmpeg.render_meet_reel_from_props(
            cards_props,
            brand_dict,
            brand_kit,
            out_path,
            meet_name=meet_name,
            duration_sec=duration_sec,
            brief_dicts=briefs_list,
            audio_plan=audio_plan,
        )

    cache_payload = {
        "cards": cards_props,
        "brand": brand_dict,
        "meet": meet_name,
        "duration": duration_sec,
        "size": list(size),
    }
    if audio_plan:
        cache_payload["audio"] = audio_plan
    cache_key = _content_hash(cache_payload, kind="reel")
    cached = _cache_dir() / f"{cache_key}.mp4"
    if cached.exists() and cached.stat().st_size > 1024:
        audio_rec = _finish_cached_video(
            cached, kind="reel", plan=audio_plan, duration_sec=duration_sec
        )
        if audio_plan:
            _update_manifest_audio(cached, audio_rec)
        return _publish(cached, out_path)

    _run_remotion(
        composition_id=COMP_REEL,
        props={"cards": cards_props, "brand": brand_dict, "meetName": meet_name},
        out_path=cached,
        duration_sec=duration_sec,
        size=size,
    )
    audio_rec = _finish_cached_video(
        cached, kind="reel", plan=audio_plan, duration_sec=duration_sec
    )
    from mediahub.visual.audio_mux import poster_path_for

    _write_render_manifest(
        cached,
        {
            "kind": "reel",
            "engine": engine,
            "format": format_name,
            "size": list(size),
            "duration_sec": duration_sec,
            "meet_name": meet_name,
            "cards": [_card_manifest_axes(cp) for cp in cards_props],
            "audio": audio_rec,
            "poster": poster_path_for(cached).name if poster_path_for(cached).exists() else "",
        },
    )
    published = _publish(cached, out_path)
    return published if published.exists() else cached


__all__ = [
    "render_story_card",
    "render_meet_reel",
    "reel_duration_for",
    "motion_format_size",
    "MOTION_FORMATS",
    "DEFAULT_MOTION_FORMAT",
    "node_available",
    "remotion_installed",
    "REMOTION_DIR",
    "ReelEngineUnavailable",
]


# Re-exported for tests; underscore-prefixed names are intentionally not in
# __all__ but stay importable as ``from mediahub.visual.motion import _logo_to_data_uri``.
