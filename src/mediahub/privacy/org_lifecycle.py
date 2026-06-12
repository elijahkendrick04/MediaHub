"""Whole-organisation deletion and takeout (PC.13, UK GDPR Arts. 15/17/20).

The DPA §9 promises a club can "delete any run, athlete or its whole
workspace through the product at any time" and take a copy first. This
module is both halves:

- :func:`delete_org` — cascade an organisation out of every store under
  ``DATA_DIR``: its runs (through the web layer's run-deletion cascade, so
  PB caches / caption memory / posting-log excerpts / motion cache are
  reached per run), media-library assets, uploaded logos, sponsor exposure
  ledger, consent + athletes registries, club records, corrections,
  posting-log rows, approval telemetry, live watches, magic-link versions,
  caption memory, the autonomy audit ledger, memberships, and finally the
  profile JSON itself (which structurally revokes the public wall token).
- :func:`org_export_zip` — one ZIP with everything the workspace holds:
  the profile, runs JSON + workflow states, media assets, captions-bearing
  packs, the consent registry CSV, athletes, sponsors + exposure ledger,
  posting log, club records, corrections and the autonomy audit log. One
  mechanism serves both SARs and portability.

Deliberately NOT deleted, recorded in the report so the UI can say so:

- org-scoped legal-acceptance rows (contract evidence; they erase with the
  accepting *account*, mirroring ``erase_account``);
- the Stripe customer/subscription (handled per the DPA — billing records
  are retained by Stripe under its legal obligations).

Like the rest of this package: counts, not booleans, and one failed store
never aborts the rest.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import shutil
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "data"))


def _db_path() -> Path:
    return _data_dir() / "data.db"


def _connect() -> Optional[sqlite3.Connection]:
    p = _db_path()
    if not p.exists():
        return None
    conn = sqlite3.connect(str(p), timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _org_run_ids(profile_id: str) -> list[str]:
    conn = _connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT id FROM runs WHERE profile_id = ?", (profile_id,)
        ).fetchall()
        return [r["id"] for r in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()
            is not None
        )
    except sqlite3.Error:
        return False


# Every data.db table that keys rows by profile_id. live_watch_swims and
# magic_link_versions hang off watches/runs and are handled separately.
_ORG_TABLES = (
    "posting_attempts",
    "approval_events",
    "content_corrections",
    "club_records",
    "athlete_consent",
    "consent_settings",
    "athlete_swims",
    "athlete_aliases",
    "athletes",
    "live_watches",
)


def _media_store():
    from mediahub.media_library.store import get_store

    return get_store()


def _safe_org(org_id: str) -> str:
    # Mirrors workflow.autonomy's filename sanitisation for the audit ledger.
    import re

    return re.sub(r"[^a-zA-Z0-9._-]+", "_", (org_id or "").strip()) or "_"


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


def delete_org(
    profile_id: str,
    *,
    delete_run: Callable[[str], bool],
    media_store=None,
) -> dict:
    """Erase one organisation from everything this deployment holds.

    ``delete_run`` is the web layer's ``_delete_run`` (DB row + files +
    per-run cascade). Returns per-store counts.
    """
    pid = (profile_id or "").strip()
    report = {
        "profile_id": pid,
        "runs_deleted": 0,
        "media_assets_deleted": 0,
        "db_rows_deleted": {},
        "magic_link_versions_deleted": 0,
        "memory_rows_deleted": 0,
        "sponsor_ledger_deleted": False,
        "audit_log_deleted": False,
        "logos_deleted": 0,
        "memberships_deleted": 0,
        "profile_deleted": False,
        "retained": [
            "org-scoped legal acceptance records (contract evidence; erased with the accepting account)",
            "Stripe customer and billing records (handled per the DPA)",
        ],
    }
    if not pid:
        return report

    # 1. Athlete names BEFORE the registry rows go — the warm PB/research
    # caches are keyed by name and hold club data.
    athlete_names: list[str] = []
    conn = _connect()
    if conn is not None:
        try:
            if _table_exists(conn, "athletes"):
                athlete_names = [
                    r["canonical_name"]
                    for r in conn.execute(
                        "SELECT canonical_name FROM athletes WHERE profile_id = ?", (pid,)
                    ).fetchall()
                ]
        except sqlite3.Error:
            pass
        finally:
            conn.close()

    # 2. Runs, through the full per-run cascade.
    run_ids = _org_run_ids(pid)
    for run_id in run_ids:
        try:
            delete_run(run_id)
            report["runs_deleted"] += 1
        except Exception:
            log.warning("org delete: run %s failed", run_id, exc_info=True)

    # 3. Media library: rows + file blobs, then the org's upload folder.
    try:
        store = media_store if media_store is not None else _media_store()
        for asset in store.list(profile_id=pid):
            try:
                if store.delete(asset.id):
                    report["media_assets_deleted"] += 1
            except Exception:
                log.warning("org delete: media asset %s failed", asset.id, exc_info=True)
        org_uploads = Path(store.uploads_dir) / pid
        if org_uploads.is_dir():
            shutil.rmtree(org_uploads, ignore_errors=True)
    except Exception:
        log.warning("org delete: media library sweep failed", exc_info=True)

    # 4. Uploaded brand logos (DATA_DIR/club_logos/<safe>).
    try:
        from mediahub.brand.logos import logos_dir

        d = logos_dir(pid)
        report["logos_deleted"] = sum(1 for f in d.glob("*") if f.is_file())
        shutil.rmtree(d, ignore_errors=True)
    except Exception:
        log.warning("org delete: logo sweep failed", exc_info=True)

    # 5. Org-keyed DB rows (consent, athletes, records, corrections, logs…).
    conn = _connect()
    if conn is not None:
        try:
            if _table_exists(conn, "live_watches") and _table_exists(conn, "live_watch_swims"):
                conn.execute(
                    "DELETE FROM live_watch_swims WHERE watch_id IN "
                    "(SELECT id FROM live_watches WHERE profile_id = ?)",
                    (pid,),
                )
            for table in _ORG_TABLES:
                if not _table_exists(conn, table):
                    continue
                cur = conn.execute(f"DELETE FROM {table} WHERE profile_id = ?", (pid,))
                if cur.rowcount and cur.rowcount > 0:
                    report["db_rows_deleted"][table] = cur.rowcount
            if run_ids and _table_exists(conn, "magic_link_versions"):
                ph = ",".join("?" for _ in run_ids)
                cur = conn.execute(
                    f"DELETE FROM magic_link_versions WHERE run_id IN ({ph})", run_ids
                )
                report["magic_link_versions_deleted"] = max(cur.rowcount or 0, 0)
            conn.commit()
        except sqlite3.Error:
            log.warning("org delete: DB sweep failed", exc_info=True)
        finally:
            conn.close()

    # 6. Warm PB + research caches for each of the org's athletes.
    try:
        from mediahub.privacy.erasure import _purge_pb_caches, _purge_research_caches

        for name in athlete_names:
            _purge_pb_caches(name)
            _purge_research_caches(name)
    except Exception:
        log.warning("org delete: PB/research cache sweep failed", exc_info=True)

    # 7. Caption memory (whole tenant).
    try:
        from mediahub.memory import store as memory_store

        report["memory_rows_deleted"] = memory_store.delete_tenant(tenant_id=pid)
    except Exception:
        log.warning("org delete: memory sweep failed", exc_info=True)

    # 8. Sponsor exposure ledger + autonomy audit ledger (org-keyed files).
    try:
        exposure = _data_dir() / "sponsors" / f"{pid}__exposure.jsonl"
        if exposure.exists():
            exposure.unlink()
            report["sponsor_ledger_deleted"] = True
    except OSError:
        pass
    try:
        audit = _data_dir() / "autonomy_audit" / f"{_safe_org(pid)}.jsonl"
        if audit.exists():
            audit.unlink()
            report["audit_log_deleted"] = True
    except OSError:
        pass

    # 9. Memberships (compacting rewrite), then the profile JSON itself —
    # deleting the profile clears the public wall token structurally.
    try:
        from mediahub.web.tenancy import MembershipStore

        report["memberships_deleted"] = MembershipStore().erase_profile(pid)
    except Exception:
        log.warning("org delete: membership sweep failed", exc_info=True)
    try:
        from mediahub.web.club_profile import _profiles_dir

        pj = _profiles_dir() / f"{pid}.json"
        if pj.exists():
            pj.unlink()
            report["profile_deleted"] = True
    except Exception:
        log.warning("org delete: profile removal failed", exc_info=True)

    return report


# ---------------------------------------------------------------------------
# Takeout
# ---------------------------------------------------------------------------


def _rows_as_dicts(conn: sqlite3.Connection, sql: str, args: tuple) -> list[dict]:
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    except sqlite3.Error:
        return []


def org_export_zip(profile_id: str, out_path: Path, *, media_store=None) -> dict:
    """Write the organisation takeout ZIP to ``out_path``.

    Contents (everything tenant-scoped, nothing cross-tenant):

    - ``profile.json`` — the ClubProfile (brand kit, sponsors registry,
      wall settings, excluded cards)
    - ``runs/<id>.json`` + ``runs/<id>__workflow.json`` — parsed results,
      cards, captions, and per-card approval states
    - ``media/<file>`` + ``media_assets.json`` — library blobs + metadata
    - ``consent_registry.csv`` + ``athletes.json`` — the W.2 registry and
      the athlete register it keys
    - ``sponsor_exposure.jsonl``, ``posting_log.json``,
      ``club_records.json``, ``corrections.json``, ``audit_log.jsonl``,
      ``memberships.json``
    - ``README.txt`` — what's inside and what is held elsewhere (Stripe)

    Returns a manifest dict with per-section counts.
    """
    pid = (profile_id or "").strip()
    manifest: dict = {
        "profile_id": pid,
        "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "runs": 0,
        "media_assets": 0,
        "athletes": 0,
        "consent_rows": 0,
        "posting_rows": 0,
        "club_records": 0,
        "corrections": 0,
        "audit_lines": 0,
        "memberships": 0,
    }
    if not pid:
        raise ValueError("profile_id required")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data_dir = _data_dir()
    runs_dir = data_dir / "runs_v4"

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Profile JSON (the on-disk record, not a re-serialisation).
        try:
            from mediahub.web.club_profile import _profiles_dir

            pj = _profiles_dir() / f"{pid}.json"
            if pj.exists():
                zf.writestr("profile.json", pj.read_text(encoding="utf-8"))
        except Exception:
            log.warning("org export: profile read failed", exc_info=True)

        # Runs + workflow sidecars (tenant-checked via the DB).
        for run_id in _org_run_ids(pid):
            rj = runs_dir / f"{run_id}.json"
            if rj.exists():
                try:
                    zf.write(rj, f"runs/{run_id}.json")
                    manifest["runs"] += 1
                except OSError:
                    continue
            wf = runs_dir / f"{run_id}__workflow.json"
            if wf.exists():
                try:
                    zf.write(wf, f"runs/{run_id}__workflow.json")
                except OSError:
                    pass

        # Media library: metadata + blobs.
        try:
            store = media_store if media_store is not None else _media_store()
            assets = store.list(profile_id=pid)
            zf.writestr(
                "media_assets.json",
                json.dumps([a.to_dict() for a in assets], indent=2, default=str),
            )
            for a in assets:
                manifest["media_assets"] += 1
                for p, prefix in ((a.path, "media"), (a.cutout_path, "media/cutouts")):
                    if p and Path(p).exists():
                        try:
                            zf.write(p, f"{prefix}/{Path(p).name}")
                        except OSError:
                            pass
        except Exception:
            log.warning("org export: media library failed", exc_info=True)

        # Consent registry + athletes.
        try:
            from mediahub.safeguarding.consent import export_csv, list_consent

            csv_text = export_csv(pid)
            zf.writestr("consent_registry.csv", csv_text)
            manifest["consent_rows"] = len(list_consent(pid))
        except Exception:
            log.warning("org export: consent export failed", exc_info=True)
        try:
            from mediahub.athletes.registry import list_athletes

            athletes = [
                {
                    "athlete_id": a.athlete_id,
                    "canonical_name": a.canonical_name,
                }
                for a in list_athletes(pid)
            ]
            manifest["athletes"] = len(athletes)
            zf.writestr("athletes.json", json.dumps(athletes, indent=2))
        except Exception:
            log.warning("org export: athletes export failed", exc_info=True)

        # Org-keyed DB tables.
        conn = _connect()
        if conn is not None:
            try:
                posting = _rows_as_dicts(
                    conn,
                    "SELECT * FROM posting_attempts WHERE profile_id = ? ORDER BY id",
                    (pid,),
                ) if _table_exists(conn, "posting_attempts") else []
                manifest["posting_rows"] = len(posting)
                zf.writestr("posting_log.json", json.dumps(posting, indent=2, default=str))

                records = _rows_as_dicts(
                    conn, "SELECT * FROM club_records WHERE profile_id = ?", (pid,)
                ) if _table_exists(conn, "club_records") else []
                manifest["club_records"] = len(records)
                zf.writestr("club_records.json", json.dumps(records, indent=2, default=str))

                corrections = _rows_as_dicts(
                    conn,
                    "SELECT * FROM content_corrections WHERE profile_id = ? ORDER BY id",
                    (pid,),
                ) if _table_exists(conn, "content_corrections") else []
                manifest["corrections"] = len(corrections)
                zf.writestr("corrections.json", json.dumps(corrections, indent=2, default=str))
            finally:
                conn.close()

        # Sponsor exposure ledger + autonomy audit ledger (verbatim).
        exposure = data_dir / "sponsors" / f"{pid}__exposure.jsonl"
        if exposure.exists():
            try:
                zf.writestr("sponsor_exposure.jsonl", exposure.read_text(encoding="utf-8"))
            except OSError:
                pass
        audit = data_dir / "autonomy_audit" / f"{_safe_org(pid)}.jsonl"
        if audit.exists():
            try:
                text = audit.read_text(encoding="utf-8")
                manifest["audit_lines"] = sum(1 for ln in text.splitlines() if ln.strip())
                zf.writestr("audit_log.jsonl", text)
            except OSError:
                pass

        # Memberships (who can sign in to this workspace).
        try:
            from mediahub.web.tenancy import MembershipStore

            members = [
                m.to_record() for m in MembershipStore().list_for_profile(pid, include_removed=True)
            ]
            manifest["memberships"] = len(members)
            zf.writestr("memberships.json", json.dumps(members, indent=2))
        except Exception:
            log.warning("org export: membership export failed", exc_info=True)

        readme = io.StringIO()
        readme.write(
            f"MediaHub organisation takeout — {pid}\n"
            f"Exported {manifest['exported_at']}\n\n"
            "Contents: profile.json (brand kit, sponsors, wall settings), runs/ "
            "(parsed results, cards, captions + per-card approval states), media/ "
            "+ media_assets.json, consent_registry.csv + athletes.json, "
            "sponsor_exposure.jsonl, posting_log.json, club_records.json, "
            "corrections.json, audit_log.jsonl, memberships.json.\n\n"
            "Not included: billing records (held by Stripe — accessible from "
            "Billing → Manage billing), and other members' account data.\n"
        )
        zf.writestr("README.txt", readme.getvalue())
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    return manifest


__all__ = ["delete_org", "org_export_zip"]
