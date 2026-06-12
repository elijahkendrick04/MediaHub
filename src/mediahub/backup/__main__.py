"""CLI for the backup drill: ``python -m mediahub.backup create|restore``.

The restore half is the human-runnable version of the rehearsed drill in
``tests/test_backup_restore.py`` and the runbook
(docs/SUPPORT_INCIDENT_RUNBOOK.md §4).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import create_backup, restore_backup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mediahub.backup")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("create", help="write one backup archive now")

    p_restore = sub.add_parser("restore", help="rebuild a DATA_DIR from an archive")
    p_restore.add_argument("archive", type=Path)
    p_restore.add_argument(
        "--data-dir", type=Path, default=None, help="target (default: $DATA_DIR)"
    )
    p_restore.add_argument("--force", action="store_true", help="restore over a non-empty target")

    args = parser.parse_args(argv)
    if args.cmd == "create":
        report = create_backup()
        print(json.dumps({k: v for k, v in report.items() if k != "manifest"}, indent=2))
        return 0
    report = restore_backup(args.archive, args.data_dir, force=args.force)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
