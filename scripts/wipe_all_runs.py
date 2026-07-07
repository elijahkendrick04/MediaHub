#!/usr/bin/env python3
"""Operator maintenance: permanently delete ALL run data across EVERY organisation.

This is the site-wide, all-tenant version of the per-org "Clear all runs"
privacy action. It is a **destructive, irreversible** wipe intended to be run
by the operator against a real deployment (e.g. a Render shell where
``DATA_DIR`` points at the persistent disk). It deletes run data only — it does
**not** touch club/org profiles, brand kits, or the media library.

What it removes (for every run, every org), reusing the app's own cascade:
  * the run record (``runs`` DB rows + ``card_reactions``),
  * the run JSON + its sidecar dir (visuals, motion, briefs, caption history),
    the ``<id>__workflow.json`` approvals file, and ``turn_into_packs/<id>``,
  * the per-run erasure cascade (``privacy.run_deletion_cascade``: per-run PB
    cache, caption-memory rows, posting-log excerpts, motion cache),
  * the raw uploaded meet files under ``UPLOADS_DIR`` (unless ``--keep-uploads``),
  * ALL semantic caption memory across every tenant (``memory.store.clear``),
  * every re-derivable cache, site-wide (``privacy.cache_purge.purge_all_caches``),
  * optionally the free-text / stub content packs ("drafts") with ``--include-packs``.

It deliberately does NOT delete: organisations/club profiles, brand kits, the
media library (uploaded club photos/videos), sport profiles, or any other
non-run configuration.

SAFETY
------
* **Dry-run by default.** Without ``--yes`` it only reports what it *would*
  delete and removes nothing.
* It refuses to run unless ``DATA_DIR`` is set to a real data directory (never
  the source tree), so it can't nuke dev fixtures by accident.
* ``DATA_DIR`` (and optional ``RUNS_DIR`` / ``UPLOADS_DIR``) are read from the
  environment exactly as the web app reads them, so on the deployment it
  operates on the same disk the app serves from.

USAGE
-----
    # See what would be deleted (safe, changes nothing):
    DATA_DIR=/var/data python scripts/wipe_all_runs.py

    # Actually delete every run for every org on this deployment:
    DATA_DIR=/var/data python scripts/wipe_all_runs.py --yes

    # Also drop the free-text/stub content packs (drafts):
    DATA_DIR=/var/data python scripts/wipe_all_runs.py --yes --include-packs

Ideally stop the web process (or run during a maintenance window) first, so an
in-flight worker can't re-persist a run mid-wipe.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from pathlib import Path

# Ensure the mediahub package is importable when run directly from the repo.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))


def _resolve_paths() -> tuple[Path, Path, Path, Path]:
    """(DATA_DIR, RUNS_DIR, UPLOADS_DIR, DB_PATH) derived exactly like web.py."""
    raw = os.environ.get("DATA_DIR")
    if not raw:
        sys.exit(
            "Refusing to run: DATA_DIR is not set. Point it at the deployment's "
            "persistent data disk (e.g. DATA_DIR=/var/data) and re-run."
        )
    data_dir = Path(raw).resolve()
    # Guard: never operate on the source tree (web.py falls back to the repo
    # root when DATA_DIR is unset; a fat-fingered run must not delete fixtures).
    if data_dir == _REPO_ROOT or data_dir == (_REPO_ROOT / "src").resolve():
        sys.exit(
            f"Refusing to run: DATA_DIR ({data_dir}) resolves to the source tree. "
            "Set it to the deployment's data disk."
        )
    runs_dir = Path(os.environ.get("RUNS_DIR", str(data_dir / "runs_v4")))
    uploads_dir = Path(os.environ.get("UPLOADS_DIR", str(data_dir / "uploads_v4")))
    db_path = data_dir / "data.db"
    return data_dir, runs_dir, uploads_dir, db_path


def _all_run_ids(db_path: Path, runs_dir: Path) -> dict[str, str]:
    """Every run id → its owning profile_id, from the DB and the runs dir.

    Union of the ``runs`` table (authoritative, all orgs, all statuses) and any
    ``<id>.json`` on disk not in the DB (orphans), so nothing is left behind.
    """
    ids: dict[str, str] = {}
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            for row in conn.execute("SELECT id, profile_id FROM runs"):
                ids[str(row["id"])] = str(row["profile_id"] or "")
            conn.close()
        except sqlite3.Error as exc:
            print(f"  ! could not read runs table: {exc}", file=sys.stderr)
    if runs_dir.is_dir():
        for p in runs_dir.glob("*.json"):
            rid = p.stem
            if rid.endswith("__workflow"):
                continue
            ids.setdefault(rid, "")
    return ids


def _owner_profile_id(run_id: str, runs_dir: Path, fallback: str) -> str:
    """Best-effort profile_id for the erasure cascade (DB value, else the JSON)."""
    if fallback:
        return fallback
    p = runs_dir / f"{run_id}.json"
    try:
        import json

        data = json.loads(p.read_text(encoding="utf-8"))
        return str(data.get("profile_id") or "")
    except Exception:  # noqa: BLE001
        return ""


def _delete_run_files(run_id: str, runs_dir: Path, data_dir: Path) -> None:
    """Remove a run's files exactly like web._delete_run (minus the DB rows)."""
    (runs_dir / f"{run_id}.json").unlink(missing_ok=True)
    (runs_dir / f"{run_id}__workflow.json").unlink(missing_ok=True)
    shutil.rmtree(runs_dir / run_id, ignore_errors=True)
    shutil.rmtree(data_dir / "turn_into_packs" / run_id, ignore_errors=True)


def _dir_stats(path: Path) -> tuple[int, int]:
    """(file_count, bytes) under path, best-effort."""
    files = 0
    total = 0
    if not path.exists():
        return 0, 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                files += 1
                total += p.stat().st_size
        except OSError:
            pass
    return files, total


def _writable(path: Path) -> bool:
    """True iff we can create + remove a file inside ``path`` (dir made if absent)."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".wipe_write_test"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _preflight_issues(data_dir: Path, runs_dir: Path, run_ids: dict) -> list[str]:
    """Blocking problems that mean the wipe would silently under-delete.

    The classic footgun is a wrong ``DATA_DIR`` (e.g. a placeholder path): the
    run files under ``RUNS_DIR`` get deleted, but the DB rows, caches and memory
    under ``DATA_DIR`` are unreachable — a half-wipe. Catch that up front.
    """
    issues: list[str] = []
    if not _writable(data_dir):
        issues.append(
            f"DATA_DIR ({data_dir}) is not writable — the DB rows, semantic "
            f"memory and caches under it could not be cleared."
        )
    if not (data_dir / "data.db").exists():
        issues.append(
            f"No data.db at {data_dir / 'data.db'} — DATA_DIR is probably wrong. "
            f"Use the value the app runs with (see render.yaml's DATA_DIR)."
            + (
                f" (Meanwhile {len(run_ids)} run(s) were found via RUNS_DIR "
                f"{runs_dir} — deleting their files without clearing the DB "
                f"would leave the app listing dead runs.)"
                if run_ids
                else ""
            )
        )
    if not _writable(runs_dir):
        issues.append(f"RUNS_DIR ({runs_dir}) is not writable — run files can't be removed.")
    return issues


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Delete ALL run data across every org.")
    ap.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete. Without this flag the script is a dry run.",
    )
    ap.add_argument(
        "--keep-uploads",
        action="store_true",
        help="Leave the raw uploaded meet files under UPLOADS_DIR in place.",
    )
    ap.add_argument(
        "--keep-memory",
        action="store_true",
        help="Do not clear the site-wide semantic caption memory.",
    )
    ap.add_argument(
        "--keep-caches",
        action="store_true",
        help="Do not purge the re-derivable caches (renders, lookups).",
    )
    ap.add_argument(
        "--include-packs",
        action="store_true",
        help="Also delete free-text / stub content packs (drafts).",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Proceed even if the pre-flight finds problems (wrong/unwritable DATA_DIR).",
    )
    args = ap.parse_args(argv)

    data_dir, runs_dir, uploads_dir, db_path = _resolve_paths()

    run_ids = _all_run_ids(db_path, runs_dir)
    up_files, up_bytes = _dir_stats(uploads_dir)
    packs_dir = data_dir / "stub_packs"
    pack_files, _ = _dir_stats(packs_dir)

    mode = "DELETE" if args.yes else "DRY RUN (nothing will be deleted)"
    print(f"wipe_all_runs — {mode}")
    print(f"  DATA_DIR    : {data_dir}")
    print(f"  RUNS_DIR    : {runs_dir}")
    print(f"  UPLOADS_DIR : {uploads_dir}")
    print(f"  runs found  : {len(run_ids)} (every org, every status)")
    if not args.keep_uploads:
        print(f"  uploads     : {up_files} file(s), {up_bytes / 1e6:.1f} MB")
    if args.include_packs:
        print(f"  packs/drafts: {pack_files} file(s)")
    print(f"  memory      : {'kept' if args.keep_memory else 'cleared (all tenants)'}")
    print(f"  caches      : {'kept' if args.keep_caches else 'purged (site-wide)'}")
    print()

    # Pre-flight: refuse a mis-pointed / unwritable DATA_DIR before deleting a
    # single file, so we never leave the app with dead run rows and orphaned
    # files (the exact half-wipe a placeholder DATA_DIR would cause).
    issues = _preflight_issues(data_dir, runs_dir, run_ids)
    if issues:
        print("Pre-flight found problem(s):")
        for msg in issues:
            print(f"  ! {msg}")
        print()
        if args.yes and not args.force:
            print(
                "Refusing to run: fix DATA_DIR / permissions and retry, or pass "
                "--force to override (you'll get a half-wipe if these aren't real)."
            )
            return 2
        if not args.yes:
            print("(These would block a real --yes run unless --force is given.)")

    if not args.yes:
        print("Dry run complete — re-run with --yes to permanently delete the above.")
        return 0 if not issues else 2

    # --- destructive from here ------------------------------------------------
    errors = 0
    try:
        from mediahub.privacy import run_deletion_cascade
    except Exception as exc:  # noqa: BLE001
        print(f"  ! could not import erasure cascade ({exc}); skipping per-run cascade")
        run_deletion_cascade = None  # type: ignore[assignment]
        errors += 1

    deleted = 0
    cascade_errors = 0
    for rid, pid in run_ids.items():
        owner = _owner_profile_id(rid, runs_dir, pid)
        if run_deletion_cascade is not None:
            try:
                run_deletion_cascade(rid, owner)
            except Exception as exc:  # noqa: BLE001
                cascade_errors += 1
                if cascade_errors <= 3:  # don't flood; the count is reported below
                    print(f"  ! cascade failed for {rid}: {exc}", file=sys.stderr)
        _delete_run_files(rid, runs_dir, data_dir)
        deleted += 1
    if cascade_errors:
        print(f"  ! erasure cascade failed for {cascade_errors}/{deleted} run(s)")
        errors += 1
    print(f"  removed {deleted} run(s) + sidecars")

    # DB rows: clear the run tables wholesale (catches any straggler rows).
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            for tbl in ("runs", "card_reactions"):
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except sqlite3.Error:
                    pass  # table may not exist on an older schema
            conn.commit()
            conn.close()
            print("  cleared runs / card_reactions tables")
        except sqlite3.Error as exc:
            print(f"  ! DB clear failed: {exc}", file=sys.stderr)
            errors += 1
    else:
        print(f"  ! no data.db at {db_path} — DB rows NOT cleared")
        errors += 1

    if not args.keep_uploads and uploads_dir.is_dir():
        for child in uploads_dir.iterdir():
            try:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
            except OSError:
                pass
        print(f"  cleared uploads ({up_files} file(s))")

    if args.include_packs and packs_dir.is_dir():
        shutil.rmtree(packs_dir, ignore_errors=True)
        print(f"  cleared content packs / drafts ({pack_files} file(s))")

    if not args.keep_memory:
        try:
            from mediahub.memory import store as memory_store

            memory_store.clear()
            print("  cleared semantic caption memory (all tenants)")
        except Exception as exc:  # noqa: BLE001
            print(f"  ! memory clear skipped: {exc}", file=sys.stderr)
            errors += 1

    if not args.keep_caches:
        try:
            from mediahub.privacy.cache_purge import purge_all_caches

            rep = purge_all_caches()
            print(
                f"  purged caches: {rep.get('files_deleted', 0)} file(s), "
                f"{rep.get('bytes_reclaimed', 0) / 1e6:.1f} MB"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ! cache purge skipped: {exc}", file=sys.stderr)
            errors += 1

    if errors:
        print(
            f"\nFinished with {errors} problem area(s) — some run data may REMAIN. "
            f"Check DATA_DIR ({data_dir}) and write permissions, then re-run."
        )
        return 1

    print("\nDone. All run data has been permanently deleted for every organisation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
