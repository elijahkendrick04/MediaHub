"""Ensure mediahub package is importable in tests."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
# Legacy package compatibility: register mediahub.* under their old top-level names
import mediahub  # noqa: E402  triggers shim registration


@pytest.fixture(autouse=True)
def _pin_gen_v2_off(monkeypatch):
    """Pin the LEGACY layout engine for the suite.

    Gen Engine v2 is the *production* default (``archetypes.is_enabled()`` returns
    True unless ``MEDIAHUB_GEN_V2=0``). The many tests that assert v1 layout /
    variation behaviour predate that and would otherwise all need per-test setup,
    so the suite is pinned to the legacy engine here. A test opts into v2 with
    ``monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")``, or exercises the real default
    by deleting the var (``monkeypatch.delenv("MEDIAHUB_GEN_V2", raising=False)``).
    """
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "0")
