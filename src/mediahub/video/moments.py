"""video/moments.py — deterministic highlight detection for footage (1.6).

Clip-Maker's first job is to find *where the moment is* in a long phone clip: the
race finish (a scene change as the camera snaps to the wall), the cheer (an
audio-energy spike as the crowd erupts). This module finds those moments and
ranks them — and it does so **deterministically**, because "which two seconds
are the highlight" is the same accuracy-critical decision as "which card
outranks which": it must be reproducible, explainable, and never a dice-roll.

The split this module is careful about (the engine's load-bearing rule):

* **Detection + ranking = facts = deterministic.** Audio loudness over time and
  scene-change timestamps come from FFmpeg measurement; the ranking is fixed
  maths over those numbers. The parsers (:func:`parse_astats_energy`,
  :func:`parse_scene_cuts`) and the ranker (:func:`rank_moments`) are **pure
  functions**, unit-tested with sample FFmpeg output and no binary present.
* **Labelling = judgement = AI, optional, honest.** Naming a moment ("race
  finish" vs "celebration") is creative judgement, so :func:`label_moment`
  routes through ``media_ai`` and returns ``""`` when no provider is configured
  — it never invents a label and never changes which moment was *detected*.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from mediahub.visual.reel_ffmpeg import ffmpeg_exe


class MomentsUnavailable(RuntimeError):
    """Raised when moments cannot be measured (no FFmpeg binary)."""


@dataclass(frozen=True)
class EnergyWindow:
    """Mean audio loudness over one analysis window."""

    start_ms: int
    rms_db: float  # FFmpeg astats RMS level in dBFS (negative; 0 = full scale)


@dataclass(frozen=True)
class Moment:
    """A ranked candidate highlight: a window of the source worth keeping."""

    start_ms: int
    end_ms: int
    score: float
    kind: str  # "energy" | "scene" | "energy+scene"
    reason: str  # human-readable explainability ("loud cheer at 0:08 + cut")
    label: str = ""  # optional AI judgement label, filled by label_moment

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    def to_dict(self) -> dict:
        return {
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "score": round(self.score, 4),
            "kind": self.kind,
            "reason": self.reason,
            "label": self.label,
        }


# --------------------------------------------------------------------------
# Pure parsers (FFmpeg text → numbers)
# --------------------------------------------------------------------------

_PTS_RE = re.compile(r"pts_time:(\d+(?:\.\d+)?)")
_RMS_RE = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(-?\d+(?:\.\d+)?|-?inf)")
_SCENE_RE = re.compile(r"lavfi\.scene_score=(\d+(?:\.\d+)?)")


def parse_astats_energy(text: str) -> list[EnergyWindow]:
    """Parse ``ametadata=print`` astats output into per-window loudness.

    The filter prints, per reset window, a ``pts_time:T`` line followed by a
    ``lavfi.astats.Overall.RMS_level=<dB>`` line. Pure and order-preserving;
    a ``-inf`` (digital silence) window is clamped to a low floor so the maths
    downstream stays finite.
    """
    windows: list[EnergyWindow] = []
    pending_pts: Optional[float] = None
    for line in (text or "").splitlines():
        pm = _PTS_RE.search(line)
        if pm:
            pending_pts = float(pm.group(1))
            continue
        rm = _RMS_RE.search(line)
        if rm and pending_pts is not None:
            raw = rm.group(1)
            rms = -120.0 if raw == "-inf" else float(raw)
            windows.append(EnergyWindow(start_ms=round(pending_pts * 1000), rms_db=rms))
            pending_pts = None
    return windows


def parse_scene_cuts(text: str) -> list[int]:
    """Parse scene-detect ``metadata=print`` output into cut timestamps (ms).

    Each detected scene change prints a ``pts_time:T`` line (optionally with a
    ``lavfi.scene_score``). Pure; returns ascending, de-duplicated millisecond
    offsets.
    """
    cuts: list[int] = []
    last_pts: Optional[float] = None
    for line in (text or "").splitlines():
        pm = _PTS_RE.search(line)
        if pm:
            last_pts = float(pm.group(1))
        if _SCENE_RE.search(line) and last_pts is not None:
            cuts.append(round(last_pts * 1000))
            last_pts = None
    # Some FFmpeg builds print only the pts_time line for select'd frames.
    if not cuts:
        for line in (text or "").splitlines():
            pm = _PTS_RE.search(line)
            if pm:
                cuts.append(round(float(pm.group(1)) * 1000))
    return sorted(set(cuts))


# --------------------------------------------------------------------------
# Pure ranking
# --------------------------------------------------------------------------


def _normalise_energy(windows: list[EnergyWindow]) -> list[tuple[int, float]]:
    """Map dB windows onto a 0..1 energy by min-max over the clip. Deterministic."""
    if not windows:
        return []
    dbs = [w.rms_db for w in windows]
    lo, hi = min(dbs), max(dbs)
    span = (hi - lo) or 1.0
    return [(w.start_ms, (w.rms_db - lo) / span) for w in windows]


def rank_moments(
    energy: list[EnergyWindow],
    scene_cuts: list[int],
    *,
    duration_ms: int,
    target_len_ms: int = 6000,
    max_moments: int = 5,
    min_gap_ms: int = 1500,
) -> list[Moment]:
    """Rank candidate highlights from energy windows + scene cuts. Pure.

    A moment is centred on a loud window (and/or a scene cut near it), extended
    to ``target_len_ms`` and clamped to the clip. Score = peak energy, boosted
    when a scene cut falls inside the window (sound *and* a visual change is the
    strongest "something happened" signal). Overlapping candidates within
    ``min_gap_ms`` are suppressed, lower score first; the top ``max_moments``
    are returned, **earliest-first** so a montage keeps chronological order.
    """
    if duration_ms <= 0:
        return []
    half = max(1, target_len_ms // 2)
    norm = _normalise_energy(energy)
    cut_set = sorted(set(scene_cuts))

    candidates: list[Moment] = []

    def _window_for(center: int) -> tuple[int, int]:
        start = max(0, center - half)
        end = min(duration_ms, start + target_len_ms)
        start = max(0, end - target_len_ms)
        return start, end

    # Energy-driven candidates: every window, scored by its energy.
    for start_ms, e in norm:
        s, en = _window_for(start_ms)
        has_cut = any(s <= c <= en for c in cut_set)
        score = e + (0.25 if has_cut else 0.0)
        kind = "energy+scene" if has_cut else "energy"
        reason = f"audio energy {e:.2f} at {start_ms // 1000}s" + (
            " with a scene cut" if has_cut else ""
        )
        candidates.append(Moment(s, en, score, kind, reason))

    # Scene-cut candidates with no nearby energy window (silent visual change).
    energy_starts = {s for s, _ in norm}
    for c in cut_set:
        if any(abs(c - s) <= half for s in energy_starts):
            continue
        s, en = _window_for(c)
        candidates.append(Moment(s, en, 0.4, "scene", f"scene cut at {c // 1000}s"))

    if not candidates:
        # No signal at all (a flat, silent clip): keep the opening as the moment.
        s, en = _window_for(0)
        return [Moment(s, en, 0.0, "energy", "no strong moment — kept the opening")]

    # Greedy non-maximum suppression by score, then sort earliest-first.
    chosen: list[Moment] = []
    for m in sorted(candidates, key=lambda x: (-x.score, x.start_ms)):
        if len(chosen) >= max_moments:
            break
        if all(abs(m.start_ms - c.start_ms) >= min_gap_ms for c in chosen):
            chosen.append(m)
    chosen.sort(key=lambda x: x.start_ms)
    return chosen


# --------------------------------------------------------------------------
# Impure orchestration (FFmpeg-gated; honest-error)
# --------------------------------------------------------------------------


def _run_for_text(args: list[str], *, timeout: int = 300) -> str:
    exe = ffmpeg_exe()
    if not exe:
        raise MomentsUnavailable(
            "Finding moments needs an FFmpeg binary (install imageio-ffmpeg, put "
            "ffmpeg on PATH, or set MEDIAHUB_FFMPEG)."
        )
    cmd = [exe, "-hide_banner", "-nostats", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise MomentsUnavailable(f"moment analysis timed out after {timeout}s") from e
    # The analysis filters print to stderr; -f null discards the (absent) output.
    return (proc.stderr or "") + "\n" + (proc.stdout or "")


def energy_args(path: Path | str, *, window_ms: int = 1000) -> list[str]:
    """FFmpeg args that print per-window RMS loudness (pure builder)."""
    samples = max(1, round(44100 * window_ms / 1000))
    return [
        "-i",
        str(path),
        "-vn",
        "-af",
        f"aresample=44100,asetnsamples=n={samples}:p=0,"
        "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
        "-f",
        "null",
        "-",
    ]


def scene_args(path: Path | str, *, threshold: float = 0.3) -> list[str]:
    """FFmpeg args that print scene-change timestamps (pure builder)."""
    return [
        "-i",
        str(path),
        "-an",
        "-vf",
        f"select='gt(scene,{threshold:g})',metadata=print",
        "-f",
        "null",
        "-",
    ]


def detect_moments(
    path: Path | str,
    *,
    duration_ms: int,
    target_len_ms: int = 6000,
    max_moments: int = 5,
) -> list[Moment]:
    """Measure + rank highlights in a clip on disk. Honest-errors without FFmpeg.

    Detection is deterministic: the same clip yields the same moments. Audio
    analysis is skipped honestly for a silent clip (the ranker then leans on
    scene cuts), so a clip with no audio still produces a sensible montage.
    """
    energy: list[EnergyWindow] = []
    try:
        energy = parse_astats_energy(_run_for_text(energy_args(path)))
    except MomentsUnavailable:
        raise
    except Exception:
        energy = []
    try:
        scene_cuts = parse_scene_cuts(_run_for_text(scene_args(path)))
    except Exception:
        scene_cuts = []
    return rank_moments(
        energy,
        scene_cuts,
        duration_ms=duration_ms,
        target_len_ms=target_len_ms,
        max_moments=max_moments,
    )


# --------------------------------------------------------------------------
# Optional AI labelling (judgement; honest-error, never required)
# --------------------------------------------------------------------------


def label_moment(reason: str, *, context: str = "") -> str:
    """Name a detected moment via ``media_ai`` — judgement, so it's optional.

    Returns ``""`` when no AI provider is configured (the deterministic
    ``reason`` already explains the moment). Never invents a label and never
    influences detection — this is decoration over a fact, not the fact.
    """
    try:
        from mediahub.media_ai import llm as _llm

        if not _llm.is_available():
            return ""
        prompt = (
            "In 2-4 words, name this moment from a sports video clip for a social "
            "caption. Be literal and factual; if unsure, answer 'highlight'.\n"
            f"Signal: {reason}\nContext: {context or 'club sport footage'}"
        )
        out = _llm.generate(prompt, max_tokens=12)
        return (out or "").strip().strip('".')[:40]
    except Exception:
        # ClaudeUnavailableError or any provider error → no label, never a fake.
        return ""


__all__ = [
    "MomentsUnavailable",
    "EnergyWindow",
    "Moment",
    "parse_astats_energy",
    "parse_scene_cuts",
    "rank_moments",
    "energy_args",
    "scene_args",
    "detect_moments",
    "label_moment",
]
