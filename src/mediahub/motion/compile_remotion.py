"""Compile motion presets to Remotion interpolation tokens.

CSS keyframes do not render in Remotion — only frame-pure ``interpolate`` /
``spring`` do. So the Remotion target is **data**, not CSS: a JSON-serialisable
token bundle that the TypeScript helper (``remotion/src/motion/compile.ts``)
samples with ``interpolate`` and the matching ``Easing.bezier`` curve.

The bundle is the contract between Python (the single source of truth) and the
generated ``remotion/src/motion/tokens.generated.ts``. ``scripts/regen_motion_tokens.py``
writes that file from :func:`export_ts`, and a guard test re-derives the bundle
and asserts the committed file is in sync — the same regen-plus-guard discipline
the self-hosted fonts use.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable

from .easing import EASINGS
from .vocabulary import FPS, GLYPH_STAGGER_SEC, MOTION_REV, PRESETS, MotionPreset


def preset_tokens(preset: MotionPreset) -> Dict[str, Any]:
    """One preset as interpolation tokens (channels → keyframes)."""
    return {
        "name": preset.name,
        "family": preset.family,
        "energy": preset.energy,
        "direction": preset.direction,
        "durationFrames": preset.duration_frames,
        "loop": preset.loop,
        "photo": preset.photo,
        "channels": {
            ch: [
                {"offset": round(k.offset, 6), "value": round(k.value, 6), "easing": k.easing}
                for k in kfs
            ]
            for ch, kfs in preset.channels.items()
        },
    }


def token_bundle(presets: Iterable[MotionPreset] | None = None) -> Dict[str, Any]:
    """The full bundle: version, fps, easing curves, presets + reduced variants."""
    items = list(presets if presets is not None else PRESETS.values())
    return {
        "version": MOTION_REV,
        "fps": FPS,
        "easings": {name: {"bezier": list(e.bezier)} for name, e in EASINGS.items()},
        "presets": {p.name: preset_tokens(p) for p in items},
        "reduced": {p.name: preset_tokens(p.reduced()) for p in items},
        # Text-level timing shared by the TSX type channels. `glyphStaggerSec`
        # is the per-glyph reveal cadence the kinetic_type / cascade intents read
        # for their opt-in per-character reveal (the per-word channel keeps its
        # own inline tempo). Single source of truth — the TSX never hard-codes it.
        "text": {"glyphStaggerSec": round(GLYPH_STAGGER_SEC, 6)},
    }


def export_json(bundle: Dict[str, Any] | None = None) -> str:
    """Stable JSON for the bundle (sorted keys → deterministic diffs)."""
    return json.dumps(bundle or token_bundle(), indent=2, sort_keys=True)


def export_ts(bundle: Dict[str, Any] | None = None) -> str:
    """The generated ``tokens.generated.ts`` source."""
    payload = export_json(bundle)
    return (
        "// MediaHub motion vocabulary — GENERATED from src/mediahub/motion/.\n"
        "// Do not edit by hand; run scripts/regen_motion_tokens.py.\n"
        "// The single source of truth is the Python preset registry; a guard\n"
        "// test (tests/test_motion_tokens_sync.py) fails if this drifts.\n"
        "\n"
        "export type MotionKeyframe = { offset: number; value: number; easing: string };\n"
        "export type MotionChannels = Record<string, MotionKeyframe[]>;\n"
        "export type MotionPresetTokens = {\n"
        "  name: string;\n"
        "  family: string;\n"
        "  energy: string;\n"
        "  direction: string;\n"
        "  durationFrames: number;\n"
        "  loop: boolean;\n"
        "  photo: boolean;\n"
        "  channels: MotionChannels;\n"
        "};\n"
        "export type MotionTokenBundle = {\n"
        "  version: number;\n"
        "  fps: number;\n"
        "  easings: Record<string, { bezier: number[] }>;\n"
        "  presets: Record<string, MotionPresetTokens>;\n"
        "  reduced: Record<string, MotionPresetTokens>;\n"
        "  text: { glyphStaggerSec: number };\n"
        "};\n"
        "\n"
        f"export const MOTION_TOKENS: MotionTokenBundle = {payload} as const;\n"
        "\nexport default MOTION_TOKENS;\n"
    )


__all__ = [
    "preset_tokens",
    "token_bundle",
    "export_json",
    "export_ts",
]
