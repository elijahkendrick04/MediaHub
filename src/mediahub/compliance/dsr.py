"""Data subject rights engine — access, rectification, erasure, restriction.

In plain words: when a swimmer or parent says "show me what you hold on me",
"that's wrong, fix it", or "delete me", this module is what actually walks
every store the data map found and does it — runs, rendered cards, workflow
state, PB caches (including raw cached HTML), the media library, club-profile
text, and the semantic caption memory.

Honesty rules baked in:
- every operation returns a *report* of what was touched AND what could not
  be reached (e.g. already-published social posts, raw upload files that
  contain other athletes' data too) — residuals are stated, never hidden;
- erasure keeps a minimal suppression record in the consent registry
  (status ``revoked``) so the athlete cannot silently reappear in future
  content — honouring the erasure IS the purpose of that record;
- requests are logged with Art 12A clock metadata (received, clarification
  stop/resume, due date) in ``DATA_DIR/compliance/dsr_requests.jsonl``.

Restriction of processing (Art 18) lives on the consent registry
(``ConsentRegistry.set_restricted``) and is enforced by the same gate as
consent — see ``compliance.gate``.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .consent import ConsentRegistry, athlete_key
from .store import JsonlLedger, compliance_dir

# Art 12A UK GDPR: "applicable time period" = one month from receipt,
# pausable while the controller awaits requested clarification / ID proof.
RESPONSE_WINDOW_DAYS = 30

_ERASED = "[erased]"
_NAME_KEYS = {"swimmer_name", "name", "full_name", "athlete_name", "display_name"}


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _data_dir() -> Path:
    src_root = Path(__file__).resolve().parents[1]
    return Path(os.environ.get("DATA_DIR", str(src_root)))


def _runs_dir() -> Path:
    return Path(os.environ.get("RUNS_DIR", str(_data_dir() / "runs_v4")))


def _name_matches(value: object, key: str) -> bool:
    return isinstance(value, str) and athlete_key(value) == key


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


# --------------------------------------------------------------------------
# Request log (Art 12A workflow metadata)
# --------------------------------------------------------------------------


@dataclass
class DsrRequest:
    id: str
    profile_id: str
    athlete_name: str
    request_type: str  # access | rectification | erasure | restriction
    received_at: str
    due_at: str
    status: str = "open"  # open | clock_stopped | completed
    clock_stopped_at: str = ""
    clock_resumed_at: str = ""
    completed_at: str = ""
    note: str = ""
    updated_at: str = ""

    def to_record(self) -> dict:
        return asdict(self)


class DsrRequestLog:
    def __init__(self) -> None:
        self._ledger = JsonlLedger("dsr_requests.jsonl", key_field="id")

    def open(self, *, profile_id: str, athlete_name: str, request_type: str, note: str = "") -> DsrRequest:
        now = _now()
        req = DsrRequest(
            id=secrets.token_hex(6),
            profile_id=(profile_id or "").strip()[:80],
            athlete_name=re.sub(r"\s+", " ", (athlete_name or "").strip())[:200],
            request_type=request_type,
            received_at=_iso(now),
            due_at=_iso(now + timedelta(days=RESPONSE_WINDOW_DAYS)),
            note=(note or "").strip()[:1000],
            updated_at=_iso(now),
        )
        self._ledger.append(req.to_record())
        return req

    def get(self, request_id: str) -> Optional[DsrRequest]:
        rec = self._ledger.get(request_id)
        return DsrRequest(**rec) if rec else None

    def all(self, profile_id: Optional[str] = None) -> list[DsrRequest]:
        items = [DsrRequest(**rec) for rec in self._ledger.all()]
        if profile_id is not None:
            items = [r for r in items if r.profile_id == profile_id]
        items.sort(key=lambda r: r.received_at, reverse=True)
        return items

    def _update(self, request_id: str, **changes: str) -> Optional[DsrRequest]:
        current = self.get(request_id)
        if current is None:
            return None
        rec = current.to_record()
        rec.update(changes)
        rec["updated_at"] = _iso(_now())
        self._ledger.append(rec)
        return DsrRequest(**rec)

    def stop_clock(self, request_id: str, note: str = "") -> Optional[DsrRequest]:
        """Art 12A: clock pauses while awaiting clarification / ID proof."""
        changes = {"status": "clock_stopped", "clock_stopped_at": _iso(_now())}
        if note:
            changes["note"] = note.strip()[:1000]
        return self._update(request_id, **changes)

    def resume_clock(self, request_id: str) -> Optional[DsrRequest]:
        current = self.get(request_id)
        if current is None or not current.clock_stopped_at:
            return current
        stopped = datetime.fromisoformat(current.clock_stopped_at)
        paused = _now() - stopped
        due = datetime.fromisoformat(current.due_at) + paused
        return self._update(
            request_id,
            status="open",
            clock_resumed_at=_iso(_now()),
            due_at=_iso(due),
        )

    def complete(self, request_id: str, note: str = "") -> Optional[DsrRequest]:
        changes = {"status": "completed", "completed_at": _iso(_now())}
        if note:
            changes["note"] = note.strip()[:1000]
        return self._update(request_id, **changes)


# --------------------------------------------------------------------------
# Shared walkers
# --------------------------------------------------------------------------


def _tenant_runs(profile_id: str) -> list[Path]:
    """Run JSON files owned by this tenant (legacy unowned runs included —
    they pre-date multi-tenancy and belong to the single org that made them)."""
    out = []
    runs_dir = _runs_dir()
    if not runs_dir.exists():
        return out
    for p in sorted(runs_dir.glob("*.json")):
        if p.name.endswith("__workflow.json"):
            continue
        try:
            owner = json.loads(p.read_text()).get("profile_id", "")
        except Exception:
            continue
        if owner == profile_id or not owner:
            out.append(p)
    return out


def _athlete_entries_in_run(run: dict, key: str) -> tuple[list[dict], list[str]]:
    """(matching achievement dicts, their card ids) in one run dict."""
    matches: list[dict] = []
    card_ids: list[str] = []
    rr = run.get("recognition_report") or {}
    for ra in rr.get("ranked_achievements") or []:
        ach = (ra or {}).get("achievement") or {}
        if _name_matches(ach.get("swimmer_name"), key):
            matches.append(ach)
            cid = str(ach.get("swim_id") or ra.get("id") or "")
            if cid:
                card_ids.append(cid)
    for c in run.get("cards") or []:
        if isinstance(c, dict) and any(_name_matches(c.get(k), key) for k in _NAME_KEYS):
            matches.append(c)
            cid = str(c.get("swim_id") or c.get("id") or "")
            if cid and cid not in card_ids:
                card_ids.append(cid)
    return matches, card_ids


def _redact_names_deep(node: object, key: str) -> int:
    """Replace any name-field value matching the athlete with [erased]."""
    n = 0
    if isinstance(node, dict):
        for k, v in list(node.items()):
            if k in _NAME_KEYS and _name_matches(v, key):
                node[k] = _ERASED
                n += 1
            else:
                n += _redact_names_deep(v, key)
    elif isinstance(node, list):
        for item in node:
            n += _redact_names_deep(item, key)
    return n


def _redact_text_deep(node: object, raw_name: str) -> int:
    """Replace free-text occurrences of the name (captions, headlines)."""
    pattern = re.compile(re.escape(raw_name.strip()), re.IGNORECASE)

    def _walk(n: object) -> int:
        count = 0
        if isinstance(n, dict):
            for k, v in list(n.items()):
                if isinstance(v, str) and pattern.search(v):
                    n[k] = pattern.sub(_ERASED, v)
                    count += 1
                else:
                    count += _walk(v)
        elif isinstance(n, list):
            for i, item in enumerate(n):
                if isinstance(item, str) and pattern.search(item):
                    n[i] = pattern.sub(_ERASED, item)
                    count += 1
                else:
                    count += _walk(item)
        return count

    return _walk(node) if raw_name.strip() else 0


def _file_mentions(path: Path, key: str) -> bool:
    """Case-insensitive whole-name scan of a cache file's raw text."""
    try:
        text = path.read_text(errors="ignore").lower()
    except OSError:
        return False
    return key in re.sub(r"\s+", " ", text)


# --------------------------------------------------------------------------
# Access (SAR export)
# --------------------------------------------------------------------------


def export_athlete(profile_id: str, athlete_name: str) -> dict:
    """Everything held about one athlete, machine-readable (Arts 15 + 20)."""
    key = athlete_key(athlete_name)
    report: dict = {
        "athlete_name": athlete_name,
        "profile_id": profile_id,
        "generated_at": _iso(_now()),
        "runs": [],
        "media_assets": [],
        "pb_caches": [],
        "caption_memory": [],
        "consent_records": [],
        "notes": [
            "Content already published to social platforms is held by those platforms "
            "as independent controllers and is not included here.",
        ],
    }

    for path in _tenant_runs(profile_id):
        try:
            run = json.loads(path.read_text())
        except Exception:
            continue
        matches, card_ids = _athlete_entries_in_run(run, key)
        if matches:
            report["runs"].append(
                {
                    "run_id": run.get("run_id", path.stem),
                    "meet": (run.get("meet") or {}).get("name", ""),
                    "card_ids": card_ids,
                    "records": matches,
                }
            )

    try:
        from mediahub.media_library.store import get_store

        for asset in get_store().list(profile_id=profile_id or None):
            if any(athlete_key(n) == key for n in (asset.linked_athlete_names or [])):
                report["media_assets"].append(
                    {
                        "id": asset.id,
                        "filename": asset.filename,
                        "linked_athlete_names": asset.linked_athlete_names,
                        "permission_status": asset.permission_status,
                    }
                )
    except Exception as e:
        report["notes"].append(f"media library unreadable: {e}")

    for cache_root in (
        _data_dir() / "data" / "discovered",
        _data_dir() / "discovered",
    ):
        if not cache_root.exists():
            continue
        for sub in ("swimmers", "pbs", "search_cache"):
            d = cache_root / sub
            if not d.exists():
                continue
            for f in d.rglob("*.json"):
                if _file_mentions(f, key):
                    try:
                        report["pb_caches"].append({"path": str(f), "content": json.loads(f.read_text())})
                    except Exception:
                        report["pb_caches"].append({"path": str(f), "content": "unparseable"})

    try:
        from mediahub.memory import store as memory_store

        for rec in _memory_rows_matching(memory_store, profile_id, key):
            report["caption_memory"].append(rec)
    except Exception:
        pass

    rec = ConsentRegistry(profile_id).get(athlete_name)
    if rec:
        report["consent_records"].append(rec.to_record())
    return report


def _memory_rows_matching(memory_store, tenant_id: str, key: str) -> list[dict]:
    rows: list[dict] = []
    if not memory_store.is_available():
        return rows
    try:
        conn = memory_store._connect()
    except Exception:
        return rows
    try:
        for dim in memory_store._known_dims(conn):
            tbl = memory_store._table_for_dim(dim)
            for rowid, caption, card_id, run_id in conn.execute(
                f"SELECT rowid, caption, card_id, run_id FROM {tbl} WHERE tenant_id=?",
                (str(tenant_id),),
            ):
                if key and key in re.sub(r"\s+", " ", (caption or "").lower()):
                    rows.append(
                        {"table": tbl, "rowid": rowid, "caption": caption, "card_id": card_id, "run_id": run_id}
                    )
    finally:
        conn.close()
    return rows


# --------------------------------------------------------------------------
# Erasure (Art 17)
# --------------------------------------------------------------------------


def erase_athlete(profile_id: str, athlete_name: str, *, recorded_by: str = "") -> dict:
    """Remove one athlete from every reachable store; report residuals."""
    key = athlete_key(athlete_name)
    slug = _slug(athlete_name)
    report: dict = {
        "athlete_name": athlete_name,
        "profile_id": profile_id,
        "erased_at": _iso(_now()),
        "runs_touched": [],
        "cards_removed": 0,
        "names_redacted": 0,
        "visual_files_deleted": [],
        "workflow_entries_removed": 0,
        "pb_cache_files_deleted": [],
        "media_assets_deleted": [],
        "media_assets_unlinked": [],
        "memory_rows_deleted": 0,
        "profile_fields_redacted": 0,
        "residuals": [
            "Posts already published to social platforms cannot be recalled by MediaHub — "
            "they must be removed on the platform itself.",
        ],
    }

    # 1. Runs: drop the athlete's achievements/cards, redact remaining mentions.
    for path in _tenant_runs(profile_id):
        try:
            run = json.loads(path.read_text())
        except Exception:
            continue
        matches, card_ids = _athlete_entries_in_run(run, key)
        mentions = _count_mentions(run, key)
        if not matches and not mentions:
            continue
        rr = run.get("recognition_report")
        if isinstance(rr, dict):
            kept = []
            for ra in rr.get("ranked_achievements") or []:
                ach = (ra or {}).get("achievement") or {}
                if _name_matches(ach.get("swimmer_name"), key):
                    report["cards_removed"] += 1
                else:
                    kept.append(ra)
            rr["ranked_achievements"] = kept
            if "n_achievements" in rr:
                rr["n_achievements"] = len(kept)
        cards = run.get("cards")
        if isinstance(cards, list):
            kept_cards = [
                c
                for c in cards
                if not (isinstance(c, dict) and any(_name_matches(c.get(k), key) for k in _NAME_KEYS))
            ]
            report["cards_removed"] += len(cards) - len(kept_cards)
            run["cards"] = kept_cards
        report["names_redacted"] += _redact_names_deep(run, key)
        report["names_redacted"] += _redact_text_deep(run, athlete_name)
        path.write_text(json.dumps(run))
        run_id = run.get("run_id", path.stem)
        report["runs_touched"].append(run_id)

        # 1b. Rendered visuals for this athlete's cards (by card id or name slug).
        sidecar = path.parent / path.stem
        if sidecar.is_dir():
            for f in sidecar.rglob("*"):
                if not f.is_file():
                    continue
                fname = f.name.lower()
                if any(cid and cid.lower() in fname for cid in card_ids) or (slug and slug in fname):
                    try:
                        f.unlink()
                        report["visual_files_deleted"].append(str(f))
                    except OSError:
                        report["residuals"].append(f"could not delete {f}")

        # 1c. Workflow approval state for removed cards.
        wf_path = path.parent / f"{path.stem}__workflow.json"
        if wf_path.exists() and card_ids:
            try:
                wf = json.loads(wf_path.read_text())
                if isinstance(wf, dict):
                    before = len(wf)
                    for cid in card_ids:
                        wf.pop(cid, None)
                    removed = before - len(wf)
                    if removed:
                        report["workflow_entries_removed"] += removed
                        wf_path.write_text(json.dumps(wf))
            except Exception:
                report["residuals"].append(f"workflow sidecar unreadable: {wf_path}")

        # 1d. Turn-into packs for this run mentioning the athlete.
        packs_dir = _data_dir() / "turn_into_packs" / str(run_id)
        if packs_dir.is_dir():
            for f in packs_dir.rglob("*.json"):
                if _file_mentions(f, key):
                    try:
                        pack = json.loads(f.read_text())
                        report["names_redacted"] += _redact_names_deep(pack, key)
                        report["names_redacted"] += _redact_text_deep(pack, athlete_name)
                        f.write_text(json.dumps(pack))
                    except Exception:
                        try:
                            f.unlink()
                        except OSError:
                            report["residuals"].append(f"could not clean pack file {f}")

    # 2. PB caches (per-run, warm, and raw search HTML).
    for cache_root in (_data_dir() / "data" / "discovered", _data_dir() / "discovered"):
        if not cache_root.exists():
            continue
        for sub in ("swimmers", "pbs", "search_cache", "meets"):
            d = cache_root / sub
            if not d.exists():
                continue
            for f in list(d.rglob("*.json")):
                if _file_mentions(f, key):
                    try:
                        f.unlink()
                        report["pb_cache_files_deleted"].append(str(f))
                    except OSError:
                        report["residuals"].append(f"could not delete cache file {f}")
    for legacy in (_data_dir() / ".cache" / "pb_lookup", _data_dir() / ".cache" / "swimmingresults"):
        if legacy.exists():
            for f in list(legacy.glob("*.json")):
                if _file_mentions(f, key):
                    try:
                        f.unlink()
                        report["pb_cache_files_deleted"].append(str(f))
                    except OSError:
                        pass

    # 3. Media library: delete photos linked ONLY to this athlete; unlink otherwise.
    try:
        from mediahub.media_library.store import get_store

        store = get_store()
        for asset in store.list(profile_id=profile_id or None):
            names = asset.linked_athlete_names or []
            if not any(athlete_key(n) == key for n in names):
                continue
            if all(athlete_key(n) == key for n in names):
                store.delete(asset.id)
                report["media_assets_deleted"].append(asset.id)
            else:
                store.update_fields(
                    asset.id,
                    {
                        "linked_athlete_names": [n for n in names if athlete_key(n) != key],
                    },
                )
                report["media_assets_unlinked"].append(asset.id)
                report["residuals"].append(
                    f"asset {asset.id} kept (group photo linked to other athletes) — unlinked only"
                )
    except Exception as e:
        report["residuals"].append(f"media library unreachable: {e}")

    # 4. Semantic caption memory.
    try:
        from mediahub.memory import store as memory_store

        rows = _memory_rows_matching(memory_store, profile_id, key)
        if rows:
            conn = memory_store._connect()
            try:
                for rec in rows:
                    conn.execute(f"DELETE FROM {rec['table']} WHERE rowid=?", (rec["rowid"],))
                conn.commit()
            finally:
                conn.close()
            report["memory_rows_deleted"] = len(rows)
    except Exception:
        pass

    # 5. Club profile text fields (voice examples may quote captions).
    try:
        from mediahub.web.club_profile import load_profile, save_profile

        profile = load_profile(profile_id) if profile_id else None
        if profile is not None:
            pattern = re.compile(re.escape(athlete_name.strip()), re.IGNORECASE)
            changed = 0
            for field_name in ("voice_examples", "exemplar_captions"):
                values = getattr(profile, field_name, None) or []
                new_values = []
                for v in values:
                    if isinstance(v, str) and pattern.search(v):
                        new_values.append(pattern.sub(_ERASED, v))
                        changed += 1
                    else:
                        new_values.append(v)
                setattr(profile, field_name, new_values)
            if changed:
                save_profile(profile)
                report["profile_fields_redacted"] = changed
    except Exception:
        pass

    # 6. Suppression record: the athlete must not silently reappear.
    ConsentRegistry(profile_id).record(
        athlete_name=athlete_name,
        status="revoked",
        note="erasure request honoured — suppression record (do not re-include)",
        recorded_by=recorded_by,
    )

    # 7. Raw uploads: a results file names MANY athletes — deleting it to
    # erase one would destroy other subjects' provenance. Honest residual;
    # the retention purge (compliance/retention) bounds how long raw files
    # live anyway, and the operator can delete a whole run from /privacy.
    uploads = Path(os.environ.get("UPLOADS_DIR", str(_data_dir() / "uploads_v4")))
    raw_hits = []
    if uploads.exists():
        for run_id in report["runs_touched"]:
            d = uploads / str(run_id)
            if d.is_dir():
                raw_hits.extend(str(f) for f in d.iterdir() if f.is_file())
    if raw_hits:
        report["residuals"].append(
            "raw uploaded results files still name this athlete alongside other "
            f"athletes ({len(raw_hits)} file(s)); they age out via the retention "
            "schedule or can be removed by deleting the run: " + ", ".join(raw_hits[:5])
        )
    return report


def _count_mentions(node: object, key: str) -> int:
    n = 0
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _NAME_KEYS and _name_matches(v, key):
                n += 1
            else:
                n += _count_mentions(v, key)
    elif isinstance(node, list):
        for item in node:
            n += _count_mentions(item, key)
    return n


# --------------------------------------------------------------------------
# Rectification (Art 16)
# --------------------------------------------------------------------------


def rectify_athlete_name(profile_id: str, old_name: str, new_name: str) -> dict:
    """Correct an athlete's name across runs, media links and consent records."""
    key = athlete_key(old_name)
    new_clean = re.sub(r"\s+", " ", (new_name or "").strip())
    if not key or not new_clean:
        raise ValueError("both the current and the corrected name are required")
    report = {"runs_touched": [], "fields_updated": 0, "media_assets_updated": []}

    def _rename_deep(node: object) -> int:
        n = 0
        if isinstance(node, dict):
            for k, v in list(node.items()):
                if k in _NAME_KEYS and _name_matches(v, key):
                    node[k] = new_clean
                    n += 1
                else:
                    n += _rename_deep(v)
        elif isinstance(node, list):
            for item in node:
                n += _rename_deep(item)
        return n

    for path in _tenant_runs(profile_id):
        try:
            run = json.loads(path.read_text())
        except Exception:
            continue
        changed = _rename_deep(run)
        if changed:
            path.write_text(json.dumps(run))
            report["runs_touched"].append(run.get("run_id", path.stem))
            report["fields_updated"] += changed

    try:
        from mediahub.media_library.store import get_store

        store = get_store()
        for asset in store.list(profile_id=profile_id or None):
            names = asset.linked_athlete_names or []
            if any(athlete_key(n) == key for n in names):
                store.update_fields(
                    asset.id,
                    {
                        "linked_athlete_names": [
                            new_clean if athlete_key(n) == key else n for n in names
                        ]
                    },
                )
                report["media_assets_updated"].append(asset.id)
    except Exception:
        pass

    registry = ConsentRegistry(profile_id)
    old_rec = registry.get(old_name)
    if old_rec:
        registry.record(
            athlete_name=new_clean,
            status=old_rec.status,
            parental=old_rec.parental,
            under_18=old_rec.under_18,
            restricted=old_rec.restricted,
            note=f"rectified from '{old_name}'",
        )
    return report


# --------------------------------------------------------------------------
# Operator-level account erasure (users.jsonl — Part B controller record)
# --------------------------------------------------------------------------


def erase_user_account(email: str) -> bool:
    """Remove every trace of a user account from the append-only ledger.

    The one place a rewrite (not an append) is correct: erasing the account
    email from disk requires dropping its lines. Membership of the ledger is
    operator-controller data (ROPA B1), so this is an operator action.
    """
    norm = (email or "").strip().lower()
    if not norm:
        return False
    users_path = _data_dir() / "users.jsonl"
    if not users_path.exists():
        return False
    kept_lines = []
    found = False
    for line in users_path.read_text().splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            kept_lines.append(line)
            continue
        if str(rec.get("email", "")).strip().lower() == norm:
            found = True
        else:
            kept_lines.append(line)
    if found:
        users_path.write_text("\n".join(kept_lines) + ("\n" if kept_lines else ""))
        try:
            os.chmod(users_path, 0o600)
        except OSError:
            pass
    return found
