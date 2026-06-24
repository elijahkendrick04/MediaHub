#!/usr/bin/env python3
"""Operator tool — permanently delete EVERY run, across ALL organisations.

This is the deployment-level "wipe all previous runs" reset. It removes every
run MediaHub has stored — for all tenants — using the SAME deletion cascade the
in-app per-run Delete uses, so nothing is left orphaned:

  * the run JSON (runs_v4/<id>.json) and its sidecar dir (visuals, motion,
    briefs, caption history, the stored launch input, …)
  * the workflow / approvals sidecars and any "turn into" derivative packs
  * the runs + card_reactions rows in data.db
  * the per-run re-derivable stores (PB lookup cache, motion renders, caption
    memory, athlete-swim rows, reel review comments, collab metadata)

It then clears the site-wide re-derivable caches. Source data that is NOT a run
— club profiles, the media-library originals, brand kits — is left untouched.

IMPORTANT — run with the web service STOPPED for a clean wipe. A live worker
that finishes a run mid-wipe could re-create that run's DB row (its
``_persist_run`` does INSERT OR REPLACE). With the service down there is no such
race.

DATA_DIR must point at the deployment's data volume — the same environment the
app runs with. The script reads it and prints it so you can confirm the target
before any deletion happens.

Usage:
    python scripts/purge_all_runs.py            # prompts for confirmation
    python scripts/purge_all_runs.py --yes      # no prompt (scripted / CI)
    python scripts/purge_all_runs.py --dry-run  # count only; delete nothing
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Editable installs already expose ``mediahub``; add src/ defensively so the
# script also runs from a bare checkout.
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Permanently delete every run, for every organisation."
    )
    parser.add_argument(
        "--yes", action="store_true", help="skip the interactive confirmation prompt"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report counts only; delete nothing"
    )
    args = parser.parse_args()

    from mediahub.web import web as wm

    # Ensure the schema (and the additive migrations) exist before we read/delete.
    wm._init_db()
    data_dir = wm.DATA_DIR
    runs_dir = Path(wm.RUNS_DIR)

    conn = wm._db()
    rows = conn.execute("SELECT id FROM runs ORDER BY created_at").fetchall()
    conn.close()
    db_ids = [r["id"] for r in rows]

    # Defensive: also catch run JSONs left on disk with no matching DB row.
    disk_ids: set[str] = set()
    try:
        for p in runs_dir.glob("*.json"):
            # Skip the workflow/approvals sidecars (``<id>__workflow.json``).
            if "__" not in p.stem:
                disk_ids.add(p.stem)
    except OSError:
        pass
    extra = sorted(disk_ids - set(db_ids))

    print(f"DATA_DIR : {data_dir}")
    print(f"RUNS_DIR : {runs_dir}")
    print(f"Runs in database          : {len(db_ids)}")
    if extra:
        print(f"Orphaned run files on disk : {len(extra)}")

    all_ids = list(dict.fromkeys([*db_ids, *extra]))
    if not all_ids:
        print("Nothing to delete.")
        return 0

    if args.dry_run:
        print(f"[dry-run] would delete {len(all_ids)} runs and clear site-wide caches.")
        return 0

    if not args.yes:
        print()
        print(f"This permanently deletes ALL {len(all_ids)} runs for EVERY organisation.")
        print("It cannot be undone. The web service should be stopped first.")
        resp = input("Type 'DELETE ALL' to proceed: ").strip()
        if resp != "DELETE ALL":
            print("Aborted.")
            return 1

    deleted = 0
    for rid in all_ids:
        try:
            wm._delete_run(rid)
            deleted += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ! failed to delete {rid}: {exc}", file=sys.stderr)
    print(f"Deleted {deleted} runs.")

    try:
        from mediahub.privacy.cache_purge import purge_all_caches

        report = purge_all_caches()
        print(
            f"Cleared site-wide caches: {report.get('files_deleted', 0)} files, "
            f"{report.get('bytes_reclaimed', 0):,} bytes."
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  ! cache purge failed: {exc}", file=sys.stderr)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
