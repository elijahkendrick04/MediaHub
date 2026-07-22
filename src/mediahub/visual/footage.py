"""M23 — deterministic race-footage sourcing for motion story cards + reel beats.

A club's real race clip becomes the moving background of that swimmer's story
card / reel beat. Everything on this path is deterministic engine work — the
same library + the same card always resolve to the same clip and the same trim
window — because "which two seconds of which clip back this card" is the same
accuracy-critical decision as "which card outranks which":

* **Clip choice** — the fixed-weight media selector (``media_library.selector``,
  new ``race_footage`` role), athlete/meet-linked and permission-gated via the
  existing :meth:`MediaAsset.is_usable_for_post` seam. A clip that fails the
  gate is NEVER used. AI never picks footage.
* **Trim window** — :func:`mediahub.video.moments.detect_moments` (deterministic
  FFmpeg measurement + pure ranking), window sized to the beat (6s story; the
  card's carved beat seconds in a reel).
* **Priority rule (simple, deterministic)** — use footage when the best
  ``race_footage`` asset's selector score is **>=** the card photo's selector
  score, else keep the photo. A card whose photo the user manually cropped
  (inspector ``photo_pos``) keeps the photo — the crop is an explicit human
  investment in that photograph. The decision is recorded in the render
  manifest either way.

The chosen window is FFmpeg-trimmed to a normalised, MUTED, keyframe-clean
H.264 clip at a bounded resolution (720p-class long edge) under
``remotion/public/footage_cache/`` — the one directory Remotion's
``staticFile()`` can serve at render time (the same mechanism the self-hosted
fonts use; ``render.js`` re-bundles ``public/`` on every render, so a fresh
clip is always picked up). The cache is bounded: a fixed count cap prunes the
oldest trims so the bundle copy stays cheap and the repo tree can't grow
without bound (the directory is gitignored).

Honest by construction: a missing FFmpeg, an unprobed clip, a too-short clip,
or a permission-gate failure NEVER fails the render — the caller falls back to
the photo path with the reason recorded in the manifest.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

log = logging.getLogger(__name__)

# remotion/public — the only tree Remotion's staticFile() serves.
REMOTION_PUBLIC = Path(__file__).resolve().parents[1] / "remotion" / "public"
FOOTAGE_CACHE_DIRNAME = "footage_cache"

# Bounded output resolution: 720p-class long edge. The clip plays under a brand
# scrim on a 1080-wide canvas, so this is visually free and keeps the per-render
# bundle copy (Remotion copies public/ into each bundle) cheap.
CLIP_MAX_EDGE = 1280

# Count cap for the trim cache — a reel needs at most 5 clips, so a dozen keeps
# warm re-renders cheap while bounding disk + bundle-copy cost.
CACHE_MAX_CLIPS = 12

# The window detect_moments returns is clamped to the clip; a clip shorter than
# the beat would leave OffthreadVideo seeking past the end of the file, so a
# window more than this many ms short of the beat skips footage honestly.
_WINDOW_SHORTFALL_TOLERANCE_MS = 40


@dataclass(frozen=True)
class FootageResolution:
    """One resolved footage beat: what plays, and why — cache- and manifest-ready."""

    video_src: str  # public-relative path ("footage_cache/<sha16>-<in>-<out>.mp4")
    video_start_sec: float  # offset into the trimmed clip (0.0 — the trim is baked)
    video_duration_sec: float  # playable seconds in the trimmed clip
    cache_sig: dict  # {fingerprint, in_ms, out_ms, src} — cache-payload fold
    provenance: dict  # manifest record (asset id, filename, window, scores, rule)


def footage_cache_dir() -> Path:
    d = REMOTION_PUBLIC / FOOTAGE_CACHE_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def source_fingerprint(path: Path) -> str:
    """sha16 identity of a source clip (resolved path | mtime_ns | size).

    The same scheme the motion cutout cache uses: replacing a clip in place
    yields a new fingerprint, so a stale trim can never be served for new
    bytes.
    """
    st = path.stat()
    return hashlib.sha256(
        f"{path.resolve()}|{st.st_mtime_ns}|{st.st_size}".encode("utf-8")
    ).hexdigest()[:16]


def clip_scale_dims(width: int, height: int, *, max_edge: int = CLIP_MAX_EDGE) -> tuple[int, int]:
    """Bounded output dims: cap the long edge, keep aspect, round to even.

    Pure maths (same inputs → same dims). Never upscales — a 640×360 phone
    clip stays 640×360 (even-rounded), only larger sources come down.
    """
    w, h = max(2, int(width)), max(2, int(height))
    long_edge = max(w, h)
    if long_edge > max_edge:
        scale = max_edge / long_edge
        w = max(2, round(w * scale))
        h = max(2, round(h * scale))
    # H.264 yuv420p needs even dimensions.
    return w - (w % 2), h - (h % 2)


def pick_trim_window(moments: list, *, beat_ms: int) -> tuple[Optional[Any], str]:
    """The single best moment window for this beat, or (None, reason).

    Pure: picks the highest-scoring detected moment (earliest wins a tie —
    chronology is the honest tiebreak) and rejects a window materially shorter
    than the beat (the clip itself is too short to fill it).
    """
    if not moments:
        return None, "no-moment-detected"
    best = max(moments, key=lambda m: (m.score, -m.start_ms))
    if (best.end_ms - best.start_ms) + _WINDOW_SHORTFALL_TOLERANCE_MS < beat_ms:
        return None, "clip-shorter-than-beat"
    return best, ""


def prune_footage_cache(*, keep: int = CACHE_MAX_CLIPS) -> int:
    """Drop the oldest trimmed clips beyond the count cap. Returns pruned count.

    Moments memos (``*.moments.json``) are capped with the same budget — they
    are tiny, but a busy library would otherwise grow them without bound.
    """
    pruned = 0
    try:
        d = footage_cache_dir()
    except OSError:
        return 0
    for pattern in ("*.mp4", "*.moments.json"):
        try:
            files = sorted(
                (p for p in d.glob(pattern) if p.is_file()),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            continue
        for stale in files[max(0, int(keep)) :]:
            try:
                stale.unlink()
                pruned += 1
            except OSError:
                pass
    return pruned


def _cached_trim_window(
    src: Path, fingerprint: str, *, duration_ms: int, beat_ms: int
) -> tuple[Optional[Any], str]:
    """Memoised detect-and-pick of a clip's trim window for one beat length.

    Moment analysis is two full FFmpeg passes over the source, so warm
    renders re-paid ~1s+ per request even when the trimmed clip itself was
    cached. The picked window (or the honest negative outcome) is memoised
    per ``(source fingerprint, beat_ms)`` beside the trimmed clips; the
    fingerprint covers mtime/size, so a replaced clip re-analyses.
    ``MomentsUnavailable`` (missing FFmpeg) is deliberately never cached —
    the environment can gain FFmpeg between requests.
    """
    memo_path = footage_cache_dir() / f"{fingerprint}-{beat_ms}.moments.json"
    try:
        memo = json.loads(memo_path.read_text(encoding="utf-8"))
        if isinstance(memo, dict) and memo.get("v") == 1:
            if memo.get("window") is None:
                return None, str(memo.get("why") or "no-moment-detected")
            return SimpleNamespace(**memo["window"]), ""
    except (OSError, ValueError):
        pass

    from mediahub.video.moments import MomentsUnavailable, detect_moments

    try:
        moments = detect_moments(src, duration_ms=duration_ms, target_len_ms=beat_ms, max_moments=3)
    except MomentsUnavailable as e:
        return None, f"moments-unavailable: {e}"
    best, why = pick_trim_window(moments, beat_ms=beat_ms)
    memo_payload: dict[str, Any] = {"v": 1, "window": None, "why": why}
    if best is not None:
        memo_payload["window"] = {
            "start_ms": int(best.start_ms),
            "end_ms": int(best.end_ms),
            "score": float(best.score),
            "kind": str(best.kind),
            "reason": str(best.reason),
        }
    try:
        memo_path.write_text(json.dumps(memo_payload), encoding="utf-8")
    except OSError:
        pass  # memo is an optimisation — never fail the render over it
    if best is None:
        return None, why
    return SimpleNamespace(**memo_payload["window"]), ""


def _stabilize_in_place(exe: str, clip: Path) -> bool:
    """Two-pass vidstab on an already-trimmed, already-scaled beat clip, in place.

    Reuses the canonical vidstab settings from ``video/enhance.py`` (fixed
    shakiness/accuracy/smoothing constants → deterministic: same clip yields the
    same steadied file). The final encode preserves the OffthreadVideo contract
    (``-an``, yuv420p, 1s GOP, faststart) that ``enhance``'s generic builder
    omits. Temp files live beside the clip so the replace is an atomic same-fs
    rename. Returns False on any failure — the caller then serves the plain trim.
    """
    from mediahub.video import enhance

    try:
        with tempfile.TemporaryDirectory(prefix="mh_vidstab_", dir=str(clip.parent)) as td:
            trf = Path(td) / "transforms.trf"
            steadied = Path(td) / "steadied.mp4"
            detect = [
                exe,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                *enhance.vidstabdetect_args(
                    clip,
                    trf,
                    shakiness=enhance.DEFAULT_SHAKINESS,
                    accuracy=enhance.DEFAULT_ACCURACY,
                ),
            ]
            p1 = subprocess.run(detect, capture_output=True, text=True, timeout=300)
            if p1.returncode != 0 or not trf.exists():
                return False
            transform = [
                exe,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(clip),
                "-vf",
                (
                    f"vidstabtransform=input={trf}:"
                    f"smoothing={enhance.DEFAULT_SMOOTHING}:optzoom=1,"
                    "unsharp=5:5:0.5:3:3:0.0"
                ),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-g",
                "30",
                "-keyint_min",
                "30",
                "-movflags",
                "+faststart",
                str(steadied),
            ]
            p2 = subprocess.run(transform, capture_output=True, text=True, timeout=300)
            if p2.returncode != 0 or not steadied.exists() or steadied.stat().st_size < 1024:
                return False
            steadied.replace(clip)
            return True
    except Exception as e:
        log.warning("footage stabilization failed for %s: %s", clip, e)
        return False


def _normalise_clip(
    src: Path,
    out_path: Path,
    *,
    in_ms: int,
    out_ms: int,
    dims: tuple[int, int],
    stabilize: bool = False,
) -> bool:
    """FFmpeg-trim ``src`` [in_ms, out_ms) into a normalised beat clip.

    Muted (``-an``), H.264 yuv420p at the bounded dims, 30fps (the composition
    cadence), keyframe-clean (full re-encode + 1s GOP so OffthreadVideo's
    frame seeks are cheap and exact), faststart. Deterministic: same source
    bytes + window + dims → the same playable content. Returns False (and
    cleans up) on any failure — never a half-written clip.

    ``stabilize`` (opt-in, off by default) adds a deterministic two-pass vidstab
    finishing pass on the trimmed clip; the default path is byte-for-byte
    unchanged. A stabilization failure fails the whole normalise (the caller
    then falls back to the photo), never a half-steadied clip.
    """
    from mediahub.visual.reel_ffmpeg import ffmpeg_exe

    exe = ffmpeg_exe()
    if not exe:
        return False
    w, h = dims
    dur_s = max(0.1, (out_ms - in_ms) / 1000.0)
    tmp = out_path.with_name(out_path.name + ".part.mp4")
    cmd = [
        exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{in_ms / 1000.0:.3f}",
        "-i",
        str(src),
        "-t",
        f"{dur_s:.3f}",
        "-an",
        "-vf",
        f"scale={w}:{h},fps=30,format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "21",
        "-g",
        "30",
        "-keyint_min",
        "30",
        "-movflags",
        "+faststart",
        str(tmp),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 1024:
            raise RuntimeError((proc.stderr or "").strip().splitlines()[-1:] or "empty output")
        if stabilize and not _stabilize_in_place(exe, tmp):
            raise RuntimeError("vidstab pass failed")
        tmp.replace(out_path)
        return True
    except Exception as e:
        log.warning("footage trim failed for %s: %s", src, e)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _photo_led_archetype(brief: dict) -> bool:
    """True when the card's archetype shows the ORIGINAL photograph full-bleed.

    Footage only backs "photo"-mode archetypes: those render the photograph as
    a rectangular stage under the template's own scrims — exactly the plane a
    muted race clip can honestly replace. Cutout-mode archetypes (spotlight
    discs, band breaks…) build their scene around a silhouette; a full-bleed
    video there would diverge from the approved still.
    """
    arch = str(brief.get("layout_template") or "")
    if not arch:
        return False
    try:
        from mediahub.graphic_renderer import archetypes as _archetypes

        return arch in _archetypes.photo_archetypes() and _archetypes.photo_mode(arch) == "photo"
    except Exception:
        return False


def _card_athlete(card: Any, brief: dict) -> str:
    layers = brief.get("text_layers") if isinstance(brief.get("text_layers"), dict) else {}
    ach = card.get("achievement") if isinstance(card, dict) else None
    if not isinstance(ach, dict):
        ach = card if isinstance(card, dict) else {}
    return str(
        layers.get("athlete_full_name")
        or ach.get("swimmer_name")
        or ach.get("athlete_name")
        or (card.get("swimmer_name") if isinstance(card, dict) else "")
        or ""
    ).strip()


def _profile_id_of(brand_kit: Any, brief: dict) -> str:
    if isinstance(brand_kit, dict):
        pid = str(brand_kit.get("profile_id") or brand_kit.get("profileId") or "")
    else:
        pid = str(getattr(brand_kit, "profile_id", "") or "")
    return pid or str(brief.get("profile_id") or "")


def resolve_card_footage(
    card: Any,
    brief: Optional[dict],
    brand_kit: Any,
    *,
    beat_seconds: float,
    photo_asset: Any = None,
    store: Any = None,
) -> tuple[Optional[FootageResolution], str]:
    """Resolve the footage beat for one card — ``(resolution, reason)``.

    ``(None, "")`` means "nothing to say" (no brief / non-photo archetype / no
    footage in the library); ``(None, reason)`` means a candidate existed but
    lost or failed, with the honest manifest-ready reason. Never raises.

    ``photo_asset`` is the card's already-resolved still photo (the brief's
    sourced asset), passed by the caller so the priority rule can score it
    without re-resolving.
    """
    try:
        return _resolve_card_footage(
            card, brief, brand_kit, beat_seconds=beat_seconds, photo_asset=photo_asset, store=store
        )
    except Exception as e:  # a footage miss must never fail the render
        log.warning("footage resolution failed: %s", e)
        return None, f"footage-resolution-error: {e}"


def _resolve_card_footage(
    card: Any,
    brief: Optional[dict],
    brand_kit: Any,
    *,
    beat_seconds: float,
    photo_asset: Any,
    store: Any,
) -> tuple[Optional[FootageResolution], str]:
    b = brief if isinstance(brief, dict) else {}
    if not b or str(b.get("photo_treatment") or "") == "no-photo":
        return None, ""
    if not _photo_led_archetype(b):
        return None, ""
    overrides = card.get("inspector_overrides") if isinstance(card, dict) else None
    overrides = overrides if isinstance(overrides, dict) else {}
    if overrides.get("no_photo"):
        return None, ""
    if str(overrides.get("photo_pos") or "").strip():
        # A manual crop is an explicit human investment in the photograph —
        # the user-tended photo always wins over footage.
        return None, "photo-pinned-by-manual-crop"

    if store is None:
        from mediahub.media_library.store import get_store

        store = get_store()
    profile_id = _profile_id_of(brand_kit, b)
    athlete = _card_athlete(card, b)
    try:
        assets = store.list(profile_id=profile_id or None, asset_type="footage", limit=200)
    except Exception:
        return None, ""
    if not assets:
        return None, ""

    from mediahub.media_library.selector import score_asset, select_assets

    picks = select_assets(assets, role="race_footage", athlete_name=athlete or None, k=3)
    if not picks:
        return None, "no-usable-footage-for-athlete"

    # Priority rule (simple + deterministic): footage plays only when the best
    # race clip scores at least as well as the card's photo. No photo → 0.0.
    photo_score = 0.0
    if photo_asset is not None:
        try:
            photo_score = score_asset(
                photo_asset, role="hero_athlete", athlete_name=athlete or None
            )
        except Exception:
            photo_score = 0.0

    for pick in picks:
        asset = store.get(str(pick.get("asset_id") or ""))
        if asset is None:
            continue
        # Belt-and-braces consent gate beside the selector's own zero-score:
        # a do_not_use / needs_parental_consent / rejected clip is NEVER used.
        if not asset.is_usable_for_post():
            continue
        footage_score = float(pick.get("score") or 0.0)
        if footage_score < photo_score:
            return None, (f"photo-outscores-footage ({photo_score:.3f} > {footage_score:.3f})")
        src = Path(str(asset.path or ""))
        if not src.exists():
            continue
        meta = asset.media_meta if isinstance(asset.media_meta, dict) else {}
        duration_ms = int(meta.get("duration_ms") or 0)
        if duration_ms <= 0:
            return None, "footage-unprobed (no duration recorded at ingest)"
        beat_ms = max(500, round(float(beat_seconds) * 1000))
        if duration_ms + _WINDOW_SHORTFALL_TOLERANCE_MS < beat_ms:
            return None, "clip-shorter-than-beat"

        fingerprint = source_fingerprint(src)
        best, why = _cached_trim_window(src, fingerprint, duration_ms=duration_ms, beat_ms=beat_ms)
        if best is None:
            return None, why

        dims = clip_scale_dims(asset.width or 1280, asset.height or 720)

        # Opt-in, deterministic stabilization: a stored per-asset boolean, gated
        # by the host FFmpeg actually having the vidstab filter. Off by default,
        # so the clip filename, cache_sig, and provenance are all byte-identical
        # for every clip that doesn't request it.
        stab_req = bool(meta.get("stabilize"))
        stab_applied = False
        if stab_req:
            from mediahub.video import enhance

            stab_applied = enhance.is_stabilize_available()

        stab_suffix = "-stab" if stab_applied else ""
        clip_name = f"{fingerprint}-{best.start_ms}-{best.end_ms}{stab_suffix}.mp4"
        clip_path = footage_cache_dir() / clip_name
        if not (clip_path.exists() and clip_path.stat().st_size > 1024):
            if not _normalise_clip(
                src,
                clip_path,
                in_ms=best.start_ms,
                out_ms=best.end_ms,
                dims=dims,
                stabilize=stab_applied,
            ):
                return None, "ffmpeg-trim-failed-or-unavailable"
            prune_footage_cache()

        video_src = f"{FOOTAGE_CACHE_DIRNAME}/{clip_name}"
        window_sec = round((best.end_ms - best.start_ms) / 1000.0, 3)
        cache_sig = {
            "src": video_src,
            "fingerprint": fingerprint,
            "in_ms": best.start_ms,
            "out_ms": best.end_ms,
        }
        provenance = {
            "used": True,
            "asset_id": asset.id,
            "filename": asset.filename,
            "in_ms": best.start_ms,
            "out_ms": best.end_ms,
            "moment": {
                "score": round(best.score, 4),
                "kind": best.kind,
                "reason": best.reason,
            },
            "footage_score": round(footage_score, 3),
            "photo_score": round(photo_score, 3),
            "decision": "footage",
            "rule": "footage plays when its selector score >= the photo's",
        }
        # Fold stabilization state only when it was requested, so the default
        # (no-stabilize) footage card keeps its exact historic cache key.
        if stab_req:
            cache_sig["stabilize"] = "applied" if stab_applied else "unavailable"
            provenance["stabilize"] = {
                "requested": True,
                "applied": stab_applied,
                "reason": "" if stab_applied else "vidstab-unavailable",
            }
        resolution = FootageResolution(
            video_src=video_src,
            video_start_sec=0.0,
            video_duration_sec=window_sec,
            cache_sig=cache_sig,
            provenance=provenance,
        )
        return resolution, ""
    return None, "no-usable-footage-for-athlete"


__all__ = [
    "FootageResolution",
    "footage_cache_dir",
    "source_fingerprint",
    "clip_scale_dims",
    "pick_trim_window",
    "prune_footage_cache",
    "resolve_card_footage",
    "CLIP_MAX_EDGE",
    "CACHE_MAX_CLIPS",
]
