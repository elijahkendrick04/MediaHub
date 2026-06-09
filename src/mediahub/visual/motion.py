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


def _card_to_props(
    card: dict,
    *,
    variation_seed: int = 0,
    brief: Optional[dict] = None,
) -> dict[str, Any]:
    """Coerce one content-pack card payload into the StoryCard props shape.

    Accepts either a flat dict ({"swimmer_name": ..., "event": ...}) or the
    nested {"achievement": {...}} variant emitted by the recognition layer.

    When ``brief`` is supplied (the AI-directed CreativeBrief for this
    card, as a dict via ``brief.to_dict()``), the variation axes the
    director picked — layout family, typography pair, composition,
    background style, accent style, mood, photo treatment — are
    forwarded to Remotion. The TypeScript StoryCard composition uses
    those axes to vary fonts, layout, animation spring, background
    pattern, and accent decoration, so a Gemini-directed run produces
    visually distinct motion for every card instead of just rotating
    palette roles.
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
    }


def _content_hash(payload: dict, *, kind: str) -> str:
    """Stable hash for the cache key. Serialises with sort_keys so call-site
    ordering doesn't bust the cache."""
    blob = json.dumps({"kind": kind, **payload}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _run_remotion(
    *,
    composition_id: str,
    props: dict,
    out_path: Path,
    duration_sec: Optional[float] = None,
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


def _dispatch_engine() -> None:
    """Validate the configured engine; raise for any non-remotion selection.

    Called at the entry of each public render function.  When the engine
    resolves to 'remotion' (the default) this is a pure no-op and the
    existing _run_remotion path continues completely unchanged.

    The 'satori' engine is registered as a future placeholder but is not
    yet implemented; callers receive an honest ReelEngineUnavailable rather
    than a fake/placeholder asset (CLAUDE.md AI-surfaces rule).
    """
    engine = select_reel_engine()
    if engine != "remotion":
        raise ReelEngineUnavailable(
            f"The '{engine}' render engine is not yet implemented. "
            "Set MEDIAHUB_REEL_ENGINE=remotion (or leave it unset) to use "
            "the production Remotion renderer."
        )


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
) -> Path:
    """Render a single content-pack card to a 1080x1920 MP4 story.

    Returns the path to the rendered MP4. Cached by content hash so
    repeated calls with the same card + brand + seed + brief reuse
    the existing file.

    Pass ``brief`` (as ``CreativeBrief.to_dict()``) to forward the
    Gemini-directed variation axes (layout/typography/background/
    accent/mood) to the TSX composition. Without a brief the render
    falls back to variationSeed-only behaviour for backwards compat.
    """
    _dispatch_engine()
    out_path = Path(out_path)
    brand_dict = _brand_to_dict(brand_kit)
    card_dict = _card_to_props(
        card_payload,
        variation_seed=variation_seed,
        brief=brief,
    )

    cache_key = _content_hash(
        {"card": card_dict, "brand": brand_dict, "duration": duration_sec},
        kind="story",
    )
    cached = _cache_dir() / f"{cache_key}.mp4"
    if cached.exists() and cached.stat().st_size > 1024:
        # Re-publish the cached MP4 at the caller-requested path (without
        # an expensive copy when the caller asked for the cache location).
        if cached.resolve() != out_path.resolve():
            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cached, out_path)
            return out_path
        return cached

    # Render into the cache first so partial failures don't leave a half-
    # written file at the user-visible out_path.
    _run_remotion(
        composition_id=COMP_STORY,
        props={"card": card_dict, "brand": brand_dict},
        out_path=cached,
        duration_sec=duration_sec,
    )
    if cached.resolve() != out_path.resolve():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cached, out_path)
    return out_path if out_path.exists() else cached


def render_meet_reel(
    top_cards: list[dict],
    brand_kit: Any,
    out_path: Path,
    *,
    meet_name: str = "",
    duration_sec: float = 15.0,
    briefs: Optional[list[Optional[dict]]] = None,
) -> Path:
    """Render a multi-card reel (default 15s) from the top cards for a meet.

    Inputs:
      top_cards   list of card dicts (typically the top 3 from the content
                  pack). Each card is shaped via ``_card_to_props``.
      brand_kit   BrandKit or dict; applies palette, club name, logo hint.
      out_path    where the final MP4 should land. Cached results may be
                  copied here from the motion cache.
      meet_name   meet headline used on the reel cover. Defaults to the
                  first card's ``meet_name`` if blank.
      duration_sec total reel duration; default 15s.
    """
    _dispatch_engine()
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
            _card_to_props(c, variation_seed=seed, brief=brief),
        )

    if not meet_name:
        for cp in cards_props:
            if cp.get("meetName"):
                meet_name = cp["meetName"]
                break

    cache_key = _content_hash(
        {
            "cards": cards_props,
            "brand": brand_dict,
            "meet": meet_name,
            "duration": duration_sec,
        },
        kind="reel",
    )
    cached = _cache_dir() / f"{cache_key}.mp4"
    if cached.exists() and cached.stat().st_size > 1024:
        if cached.resolve() != out_path.resolve():
            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cached, out_path)
            return out_path
        return cached

    _run_remotion(
        composition_id=COMP_REEL,
        props={"cards": cards_props, "brand": brand_dict, "meetName": meet_name},
        out_path=cached,
        duration_sec=duration_sec,
    )
    if cached.resolve() != out_path.resolve():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cached, out_path)
    return out_path if out_path.exists() else cached


__all__ = [
    "render_story_card",
    "render_meet_reel",
    "node_available",
    "remotion_installed",
    "REMOTION_DIR",
    "ReelEngineUnavailable",
]


# Re-exported for tests; underscore-prefixed names are intentionally not in
# __all__ but stay importable as ``from mediahub.visual.motion import _logo_to_data_uri``.
