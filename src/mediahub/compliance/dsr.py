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

from mediahub._atomic_io import atomic_write_text

from .consent import ConsentRegistry, athlete_key
from .store import JsonlLedger

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

    def open(
        self, *, profile_id: str, athlete_name: str, request_type: str, note: str = ""
    ) -> DsrRequest:
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


def _tenant_runs(profile_id: str, *, include_ownerless: bool = True) -> list[Path]:
    """Run JSON files this tenant may act on under a DSR request.

    A run owned by this tenant (``owner == profile_id``) is always included.
    Ownerless runs (legacy / pre-multi-tenancy, ``profile_id == ""``) are
    included only when ``include_ownerless`` is set. The caller decides that
    from the SAME ADR-0014 rule the run routes use (``_ownerless_run_readable``):
    the operator and single-tenant / anonymous (pilot) sessions keep today's
    reach over legacy data, while a signed-in *regular* tenant on a shared
    instance is confined to its own runs — an ownerless run may be another
    club's legacy data (finding #111). Defaults to ``True`` so direct/library
    callers, tests, and the single-org legacy path are unchanged; the web
    routes pass the gated value."""
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
        if owner == profile_id or (include_ownerless and not owner):
            out.append(p)
    return out


def _tenant_pbs_dirs(profile_id: str, cache_root: Path, *, include_ownerless: bool) -> list[Path]:
    """``pbs/<run_id>/`` cache dirs under ``cache_root`` for this tenant's runs.

    Unlike the global ``swimmers/`` warm cache (keyed by ``md5(name|club)`` with
    no tenant dimension), ``pbs/`` is keyed by run id — ``pb_discovery.cache``'s
    ``RunCache`` writes ``discovered/pbs/<_safe(run_id)>/`` — so it carries the
    run's tenant attribution. The SAR export and the erasure sweep confine the
    ``pbs/`` walk to the tenant's own runs (the finding #111 rule applied one
    layer down) instead of reading or deleting every tenant's PB cache. A run's
    flat file is ``<run_id>.json``, so its stem is the run id the cache was
    keyed under; ``include_ownerless`` follows the same gate as the run walk."""
    from mediahub.pb_discovery.cache import _safe

    pbs_root = cache_root / "pbs"
    if not pbs_root.exists():
        return []
    dirs = []
    for path in _tenant_runs(profile_id, include_ownerless=include_ownerless):
        d = pbs_root / _safe(path.stem)
        if d.exists():
            dirs.append(d)
    return dirs


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


def _name_pattern(key: str) -> re.Pattern:
    """Whole-name matcher for a normalised athlete key.

    The key must not sit inside a longer alphanumeric run on either side, so
    'sam lee' matches 'Sam Lee' but never 'Sam Leeson'. The discovered/*
    caches are global (not tenant-scoped), so a bare substring scan would
    cross data subjects — and tenants — on a name-prefix collision.
    """
    return re.compile(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])")


def _file_mentions(path: Path, key: str) -> bool:
    """Case-insensitive whole-name scan of a cache file's raw text."""
    if not key:
        return False
    try:
        text = path.read_text(errors="ignore").lower()
    except OSError:
        return False
    return _name_pattern(key).search(re.sub(r"\s+", " ", text)) is not None


def _redact_rows_for_subject(node: object, pattern: re.Pattern) -> tuple[object, int]:
    """Drop list rows that carry no whole-name mention of the subject.

    A cache file matched on the subject's name can also hold rows about
    other swimmers (other clubs included — the cache is global). A SAR
    export must not disclose those, so every list element without the
    subject's name is dropped; returns ``(filtered_node, rows_dropped)``.
    """
    dropped = 0
    if isinstance(node, list):
        kept = []
        for item in node:
            try:
                blob = json.dumps(item, default=str).lower()
            except Exception:
                blob = str(item).lower()
            if pattern.search(re.sub(r"\s+", " ", blob)):
                sub, d = _redact_rows_for_subject(item, pattern)
                kept.append(sub)
                dropped += d
            else:
                dropped += 1
        return kept, dropped
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            sub, d = _redact_rows_for_subject(v, pattern)
            out[k] = sub
            dropped += d
        return out, dropped
    return node, 0


# --------------------------------------------------------------------------
# Access (SAR export)
# --------------------------------------------------------------------------


def export_athlete(profile_id: str, athlete_name: str, *, include_ownerless: bool = True) -> dict:
    """Everything held about one athlete, machine-readable (Arts 15 + 20).

    ``include_ownerless`` gates whether legacy ownerless runs are read (see
    ``_tenant_runs``); the web route passes the ADR-0014 value so a signed-in
    regular tenant cannot disclose another club's ownerless data."""
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

    for path in _tenant_runs(profile_id, include_ownerless=include_ownerless):
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
        # swimmers/ + search_cache/ are global public-reference caches with no
        # tenant dimension (keyed by md5(name|club) / query hash); pbs/ is
        # run-keyed, so confine it to this tenant's own runs — the finding #111
        # rule one layer down — rather than reading every tenant's PB cache.
        scan_dirs = [cache_root / "swimmers", cache_root / "search_cache"]
        scan_dirs += _tenant_pbs_dirs(profile_id, cache_root, include_ownerless=include_ownerless)
        for d in scan_dirs:
            if not d.exists():
                continue
            for f in d.rglob("*.json"):
                if _file_mentions(f, key):
                    # Path is relative to the cache root so the export never
                    # leaks the DATA_DIR filesystem layout; rows_redacted is
                    # always present so the SAR never implies false completeness.
                    rel = str(f.relative_to(cache_root))
                    try:
                        content, dropped = _redact_rows_for_subject(
                            json.loads(f.read_text()), _name_pattern(key)
                        )
                        report["pb_caches"].append(
                            {"path": rel, "content": content, "rows_redacted": dropped}
                        )
                    except Exception:
                        report["pb_caches"].append(
                            {"path": rel, "content": "unparseable", "rows_redacted": 0}
                        )

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
                        {
                            "table": tbl,
                            "rowid": rowid,
                            "caption": caption,
                            "card_id": card_id,
                            "run_id": run_id,
                        }
                    )
    finally:
        conn.close()
    return rows


# --------------------------------------------------------------------------
# Erasure (Art 17)
# --------------------------------------------------------------------------


def erase_athlete(
    profile_id: str,
    athlete_name: str,
    *,
    recorded_by: str = "",
    include_ownerless: bool = True,
) -> dict:
    """Remove one athlete from every reachable store; report residuals.

    ``include_ownerless`` gates whether legacy ownerless runs are mutated (see
    ``_tenant_runs``); the web route passes the ADR-0014 value so a signed-in
    regular tenant cannot rewrite another club's ownerless data. The privacy
    cascade below is already strict (``!= profile_id``), so it never reaches
    ownerless runs regardless.

    ONE erasure engine, two layers: the UK-legal cascade
    (``mediahub.privacy.erasure`` — runs/cards/rendered assets, PB caches,
    research caches, caption memory) runs first, then
    this module's extras (media library photos, club-profile text, workflow
    sidecars, turn-into packs, legacy unowned runs, the consent suppression
    record, and the W.2 level set to do_not_feature). Both the Privacy-page
    quick action and the Art 12A DSR workflow land here.
    """
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
    for path in _tenant_runs(profile_id, include_ownerless=include_ownerless):
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
                if not (
                    isinstance(c, dict) and any(_name_matches(c.get(k), key) for k in _NAME_KEYS)
                )
            ]
            report["cards_removed"] += len(cards) - len(kept_cards)
            run["cards"] = kept_cards
        report["names_redacted"] += _redact_names_deep(run, key)
        report["names_redacted"] += _redact_text_deep(run, athlete_name)
        atomic_write_text(path, json.dumps(run))
        run_id = run.get("run_id", path.stem)
        report["runs_touched"].append(run_id)

        # 1b. Rendered visuals for this athlete's cards (by card id or name slug).
        sidecar = path.parent / path.stem
        if sidecar.is_dir():
            for f in sidecar.rglob("*"):
                if not f.is_file():
                    continue
                fname = f.name.lower()
                if any(cid and cid.lower() in fname for cid in card_ids) or (
                    slug and slug in fname
                ):
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
                        atomic_write_text(wf_path, json.dumps(wf))
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
                        atomic_write_text(f, json.dumps(pack))
                    except Exception:
                        try:
                            f.unlink()
                        except OSError:
                            report["residuals"].append(f"could not clean pack file {f}")

    # 1e. UK-legal cascade (privacy.erasure) AFTER the name-keyed walkers
    # above — the cascade redacts residual mentions to "[removed]", which
    # would defeat name matching if it ran first. It adds the stores this
    # module doesn't walk: research caches, motion
    # cache, plus a second sweep of runs/caches/caption memory.
    try:
        from mediahub.privacy import erase_athlete as _cascade_erase

        cascade = _cascade_erase(profile_id, athlete_name)
        report["cascade"] = (
            cascade.to_dict()
            if hasattr(cascade, "to_dict")
            else dict(getattr(cascade, "__dict__", {}))
        )
    except Exception as e:
        report["residuals"].append(f"privacy cascade unavailable: {e}")

    # 2. PB caches (per-run, warm, and search). swimmers/search_cache/meets are
    #    global public-reference caches; pbs/ is run-keyed, so confine it to this
    #    tenant's own runs (finding #111) — a signed-in regular tenant must not
    #    delete another club's PB cache.
    for cache_root in (_data_dir() / "data" / "discovered", _data_dir() / "discovered"):
        if not cache_root.exists():
            continue
        scan_dirs = [cache_root / "swimmers", cache_root / "search_cache", cache_root / "meets"]
        scan_dirs += _tenant_pbs_dirs(profile_id, cache_root, include_ownerless=include_ownerless)
        for d in scan_dirs:
            if not d.exists():
                continue
            for f in list(d.rglob("*.json")):
                if _file_mentions(f, key):
                    try:
                        f.unlink()
                        report["pb_cache_files_deleted"].append(str(f))
                    except OSError:
                        report["residuals"].append(f"could not delete cache file {f}")
    for legacy in (
        _data_dir() / ".cache" / "pb_lookup",
        _data_dir() / ".cache" / "swimmingresults",
    ):
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

    # 6b. W.2 safeguarding registry: the erased athlete's consent level
    # becomes do_not_feature — the second registry agrees they never
    # reappear (the gate blocks if EITHER registry blocks).
    try:
        from mediahub.athletes.registry import resolve as _resolve_athlete
        from mediahub.safeguarding import set_consent as _set_consent_level

        rec_w = _resolve_athlete(profile_id, athlete_name)
        if rec_w is not None:
            _set_consent_level(
                profile_id,
                rec_w.athlete_id,
                "do_not_feature",
                actor=recorded_by or "erasure",
                note="erasure request honoured — suppression",
            )
    except Exception:
        pass

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


def rectify_athlete_name(
    profile_id: str, old_name: str, new_name: str, *, include_ownerless: bool = True
) -> dict:
    """Correct an athlete's name across runs, media links and consent records.

    ``include_ownerless`` gates whether legacy ownerless runs are renamed (see
    ``_tenant_runs``); the web route passes the ADR-0014 value so a signed-in
    regular tenant cannot rewrite another club's ownerless data."""
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

    for path in _tenant_runs(profile_id, include_ownerless=include_ownerless):
        try:
            run = json.loads(path.read_text())
        except Exception:
            continue
        changed = _rename_deep(run)
        if changed:
            atomic_write_text(path, json.dumps(run))
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

    Delegates to :meth:`UserStore.delete` — the single, canonical account-erasure
    path — so this shares its guarantees instead of re-implementing them: it takes
    ``_LEDGER_LOCK`` (so it can't race a concurrent signup and silently erase the
    new account) and rewrites via a temp + ``os.replace`` (so a crash mid-write
    can't destroy every account). Membership of the ledger is operator-controller
    data (ROPA B1), so this is an operator action. Returns True when a record was
    removed.
    """
    norm = (email or "").strip().lower()
    if not norm:
        return False
    from mediahub.web.auth import UserStore  # noqa: PLC0415

    # No path arg: UserStore resolves the SAME ledger signups write to
    # (auth._users_path()), so erasure targets the real account store.
    return UserStore().delete(email)
