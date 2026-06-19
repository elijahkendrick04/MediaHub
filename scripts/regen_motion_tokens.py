#!/usr/bin/env python3
"""Regenerate the motion-vocabulary artifacts from the Python source of truth.

The Remotion stack can't import Python, so it reads a **generated** copy of the
motion vocabulary (roadmap 1.5). This script writes that copy, plus the served
CSS stylesheet for the browser surfaces, from ``src/mediahub/motion/``:

* ``src/mediahub/remotion/src/motion/tokens.generated.ts`` — interpolation
  tokens the Remotion ``compile.ts`` helper samples.
* ``src/mediahub/web/static/theme/motion-vocabulary.css`` — the ``@keyframes``
  the web UI / HTML previews use.

Run from the repo root after editing any preset:

    python scripts/regen_motion_tokens.py

``--check`` writes nothing and exits non-zero if the committed files are stale —
the guard ``tests/test_motion_tokens_sync.py`` uses it, the same regen-plus-guard
discipline as the self-hosted fonts.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "mediahub"
TS_OUT = SRC / "remotion" / "src" / "motion" / "tokens.generated.ts"
CSS_OUT = SRC / "web" / "static" / "theme" / "motion-vocabulary.css"

# Importable without installing the package.
sys.path.insert(0, str(SRC.parent))


def _render() -> dict[Path, str]:
    from mediahub.motion import compile_css, compile_remotion

    return {
        TS_OUT: compile_remotion.export_ts(),
        CSS_OUT: compile_css.compile_all_css(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check", action="store_true",
        help="exit non-zero if a committed file is out of date (writes nothing)",
    )
    args = ap.parse_args()

    rendered = _render()
    stale: list[Path] = []
    for path, content in rendered.items():
        current = path.read_text() if path.exists() else None
        if current == content:
            continue
        if args.check:
            stale.append(path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        print(f"wrote {path.relative_to(ROOT)}")

    if args.check and stale:
        for p in stale:
            print(f"STALE: {p.relative_to(ROOT)} — run scripts/regen_motion_tokens.py", file=sys.stderr)
        return 1
    if not args.check:
        print("motion tokens up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
