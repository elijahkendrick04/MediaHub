"""Regenerate the Phase 1.6 Stage I golden-master snapshots.

Usage:
    python scripts/update_theme_snapshots.py

Idempotent: running twice produces no diff. Prints a per-seed
summary; lines marked ``CHANGED`` carry a key-by-key delta from
the previous snapshot.

The script is the single source of truth for snapshot content —
the test loads + compares only; the script writes.

References:
    - docs/stage_i_test_coverage_plan.md §4
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def main() -> int:
    # Late imports so the script's argparse-style help doesn't
    # pay the engine boot cost when the user just runs --help.
    import tempfile, os
    os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="snap-"))

    from mediahub.theming import derive_theme
    from tests.theming.seeds_catalogue import SEEDS_CATALOGUE
    from tests.theming._snapshot_helpers import (
        build_snapshot, load_snapshot, write_snapshot, diff_snapshots,
        SNAPSHOTS_DIR,
    )

    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Regenerating {len(SEEDS_CATALOGUE)} snapshots → {SNAPSHOTS_DIR}")

    n_unchanged = 0
    n_changed = 0
    n_created = 0

    for seed_hex, label, category in SEEDS_CATALOGUE:
        theme = derive_theme(seed_hex)
        actual = build_snapshot(theme.to_json(), label=label)
        previous = load_snapshot(seed_hex)
        write_snapshot(seed_hex, actual)

        if previous is None:
            n_created += 1
            print(f"  + {seed_hex} — {label} (CREATED, was_repaired={actual['was_repaired']})")
        elif previous == actual:
            n_unchanged += 1
            # Silent on unchanged to keep output skimmable.
        else:
            n_changed += 1
            print(f"  ! {seed_hex} — {label} (CHANGED)")
            for diff_line in diff_snapshots(previous, actual)[:8]:
                print(diff_line)
            extra = max(0, len(diff_snapshots(previous, actual)) - 8)
            if extra:
                print(f"    ... and {extra} more diffs (see snapshot file)")

    print()
    print(f"Done — {n_unchanged} unchanged, {n_changed} changed, {n_created} created.")
    print(f"Review with: git diff {SNAPSHOTS_DIR.relative_to(_ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
