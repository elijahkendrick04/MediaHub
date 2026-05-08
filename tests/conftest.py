"""Ensure mediahub package is importable in tests."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
# Legacy package compatibility: register mediahub.* under their old top-level names
import mediahub  # noqa: E402  triggers shim registration
