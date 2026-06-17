#!/usr/bin/env python3
"""Operator/CI front-end for the motion visual-regression harness (roadmap R1.27).

The harness itself lives in ``mediahub.visual.motion_regression``; this is the
hand-run / CI command around it. It renders the canonical reference frames from
the real StoryCard / MeetReel compositions and pixel-diffs them against the
committed baselines under ``tests/baseline/motion_frames/``.

Subcommands
-----------
  list                List the reference scenarios and the frames each captures.

  capture             Render the scenarios and (over)write the committed
                      baselines. The ONLY way baselines are written — review the
                      resulting PNGs before committing them.

  check               Render the scenarios and diff every frame against its
                      baseline. Exit 0 when all frames are within tolerance
                      (frames with no baseline are an honest skip, not a
                      failure); exit 1 on any regression or render error.

Examples
--------
  python scripts/motion_vr.py list
  python scripts/motion_vr.py capture                 # refresh all baselines
  python scripts/motion_vr.py capture --scenario story_pb
  python scripts/motion_vr.py check --write-diffs --out data/motion_vr

Requires Node 18+ and an ``npm install`` inside ``src/mediahub/remotion`` (the
same toolchain ``render.js`` needs). Tolerances are tunable via
MEDIAHUB_MOTION_VR_MAX_DIFF / MEDIAHUB_MOTION_VR_PIXEL_DELTA.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure we can import mediahub when running this script directly.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from mediahub.visual import motion_regression as mvr  # noqa: E402


def _cmd_list(_args: argparse.Namespace) -> int:
    print("Motion visual-regression reference scenarios:\n")
    for s in mvr.SCENARIOS:
        w, h = s.size
        print(f"  {s.name}")
        print(f"    composition : {s.composition_id}")
        print(f"    format      : {s.format_name} ({w}x{h})")
        print(f"    duration    : {s.duration_sec}s ({s.duration_in_frames} frames @ {mvr.FPS}fps)")
        print(f"    frames      : {', '.join(str(f) for f in s.frames)}")
        print(f"    baseline    : {mvr.baseline_dir() / s.name}")
        print()
    return 0


def _preflight() -> int:
    if not mvr.node_available():
        print("ERROR: Node is not installed (need Node 18+ to render frames).", file=sys.stderr)
        return 2
    if not mvr.remotion_installed():
        print(
            "ERROR: Remotion deps not installed — run `npm install` in src/mediahub/remotion.",
            file=sys.stderr,
        )
        return 2
    return 0


def _cmd_capture(args: argparse.Namespace) -> int:
    rc = _preflight()
    if rc:
        return rc
    names = [args.scenario] if args.scenario else None
    print(f"Capturing baselines into {mvr.baseline_dir()} ...")
    try:
        written = mvr.capture_baselines(names)
    except Exception as exc:  # noqa: BLE001 — surface the cause to the operator
        print(f"ERROR: capture failed: {exc}", file=sys.stderr)
        return 1
    for p in written:
        print(f"  wrote {p}")
    print(f"\nDone — {len(written)} baseline frame(s) written. Review, then commit.")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    rc = _preflight()
    if rc:
        return rc
    names = [args.scenario] if args.scenario else None
    work_dir = Path(args.out) if args.out else None
    print("Running motion visual-regression check ...\n")
    report = mvr.run_regression(names, work_dir=work_dir, write_diffs=args.write_diffs)

    for r in report.results:
        if r.status == "ok":
            print(f"  OK         {r.scenario} frame {r.frame}  ({r.ratio:.3%} changed)")
        elif r.status == "regression":
            print(f"  REGRESSION {r.scenario} frame {r.frame}  {r.message}")
            if r.diff_path:
                print(f"             diff: {r.diff_path}")
        elif r.status == "no_baseline":
            print(f"  SKIP       {r.scenario} frame {r.frame}  (no baseline)")
        else:
            print(f"  ERROR      {r.scenario} frame {r.frame}  {r.message}")

    print(f"\n{report.summary()}")
    if report.skipped and not report.regressions and not report.errors:
        print(
            "\nNo baselines committed for some frames — run "
            "`python scripts/motion_vr.py capture` to create them."
        )
    return 0 if report.passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="motion_vr",
        description="Frame-by-frame motion visual-regression harness (R1.27).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list reference scenarios and frames")
    p_list.set_defaults(func=_cmd_list)

    p_cap = sub.add_parser("capture", help="render and (over)write committed baselines")
    p_cap.add_argument("--scenario", help="only this scenario (default: all)")
    p_cap.set_defaults(func=_cmd_capture)

    p_chk = sub.add_parser("check", help="render and diff frames against baselines")
    p_chk.add_argument("--scenario", help="only this scenario (default: all)")
    p_chk.add_argument("--write-diffs", action="store_true", help="write diff heatmaps for regressions")
    p_chk.add_argument("--out", help="keep rendered frames / diffs in this dir (default: temp)")
    p_chk.set_defaults(func=_cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
