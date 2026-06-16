"""G1.23 — Headless-Chromium context pooling.

The renderer keeps a small set of Chromium browsers WARM and reuses their
contexts across renders so a batch (a content pack's many cards × formats)
pays the Chromium-launch cost once instead of once per render.

Two layers of test:

* **Fake-Playwright tests** (no browser needed) pin the *mechanics*: a lone
  render still one-shots, a session reuses warm browsers, contexts are cached
  per size, the kill switch / always-on flag behave, sessions ref-count,
  a dead browser is recreated mid-batch, and a broken pool falls back to a
  one-shot launch. These run everywhere and are fast + deterministic.
* **Real-Chromium tests** (skipped when Chromium is absent) prove the pooled
  output is byte-identical to a one-shot render and that concurrent renders
  from many threads are safe — the exact shape ``render_all_formats`` uses.
"""

from __future__ import annotations

import hashlib
import io
import sys
import threading
import types

import pytest

from mediahub.graphic_renderer import render as R


# ---------------------------------------------------------------------------
# Fake Playwright — records lifecycle calls so we can assert on reuse.
# ---------------------------------------------------------------------------

_TINY_PNG = (  # a valid 1x1 transparent PNG, used when PIL is unavailable
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00"
    b"\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _png_bytes(w: int, h: int) -> bytes:
    try:
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGBA", (max(1, w), max(1, h)), (10, 37, 64, 255)).save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return _TINY_PNG


class Reg:
    """Shared call-counter the fakes write to."""

    def __init__(self) -> None:
        self.launches = 0
        self.contexts = 0
        self.context_closes = 0
        self.pages = 0
        self.page_closes = 0
        self.screenshots = 0
        self.browser_closes = 0
        self.pw_starts = 0
        self.pw_stops = 0
        self.context_args: list = []
        # one-shot "kill the page N times" knob for the recovery test
        self.fail_pages_remaining = 0


class FakePage:
    def __init__(self, reg: Reg):
        self._reg = reg

    def goto(self, url, **kw):
        self._url = url

    def evaluate(self, js):
        return True

    def wait_for_timeout(self, ms):
        pass

    def screenshot(self, **kw):
        self._reg.screenshots += 1
        clip = kw.get("clip") or {}
        return _png_bytes(int(clip.get("width", 1)), int(clip.get("height", 1)))

    def close(self):
        self._reg.page_closes += 1


class FakeContext:
    def __init__(self, reg: Reg):
        self._reg = reg

    def route(self, pattern, handler):
        pass

    def new_page(self):
        self._reg.pages += 1
        if self._reg.fail_pages_remaining > 0:
            self._reg.fail_pages_remaining -= 1
            raise RuntimeError("Target page, context or browser has been closed")
        return FakePage(self._reg)

    def close(self):
        self._reg.context_closes += 1


class FakeBrowser:
    def __init__(self, reg: Reg):
        self._reg = reg

    def new_context(self, viewport=None, device_scale_factor=None):
        self._reg.contexts += 1
        self._reg.context_args.append((viewport, device_scale_factor))
        return FakeContext(self._reg)

    def close(self):
        self._reg.browser_closes += 1


class FakeChromium:
    def __init__(self, reg: Reg):
        self._reg = reg

    def launch(self, args=None, **kw):
        self._reg.launches += 1
        return FakeBrowser(self._reg)


class FakePlaywright:
    def __init__(self, reg: Reg):
        self._reg = reg
        self.chromium = FakeChromium(reg)

    def stop(self):
        self._reg.pw_stops += 1


class FakeSyncPlaywright:
    """Returned by ``sync_playwright()`` — both with-block and start()/stop()."""

    def __init__(self, reg: Reg, fail_start: bool = False):
        self._reg = reg
        self._fail_start = fail_start
        self._pw = None

    def __enter__(self):
        self._reg.pw_starts += 1
        self._pw = FakePlaywright(self._reg)
        return self._pw

    def __exit__(self, *exc):
        if self._pw is not None:
            self._pw.stop()
        return False

    def start(self):
        self._reg.pw_starts += 1
        if self._fail_start:
            raise RuntimeError("cannot launch driver subprocess")
        self._pw = FakePlaywright(self._reg)
        return self._pw


def _install_fake(monkeypatch, reg: Reg, *, fail_start: bool = False) -> None:
    """Swap ``playwright.sync_api.sync_playwright`` for the fake factory."""

    def factory():
        return FakeSyncPlaywright(reg, fail_start=fail_start)

    mod = types.ModuleType("playwright.sync_api")
    mod.sync_playwright = factory
    if "playwright" not in sys.modules:
        monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", mod)


@pytest.fixture(autouse=True)
def _clean_pool_state(monkeypatch):
    """Each test starts and ends with no pool and default flags + DPR=1."""
    for var in (
        "MEDIAHUB_RENDER_POOL",
        "MEDIAHUB_RENDER_POOL_ALWAYS",
        "MEDIAHUB_RENDER_POOL_SIZE",
        "MEDIAHUB_RENDER_WORKERS",
        "MEDIAHUB_RENDERER_ALLOW_NET",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MEDIAHUB_RENDER_DPR", "1")  # skip PIL resample in fakes
    R.shutdown_render_pool()
    yield
    R.shutdown_render_pool()


# ---------------------------------------------------------------------------
# Mechanics (fake browser)
# ---------------------------------------------------------------------------


def test_lone_render_one_shots_no_pool(tmp_path, monkeypatch):
    reg = Reg()
    _install_fake(monkeypatch, reg)
    for i in range(3):
        R.render_html_to_png("<html></html>", tmp_path / f"a{i}.png", (300, 200))
    # Every render launched + tore down its own Chromium.
    assert reg.launches == 3
    assert reg.browser_closes == 3
    assert reg.pages == 3 and reg.page_closes == 3
    assert reg.pw_starts == 3 and reg.pw_stops == 3
    assert R.render_pool_active() is False


def test_session_reuses_one_warm_browser(tmp_path, monkeypatch):
    reg = Reg()
    _install_fake(monkeypatch, reg)
    monkeypatch.setenv("MEDIAHUB_RENDER_POOL_SIZE", "2")
    n = 6
    with R.render_pool_session():
        assert R.render_pool_active() is True
        for i in range(n):
            R.render_html_to_png("<html></html>", tmp_path / f"b{i}.png", (300, 200))
    # The headline: 2 warm browsers served all 6 renders — NOT 6 launches.
    assert reg.launches == 2
    assert reg.pw_starts == 2
    assert reg.pages == n  # one cheap page per render
    assert reg.page_closes == n
    assert reg.screenshots == n
    # Same size every render → at most one context per worker (reused).
    assert 1 <= reg.contexts <= 2
    # Torn down cleanly on exit — no leaked browser/driver.
    assert reg.browser_closes == 2
    assert reg.pw_stops == 2
    assert R.render_pool_active() is False


def test_kill_switch_forces_one_shot(tmp_path, monkeypatch):
    reg = Reg()
    _install_fake(monkeypatch, reg)
    monkeypatch.setenv("MEDIAHUB_RENDER_POOL", "0")
    with R.render_pool_session():  # no-op when disabled
        assert R.render_pool_active() is False
        for i in range(3):
            R.render_html_to_png("<html></html>", tmp_path / f"c{i}.png", (300, 200))
    assert reg.launches == 3  # one-shot each, pool never warmed
    assert R.warm_render_pool() is None


def test_always_on_flag_pools_without_session(tmp_path, monkeypatch):
    reg = Reg()
    _install_fake(monkeypatch, reg)
    monkeypatch.setenv("MEDIAHUB_RENDER_POOL_ALWAYS", "1")
    monkeypatch.setenv("MEDIAHUB_RENDER_POOL_SIZE", "1")
    for i in range(4):
        R.render_html_to_png("<html></html>", tmp_path / f"d{i}.png", (300, 200))
    assert reg.launches == 1  # single warm browser, reused for all 4
    assert reg.pages == 4
    R.shutdown_render_pool()
    assert reg.browser_closes == 1


def test_nested_sessions_are_refcounted(tmp_path, monkeypatch):
    reg = Reg()
    _install_fake(monkeypatch, reg)
    monkeypatch.setenv("MEDIAHUB_RENDER_POOL_SIZE", "1")
    with R.render_pool_session():
        assert R.render_pool_active() is True
        outer_pool = R._POOL
        with R.render_pool_session():
            assert R.render_pool_active() is True
            assert R._POOL is outer_pool  # inner scope reuses the same pool
            R.render_html_to_png("<html></html>", tmp_path / "n0.png", (300, 200))
        # Inner exit must NOT tear the pool down.
        assert R.render_pool_active() is True
        R.render_html_to_png("<html></html>", tmp_path / "n1.png", (300, 200))
    assert R.render_pool_active() is False
    assert reg.launches == 1  # one pool the whole time
    assert reg.pages == 2


def test_contexts_cached_per_size(tmp_path, monkeypatch):
    reg = Reg()
    _install_fake(monkeypatch, reg)
    monkeypatch.setenv("MEDIAHUB_RENDER_POOL_SIZE", "1")
    with R.render_pool_session():
        R.render_html_to_png("<html></html>", tmp_path / "s0.png", (300, 200))
        R.render_html_to_png("<html></html>", tmp_path / "s1.png", (400, 400))
        R.render_html_to_png("<html></html>", tmp_path / "s2.png", (300, 200))  # repeat
    # Two distinct sizes → two contexts; the repeat reused the first.
    assert reg.launches == 1
    assert reg.contexts == 2
    assert reg.pages == 3


def test_context_cache_is_bounded(tmp_path, monkeypatch):
    reg = Reg()
    _install_fake(monkeypatch, reg)
    monkeypatch.setenv("MEDIAHUB_RENDER_POOL_SIZE", "1")
    n_sizes = R._CTX_CACHE_CAP + 2
    with R.render_pool_session():
        for i in range(n_sizes):
            R.render_html_to_png("<html></html>", tmp_path / f"z{i}.png", (300 + i, 200))
        # Each distinct size made a context; the oldest were evicted (closed)
        # to keep the per-worker cache bounded.
        assert reg.contexts == n_sizes
        assert reg.context_closes >= n_sizes - R._CTX_CACHE_CAP


def test_dead_browser_is_recreated_mid_batch(tmp_path, monkeypatch):
    reg = Reg()
    _install_fake(monkeypatch, reg)
    monkeypatch.setenv("MEDIAHUB_RENDER_POOL_SIZE", "1")
    reg.fail_pages_remaining = 1  # the very first new_page() dies like a crash
    with R.render_pool_session():
        n = R.render_html_to_png("<html></html>", tmp_path / "r.png", (300, 200))
    assert n > 0
    assert (tmp_path / "r.png").exists()
    # The crash forced a relaunch, then the retry succeeded.
    assert reg.launches == 2
    assert reg.screenshots == 1


def test_broken_pool_falls_back_to_one_shot(tmp_path, monkeypatch):
    reg = Reg()
    # Worker .start() blows up (driver won't launch); the one-shot with-block
    # still works, so the render must still succeed via fallback.
    _install_fake(monkeypatch, reg, fail_start=True)
    monkeypatch.setenv("MEDIAHUB_RENDER_POOL_ALWAYS", "1")
    monkeypatch.setenv("MEDIAHUB_RENDER_POOL_SIZE", "1")
    n = R.render_html_to_png("<html></html>", tmp_path / "fb.png", (300, 200))
    assert n > 0
    assert (tmp_path / "fb.png").exists()
    # The successful render came from the one-shot path (a with-block enter).
    assert reg.screenshots == 1
    assert reg.browser_closes >= 1


def test_shutdown_is_idempotent(monkeypatch):
    reg = Reg()
    _install_fake(monkeypatch, reg)
    R.warm_render_pool(size=1)
    assert R.render_pool_active() is True
    R.shutdown_render_pool()
    R.shutdown_render_pool()  # second call must be a harmless no-op
    assert R.render_pool_active() is False


def test_session_is_noop_when_disabled(monkeypatch):
    reg = Reg()
    _install_fake(monkeypatch, reg)
    monkeypatch.setenv("MEDIAHUB_RENDER_POOL", "off")
    with R.render_pool_session():
        assert R.render_pool_active() is False
    assert R.warm_render_pool() is None


# ---------------------------------------------------------------------------
# Public API + wiring guards
# ---------------------------------------------------------------------------


def test_public_api_exported():
    import mediahub.graphic_renderer as gr

    for name in (
        "render_pool_session",
        "warm_render_pool",
        "shutdown_render_pool",
        "render_pool_active",
    ):
        assert hasattr(gr, name), name
        assert name in gr.__all__


def test_content_pack_loop_wraps_render_in_a_session():
    """The batch loop must render inside a pool session (regression guard)."""
    import inspect
    from mediahub.content_pack_visual import integration

    src = inspect.getsource(integration.create_candidate_pool_for_item)
    assert "with render_pool_session():" in src
    # …and the session opens BEFORE the per-candidate loop, so every candidate
    # × format shares the one warm pool.
    assert src.index("with render_pool_session():") < src.index("for idx, (spec")


# ---------------------------------------------------------------------------
# Real Chromium — byte-identity + thread safety
# ---------------------------------------------------------------------------


def _have_chromium() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch(args=["--no-sandbox"])
            b.close()
        return True
    except Exception:
        return False


_CHROMIUM = _have_chromium()

_REAL_HTML = (
    "<!doctype html><html><head><meta charset=utf-8><style>"
    "html,body{margin:0;padding:0}"
    "#c{width:320px;height:240px;background:linear-gradient(135deg,#0A2540,#0E5BFF);"
    "color:#fff;font:bold 30px sans-serif;display:flex;align-items:center;"
    "justify-content:center}</style></head><body><div id=c>G1.23</div></body></html>"
)


@pytest.mark.skipif(not _CHROMIUM, reason="Chromium not available")
def test_pooled_output_is_byte_identical_to_one_shot(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_DPR", "1")
    R.shutdown_render_pool()

    one = tmp_path / "one.png"
    R.render_html_to_png(_REAL_HTML, one, (320, 240))
    h_one = hashlib.sha256(one.read_bytes()).hexdigest()

    hashes = []
    with R.render_pool_session():
        for i in range(3):
            p = tmp_path / f"pool{i}.png"
            R.render_html_to_png(_REAL_HTML, p, (320, 240))
            hashes.append(hashlib.sha256(p.read_bytes()).hexdigest())

    assert all(h == h_one for h in hashes), "pooled renders must match the one-shot PNG"


@pytest.mark.skipif(not _CHROMIUM, reason="Chromium not available")
def test_pooled_render_keeps_target_dimensions(tmp_path):
    from PIL import Image

    with R.render_pool_session():
        out = tmp_path / "dim.png"
        R.render_html_to_png(_REAL_HTML, out, (320, 240))
    assert Image.open(out).size == (320, 240)


@pytest.mark.skipif(not _CHROMIUM, reason="Chromium not available")
def test_concurrent_renders_in_a_session_are_safe(tmp_path, monkeypatch):
    """Mirror render_all_formats: many threads render at once through the pool."""
    monkeypatch.setenv("MEDIAHUB_RENDER_DPR", "1")
    monkeypatch.setenv("MEDIAHUB_RENDER_POOL_SIZE", "3")
    R.shutdown_render_pool()

    errors: list = []
    paths: list = []
    lock = threading.Lock()

    def _worker(i: int):
        try:
            p = tmp_path / f"t{i}.png"
            R.render_html_to_png(_REAL_HTML, p, (320, 240))
            with lock:
                paths.append(p)
        except Exception as e:  # pragma: no cover - failure path
            with lock:
                errors.append(e)

    with R.render_pool_session():
        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

    assert not errors, f"concurrent pooled renders raised: {errors}"
    assert len(paths) == 8
    from PIL import Image

    for p in paths:
        assert Image.open(p).size == (320, 240)
