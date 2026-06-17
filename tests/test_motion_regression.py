"""Tests for the frame-by-frame motion visual-regression harness (R1.27).

Two layers, mirroring ``tests/test_motion.py``:

* The **fast layer** runs everywhere with no Node — it drives the diff /
  baseline / report logic with synthetic PNGs and an injected render function,
  so the harness's brain is fully covered even where Remotion isn't installed.
* The **real-render layer** shells out to Node + Remotion. The structural
  validity check runs by default when Node is present (Phase 1.5 no-skips
  directive, same as the MP4 integration test); the heavier determinism and
  committed-baseline pixel-diffs are opt-in via ``MEDIAHUB_MOTION_VR=1`` so the
  default suite stays fast and environment-drift-proof.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

PIL = pytest.importorskip("PIL")  # Pillow is a runtime dep
from PIL import Image  # noqa: E402

from mediahub.visual import motion_regression as mvr  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _png(path: Path, color, size=(40, 30)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def _fake_render_fn(frame_color: dict[int, tuple], size=(40, 30)):
    """Build a render_fn that writes a PNG per scenario frame in ``frame_color``.

    Lets the fast layer exercise check_scenario without Node: the returned
    function paints each requested frame the colour the test chose.
    """

    def _render(scenario, out_dir: Path):
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for f in scenario.frames:
            p = out_dir / mvr.frame_filename(f)
            _png(p, frame_color.get(f, (10, 20, 30)), size=size)
            written.append((f, p))
        return written

    return _render


# ---------------------------------------------------------------------------
# diff_ratio
# ---------------------------------------------------------------------------

def test_identical_images_zero_diff(tmp_path):
    a = _png(tmp_path / "a.png", (10, 20, 30))
    b = _png(tmp_path / "b.png", (10, 20, 30))
    assert mvr.diff_ratio(a, b) == 0.0


def test_fully_different_images_full_diff(tmp_path):
    a = _png(tmp_path / "a.png", (0, 0, 0))
    b = _png(tmp_path / "b.png", (255, 255, 255))
    assert mvr.diff_ratio(a, b) == 1.0


def test_size_mismatch_is_full_diff(tmp_path):
    a = _png(tmp_path / "a.png", (0, 0, 0), size=(40, 30))
    b = _png(tmp_path / "b.png", (0, 0, 0), size=(20, 30))
    assert mvr.diff_ratio(a, b) == 1.0


def test_subdelta_noise_is_not_a_diff(tmp_path):
    # A per-channel change of 10 is below the default delta (24) → 0 changed.
    a = _png(tmp_path / "a.png", (100, 100, 100))
    b = _png(tmp_path / "b.png", (110, 110, 110))
    assert mvr.diff_ratio(a, b) == 0.0
    # ...but counts once the delta is tightened below the change.
    assert mvr.diff_ratio(a, b, pixel_delta=5) == 1.0


def test_partial_diff_ratio(tmp_path):
    # Left half black, right half white vs all-black → ~50% changed.
    base = Image.new("RGB", (40, 30), (0, 0, 0))
    cur = Image.new("RGB", (40, 30), (0, 0, 0))
    for x in range(20, 40):
        for y in range(30):
            cur.putpixel((x, y), (255, 255, 255))
    a = tmp_path / "cur.png"
    b = tmp_path / "base.png"
    cur.save(a)
    base.save(b)
    ratio = mvr.diff_ratio(a, b)
    assert 0.45 < ratio < 0.55


# ---------------------------------------------------------------------------
# write_diff_image
# ---------------------------------------------------------------------------

def test_write_diff_image_produces_png(tmp_path):
    a = _png(tmp_path / "a.png", (0, 0, 0))
    b = _png(tmp_path / "b.png", (255, 255, 255))
    out = tmp_path / "diff.png"
    res = mvr.write_diff_image(a, b, out)
    assert res == out and out.exists()
    with Image.open(out) as im:
        assert im.size == (40, 30)


def test_write_diff_image_size_mismatch_returns_none(tmp_path):
    a = _png(tmp_path / "a.png", (0, 0, 0), size=(40, 30))
    b = _png(tmp_path / "b.png", (0, 0, 0), size=(10, 10))
    assert mvr.write_diff_image(a, b, tmp_path / "diff.png") is None


# ---------------------------------------------------------------------------
# Scenario registry — well-formedness (deterministic, no Node)
# ---------------------------------------------------------------------------

def test_scenarios_present():
    names = {s.name for s in mvr.SCENARIOS}
    assert {"story_pb", "reel_meet"} <= names


def test_scenario_names_unique():
    names = [s.name for s in mvr.SCENARIOS]
    assert len(names) == len(set(names))


def test_scenario_frames_in_range_and_sorted_unique():
    for s in mvr.SCENARIOS:
        assert s.frames, f"{s.name} has no frames"
        assert list(s.frames) == sorted(set(s.frames)), f"{s.name} frames not sorted/unique"
        last = s.duration_in_frames - 1
        for f in s.frames:
            assert 0 <= f <= last, f"{s.name} frame {f} outside [0,{last}]"


def test_scenario_sizes_are_valid_motion_formats():
    for s in mvr.SCENARIOS:
        assert s.format_name in mvr.MOTION_FORMATS
        assert s.size == mvr.MOTION_FORMATS[s.format_name]


def test_story_scenario_props_shape():
    s = mvr.scenario_by_name("story_pb")
    assert set(s.props) == {"card", "brand"}
    card = s.props["card"]
    # Every field the StoryCard schema reads must be present and a string/int.
    for key in ("athleteFullName", "eventName", "resultValue", "achievementLabel"):
        assert isinstance(card[key], str) and card[key]
    assert isinstance(card["variationSeed"], int)
    assert card["photoSrc"] == "" and card["photoTreatment"] == "no-photo"


def test_reel_scenario_props_shape():
    s = mvr.scenario_by_name("reel_meet")
    assert set(s.props) == {"cards", "brand", "meetName"}
    assert len(s.props["cards"]) == 3
    assert s.props["meetName"]


def test_scenario_by_name_unknown_raises():
    with pytest.raises(KeyError):
        mvr.scenario_by_name("does_not_exist")


def test_resolve_scenarios_subset_and_unknown():
    only = mvr.resolve_scenarios(["story_pb"])
    assert [s.name for s in only] == ["story_pb"]
    assert len(mvr.resolve_scenarios()) == len(mvr.SCENARIOS)
    with pytest.raises(KeyError):
        mvr.resolve_scenarios(["nope"])


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def test_frame_filename_zero_padded():
    assert mvr.frame_filename(0) == "frame_000000.png"
    assert mvr.frame_filename(45) == "frame_000045.png"
    assert mvr.frame_filename(170) == "frame_000170.png"


def test_baseline_path_layout():
    p = mvr.baseline_path("story_pb", 45)
    assert p.name == "frame_000045.png"
    assert p.parent.name == "story_pb"
    assert p.parent.parent == mvr.baseline_dir()


def test_baseline_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAHUB_MOTION_VR_BASELINE_DIR", str(tmp_path / "bl"))
    assert mvr.baseline_dir() == tmp_path / "bl"


def test_repo_root_resolves_to_repo():
    root = mvr.repo_root()
    assert (root / "src" / "mediahub").is_dir()
    assert (root / "tests").is_dir()


# ---------------------------------------------------------------------------
# check_scenario / run_regression — logic via injected render_fn (no Node)
# ---------------------------------------------------------------------------

def test_check_no_baseline_honest_skips(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAHUB_MOTION_VR_BASELINE_DIR", str(tmp_path / "baseline"))
    s = mvr.scenario_by_name("story_pb")
    results = mvr.check_scenario(
        s, work_dir=tmp_path / "work", render_fn=_fake_render_fn({}),
    )
    assert len(results) == len(s.frames)
    assert all(r.status == "no_baseline" for r in results)
    # Honest skip never invents a regression.
    assert not any(r.is_regression for r in results)


def test_check_matching_baseline_is_ok(monkeypatch, tmp_path):
    base = tmp_path / "baseline"
    monkeypatch.setenv("MEDIAHUB_MOTION_VR_BASELINE_DIR", str(base))
    s = mvr.scenario_by_name("story_pb")
    color = {f: (12, 34, 56) for f in s.frames}
    # Commit baselines identical to what the fake renderer will produce.
    for f in s.frames:
        _png(mvr.baseline_path(s.name, f), color[f])
    results = mvr.check_scenario(
        s, work_dir=tmp_path / "work", render_fn=_fake_render_fn(color),
    )
    assert [r.status for r in results] == ["ok"] * len(s.frames)
    assert all(r.ratio == 0.0 for r in results)


def test_check_changed_frame_is_regression(monkeypatch, tmp_path):
    base = tmp_path / "baseline"
    monkeypatch.setenv("MEDIAHUB_MOTION_VR_BASELINE_DIR", str(base))
    s = mvr.scenario_by_name("story_pb")
    # Baseline all black; renderer paints the FIRST frame white → regression on it.
    for f in s.frames:
        _png(mvr.baseline_path(s.name, f), (0, 0, 0))
    changed = s.frames[0]
    color = {f: ((255, 255, 255) if f == changed else (0, 0, 0)) for f in s.frames}
    results = mvr.check_scenario(
        s, work_dir=tmp_path / "work", render_fn=_fake_render_fn(color),
    )
    by_frame = {r.frame: r for r in results}
    assert by_frame[changed].status == "regression"
    assert by_frame[changed].ratio == 1.0
    assert by_frame[changed].message
    for f in s.frames[1:]:
        assert by_frame[f].status == "ok"


def test_check_writes_diff_image_for_regression(monkeypatch, tmp_path):
    base = tmp_path / "baseline"
    monkeypatch.setenv("MEDIAHUB_MOTION_VR_BASELINE_DIR", str(base))
    s = mvr.scenario_by_name("story_pb")
    for f in s.frames:
        _png(mvr.baseline_path(s.name, f), (0, 0, 0))
    color = {f: (255, 255, 255) for f in s.frames}
    work = tmp_path / "work"
    results = mvr.check_scenario(
        s, work_dir=work, render_fn=_fake_render_fn(color), write_diffs=True,
    )
    regs = [r for r in results if r.is_regression]
    assert regs and all(r.diff_path and Path(r.diff_path).exists() for r in regs)


def test_check_render_failure_is_one_error_row(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAHUB_MOTION_VR_BASELINE_DIR", str(tmp_path / "baseline"))
    s = mvr.scenario_by_name("story_pb")

    def _boom(scenario, out_dir):
        raise mvr.MotionRegressionError("node exploded")

    results = mvr.check_scenario(s, work_dir=tmp_path / "work", render_fn=_boom)
    assert len(results) == 1
    assert results[0].status == "error" and "node exploded" in results[0].message


def test_check_size_mismatch_is_regression(monkeypatch, tmp_path):
    base = tmp_path / "baseline"
    monkeypatch.setenv("MEDIAHUB_MOTION_VR_BASELINE_DIR", str(base))
    s = mvr.scenario_by_name("story_pb")
    # Baseline at one size, render at another → full diff → regression.
    for f in s.frames:
        _png(mvr.baseline_path(s.name, f), (10, 20, 30), size=(40, 30))
    results = mvr.check_scenario(
        s, work_dir=tmp_path / "work",
        render_fn=_fake_render_fn({f: (10, 20, 30) for f in s.frames}, size=(20, 30)),
    )
    assert all(r.status == "regression" and r.ratio == 1.0 for r in results)


def test_custom_tolerance_passes_a_small_diff(monkeypatch, tmp_path):
    base = tmp_path / "baseline"
    monkeypatch.setenv("MEDIAHUB_MOTION_VR_BASELINE_DIR", str(base))
    s = mvr.scenario_by_name("story_pb")
    # ~50% of pixels differ; default tol (2%) → regression, tol 0.6 → ok.
    half = Image.new("RGB", (40, 30), (0, 0, 0))
    for x in range(20, 40):
        for y in range(30):
            half.putpixel((x, y), (255, 255, 255))

    def _render(scenario, out_dir):
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for f in scenario.frames:
            p = out_dir / mvr.frame_filename(f)
            half.save(p)
            written.append((f, p))
        return written

    for f in s.frames:
        _png(mvr.baseline_path(s.name, f), (0, 0, 0), size=(40, 30))

    strict = mvr.check_scenario(s, work_dir=tmp_path / "w1", render_fn=_render)
    assert all(r.status == "regression" for r in strict)
    loose = mvr.check_scenario(s, work_dir=tmp_path / "w2", render_fn=_render, tolerance=0.6)
    assert all(r.status == "ok" for r in loose)


def test_run_regression_aggregates(monkeypatch, tmp_path):
    base = tmp_path / "baseline"
    monkeypatch.setenv("MEDIAHUB_MOTION_VR_BASELINE_DIR", str(base))
    # story_pb: matching baselines (ok). reel_meet: no baselines (skip).
    story = mvr.scenario_by_name("story_pb")
    color = {f: (12, 34, 56) for f in story.frames}
    for f in story.frames:
        _png(mvr.baseline_path(story.name, f), color[f])

    def _render(scenario, out_dir):
        return _fake_render_fn(
            {f: (12, 34, 56) for f in scenario.frames}
        )(scenario, out_dir)

    report = mvr.run_regression(work_dir=tmp_path / "work", render_fn=_render)
    assert len(report.ok) == len(story.frames)
    assert len(report.skipped) == len(mvr.scenario_by_name("reel_meet").frames)
    assert report.passed  # no regressions, no errors → soft-skips don't fail
    assert "ok" in report.summary()


def test_run_regression_fails_on_regression(monkeypatch, tmp_path):
    base = tmp_path / "baseline"
    monkeypatch.setenv("MEDIAHUB_MOTION_VR_BASELINE_DIR", str(base))
    story = mvr.scenario_by_name("story_pb")
    for f in story.frames:
        _png(mvr.baseline_path(story.name, f), (0, 0, 0))

    def _render(scenario, out_dir):
        return _fake_render_fn(
            {f: (255, 255, 255) for f in scenario.frames}
        )(scenario, out_dir)

    report = mvr.run_regression(["story_pb"], work_dir=tmp_path / "work", render_fn=_render)
    assert report.regressions
    assert not report.passed


def test_env_tolerance_knobs(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_MOTION_VR_MAX_DIFF", "0.10")
    monkeypatch.setenv("MEDIAHUB_MOTION_VR_PIXEL_DELTA", "40")
    assert mvr._max_diff_ratio() == 0.10
    assert mvr._pixel_delta() == 40
    # Bad values fall back to defaults rather than crashing.
    monkeypatch.setenv("MEDIAHUB_MOTION_VR_MAX_DIFF", "not-a-float")
    monkeypatch.setenv("MEDIAHUB_MOTION_VR_PIXEL_DELTA", "xx")
    assert mvr._max_diff_ratio() == 0.02
    assert mvr._pixel_delta() == 24


# ---------------------------------------------------------------------------
# Node-side script presence (no execution)
# ---------------------------------------------------------------------------

def test_frame_render_script_exists():
    assert mvr.FRAME_SCRIPT.exists(), f"missing Node frame renderer at {mvr.FRAME_SCRIPT}"
    assert mvr.FRAME_SCRIPT.name == "render_frame.js"


def test_render_raises_without_remotion(monkeypatch, tmp_path):
    # With Node forced absent the renderer raises a clear, typed error.
    monkeypatch.setattr(mvr, "node_available", lambda: False)
    with pytest.raises(mvr.MotionRegressionError):
        mvr.render_scenario_frames(mvr.scenario_by_name("story_pb"), tmp_path)


def test_render_passes_absolute_paths_to_node(monkeypatch, tmp_path):
    """The Node renderer runs with cwd=REMOTION_DIR, so a *relative* out_dir
    (e.g. CI's ``--out motion_vr_out``) must still reach it as absolute --props
    / --output-dir — else Node ENOENTs resolving them against the wrong dir.
    Regression guard for that CI failure; no Node needed (subprocess faked)."""
    monkeypatch.setattr(mvr, "node_available", lambda: True)
    monkeypatch.setattr(mvr, "remotion_installed", lambda: True)
    captured: dict = {}

    class _Proc:
        returncode = 0
        stderr = ""
        stdout = '{"frames": []}'

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _Proc()

    monkeypatch.setattr(mvr.subprocess, "run", _fake_run)
    monkeypatch.chdir(tmp_path)  # so a relative out_dir is meaningful
    mvr.render_scenario_frames(mvr.scenario_by_name("story_pb"), Path("rel_out"))
    cmd = captured["cmd"]
    props = cmd[cmd.index("--props") + 1]
    out_dir = cmd[cmd.index("--output-dir") + 1]
    assert Path(props).is_absolute(), f"--props not absolute: {props}"
    assert Path(out_dir).is_absolute(), f"--output-dir not absolute: {out_dir}"


# ---------------------------------------------------------------------------
# Real-render layer — needs Node + Remotion
# ---------------------------------------------------------------------------

def _can_render() -> bool:
    return (
        mvr.node_available()
        and mvr.remotion_installed()
        and os.environ.get("MEDIAHUB_SKIP_MOTION_TESTS", "").lower() not in ("1", "true", "yes")
    )


_VR_OPT_IN = os.environ.get("MEDIAHUB_MOTION_VR", "").lower() in ("1", "true", "yes")


@pytest.mark.skipif(not _can_render(), reason="Node + Remotion not available")
def test_reference_frames_render_valid(tmp_path):
    """Default-on (Node present): the real composition renders every reference
    frame of the story scenario as a valid PNG of the right dimensions."""
    s = mvr.scenario_by_name("story_pb")
    rendered = mvr.render_scenario_frames(s, tmp_path / "frames")
    assert [f for f, _ in rendered] == list(s.frames)
    w, h = s.size
    for frame, p in rendered:
        assert p.exists() and p.stat().st_size > 64
        with Image.open(p) as im:
            assert im.format == "PNG"
            assert im.size == (w, h), f"frame {frame} is {im.size}, expected {(w, h)}"


@pytest.mark.skipif(not _VR_OPT_IN, reason="set MEDIAHUB_MOTION_VR=1 for the slow render-diff")
@pytest.mark.skipif(not _can_render(), reason="Node + Remotion not available")
def test_render_is_deterministic(tmp_path):
    """The premise behind committed baselines: the same props + frame paint the
    same pixels twice (within the AA tolerance)."""
    s = mvr.scenario_by_name("story_pb")
    first = dict(mvr.render_scenario_frames(s, tmp_path / "a"))
    second = dict(mvr.render_scenario_frames(s, tmp_path / "b"))
    for frame in s.frames:
        ratio = mvr.diff_ratio(first[frame], second[frame])
        assert ratio <= mvr._max_diff_ratio(), (
            f"frame {frame} not deterministic across renders: {ratio:.3%} changed"
        )


@pytest.mark.skipif(not _VR_OPT_IN, reason="set MEDIAHUB_MOTION_VR=1 for the slow render-diff")
@pytest.mark.skipif(not _can_render(), reason="Node + Remotion not available")
def test_committed_baselines_match(tmp_path):
    """The real pixel-diff in CI: every reference frame matches its committed
    baseline within tolerance. Frames with no baseline honest-skip."""
    report = mvr.run_regression(work_dir=tmp_path, write_diffs=True)
    assert not report.errors, f"render errors: {[r.message for r in report.errors]}"
    assert not report.regressions, (
        "motion visual regression: "
        + "; ".join(f"{r.scenario}#{r.frame} {r.message}" for r in report.regressions)
    )
