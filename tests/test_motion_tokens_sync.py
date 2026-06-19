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

ROOT = Path(__file__).resolve().parent.parent
TS = ROOT / "src" / "mediahub" / "remotion" / "src" / "motion" / "tokens.generated.ts"
CSS = ROOT / "src" / "mediahub" / "web" / "static" / "theme" / "motion-vocabulary.css"


def test_generated_ts_is_in_sync():
    assert TS.exists(), "tokens.generated.ts missing — run scripts/regen_motion_tokens.py"
    assert TS.read_text() == compile_remotion.export_ts(), (
        "tokens.generated.ts is stale — run python scripts/regen_motion_tokens.py"
    )


def test_generated_css_is_in_sync():
    assert CSS.exists(), "motion-vocabulary.css missing — run scripts/regen_motion_tokens.py"
    assert CSS.read_text() == compile_css.compile_all_css(), (
        "motion-vocabulary.css is stale — run python scripts/regen_motion_tokens.py"
    )


def test_regen_script_check_mode_passes():
    """``--check`` (used by CI) agrees the committed files are current."""
    import subprocess
    import sys

    res = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "regen_motion_tokens.py"), "--check"],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
