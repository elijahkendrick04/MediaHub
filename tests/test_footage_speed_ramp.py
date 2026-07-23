"""speed-ramp (AE-gap) — deterministic footage decelerate-into-the-beat bake.

The ramp is baked into the trimmed clip via ffmpeg ``setpts`` (Remotion keeps
playing the clip at native 1x — ``OffthreadVideo`` playbackRate is not
frame-pure). Coverage:

* pure ``speed_ramp_plan`` maths (W == 0.75·beat at r_end=0.5, monotonic setpts
  mapping 0→0 and W→beat, output frames == beat·30);
* default-off byte-identity of ``video_src`` + ``cache_sig`` + duration;
* an active ramp re-tags the clip name + folds ``ramp`` into ``cache_sig`` AND
  decouples ``video_duration_sec`` to the baked beat length (not the source
  span);
* honest degrade to the native trim when the ramped bake fails — native bytes
  keep the native cache_sig/key so a ramped clip and a degraded clip never
  alias.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.video.moments import Moment  # noqa: E402
from mediahub.visual import footage as footage_mod  # noqa: E402

# Reuse the Phase-D footage fixtures/helpers so the sourcing setup can't drift.
from tests.test_phase_d_footage import (  # noqa: E402
    BRAND,
    FakeStore,
    _card,
    _footage_asset,
)


def _eval_setpts(expr: str, s: float, tb: float = 1.0) -> float:
    """Evaluate the generated ffmpeg setpts expression in Python.

    ``T`` is the input (source) timestamp in seconds; ``TB`` the timebase.
    Order matters: replace ``TB`` and ``sqrt`` before the bare ``T`` variable.
    """
    e = expr.replace("TB", "tb").replace("sqrt", "math.sqrt")
    e = e.replace("T", repr(float(s)))
    return eval(e, {"math": math, "tb": tb})  # noqa: S307 — our own generated string


# ---------------------------------------------------------------------------
# Pure ramp maths
# ---------------------------------------------------------------------------


class TestSpeedRampPlan:
    def test_slow_in_source_span_is_075_beat(self):
        setpts, span_ms, params = footage_mod.speed_ramp_plan("slow_in", 6000)
        # W = beat·(1+r_end)/2 = 0.75·beat at r_end = 0.5.
        assert span_ms == 4500
        assert params["r_end"] == 0.5
        assert params["kind"] == "slow_in"
        assert params["code"] == "si50"
        assert params["source_span_ms"] == 4500
        assert isinstance(setpts, str) and "setpts" not in setpts  # bare expr

    def test_unknown_kind_and_bad_beat_return_none(self):
        assert footage_mod.speed_ramp_plan("warp_zoom", 6000) is None
        assert footage_mod.speed_ramp_plan("", 6000) is None
        assert footage_mod.speed_ramp_plan("slow_in", 0) is None
        assert footage_mod.speed_ramp_plan("slow_in", -100) is None

    def test_setpts_expr_monotonic_and_maps_span_to_full_beat(self):
        beat_ms = 6000
        setpts, span_ms, _ = footage_mod.speed_ramp_plan("slow_in", beat_ms)
        out_s = beat_ms / 1000.0
        w_s = span_ms / 1000.0
        # Endpoints: source 0 → output 0, source W → output full beat. The clip
        # therefore covers exactly the beat (output frames == beat·30 at 30fps),
        # so video_duration_sec stays == beat.
        assert _eval_setpts(setpts, 0.0) == pytest.approx(0.0, abs=1e-6)
        assert _eval_setpts(setpts, w_s) == pytest.approx(out_s, abs=1e-6)
        # Strictly monotonic increasing across the consumed source span.
        prev = -1.0
        for i in range(0, 46):
            t = _eval_setpts(setpts, w_s * i / 45.0)
            assert t > prev
            prev = t

    def test_plan_is_pure_deterministic(self):
        a = footage_mod.speed_ramp_plan("slow_in", 4200)
        b = footage_mod.speed_ramp_plan("slow_in", 4200)
        assert a == b


# ---------------------------------------------------------------------------
# Resolve-path: default-off byte-identity, active ramp, honest degrade
# ---------------------------------------------------------------------------


@pytest.fixture
def ramp_env(tmp_path, monkeypatch):
    """A DATA_DIR-isolated footage env with a window LONGER than the beat.

    A longer-than-beat window lets the tests prove the decoupling: the native
    trim's video_duration_sec follows the 8s window, the ramped one follows the
    6s beat, and the source span consumed is a third value (0.75·beat).
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    # One strong 8s window starting at 4000ms (longer than the 6s beat).
    monkeypatch.setattr(
        "mediahub.video.moments.detect_moments",
        lambda path, *, duration_ms, target_len_ms=6000, max_moments=5: [
            Moment(4000, 12000, 0.9, "energy", "loud cheer at 4s"),
        ],
    )
    trims: list[dict] = []

    def fake_trim(
        src, out_path, *, in_ms, out_ms, dims, stabilize=False, setpts_expr=None, out_dur_ms=None
    ):
        trims.append(
            {
                "in": in_ms,
                "out": out_ms,
                "dims": dims,
                "stabilize": stabilize,
                "setpts_expr": setpts_expr,
                "out_dur_ms": out_dur_ms,
            }
        )
        Path(out_path).write_bytes(b"clip" * 512)
        return True

    monkeypatch.setattr(footage_mod, "_normalise_clip", fake_trim)
    cache = tmp_path / "footage_cache"
    monkeypatch.setattr(
        footage_mod, "footage_cache_dir", lambda: cache.mkdir(exist_ok=True) or cache
    )
    return {"tmp": tmp_path, "trims": trims, "cache": cache, "monkeypatch": monkeypatch}


def _resolve_full(tmp_path, *, store, speed_ramp=None, beat=6.0):
    from tests.test_phase_d_footage import _brief

    return footage_mod.resolve_card_footage(
        _card(),
        _brief(),
        BRAND,
        beat_seconds=beat,
        store=store,
        speed_ramp=speed_ramp,
    )


class TestRampResolve:
    def test_default_off_cache_sig_and_clip_name_byte_identical(self, ramp_env):
        tmp = ramp_env["tmp"]
        store = FakeStore([_footage_asset(tmp)])
        base, _ = _resolve_full(tmp, store=store, speed_ramp=None)
        assert base is not None
        # No ramp fold anywhere; the window drives the (8s) duration as before.
        assert "ramp" not in base.cache_sig
        assert "ramp" not in base.provenance
        assert "-r" not in base.video_src
        assert base.cache_sig["in_ms"] == 4000 and base.cache_sig["out_ms"] == 12000
        assert base.video_duration_sec == 8.0
        # An unknown ramp kind degrades to the exact native identity (only a
        # provenance note records the miss — the cache_sig/key stay native).
        other, _ = _resolve_full(
            tmp, store=FakeStore([_footage_asset(tmp)]), speed_ramp="warp_zoom"
        )
        assert other.cache_sig == base.cache_sig
        assert other.video_src == base.video_src
        assert other.provenance["ramp"] == {
            "requested": True,
            "applied": False,
            "reason": "unknown-ramp-kind",
        }

    def test_ramp_active_changes_clip_name_and_cache_sig(self, ramp_env):
        tmp = ramp_env["tmp"]
        store = FakeStore([_footage_asset(tmp)])
        res, why = _resolve_full(tmp, store=store, speed_ramp="slow_in")
        assert res is not None and why == ""
        # Ramp-tagged clip name so it never aliases the native trim.
        assert res.video_src.endswith("-rsi50.mp4")
        # Source sub-window is the first 0.75·beat of the detected window.
        assert res.cache_sig["in_ms"] == 4000 and res.cache_sig["out_ms"] == 8500
        # Ramp descriptor folded into cache_sig (applied-state distinct key).
        assert res.cache_sig["ramp"]["code"] == "si50"
        assert res.provenance["ramp"]["applied"] is True
        # DECOUPLED: baked clip fills the full beat (6s), not the 8s window and
        # not the 4.5s source span.
        assert res.video_duration_sec == 6.0
        # The bake was invoked with the setpts expr + the full-beat output -t.
        last = ramp_env["trims"][-1]
        assert last["setpts_expr"] is not None
        assert last["in"] == 4000 and last["out"] == 8500
        assert last["out_dur_ms"] == 6000

    def test_ramp_active_rekeys_motion_content_hash(self, ramp_env):
        from mediahub.visual import motion

        tmp = ramp_env["tmp"]
        base, _ = _resolve_full(tmp, store=FakeStore([_footage_asset(tmp)]), speed_ramp=None)
        ramped, _ = _resolve_full(tmp, store=FakeStore([_footage_asset(tmp)]), speed_ramp="slow_in")
        h_plain = motion._content_hash({"footage": base.cache_sig}, kind="story")
        h_ramp = motion._content_hash({"footage": ramped.cache_sig}, kind="story")
        assert h_plain != h_ramp
        # Stable: hashing the same sig twice is identical (fold-only-when-active).
        assert h_plain == motion._content_hash({"footage": base.cache_sig}, kind="story")

    def test_ramped_bake_failure_degrades_to_native_trim(self, ramp_env):
        tmp = ramp_env["tmp"]
        monkeypatch = ramp_env["monkeypatch"]

        # Fail ONLY the ramped bake (setpts present); native trim still succeeds.
        def selective_trim(
            src,
            out_path,
            *,
            in_ms,
            out_ms,
            dims,
            stabilize=False,
            setpts_expr=None,
            out_dur_ms=None,
        ):
            if setpts_expr is not None:
                return False
            Path(out_path).write_bytes(b"clip" * 512)
            return True

        monkeypatch.setattr(footage_mod, "_normalise_clip", selective_trim)
        res, why = _resolve_full(tmp, store=FakeStore([_footage_asset(tmp)]), speed_ramp="slow_in")
        assert res is not None and why == ""
        # Degraded to the native identity: native clip name, native window, NO
        # ramp fold in cache_sig (so it can never alias the ramped clip's key).
        assert "-rsi50" not in res.video_src
        assert "ramp" not in res.cache_sig
        assert res.cache_sig["in_ms"] == 4000 and res.cache_sig["out_ms"] == 12000
        assert res.video_duration_sec == 8.0
        # Honest provenance: the ramp was requested but not applied.
        assert res.provenance["ramp"] == {
            "requested": True,
            "applied": False,
            "reason": "speed-ramp-bake-failed",
        }
