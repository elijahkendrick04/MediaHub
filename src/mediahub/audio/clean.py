"""audio/clean.py — deterministic denoise + loudness levelling (roadmap 1.8).

The "Enhance Voice" / "Balance All" family from the competitor inventory, done
the MediaHub way: as fixed, deterministic FFmpeg filter graphs, not a per-clip
AI judgement. Two jobs:

* **Loudness normalisation** to the EBU R128 standard (``loudnorm``). Social
  platforms target roughly -14 LUFS integrated; spoken voiceover sits a touch
  hotter. We expose fixed, named targets so a club's clips all land at the same
  perceived loudness — the "Balance All" promise — reproducibly.
* **Denoise** to lift a voice recording out of room hiss. The default is
  FFmpeg's built-in ``afftdn`` (spectral noise reduction — dependency-free,
  deterministic). A heavier RNNoise model (``arnndn``) is an **optional provider
  slot**: it engages only when the operator points ``MEDIAHUB_RNNOISE_MODEL`` at
  a model file, and honest-errors if that path is set but unusable — never a
  silent downgrade.

Both are maths, not judgement, so they belong on the deterministic side of the
engine boundary. FFmpeg is resolved through ``audio/ops.py`` and failures raise
:class:`~mediahub.audio.ops.AudioOpError`.
"""

from __future__ import annotations

import os
from pathlib import Path

from mediahub.audio import ops
from mediahub.audio.ops import AudioOpError

# Named EBU R128 loudness targets: (integrated LUFS, true-peak dBTP, loudness
# range LU). Fixed constants → deterministic levelling. "social" is the safe
# default for feed/story/reel; "voice" runs a touch hotter for spoken narration;
# "broadcast" matches the -23 LUFS broadcast spec for completeness.
LOUDNESS_TARGETS: dict[str, tuple[float, float, float]] = {
    "social": (-14.0, -1.0, 11.0),
    "voice": (-16.0, -1.5, 7.0),
    "broadcast": (-23.0, -1.0, 7.0),
}
DEFAULT_LOUDNESS = "social"


def resolve_target(name: object) -> str:
    """Canonical loudness-target name; unknown/empty → the default."""
    key = str(name or "").strip().lower()
    return key if key in LOUDNESS_TARGETS else DEFAULT_LOUDNESS


def loudnorm_filter(target: object = DEFAULT_LOUDNESS) -> str:
    """A single-pass ``loudnorm`` filter for a named target. Pure + testable.

    Single-pass is deterministic and good enough for short club clips; the
    measured-then-corrected two-pass mode would re-probe per file and is not
    needed for the catalogue's short beds/voiceovers.
    """
    i, tp, lra = LOUDNESS_TARGETS[resolve_target(target)]
    return f"loudnorm=I={i:g}:TP={tp:g}:LRA={lra:g}"


def rnnoise_model_path() -> str:
    """Operator-supplied RNNoise model path (``MEDIAHUB_RNNOISE_MODEL``) or ''."""
    return os.environ.get("MEDIAHUB_RNNOISE_MODEL", "").strip()


def denoise_filter(*, strength: float = 12.0) -> str:
    """The default spectral denoiser (``afftdn``). ``strength`` is noise-reduction dB.

    Deterministic and dependency-free. The RNNoise provider slot is handled in
    :func:`denoise` (it needs the operator's model path), not here.
    """
    nr = max(0.01, min(97.0, float(strength)))
    return f"afftdn=nr={nr:g}:nt=w"


def normalise(src: Path, out: Path, *, target: object = DEFAULT_LOUDNESS) -> Path:
    """Loudness-normalise ``src`` to a named EBU R128 target."""
    return ops.apply_filter(Path(src), Path(out), chain=loudnorm_filter(target))


def denoise(src: Path, out: Path, *, strength: float = 12.0) -> Path:
    """Denoise ``src``.

    Uses the operator's RNNoise model (``arnndn``) when ``MEDIAHUB_RNNOISE_MODEL``
    is set, else the built-in ``afftdn``. If the model path is set but missing,
    raises :class:`AudioOpError` rather than silently falling back — an honest
    error beats a surprising downgrade.
    """
    model = rnnoise_model_path()
    if model:
        if not Path(model).is_file():
            raise AudioOpError(
                f"MEDIAHUB_RNNOISE_MODEL={model!r} is set but not a readable file"
            )
        chain = f"arnndn=m={model}"
    else:
        chain = denoise_filter(strength=strength)
    return ops.apply_filter(Path(src), Path(out), chain=chain)


def enhance_voice(src: Path, out: Path, *, target: object = "voice") -> Path:
    """Denoise then loudness-normalise — the one-tap "Enhance Voice" pipeline.

    Runs as two deterministic passes through a temp intermediate so the result is
    identical to chaining the filters by hand.
    """
    with ops.with_temp_wav() as td:
        mid = Path(td) / "denoised.wav"
        denoise(src, mid)
        normalise(mid, out, target=target)
    return Path(out)


__all__ = [
    "LOUDNESS_TARGETS",
    "DEFAULT_LOUDNESS",
    "resolve_target",
    "loudnorm_filter",
    "rnnoise_model_path",
    "denoise_filter",
    "normalise",
    "denoise",
    "enhance_voice",
]
