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


# --------------------------------------------------------------------------- #
# Render-engine parity layer (deep-review finding #132)
# --------------------------------------------------------------------------- #
# Gen Engine v2 is the *production* default still-render engine, but the autouse
# pin below runs the whole suite on the *legacy* v1 engine so the many tests that
# predate v2 keep asserting v1 layout/variation behaviour without per-test setup.
# That trade-off left the production render path under-tested — the path a real
# customer's card actually takes. The ``render_engine`` fixture is the parity
# layer that closes the gap: a render test that requests it runs **twice** — once
# pinned to legacy v1, once under the real production default — so both engines
# get coverage from one test body. See ``tests/test_render_engine_parity.py`` and
# ``docs/RENDER_ENGINE_PARITY.md`` for the rollout plan.

_RENDER_ENGINES = ("v1", "v2")


@pytest.fixture(params=_RENDER_ENGINES)
def render_engine(request, monkeypatch):
    """Run a render test under **both** still-render engines.

    Parametrised over:

    * ``"v1"`` — pins the legacy engine (``MEDIAHUB_GEN_V2=0``), the same path the
      suite-wide autouse pin selects.
    * ``"v2"`` — clears the kill-switch entirely so the test runs under the **real
      production default** (``archetypes.is_enabled()`` → ``True``), exactly what a
      customer's render takes.

    Requesting this fixture makes the autouse ``_pin_gen_v2_off`` stand down (it
    checks ``request.fixturenames``), so the two never race over the env var — the
    parametrised fixture solely owns ``MEDIAHUB_GEN_V2`` for the test that uses it.
    """
    engine = request.param
    if engine == "v1":
        monkeypatch.setenv("MEDIAHUB_GEN_V2", "0")
    else:  # "v2" — the production default is the *absence* of the kill-switch
        monkeypatch.delenv("MEDIAHUB_GEN_V2", raising=False)
    return engine


@pytest.fixture(autouse=True)
def _pin_gen_v2_off(request, monkeypatch):
    """Pin the LEGACY layout engine for the suite.

    Gen Engine v2 is the *production* default (``archetypes.is_enabled()`` returns
    True unless ``MEDIAHUB_GEN_V2=0``). The many tests that assert v1 layout /
    variation behaviour predate that and would otherwise all need per-test setup,
    so the suite is pinned to the legacy engine here. A test opts into v2 with
    ``monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")``, or exercises the real default
    by deleting the var (``monkeypatch.delenv("MEDIAHUB_GEN_V2", raising=False)``).

    A render-parity test opts out of the pin by requesting the ``render_engine``
    fixture, which drives ``MEDIAHUB_GEN_V2`` itself across both engines; the pin
    stands down for those so it can never clobber the parametrised value.
    """
    if "render_engine" in request.fixturenames:
        return
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "0")
