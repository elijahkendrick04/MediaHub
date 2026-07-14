"""Shared pytest fixtures for the MediaHub suite.

Historically every web-surface test copy-pasted the same boilerplate — set
``DATA_DIR`` (+ ``RUNS_DIR`` / ``UPLOADS_DIR`` / ``SWIM_CONTENT_PROFILES_DIR``)
to a fresh ``tmp_path``, ``importlib.reload`` the ~69k-line ``web.py`` monolith
so it re-derives its import-time path constants, then call ``create_app()``.
That reload ran hundreds of times per suite (once per test), which was the
single biggest slowness driver *and* a heisenbug source: reloading rebuilds
every class object in the module, so ``isinstance`` / singleton-identity checks
silently break across the reload boundary.

The canonical fixtures below replace that pattern. ``web.py`` is imported
**once** for the whole session (never reloaded), and per-test isolation is
achieved by the ``_isolate_data_dir`` fixture, which:

  * points ``DATA_DIR`` (and the derived dirs) at this test's ``tmp_path``, and
  * repoints the already-imported module's path globals + resets its per-run
    module-level state (lazy stores, bounded caches, memoised lookups) so no
    tenant data leaks between tests.

Because the module object is stable across the whole session, class identity is
stable too — the reload heisenbug is gone. Tests opt into a ready-built app via
the ``app`` / ``client`` / ``web_module`` fixtures; requesting any of them is
what switches the isolation on (``_isolate_data_dir`` is deliberately not
``autouse``, so files that still manage their own ``DATA_DIR`` — including via a
module- or session-scoped fixture — are left untouched until they migrate).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
# Legacy package compatibility: register mediahub.* under their old top-level names
import mediahub  # noqa: E402  triggers shim registration

_WEB_MODULE_NAME = "mediahub.web.web"


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


# --------------------------------------------------------------------------
# Canonical DATA_DIR isolation + web app/client fixtures (deep-review #130)
# --------------------------------------------------------------------------


def _reset_web_module_state(wm, data_dir: Path) -> None:
    """Repoint the already-imported ``web.py`` at ``data_dir`` and clear the
    per-run module-level state a reload used to reset.

    ``web.py`` computes ``DATA_DIR`` / ``RUNS_DIR`` / ``UPLOADS_DIR`` / ``DB_PATH``
    once at import (module-level constants) and lazily memoises a workflow store,
    an approval ledger, several ``BoundedCache`` instances, a few plain-dict
    caches and an ``lru_cache``-wrapped default-theme lookup. A reload rebuilt all
    of that from scratch; here we do the same surgically so each test sees a clean,
    correctly-pointed module without paying to re-execute 69k lines.
    """
    runs = data_dir / "runs_v4"
    uploads = data_dir / "uploads_v4"
    runs.mkdir(parents=True, exist_ok=True)
    uploads.mkdir(parents=True, exist_ok=True)

    # 1. Path constants captured at import time.
    wm.DATA_DIR = data_dir
    wm.RUNS_DIR = runs
    wm.UPLOADS_DIR = uploads
    wm.DB_PATH = data_dir / "data.db"

    # 2. Recreate the SQLite schema on this test's fresh DB. ``_init_db()`` is a
    #    module-load-time side effect (idempotent — ``CREATE TABLE IF NOT EXISTS``
    #    + column-guarded ``ALTER``) that a reload used to re-run; without it the
    #    per-test ``data.db`` has no tables and any DB route raises "no such table".
    wm._init_db()

    # 3. Lazy singletons keyed on the (now-stale) RUNS_DIR — force re-init.
    wm._wf_store = None
    wm._approval_ledger = None

    # 4. Every in-process cache a reload would have discarded. BoundedCache
    #    instances are cleared generically (robust to new ones being added) —
    #    ``type() is`` avoids ``isinstance``/``getattr`` triggering attribute
    #    resolution on the werkzeug ``LocalProxy`` objects (``request`` etc.) that
    #    also live in the module namespace. The lru_cache-wrapped default-theme
    #    lookup and the plain-dict job/version caches are cleared by name.
    from mediahub.web.bounded_cache import BoundedCache

    for value in vars(wm).values():
        if type(value) is BoundedCache:
            value.clear()
    theme_cache = getattr(wm, "_default_theme_json_cached", None)
    if theme_cache is not None and hasattr(theme_cache, "cache_clear"):
        theme_cache.cache_clear()
    for _dict_cache in ("_url_jobs", "_url_fetch_rate", "_STATIC_VER_CACHE"):
        d = getattr(wm, _dict_cache, None)
        if isinstance(d, dict):
            d.clear()


@pytest.fixture
def _isolate_data_dir(tmp_path, monkeypatch):
    """Give a test a private ``DATA_DIR`` and keep the shared ``web.py`` in sync.

    This is the single source of per-test tenant isolation for the shared web
    fixtures. It sets the four storage-path env vars to subdirectories of pytest's
    ``tmp_path`` (so a test that also requests ``tmp_path`` sees the exact same
    directory the app writes to), and — if ``web.py`` has already been imported
    this session — repoints its module globals and clears its per-run caches. A
    test that goes through these fixtures never observes another test's runs,
    profiles, uploads or DB.

    Deliberately **not** ``autouse``: it activates only for tests that reach it
    through ``web_module`` / ``app`` / ``client`` (below). That keeps the rollout
    incremental — the ~260 not-yet-migrated files that still manage their own
    ``DATA_DIR`` (often via a module- or session-scoped fixture) are left entirely
    untouched, so this fixture can never clobber a broader-scoped setup. Once a
    file is migrated onto the shared fixtures it picks the isolation up for free.
    """
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))

    wm = sys.modules.get(_WEB_MODULE_NAME)
    if wm is not None:
        _reset_web_module_state(wm, tmp_path)
    yield


@pytest.fixture
def web_module(_isolate_data_dir):
    """The imported ``mediahub.web.web`` module, pointed at this test's DATA_DIR.

    Imported once per session and reused (never reloaded), so class identity is
    stable across tests. Depending on ``_isolate_data_dir`` means requesting this
    fixture (directly, or via ``app`` / ``client``) is what switches the shared
    per-test DATA_DIR isolation on — its path globals are already repointed and
    its caches cleared by the time this yields.
    """
    import mediahub.web.web as wm

    return wm


@pytest.fixture
def app(web_module):
    """A fresh Flask app for this test (``create_app()`` builds a new app object
    each call), wired to this test's isolated DATA_DIR."""
    application = web_module.create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret-key"
    return application


@pytest.fixture
def client(app):
    """A Flask test client for the isolated app.

    Yielded inside the client's context manager so the request/session context is
    available for inspection after a request and torn down cleanly — matching the
    ``with app.test_client() as c`` idiom the migrated tests used."""
    with app.test_client() as c:
        yield c
