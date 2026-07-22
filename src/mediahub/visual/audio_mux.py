"""visual/audio_mux.py — engine-agnostic audio + poster finishing for MP4s.

Motion renders (Remotion or the free FFmpeg engine) historically shipped
silent. This module is the one seam that changes that: after an MP4 is
rendered, it can

* speak a deterministic, fact-only narration (built by
  ``visual/narration.py``, synthesised by ``visual/voiceover.py`` — the
  same verbatim-text TTS the caption voiceover uses), and/or
* lay an operator-supplied music bed under it — shaped by the R1.20
  music-bed upgrade: a sidechain compressor ducks the bed dynamically under
  narration (rather than a static level), intro/outro stings swell it in and
  resolve it out, and a brief accent lands on every card cut so the bed feels
  cut to the edit, and
* extract a poster-frame PNG sidecar for review surfaces and platforms
  that want a thumbnail.

Rules (the same honesty contract as the rest of the renderer):

- **Off by default.** Voice rides the existing ``MEDIAHUB_VOICEOVER=1``
  opt-in; music only plays when the operator points
  ``MEDIAHUB_REEL_MUSIC_DIR`` at a directory of files *they* hold the
  licence for. MediaHub ships no audio assets and asserts no rights — every
  sting and accent is shaped from the operator's *own* bed, never fabricated.
- **Honest silent fallback.** If synthesis or the mux fails, the video
  stays silent and the manifest records why — never a placeholder track.
- **Deterministic.** The music track for a given render is picked by
  content hash from the sorted directory listing; the beat grid the accents
  align to is the reel's own structure; the bed's resting balance follows the
  render's fixed audio-mix profile (voice_lead / balanced / music_forward);
  ducking, stings, accents, and fades are all fixed constants (one optional
  knob: an operator-declared tempo in the filename tunes accent width). Same
  inputs → same audio.
- **Video bits untouched.** The mux stream-copies the video track; only an
  audio track is added.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from mediahub.visual.reel_ffmpeg import ffmpeg_exe

# Fixed mix constants — deterministic by design (no per-render knobs).
MUSIC_BED_VOLUME = 0.40  # music alone
MUSIC_UNDER_VOICE_WEIGHT = 0.30  # music's resting level under narration
AUDIO_FADE_OUT_SEC = 0.6

# R1.20 — refined automatic ducking. Music under narration is no longer held
# at one static level; a sidechain compressor keyed off the voice ducks the bed
# only while someone is speaking and lets it breathe back up in the gaps.
# Fixed constants → deterministic, same inputs give the same mix.
DUCK_THRESHOLD = 0.03  # voice level (linear) that starts ducking the bed
DUCK_RATIO = 6.0  # how hard the bed is pushed down while voice is present
DUCK_ATTACK_MS = 20.0  # how fast the bed gets out of the way
DUCK_RELEASE_MS = 300.0  # how fast it recovers in a speech gap

# R1.20 — intro/outro stings. Short shaped accents on the operator's *own* bed
# (MediaHub ships no audio): a punchy swell-in at the top and a final accent
# that resolves into the shared tail fade-out. No fabricated track.
INTRO_STING_SEC = 0.8
OUTRO_STING_SEC = 0.7
STING_GAIN = 1.6  # transient boost over bed level for a sting accent

# R1.20 — beat-aware alignment of card cuts. A brief music emphasis lands on
# every card transition so the bed feels cut to the edit. When the operator
# declares a track's tempo (music-pool logic, see ``track_bpm``) the accent is
# one musical beat long; otherwise a fixed default width is used.
CUT_ACCENT_SEC = 0.25
CUT_ACCENT_GAIN = 1.35

_MUSIC_SUFFIXES = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac"}

# Operator-declared tempo in a filename, e.g. ``anthem.128bpm.mp3`` or
# ``warmup-90 bpm.wav``. Never inferred by DSP — kept deterministic.
_BPM_RE = re.compile(r"(?:^|[^0-9])(\d{2,3})\s*bpm", re.IGNORECASE)
_BPM_MIN, _BPM_MAX = 40.0, 300.0

_TRUTHY = {"1", "true", "yes", "on"}

# Opt-in EBU R128 loudness normalisation. Off by default; when the operator sets
# ``MEDIAHUB_REEL_LOUDNORM=1`` the final mix is normalised to a fixed integrated
# loudness / true-peak / range target so reels hit a consistent platform level
# instead of the uncalibrated fixed gains. Single-pass (a stateless one-shot
# filter) so it stays deterministic — targets come only from env, parsed and
# clamped to fixed ranges (malformed → defaults, never raises). Folded into the
# audio plan (and therefore the cache key) only when on, so the default path —
# and every existing cached MP4 — stays byte-identical.
LOUDNORM_DEFAULT_I = -14.0  # integrated loudness target (LUFS) — a common social level
LOUDNORM_DEFAULT_TP = -1.0  # true-peak ceiling (dBTP)
LOUDNORM_DEFAULT_LRA = 11.0  # loudness range (LU)
_LOUDNORM_I_RANGE = (-31.0, -5.0)
_LOUDNORM_TP_RANGE = (-9.0, 0.0)
_LOUDNORM_LRA_RANGE = (1.0, 50.0)

# Operator-declared music-bed volume envelope — a keyframable generalisation of
# the fixed per-profile resting level. A sibling ``<track>.env.json`` sidecar (or
# a global ``MEDIAHUB_REEL_AUDIO_ENVELOPE`` file) holds a JSON array of
# ``{"t": seconds, "gain": multiplier}`` points; the bed's resting level then
# steps between them (the intro/outro stings, cut accents and sidechain ducking
# still act on top). File-derived and deterministic — never inferred by DSP.
_ENV_SUFFIX = ".env.json"
_ENV_MAX_GAIN = 3.0  # ceiling on a bed boost when the bed plays alone
# Under narration the envelope may only duck the bed, never boost it above the
# profile's tuned resting level — so a keyframe can't defeat voice intelligibility.
_ENV_MAX_GAIN_UNDER_VOICE = 1.0


# ---------------------------------------------------------------------------
# Per-card audio-mix profiles (R1.19)
#
# A render chooses how the narration and the music bed sit against each other.
# Each profile is a fixed, deterministic level set folded into the audio plan
# (and therefore the motion cache key), so a voice-lead and a music-forward cut
# of the same card can never serve each other from cache. The profile sets the
# bed's RESTING level (the base the R1.20 sidechain ducking, stings and accents
# then act on) and how hard the bed ducks under speech — it does not replace the
# dynamics, only the balance they work from. ``balanced`` *is* the historic mix:
# it reuses the module constants above, so the default path stays byte-for-byte
# identical and no existing cache is orphaned. The bed always ducks under the
# voice, so the narration stays intelligible under every profile (it is fact
# narration, never decoration).
# ---------------------------------------------------------------------------

DEFAULT_MIX_PROFILE = "balanced"

AUDIO_MIX_PROFILES: dict[str, dict[str, float]] = {
    # Narration is the star: a low resting bed that ducks hard under speech.
    "voice_lead": {
        "music_under_voice_weight": 0.18,
        "music_bed_volume": 0.32,
        "duck_ratio": 9.0,
    },
    # The historic fixed mix (references the constants so it can never drift).
    "balanced": {
        "music_under_voice_weight": MUSIC_UNDER_VOICE_WEIGHT,
        "music_bed_volume": MUSIC_BED_VOLUME,
        "duck_ratio": DUCK_RATIO,
    },
    # Music carries the piece: a higher resting bed that ducks more gently, so
    # the bed stays present under the (still fully intelligible) narration.
    "music_forward": {
        "music_under_voice_weight": 0.50,
        "music_bed_volume": 0.60,
        "duck_ratio": 3.5,
    },
}


def resolve_mix_profile(name: Any) -> str:
    """Canonical mix-profile name; unknown / empty / ``None`` → the default."""
    key = str(name or "").strip().lower()
    return key if key in AUDIO_MIX_PROFILES else DEFAULT_MIX_PROFILE


def env_mix_profile() -> str:
    """Operator-wide default mix profile (``MEDIAHUB_REEL_MIX_PROFILE``)."""
    return resolve_mix_profile(os.environ.get("MEDIAHUB_REEL_MIX_PROFILE", ""))


def mix_profile_levels(name: Any) -> dict[str, float]:
    """The fixed level set for a profile (validated). Always a fresh dict."""
    return dict(AUDIO_MIX_PROFILES[resolve_mix_profile(name)])


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def resolve_loudnorm() -> Optional[dict]:
    """Opt-in EBU R128 loudness target for the final mix, or ``None`` when off.

    Off unless ``MEDIAHUB_REEL_LOUDNORM`` is truthy. When on, the integrated
    loudness / true-peak / range targets may be tuned via
    ``MEDIAHUB_REEL_LOUDNORM_LUFS`` / ``_TP`` / ``_LRA`` — each parsed and clamped
    to a fixed range, with malformed values falling back to the default (never
    raises). Returns a canonical ``{"i", "tp", "lra"}`` dict so identical env
    gives an identical filter string, and therefore an identical cache key.
    """
    if os.environ.get("MEDIAHUB_REEL_LOUDNORM", "").strip().lower() not in _TRUTHY:
        return None

    def _read(name: str, default: float, lo: float, hi: float) -> float:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return default
        try:
            return _clamp(float(raw), lo, hi)
        except ValueError:
            return default

    return {
        "i": _read("MEDIAHUB_REEL_LOUDNORM_LUFS", LOUDNORM_DEFAULT_I, *_LOUDNORM_I_RANGE),
        "tp": _read("MEDIAHUB_REEL_LOUDNORM_TP", LOUDNORM_DEFAULT_TP, *_LOUDNORM_TP_RANGE),
        "lra": _read("MEDIAHUB_REEL_LOUDNORM_LRA", LOUDNORM_DEFAULT_LRA, *_LOUDNORM_LRA_RANGE),
    }


def _coalesce_profile(explicit: Any) -> str:
    """Precedence for a render's mix profile: a known per-card override wins,
    else the operator env default, else ``balanced``."""
    key = str(explicit or "").strip().lower()
    if key in AUDIO_MIX_PROFILES:
        return key
    return env_mix_profile()


def voice_active() -> bool:
    """True when the operator opted into voiceover AND a backend can speak."""
    if os.environ.get("MEDIAHUB_VOICEOVER", "").strip().lower() not in _TRUTHY:
        return False
    try:
        from mediahub.visual import voiceover

        return voiceover.is_available()
    except Exception:
        return False


def voice_name() -> str:
    """The configured TTS voice (same env the caption voiceover honours)."""
    from mediahub.visual.voiceover import DEFAULT_VOICE

    return os.environ.get("MEDIAHUB_VOICEOVER_VOICE", "").strip() or DEFAULT_VOICE


def music_dir() -> Optional[Path]:
    """The operator's licensed-music directory, or None when unset/missing."""
    raw = os.environ.get("MEDIAHUB_REEL_MUSIC_DIR", "").strip()
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_dir() else None


def library_bed_enabled() -> bool:
    """True when reels may use MediaHub's bundled licence-clean audio library
    as the default music bed (roadmap 1.8, opt-in via
    ``MEDIAHUB_REEL_MUSIC_LIBRARY``).

    Off by default so an existing deployment's renders — and every cached MP4 —
    stay byte-identical. When on, a reel with no operator-supplied music bed
    (``MEDIAHUB_REEL_MUSIC_DIR``) gets a deterministically-picked bed from the
    bundled CC0 pool, so reels have sound out of the box. The operator's own
    licensed directory always takes precedence over the bundled pool.
    """
    return os.environ.get("MEDIAHUB_REEL_MUSIC_LIBRARY", "").strip().lower() in _TRUTHY


def music_candidates() -> list[Path]:
    d = music_dir()
    if d is None:
        return []
    return sorted(
        (p for p in d.iterdir() if p.is_file() and p.suffix.lower() in _MUSIC_SUFFIXES),
        key=lambda p: p.name,
    )


def pick_music(content_key: str) -> Optional[Path]:
    """Deterministic track pick: stable per content key, spread across the pool."""
    tracks = music_candidates()
    if not tracks:
        return None
    digest = hashlib.sha256((content_key or "").encode("utf-8")).hexdigest()
    return tracks[int(digest[:8], 16) % len(tracks)]


def track_bpm(path) -> Optional[float]:
    """The operator-declared tempo of a bed, or ``None`` — never DSP-guessed.

    Read from the filename (``anthem.128bpm.mp3``) or a sibling ``<track>.bpm``
    sidecar holding a single number. This is the music-pool metadata that lets
    the beat-aware cut accents be exactly one musical beat long; absent it the
    accents fall back to a fixed width. Deterministic and dependency-free.
    """
    p = Path(path)
    m = _BPM_RE.search(p.stem)
    if m:
        try:
            v = float(m.group(1))
            if _BPM_MIN <= v <= _BPM_MAX:
                return v
        except ValueError:
            pass
    side = p.with_name(p.name + ".bpm")
    try:
        if side.is_file():
            v = float(side.read_text(encoding="utf-8").strip())
            if _BPM_MIN <= v <= _BPM_MAX:
                return v
    except (OSError, ValueError):
        pass
    return None


def track_envelope(path) -> Optional[list[dict]]:
    """The operator-declared volume envelope for a bed, or ``None`` — never DSP-guessed.

    Read from a sibling ``<track>.env.json`` sidecar, else a global
    ``MEDIAHUB_REEL_AUDIO_ENVELOPE`` JSON file (mirrors ``env_mix_profile``). The
    file is a JSON array of ``{"t": seconds, "gain": multiplier}`` points. Parsed
    defensively: non-dict / non-numeric points dropped, ``t`` clamped ``>= 0``,
    ``gain`` clamped to ``[0, _ENV_MAX_GAIN]``, both rounded to 3dp, sorted by
    ``t`` with duplicate timestamps de-duped (last wins). Empty / invalid /
    missing → ``None``. Purely file-derived (the same 'never DSP-guessed' rule as
    ``track_bpm``), so the render stays deterministic.
    """
    p = Path(path)
    raw_text: Optional[str] = None
    side = p.with_name(p.name + _ENV_SUFFIX)
    try:
        if side.is_file():
            raw_text = side.read_text(encoding="utf-8")
    except OSError:
        raw_text = None
    if raw_text is None:
        env_path = os.environ.get("MEDIAHUB_REEL_AUDIO_ENVELOPE", "").strip()
        if env_path:
            try:
                ep = Path(env_path)
                if ep.is_file():
                    raw_text = ep.read_text(encoding="utf-8")
            except OSError:
                raw_text = None
    if raw_text is None:
        return None
    try:
        data = json.loads(raw_text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, list):
        return None
    cleaned: dict[float, float] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            t = float(item["t"])
            g = float(item["gain"])
        except (KeyError, TypeError, ValueError):
            continue
        t = max(0.0, t)
        g = _clamp(g, 0.0, _ENV_MAX_GAIN)
        cleaned[round(t, 3)] = round(g, 3)  # last write wins for a duplicate t
    if not cleaned:
        return None
    return [{"t": t, "gain": cleaned[t]} for t in sorted(cleaned)]


def envelope_filter(
    points: Optional[list[dict]], duration_sec: float, *, max_gain: Optional[float] = None
) -> str:
    """A piecewise-constant volume chain for the bed's resting level, or ``""``.

    Each point holds its gain until the next point (the last runs to
    ``duration_sec``); the region before the first point stays at unit gain (no
    filter emitted). ``max_gain`` caps every gain — used under narration so the
    envelope can only duck the bed, never boost it above its tuned resting level.
    Pure: a comma-joined chain of ``volume=g:enable='between(t,a,b)'`` gates, the
    same idiom as the stings/accents. Empty / ``None`` points → ``""``.
    """
    pts = points or []
    if not pts:
        return ""
    d = max(0.1, float(duration_sec))
    gates: list[str] = []
    n = len(pts)
    for i, pt in enumerate(pts):
        a = float(pt["t"])
        if a >= d:
            break
        b = float(pts[i + 1]["t"]) if i + 1 < n else d
        b = min(b, d)
        if b <= a:
            continue
        g = float(pt["gain"])
        if max_gain is not None:
            g = min(g, max_gain)
        gates.append(f"volume={g:.3f}:enable='between(t,{a:.3f},{b:.3f})'")
    return ",".join(gates)


def music_pool_summary() -> dict:
    """Explainability snapshot of the operator's music pool (for manifests)."""
    tracks = music_candidates()
    return {
        "count": len(tracks),
        "with_declared_bpm": sum(1 for t in tracks if track_bpm(t) is not None),
        "tracks": [t.name for t in tracks],
    }


def audio_active() -> bool:
    """True when any audio source could apply to a render right now."""
    return voice_active() or bool(music_candidates()) or library_bed_enabled()


def build_audio_plan(
    *, script: str, content_key: str, mix_profile: Any = None, library_track: Any = None
) -> Optional[dict]:
    """The cache-identity description of a render's audio, or None for silent.

    Only identity fields live here (voice name, the exact script, the music
    file's name + size, and the non-default mix profile) — the plan is folded
    into the motion cache hash, so a changed script, voice, track, or mix can
    never serve a stale render. ``None`` keeps the silent path's cache keys
    byte-identical to the pre-audio era.

    ``mix_profile`` picks the voice/music balance (``voice_lead`` /
    ``balanced`` / ``music_forward``); an unknown or absent value falls back
    to the operator env default (``MEDIAHUB_REEL_MIX_PROFILE``) and then to
    ``balanced``. The profile is recorded here — and so in the cache key —
    *only* when it is not the default, so a balanced render keeps the
    pre-profile cache key byte-for-byte (no cache is orphaned).

    ``library_track`` (roadmap 1.8) is an optional bundled-library bed
    (an ``AudioTrack``-like object with ``id`` + ``path``) used **only** when the
    operator supplies no ``MEDIAHUB_REEL_MUSIC_DIR`` track — their own licensed
    music always wins. It records the track's absolute path so the mux can read
    it from the package assets. ``None`` (the default) keeps the historic plan
    byte-for-byte.
    """
    plan: dict[str, Any] = {}
    if voice_active() and (script or "").strip():
        plan["voice"] = voice_name()
        plan["script"] = script.strip()
    track = pick_music(content_key)
    if track is not None:
        try:
            plan["music"] = track.name
            plan["music_bytes"] = track.stat().st_size
        except OSError:
            pass
    elif library_track is not None:
        try:
            plan["music"] = library_track.id
            plan["music_path"] = str(library_track.path)
            plan["music_bytes"] = Path(library_track.path).stat().st_size
            if getattr(library_track, "source", ""):
                plan["music_source"] = library_track.source
        except OSError:
            plan.pop("music", None)
            plan.pop("music_path", None)
    # Operator-declared volume envelope shapes the bed's resting level over time;
    # folded into the plan (and so the cache key) only when a bed exists and a
    # valid sidecar resolves — otherwise the plan is byte-identical to before.
    if "music" in plan:
        env_source = track if track is not None else Path(library_track.path)
        env_points = track_envelope(env_source)
        if env_points:
            plan["audio_envelope"] = env_points
    if not plan:
        return None
    profile = _coalesce_profile(mix_profile)
    if profile != DEFAULT_MIX_PROFILE:
        plan["mix"] = profile
    # EBU R128 loudness normalisation rides inside the plan (and so the cache
    # key) only when the operator opted in — the default plan is unchanged.
    loudnorm = resolve_loudnorm()
    if loudnorm is not None:
        plan["loudnorm"] = loudnorm
    return plan


def _resolve_music_path(plan: dict) -> Optional[Path]:
    # 1.8 — a bundled-library bed records its absolute path in the plan.
    abs_path = str((plan or {}).get("music_path") or "")
    if abs_path:
        p = Path(abs_path)
        return p if p.is_file() else None
    name = str((plan or {}).get("music") or "")
    if not name:
        return None
    d = music_dir()
    if d is None:
        return None
    p = d / name
    return p if p.is_file() else None


def card_cut_times(duration_sec: float, n_cards: int, rhythm: Optional[dict] = None) -> list[float]:
    """Timestamps where a reel cuts to a new card scene — the beat grid the
    music accents align to.

    Mirrors ``motion.reel_duration_for``'s deterministic structure (a brand
    cover, then one beat per card), scaled proportionally if the caller
    overrides the total duration, so the maths stay the single source of truth.
    Story (single-scene) renders have no internal cuts and pass ``n_cards=0`` →
    ``[]``.

    R1.12 — ``rhythm`` (a canonical dict from ``motion.normalise_reel_rhythm``)
    moves the cuts the same way the MeetReel carve and
    ``reel_segment_durations`` move the scenes: cumulative weighted seconds
    (cover + running per-card·weight), so the accents land on the reel's real
    cuts. ``None`` keeps the historic flat grid byte-identical.
    """
    n = int(n_cards or 0)
    if n <= 0:
        return []
    from mediahub.visual.motion import (
        REEL_COVER_SEC,
        REEL_PER_CARD_SEC,
        _fit_beat_weights,
        reel_duration_for,
    )

    n = min(n, 5)
    total = float(duration_sec or 0.0)
    if rhythm:
        cover = float(rhythm.get("coverSec", REEL_COVER_SEC))
        per_card = float(rhythm.get("perCardSec", REEL_PER_CARD_SEC))
        weights_raw = list(rhythm.get("beatWeights") or [])
        weights = _fit_beat_weights(weights_raw, n) if weights_raw else [1.0] * n
        from mediahub.visual.motion import REEL_OUTRO_SEC

        ref_total = reel_duration_for(
            n,
            cover_sec=cover,
            outro_sec=float(rhythm.get("outroSec", REEL_OUTRO_SEC)),
            per_card_sec=per_card,
            beat_weights=(weights_raw or None),
        )
        factor = (total / ref_total) if total > 0 and ref_total else 1.0
        cuts: list[float] = []
        acc = cover
        for k in range(n):
            cuts.append(round(acc * factor, 3))
            acc += per_card * weights[k]
        return cuts
    factor = (total / reel_duration_for(n)) if total > 0 else 1.0
    return [round((REEL_COVER_SEC + k * REEL_PER_CARD_SEC) * factor, 3) for k in range(n)]


def _accent_width(bpm: Optional[float]) -> float:
    """Cut-accent length: one musical beat when the tempo is declared
    (music-pool logic), else the fixed default. Clamped so a single accent
    never smears across a whole card beat."""
    if bpm and bpm > 0:
        return max(0.12, min(60.0 / bpm, 0.5))
    return CUT_ACCENT_SEC


def _sting_windows(duration_sec: float) -> tuple[bool, bool, float, float]:
    """``(intro_on, outro_on, outro_start, fade_start)`` for the bed stings.

    Both stings are suppressed on clips too short to carry them cleanly, so a
    one-second story bed never gets a clashing swell on top of its fade.
    """
    d = max(0.1, float(duration_sec))
    fade_start = max(0.0, d - AUDIO_FADE_OUT_SEC)
    intro_on = d >= 2.0 * INTRO_STING_SEC
    outro_start = fade_start - OUTRO_STING_SEC
    outro_on = outro_start >= INTRO_STING_SEC
    return intro_on, outro_on, outro_start, fade_start


def music_filterchain(
    *,
    base_vol: float,
    duration_sec: float,
    cut_times: Optional[list[float]] = None,
    bpm: Optional[float] = None,
    envelope: Optional[list[dict]] = None,
    under_voice: bool = False,
) -> str:
    """The deterministic music-bed shaping chain: resting level, intro/outro
    stings, and a beat-aware accent on each card cut. Pure + testable — returns
    a comma-joined FFmpeg filterchain (no input/output pad labels).

    ``envelope`` (optional) time-varies the resting bed level between the
    operator's keyframes; ``under_voice`` caps its gain so a keyframe can only
    duck (never boost) the bed under narration. The stings/accents/ducking still
    act on top of the enveloped level, exactly as they do on the flat one."""
    intro_on, outro_on, outro_start, fade_start = _sting_windows(duration_sec)
    filters = [f"volume={base_vol:.3f}"]
    if envelope:
        cap = _ENV_MAX_GAIN_UNDER_VOICE if under_voice else None
        chain = envelope_filter(envelope, duration_sec, max_gain=cap)
        if chain:
            filters.append(chain)
    # Intro: a punchy swell-in (the sting), or a gentle fade when there's no room.
    if intro_on:
        filters.append(f"afade=t=in:st=0:d={INTRO_STING_SEC}")
        filters.append(f"volume={STING_GAIN}:enable='between(t,0,{INTRO_STING_SEC})'")
    else:
        filters.append("afade=t=in:st=0:d=0.5")
    # Outro: a final accent that resolves into the shared tail fade-out.
    if outro_on:
        filters.append(
            f"volume={STING_GAIN}:enable='between(t,{outro_start:.3f},{fade_start:.3f})'"
        )
    # Beat-aware: a short emphasis on every card cut that sits inside the bed
    # (clear of the intro/outro stings so accents never stack).
    upper = outro_start if outro_on else fade_start
    accents = [c for c in (cut_times or []) if INTRO_STING_SEC < c < upper]
    if accents:
        w = _accent_width(bpm)
        expr = "+".join(f"between(t,{c:.3f},{c + w:.3f})" for c in accents)
        filters.append(f"volume={CUT_ACCENT_GAIN}:enable='{expr}'")
    return ",".join(filters)


def mux_args(
    video: Path,
    voice: Optional[Path],
    music: Optional[Path],
    out: Path,
    *,
    duration_sec: float,
    cut_times: Optional[list[float]] = None,
    profile: Any = DEFAULT_MIX_PROFILE,
    loudnorm: Optional[dict] = None,
    envelope: Optional[list[dict]] = None,
) -> list[str]:
    """Argument list (after the binary) for the audio mux. Pure + testable.

    The video stream is copied untouched; the audio chain is trimmed to the
    exact video duration with a fixed fade-out, so a long narration ends
    cleanly rather than spilling past the outro. The music bed is shaped by
    ``music_filterchain`` (intro/outro stings + beat-aware cut accents) and,
    under narration, ducked dynamically by a voice-keyed sidechain compressor
    rather than held at one static level.

    The audio-mix ``profile`` (R1.19) sets the bed's resting level — the base
    the stings/accents/ducking then act on — and how hard it ducks under
    speech: ``voice_lead`` keeps a low bed that ducks hard, ``music_forward`` a
    higher bed that ducks gently, and ``balanced`` (the default) reproduces the
    historic levels byte-for-byte. The bed always ducks under the voice, so the
    narration stays intelligible under every profile.
    """
    if voice is None and music is None:
        raise ValueError("at least one audio source is required")
    levels = mix_profile_levels(profile)
    duck_ratio = levels["duck_ratio"]
    d = max(0.1, float(duration_sec))
    fade_start = max(0.0, d - AUDIO_FADE_OUT_SEC)
    args: list[str] = ["-i", str(video)]
    if voice is not None:
        args += ["-i", str(voice)]
    if music is not None:
        # Loop the bed so short tracks cover long reels; atrim cuts the tail.
        args += ["-stream_loop", "-1", "-i", str(music)]

    # Loudness normalisation sits AFTER the trim but BEFORE the tail fade-out, so
    # the fade stays the final gesture: loudnorm's time-varying make-up gain can't
    # pump the outro back up and muddy the resolve. Empty when off → byte-identical.
    ln_stage = ""
    if loudnorm:
        ln_stage = f"loudnorm=I={loudnorm['i']:g}:TP={loudnorm['tp']:g}:LRA={loudnorm['lra']:g},"
    tail = (
        f"atrim=0:{d:.3f},{ln_stage}"
        f"afade=t=out:st={fade_start:.3f}:d={AUDIO_FADE_OUT_SEC}[aout]"
    )
    if voice is not None and music is not None:
        bpm = track_bpm(music)
        chain = music_filterchain(
            base_vol=levels["music_under_voice_weight"],
            duration_sec=d,
            cut_times=cut_times,
            bpm=bpm,
            envelope=envelope,
            under_voice=True,
        )
        # Voice is split: one copy mixes, one keys the sidechain that ducks the
        # bed only while there's speech (refined automatic ducking).
        graph = (
            f"[1:a]apad,asplit=2[vmain][vkey];"
            f"[2:a]{chain}[mraw];"
            f"[mraw][vkey]sidechaincompress="
            f"threshold={DUCK_THRESHOLD:g}:ratio={duck_ratio:g}:"
            f"attack={DUCK_ATTACK_MS:g}:release={DUCK_RELEASE_MS:g}[mduck];"
            f"[vmain][mduck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
            f"{tail}"
        )
    elif voice is not None:
        graph = f"[1:a]apad,{tail}"
    else:
        bpm = track_bpm(music)
        chain = music_filterchain(
            base_vol=levels["music_bed_volume"],
            duration_sec=d,
            cut_times=cut_times,
            bpm=bpm,
            envelope=envelope,
            under_voice=False,
        )
        graph = f"[1:a]{chain},{tail}"

    args += [
        "-filter_complex",
        graph,
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "44100",
        "-movflags",
        "+faststart",
        str(out),
    ]
    return args


def _run_ffmpeg(args: list[str], *, timeout: int = 300) -> None:
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("no FFmpeg binary available for the audio mux")
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip().splitlines()
        tail = "\n".join(stderr[-8:]) if stderr else "(no stderr)"
        raise RuntimeError(f"audio mux failed (exit {proc.returncode}):\n{tail}")


def has_audio_stream(video: Path) -> bool:
    """True when the container declares an audio stream (ffmpeg -i probe)."""
    exe = ffmpeg_exe()
    if not exe or not Path(video).exists():
        return False
    proc = subprocess.run([exe, "-hide_banner", "-i", str(video)], capture_output=True, text=True)
    return "Audio:" in (proc.stderr or "")


def apply_audio(
    video: Path,
    plan: Optional[dict],
    *,
    duration_sec: float,
    cut_times: Optional[list[float]] = None,
) -> dict:
    """Attach the planned audio to ``video`` in place; report what happened.

    ``cut_times`` are the reel's card-cut timestamps (from
    ``card_cut_times``); when a music bed is present they drive the beat-aware
    accents. Returns the manifest-ready record. Every failure path leaves the
    rendered video exactly as it was (silent) and says why — the honest
    fallback the motion rules require.
    """
    if not plan:
        return {"status": "off"}
    video = Path(video)
    profile = resolve_mix_profile(plan.get("mix"))
    voice_path: Optional[Path] = None
    transcript = ""
    voice_error = ""
    script = str(plan.get("script") or "")
    if plan.get("voice") and script:
        try:
            from mediahub.visual import voiceover

            result = voiceover.synthesize(script, voice=str(plan["voice"]))
            voice_path = result.audio_path
            transcript = result.transcript
        except Exception as e:
            voice_error = f"voiceover failed: {e}"
            voice_path = None

    music_path = _resolve_music_path(plan)
    if voice_path is None and music_path is None:
        return {
            "status": "silent_fallback",
            "reason": voice_error or "no audio source resolved",
        }

    try:
        # dir=video.parent keeps the mux temp on the SAME filesystem as the target
        # MP4, so the os.replace below is an atomic same-fs rename. Without it the
        # temp lands in the default /tmp, which on Render is a different mount from
        # DATA_DIR — os.replace then raises EXDEV, the broad except reports
        # silent_fallback, and the whole voiceover/music feature is dead in prod.
        with tempfile.TemporaryDirectory(prefix="mh_audio_mux_", dir=str(video.parent)) as td:
            tmp_out = Path(td) / video.name
            _run_ffmpeg(
                mux_args(
                    video,
                    voice_path,
                    music_path,
                    tmp_out,
                    duration_sec=duration_sec,
                    cut_times=cut_times,
                    profile=profile,
                    loudnorm=plan.get("loudnorm"),
                    envelope=plan.get("audio_envelope"),
                )
            )
            if not tmp_out.exists() or tmp_out.stat().st_size < 1024:
                raise RuntimeError("mux produced no output")
            os.replace(tmp_out, video)
    except Exception as e:
        reason = f"{voice_error + '; ' if voice_error else ''}{e}"
        # Flag a loudnorm-caused failure (e.g. an ffmpeg build without the
        # filter) so it isn't misread as a generic mux failure — the clip is
        # still shipped silent, but the manifest says which stage broke.
        if plan.get("loudnorm"):
            reason = f"loudnorm active; {reason}"
        return {"status": "silent_fallback", "reason": reason}

    record: dict[str, Any] = {
        "status": "mixed",
        "voice": str(plan.get("voice") or "") if voice_path is not None else "",
        "music": str(plan.get("music") or "") if music_path is not None else "",
        "mix": profile,
        "transcript": transcript,
    }
    if plan.get("loudnorm"):
        record["loudnorm"] = plan["loudnorm"]
    # 1.24 AI-dub provenance: when the voice track is a translated dub, label it
    # in the manifest (clearly AI-dubbed, source→target) so every downstream
    # surface can show it honestly.
    if voice_path is not None and plan.get("dubbed"):
        record["dubbed"] = True
        record["dub_source_language"] = str(plan.get("dub_source_language") or "")
        record["dub_target_language"] = str(plan.get("dub_target_language") or "")
    if voice_path is not None and music_path is not None:
        record["ducking"] = "sidechain"
    if music_path is not None:
        bpm = track_bpm(music_path)
        if bpm is not None:
            record["music_bpm"] = bpm
        if plan.get("audio_envelope"):
            record["audio_envelope"] = plan["audio_envelope"]
        aligned = [c for c in (cut_times or []) if c > 0]
        if aligned:
            record["beat_aligned_cuts"] = aligned
        # Explainability: the operator pool the deterministic pick chose from
        # (empty for a bundled-library bed, which has no operator pool).
        pool = music_pool_summary()
        if pool.get("count"):
            record["music_pool"] = pool
    if voice_error:
        record["reason"] = voice_error
    return record


# ---------------------------------------------------------------------------
# Poster frames
# ---------------------------------------------------------------------------


def poster_time_for(kind: str, duration_sec: float) -> float:
    """Deterministic poster timestamp: stories late enough that the layers
    have animated in; reels on the brand cover.

    Mirrored by ``remotion/render.js``'s ``posterTimeFor`` for the in-render
    poster capture (R1.29) — keep the two formulas in sync. This is still the
    timestamp used for the ffmpeg fallback grab when the in-render poster is
    absent (the free ffmpeg engine, or a render.js capture failure).
    """
    d = max(0.1, float(duration_sec))
    if kind == "reel":
        return min(1.5, max(0.0, d - 0.2))
    return max(0.0, min(d * 0.55, d - 0.2))


def poster_path_for(video: Path) -> Path:
    return Path(video).with_suffix(".poster.png")


def write_poster(video: Path, poster: Path, *, at_sec: float) -> bool:
    """Extract one PNG frame beside the MP4. Best-effort: False, never raise."""
    exe = ffmpeg_exe()
    video = Path(video)
    poster = Path(poster)
    if not exe or not video.exists():
        return False
    try:
        poster.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [
                exe,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{max(0.0, at_sec):.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                str(poster),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return proc.returncode == 0 and poster.exists() and poster.stat().st_size > 0
    except Exception:
        return False


__all__ = [
    "MUSIC_BED_VOLUME",
    "MUSIC_UNDER_VOICE_WEIGHT",
    "AUDIO_FADE_OUT_SEC",
    "DUCK_THRESHOLD",
    "DUCK_RATIO",
    "DUCK_ATTACK_MS",
    "DUCK_RELEASE_MS",
    "INTRO_STING_SEC",
    "OUTRO_STING_SEC",
    "STING_GAIN",
    "CUT_ACCENT_SEC",
    "CUT_ACCENT_GAIN",
    "DEFAULT_MIX_PROFILE",
    "AUDIO_MIX_PROFILES",
    "LOUDNORM_DEFAULT_I",
    "LOUDNORM_DEFAULT_TP",
    "LOUDNORM_DEFAULT_LRA",
    "resolve_loudnorm",
    "resolve_mix_profile",
    "env_mix_profile",
    "mix_profile_levels",
    "voice_active",
    "voice_name",
    "music_dir",
    "library_bed_enabled",
    "music_candidates",
    "pick_music",
    "track_bpm",
    "track_envelope",
    "envelope_filter",
    "music_pool_summary",
    "audio_active",
    "build_audio_plan",
    "card_cut_times",
    "music_filterchain",
    "mux_args",
    "has_audio_stream",
    "apply_audio",
    "poster_time_for",
    "poster_path_for",
    "write_poster",
]
