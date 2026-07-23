"""Guard: the generated motion artifacts must match the Python source of truth.

The Remotion stack and the browser can't import Python, so they read generated
copies of the vocabulary (``tokens.generated.ts`` and ``motion-vocabulary.css``).
If a preset changes and these aren't regenerated, reels and the web surface
silently drift. This is the same regen-plus-guard discipline the self-hosted
fonts use — fix a failure with ``python scripts/regen_motion_tokens.py``.
"""

from __future__ import annotations

from pathlib import Path

from mediahub.motion import compile_css, compile_remotion
from mediahub.motion import vocabulary as v

ROOT = Path(__file__).resolve().parent.parent
TS = ROOT / "src" / "mediahub" / "remotion" / "src" / "motion" / "tokens.generated.ts"
CSS = ROOT / "src" / "mediahub" / "web" / "static" / "theme" / "motion-vocabulary.css"


def test_generated_ts_is_in_sync():
    assert TS.exists(), "tokens.generated.ts missing — run scripts/regen_motion_tokens.py"
    assert (
        TS.read_text() == compile_remotion.export_ts()
    ), "tokens.generated.ts is stale — run python scripts/regen_motion_tokens.py"


def test_generated_css_is_in_sync():
    assert CSS.exists(), "motion-vocabulary.css missing — run scripts/regen_motion_tokens.py"
    assert (
        CSS.read_text() == compile_css.compile_all_css()
    ), "motion-vocabulary.css is stale — run python scripts/regen_motion_tokens.py"


def test_shipped_presets_emit_no_interp_key():
    """Fold-only-when-present: no shipped preset uses a non-default interp mode,
    so every emitted keyframe dict must omit 'interp' — proving the serialized
    token DATA stays byte-identical to the pre-interp bundle.
    """
    for p in v.PRESETS.values():
        tok = compile_remotion.preset_tokens(p)
        for kfs in tok["channels"].values():
            for k in kfs:
                assert "interp" not in k, f"{p.name} leaked an interp key: {k}"
        # the reduced variant likewise stays bezier
        rtok = compile_remotion.preset_tokens(p.reduced())
        for kfs in rtok["channels"].values():
            for k in kfs:
                assert "interp" not in k, f"{p.name} (reduced) leaked an interp key: {k}"


def test_regen_script_check_mode_passes():
    """``--check`` (used by CI) agrees the committed files are current."""
    import subprocess
    import sys

    res = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "regen_motion_tokens.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
