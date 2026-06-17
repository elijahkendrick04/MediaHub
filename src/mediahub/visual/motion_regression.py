"""Frame-by-frame motion visual-regression harness (roadmap R1.27).

The MP4 render path (``visual/motion.py`` → ``remotion/render.js``) has a
*cache-key* render-diff guard (``tests/test_motion.py``) that proves two briefs
produce byte-distinct videos — but byte-distinctness can't tell you whether a
TSX refactor quietly *broke* a scene (wrong colour, a layer that stopped
painting, a transition that collapsed). Bytes change for benign reasons too
(encoder timestamps), so MP4 bytes are the wrong signal for "did this still look
right?".

This module is the pixel-level backbone for that question — the motion analogue
of ``autotest/visual_regression.py`` (which pixel-diffs still *surfaces*). It:

* renders a fixed set of **reference frames** from the real StoryCard / MeetReel
  compositions (via ``remotion/render_frame.js`` → Remotion ``renderStill``),
  using frozen, self-contained props so the only thing that can move the pixels
  is the composition code itself;
* **pixel-diffs** each frame against a committed, human-blessed baseline PNG;
* reports a ``regression`` above tolerance, **honest-skips** (never invents a
  regression) when no baseline exists yet, and surfaces render/IO errors
  honestly.

Baselines live under ``tests/baseline/motion_frames/<scenario>/frame_<NNNNNN>.png``
and are **human-committed, never auto-written** by the check path — the same
anti-circularity rule the still backbone follows. Capture / refresh them
deliberately with ``scripts/motion_vr.py capture`` (or :func:`capture_baselines`).

Determinism note: the compositions use no ``Math.random`` and no wall clock,
fonts are self-hosted and held by ``delayRender`` until ``document.fonts.ready``,
and a given (props, frame) always paints the same pixels — that reproducibility
is what makes a committed baseline meaningful. The per-channel ``PIXEL_DELTA``
and the ``MAX_DIFF`` ratio absorb sub-pixel anti-aliasing so benign noise never
reads as a regression.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from mediahub.visual.motion import (
    MOTION_FORMATS,
    REMOTION_DIR,
    node_available,
    remotion_installed,
)

# Node half of the harness (sibling of render.js).
FRAME_SCRIPT = REMOTION_DIR / "render_frame.js"

FPS = 30  # both compositions declare 30fps in Root.tsx


# ---------------------------------------------------------------------------
# Tolerances (env-overridable, same knobs as the still backbone)
# ---------------------------------------------------------------------------


def _pixel_delta() -> int:
    """Per-channel difference (0–255) above which a pixel counts as changed.

    Defaults to 24 so JPEG-ish noise / sub-pixel anti-aliasing doesn't read as a
    regression — identical to ``autotest/visual_regression.py``.
    """
    try:
        return int(os.environ.get("MEDIAHUB_MOTION_VR_PIXEL_DELTA", "24"))
    except ValueError:
        return 24


def _max_diff_ratio() -> float:
    """Fraction of changed pixels above which a frame is a regression (default 2%)."""
    try:
        return float(os.environ.get("MEDIAHUB_MOTION_VR_MAX_DIFF", "0.02"))
    except ValueError:
        return 0.02


# ---------------------------------------------------------------------------
# Reference scenarios — frozen, self-contained props
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameScenario:
    """One reference clip the harness renders and diffs frame-by-frame.

    ``props`` is the complete Remotion input-props object for ``composition_id``
    (``{"card", "brand"}`` for StoryCard, ``{"cards", "brand", "meetName"}`` for
    MeetReel) — deliberately literal and DATA_DIR-free so a frame's only moving
    part is the composition code. ``frames`` are the frame indices to capture
    (must be inside ``round(duration_sec * FPS)``); they span the clip's beats
    (entrance → settle → breathe) so a regression in any phase is caught.
    """

    name: str
    composition_id: str
    format_name: str
    duration_sec: float
    frames: tuple[int, ...]
    props: dict

    @property
    def size(self) -> tuple[int, int]:
        return MOTION_FORMATS[self.format_name]

    @property
    def duration_in_frames(self) -> int:
        return max(1, round(self.duration_sec * FPS))


# A frozen, on-brand brand kit shared by every scenario.
_BRAND = {
    "primary": "#0A2540",
    "secondary": "#FF6F61",
    "accent": "#FFD43B",
    "displayName": "Riverside Swimming Club",
    "shortName": "RSC",
    "logoDataUri": "",
    "themeSource": "brand-kit",
}


def _card(
    *,
    full: str,
    first: str,
    surname: str,
    event: str,
    result: str,
    label: str,
    place: str,
    seed: int,
    background: str,
    composition: str,
    typography: str,
    accent: str,
    mood: str,
) -> dict:
    """A complete StoryCard card-props dict (every schema field populated).

    Photo-free and role-pinned so the frame is fully reproducible without any
    media-library / theme-store state.
    """
    return {
        "athleteFullName": full,
        "athleteFirstName": first,
        "athleteSurname": surname,
        "eventName": event,
        "resultValue": result,
        "achievementLabel": label,
        "meetName": "MediaHub Regional Open",
        "place": place,
        "variationSeed": seed,
        "backgroundStyle": background,
        "composition": composition,
        "typographyPair": typography,
        "accentStyle": accent,
        "mood": mood,
        "photoTreatment": "no-photo",
        "photoSrc": "",
        "photoPos": "",
        "archetype": "",
        "heroStat": "",
        "stylePack": "",
        "motionIntent": "",
        "roleGround": "#0A2540",
        "roleSurface": "#0E2E4D",
        "roleAccent": "#FFD43B",
        "roleOnGround": "#FFFFFF",
    }


_STORY_CARD = _card(
    full="Jordan Rivers",
    first="Jordan",
    surname="Rivers",
    event="100m Freestyle LC",
    result="00:52.18",
    label="NEW PB",
    place="1",
    seed=7,
    background="diagonal",
    composition="left",
    typography="anton-inter",
    accent="brackets",
    mood="electric, precise",
)

_REEL_CARDS = [
    _card(
        full="Jordan Rivers",
        first="Jordan",
        surname="Rivers",
        event="100m Freestyle LC",
        result="00:52.18",
        label="NEW PB",
        place="1",
        seed=7,
        background="diagonal",
        composition="left",
        typography="anton-inter",
        accent="brackets",
        mood="electric, precise",
    ),
    _card(
        full="Amara Okafor",
        first="Amara",
        surname="Okafor",
        event="200m Butterfly LC",
        result="02:14.06",
        label="GOLD",
        place="1",
        seed=13,
        background="halftone",
        composition="center",
        typography="archivo-inter",
        accent="ribbon",
        mood="celebratory, bold",
    ),
    _card(
        full="Lena Park",
        first="Lena",
        surname="Park",
        event="50m Backstroke SC",
        result="00:29.44",
        label="CLUB RECORD",
        place="2",
        seed=21,
        background="geometric",
        composition="right",
        typography="bebas-grotesk",
        accent="badge",
        mood="kinetic",
    ),
]


# The canonical reference set. Small on purpose — every frame is a committed PNG
# and a render in CI, so the set spans the beats without ballooning render time.
SCENARIOS: tuple[FrameScenario, ...] = (
    FrameScenario(
        name="story_pb",
        composition_id="StoryCard",
        format_name="story",
        duration_sec=6.0,
        # The card springs in over ~1s then holds, so the distinct states all
        # live early: 0 entrance start (ground + watermark) · 18 mid-entrance
        # (elements springing in) · 34 the spring's overshoot peak · 60 the
        # settled final composition. (Later frames are identical to 60 — no
        # late motion — so sampling them would be wasted baselines.)
        frames=(0, 18, 34, 60),
        props={"card": _STORY_CARD, "brand": _BRAND},
    ),
    FrameScenario(
        name="reel_meet",
        composition_id="MeetReel",
        format_name="story",
        duration_sec=15.0,
        # Frames land on settled beats, not mid-transition (the cover is 2s,
        # cards are rank-weighted, outro the last ~1s): 60 cover · 130 card#1
        # (Rivers/diagonal) · 260 card#2 (Okafor/halftone) · 370 card#3
        # (Park/geometric) · 440 outro — one frame per distinct scene.
        frames=(60, 130, 260, 370, 440),
        props={"cards": _REEL_CARDS, "brand": _BRAND, "meetName": "MediaHub Regional Open"},
    ),
)


def scenario_by_name(name: str) -> FrameScenario:
    for s in SCENARIOS:
        if s.name == name:
            return s
    raise KeyError(f"unknown motion-VR scenario {name!r}; valid: {[s.name for s in SCENARIOS]}")


def resolve_scenarios(names: Optional[list[str]] = None) -> list[FrameScenario]:
    """All scenarios, or just the named subset (preserving the canonical order)."""
    if not names:
        return list(SCENARIOS)
    wanted = set(names)
    out = [s for s in SCENARIOS if s.name in wanted]
    missing = wanted - {s.name for s in out}
    if missing:
        raise KeyError(f"unknown motion-VR scenario(s): {sorted(missing)}")
    return out


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def repo_root() -> Path:
    # src/mediahub/visual/motion_regression.py → parents[3] is the repo root.
    return Path(__file__).resolve().parents[3]


def baseline_dir() -> Path:
    override = os.environ.get("MEDIAHUB_MOTION_VR_BASELINE_DIR")
    if override:
        return Path(override)
    return repo_root() / "tests" / "baseline" / "motion_frames"


def frame_filename(frame: int) -> str:
    return f"frame_{int(frame):06d}.png"


def baseline_path(scenario: str, frame: int) -> Path:
    return baseline_dir() / scenario / frame_filename(frame)


# ---------------------------------------------------------------------------
# Pixel diff
# ---------------------------------------------------------------------------


def diff_ratio(
    current_png: Path, baseline_png: Path, *, pixel_delta: Optional[int] = None
) -> float:
    """Fraction of pixels that differ beyond the per-channel delta.

    A size mismatch is a full (1.0) difference; an exact match is 0.0. Mirrors
    ``autotest/visual_regression.py`` so the two backbones agree on what "the
    same pixel" means.
    """
    from PIL import Image, ImageChops

    delta = _pixel_delta() if pixel_delta is None else int(pixel_delta)
    with Image.open(current_png) as a_img, Image.open(baseline_png) as b_img:
        a = a_img.convert("RGB")
        b = b_img.convert("RGB")
        if a.size != b.size:
            return 1.0
        diff = ImageChops.difference(a, b).convert("L")
        mask = diff.point(lambda p: 255 if p > delta else 0)
        changed = sum(mask.point(lambda p: 1 if p else 0).getdata())
        total = a.size[0] * a.size[1]
        return (changed / total) if total else 0.0


def write_diff_image(current_png: Path, baseline_png: Path, out_png: Path) -> Optional[Path]:
    """Write a red-on-grey heatmap of the changed pixels for eyeballing a diff.

    Best-effort debugging aid: returns the path on success, ``None`` on a size
    mismatch or any failure (it must never break a check run).
    """
    try:
        from PIL import Image, ImageChops

        delta = _pixel_delta()
        with Image.open(current_png) as a_img, Image.open(baseline_png) as b_img:
            a = a_img.convert("RGB")
            b = b_img.convert("RGB")
            if a.size != b.size:
                return None
            diff = ImageChops.difference(a, b).convert("L")
            mask = diff.point(lambda p: 255 if p > delta else 0)
            grey = b.convert("L").convert("RGB")
            red = Image.new("RGB", a.size, (255, 0, 0))
            out = Image.composite(red, grey, mask)
            out_png.parent.mkdir(parents=True, exist_ok=True)
            out.save(out_png)
            return out_png
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class MotionRegressionError(RuntimeError):
    """Raised when the Node frame renderer can't run or fails."""


def render_scenario_frames(
    scenario: FrameScenario, out_dir: Path, *, timeout: int = 600
) -> list[tuple[int, Path]]:
    """Render a scenario's reference frames to ``out_dir`` as PNGs.

    Shells out to ``remotion/render_frame.js`` (bundle once, ``renderStill`` per
    frame) and returns ``[(frame_index, png_path), ...]`` sorted by frame.
    Raises :class:`MotionRegressionError` if Node/Remotion is unavailable or the
    render fails — callers that want a soft skip should gate on
    :func:`node_available` / :func:`remotion_installed` first.
    """
    if not node_available():
        raise MotionRegressionError(
            "Node is not installed; install Node 18+ to render motion reference frames."
        )
    if not remotion_installed():
        raise MotionRegressionError(
            "Remotion deps not installed (run `npm install` in src/mediahub/remotion)."
        )
    if not FRAME_SCRIPT.exists():
        raise MotionRegressionError(f"Frame render script missing at {FRAME_SCRIPT}")

    # Resolve to an ABSOLUTE dir: the Node renderer runs with cwd=REMOTION_DIR,
    # so a relative --props / --output-dir (e.g. CI's `--out motion_vr_out`)
    # would resolve against the wrong directory and ENOENT.
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    props_path = out_dir / f"{scenario.name}.props.json"
    props_path.write_text(json.dumps(scenario.props, indent=2), encoding="utf-8")

    w, h = scenario.size
    cmd = [
        "node",
        str(FRAME_SCRIPT),
        "--composition",
        scenario.composition_id,
        "--props",
        str(props_path),
        "--output-dir",
        str(out_dir),
        "--frames",
        ",".join(str(f) for f in scenario.frames),
        "--duration",
        str(scenario.duration_sec),
        "--width",
        str(int(w)),
        "--height",
        str(int(h)),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REMOTION_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise MotionRegressionError(
            f"Frame render timed out after {timeout}s for scenario {scenario.name}"
        ) from e

    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-15:]) or "(no stderr)"
        raise MotionRegressionError(
            f"Frame render failed for {scenario.name} (exit {proc.returncode}):\n{tail}"
        )

    # The Node script prints one JSON line on stdout describing the written files.
    manifest_line = ""
    for line in (proc.stdout or "").strip().splitlines():
        line = line.strip()
        if line.startswith("{"):
            manifest_line = line
    if not manifest_line:
        raise MotionRegressionError(
            f"Frame render for {scenario.name} produced no manifest on stdout"
        )
    try:
        manifest = json.loads(manifest_line)
    except ValueError as e:
        raise MotionRegressionError(
            f"Could not parse frame-render manifest for {scenario.name}: {e}"
        ) from e

    out: list[tuple[int, Path]] = []
    for entry in manifest.get("frames", []):
        p = Path(entry["path"])
        if not p.exists():
            raise MotionRegressionError(f"Frame renderer reported {p} but it is missing")
        out.append((int(entry["frame"]), p))
    out.sort(key=lambda t: t[0])
    return out


# ---------------------------------------------------------------------------
# Baseline capture (deliberate / human-invoked)
# ---------------------------------------------------------------------------


def capture_baselines(names: Optional[list[str]] = None, *, timeout: int = 600) -> list[Path]:
    """Render the (selected) scenarios and write their frames into the baseline dir.

    Deliberate, operator-invoked baseline refresh — the only writer of the
    committed baselines. The check path never calls this (anti-circularity).
    Returns the list of written baseline PNG paths.
    """
    import tempfile

    from PIL import Image

    written: list[Path] = []
    for scenario in resolve_scenarios(names):
        with tempfile.TemporaryDirectory(prefix=f"motionvr-cap-{scenario.name}-") as tmp:
            rendered = render_scenario_frames(scenario, Path(tmp), timeout=timeout)
            for frame, src in rendered:
                dst = baseline_path(scenario.name, frame)
                dst.parent.mkdir(parents=True, exist_ok=True)
                # Re-save losslessly (identical pixels) with max PNG compression so
                # a committed baseline stays well under the repo's new-file size
                # guard. The check decodes pixels (RGB), so an optimised baseline
                # still diffs 0.0 against a fresh, unoptimised render.
                with Image.open(src) as im:
                    im.convert("RGB").save(dst, format="PNG", optimize=True, compress_level=9)
                written.append(dst)
    return written


# ---------------------------------------------------------------------------
# Check (render → diff → report)
# ---------------------------------------------------------------------------

# A render function: (scenario, out_dir) -> [(frame, png_path), ...]. Injectable
# so tests can drive the diff/baseline logic without Node.
RenderFn = Callable[[FrameScenario, Path], "list[tuple[int, Path]]"]


@dataclass
class FrameResult:
    scenario: str
    frame: int
    status: str  # "ok" | "regression" | "no_baseline" | "error"
    ratio: Optional[float] = None
    tolerance: Optional[float] = None
    current_path: Optional[Path] = None
    baseline_path: Optional[Path] = None
    diff_path: Optional[Path] = None
    message: str = ""

    @property
    def is_regression(self) -> bool:
        return self.status == "regression"


@dataclass
class RegressionReport:
    results: list[FrameResult] = field(default_factory=list)

    @property
    def regressions(self) -> list[FrameResult]:
        return [r for r in self.results if r.status == "regression"]

    @property
    def errors(self) -> list[FrameResult]:
        return [r for r in self.results if r.status == "error"]

    @property
    def skipped(self) -> list[FrameResult]:
        return [r for r in self.results if r.status == "no_baseline"]

    @property
    def ok(self) -> list[FrameResult]:
        return [r for r in self.results if r.status == "ok"]

    @property
    def passed(self) -> bool:
        """No regressions and no hard errors (missing baselines are a soft skip)."""
        return not self.regressions and not self.errors

    def summary(self) -> str:
        return (
            f"{len(self.ok)} ok · {len(self.regressions)} regression(s) · "
            f"{len(self.skipped)} no-baseline · {len(self.errors)} error(s)"
        )


def check_scenario(
    scenario: FrameScenario,
    *,
    work_dir: Path,
    tolerance: Optional[float] = None,
    pixel_delta: Optional[int] = None,
    write_diffs: bool = False,
    render_fn: Optional[RenderFn] = None,
) -> list[FrameResult]:
    """Render ``scenario``'s frames into ``work_dir`` and diff each vs its baseline.

    Returns one :class:`FrameResult` per frame:

    * ``no_baseline`` — no committed baseline yet (honest skip, never a regression);
    * ``ok`` — diff within tolerance;
    * ``regression`` — diff above tolerance (a ``diff_path`` heatmap when
      ``write_diffs``);
    * ``error`` — the render itself failed (reported once for the scenario).

    ``render_fn`` defaults to the real Node renderer; tests inject a fake.
    """
    work_dir = Path(work_dir)
    tol = _max_diff_ratio() if tolerance is None else float(tolerance)
    renderer = render_fn or render_scenario_frames

    try:
        rendered = renderer(scenario, work_dir / scenario.name)
    except Exception as exc:  # render failure → one honest error row
        return [
            FrameResult(
                scenario=scenario.name,
                frame=-1,
                status="error",
                message=str(exc)[:400],
            )
        ]

    rendered_by_frame = {int(f): Path(p) for f, p in rendered}
    results: list[FrameResult] = []
    for frame in scenario.frames:
        cur = rendered_by_frame.get(int(frame))
        base = baseline_path(scenario.name, frame)
        if cur is None or not cur.exists():
            results.append(
                FrameResult(
                    scenario=scenario.name,
                    frame=frame,
                    status="error",
                    current_path=cur,
                    baseline_path=base,
                    message=f"frame {frame} was not rendered",
                )
            )
            continue
        if not base.exists():
            results.append(
                FrameResult(
                    scenario=scenario.name,
                    frame=frame,
                    status="no_baseline",
                    current_path=cur,
                    baseline_path=base,
                    message=(
                        f"no committed baseline at {base} — capture & human-review "
                        "one to enable regression diffing"
                    ),
                )
            )
            continue
        try:
            ratio = diff_ratio(cur, base, pixel_delta=pixel_delta)
        except Exception as exc:
            results.append(
                FrameResult(
                    scenario=scenario.name,
                    frame=frame,
                    status="error",
                    current_path=cur,
                    baseline_path=base,
                    message=str(exc)[:400],
                )
            )
            continue
        if ratio > tol:
            diff_path = None
            if write_diffs:
                diff_path = write_diff_image(
                    cur, base, work_dir / scenario.name / f"diff_{frame_filename(frame)}"
                )
            results.append(
                FrameResult(
                    scenario=scenario.name,
                    frame=frame,
                    status="regression",
                    ratio=ratio,
                    tolerance=tol,
                    current_path=cur,
                    baseline_path=base,
                    diff_path=diff_path,
                    message=f"{ratio:.2%} of pixels changed (> {tol:.0%} tolerance)",
                )
            )
        else:
            results.append(
                FrameResult(
                    scenario=scenario.name,
                    frame=frame,
                    status="ok",
                    ratio=ratio,
                    tolerance=tol,
                    current_path=cur,
                    baseline_path=base,
                )
            )
    return results


def run_regression(
    names: Optional[list[str]] = None,
    *,
    work_dir: Optional[Path] = None,
    tolerance: Optional[float] = None,
    pixel_delta: Optional[int] = None,
    write_diffs: bool = False,
    render_fn: Optional[RenderFn] = None,
) -> RegressionReport:
    """Run the harness across the (selected) scenarios and aggregate the report.

    When ``work_dir`` is None, a TemporaryDirectory is used and cleaned up
    (diff heatmaps are then transient — pass an explicit ``work_dir`` to keep
    them).
    """
    import tempfile

    report = RegressionReport()
    scenarios = resolve_scenarios(names)

    def _run(base: Path) -> None:
        for scenario in scenarios:
            report.results.extend(
                check_scenario(
                    scenario,
                    work_dir=base,
                    tolerance=tolerance,
                    pixel_delta=pixel_delta,
                    write_diffs=write_diffs,
                    render_fn=render_fn,
                )
            )

    if work_dir is None:
        with tempfile.TemporaryDirectory(prefix="motionvr-check-") as tmp:
            _run(Path(tmp))
    else:
        _run(Path(work_dir))
    return report


__all__ = [
    "FrameScenario",
    "FrameResult",
    "RegressionReport",
    "MotionRegressionError",
    "SCENARIOS",
    "FPS",
    "FRAME_SCRIPT",
    "scenario_by_name",
    "resolve_scenarios",
    "repo_root",
    "baseline_dir",
    "baseline_path",
    "frame_filename",
    "diff_ratio",
    "write_diff_image",
    "render_scenario_frames",
    "capture_baselines",
    "check_scenario",
    "run_regression",
    "node_available",
    "remotion_installed",
]
