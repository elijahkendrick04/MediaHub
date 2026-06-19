"""
pb_history/service.py — wire the accumulating store to the pipeline.

Two entry points the pipeline calls:

  * ``load_history_snapshots`` — BEFORE detection: turn the club's prior real
    results into the ``BridgedSnapshot`` shape the existing PB detectors already
    consume, so ``pb_confirmed`` / ``official_pb`` fire from genuine history.
  * ``record_meet_results`` — AFTER detection: fold THIS meet's swims into the
    store so the next upload has a richer baseline.

Both are deterministic, free, network-free, and tenant-scoped. Neither raises:
PB history is an enhancement, never a reason a run fails.
"""

from __future__ import annotations

from typing import Optional

from mediahub.pipeline.pb_bridge import BridgedSnapshot

from .identity import canon_meet_key, event_key, name_key, swimmer_identity
from .store import PBHistoryStore

# Shown on the card as the source of the prior best (honest, no fake domain).
_SOURCE_LABEL = "Club results history"


def _meet_year(meet) -> Optional[int]:
    for attr in ("start_date", "end_date"):
        d = getattr(meet, attr, None)
        if d and len(str(d)) >= 4 and str(d)[:4].isdigit():
            return int(str(d)[:4])
    return None


def _swimmer_yob(swimmer, meet) -> Optional[int]:
    dob = getattr(swimmer, "dob", None)
    if dob and len(str(dob)) >= 4 and str(dob)[:4].isdigit():
        return int(str(dob)[:4])
    age = getattr(swimmer, "age_at_meet", None)
    yr = _meet_year(meet)
    if isinstance(age, int) and age > 0 and yr:
        return yr - age
    return None


def _identity_for(swimmer, meet) -> str:
    club = getattr(swimmer, "club_name", None) or getattr(swimmer, "club_code", None) or ""
    return swimmer_identity(
        getattr(swimmer, "first_name", "") or "",
        getattr(swimmer, "last_name", "") or "",
        club,
        _swimmer_yob(swimmer, meet),
    )


def meet_key_for(meet) -> str:
    return canon_meet_key(
        getattr(meet, "name", None),
        getattr(meet, "start_date", None),
        getattr(meet, "venue", None),
    )


def load_history_snapshots(
    meet,
    our_swimmer_keys,
    tenant_id: str,
    store: Optional[PBHistoryStore] = None,
) -> "dict[str, BridgedSnapshot]":
    """Build ``{swimmer_key: BridgedSnapshot}`` from the club's prior results.

    Keyed by the canonical ``swimmer_key`` (what the recognition report expects),
    populated from the stable cross-upload identity. The current meet is excluded
    so a swim is never its own baseline.
    """
    tenant_id = (tenant_id or "").strip()
    if not tenant_id:
        return {}
    store = store or PBHistoryStore()
    this_meet = meet_key_for(meet)

    # Map canonical swimmer_key -> stable identity (skip nameless / missing).
    key_to_ident: dict[str, str] = {}
    for k in our_swimmer_keys:
        sw = (getattr(meet, "swimmers", {}) or {}).get(k)
        if sw is None:
            continue
        ident = _identity_for(sw, meet)
        if ident:
            key_to_ident[k] = ident
    if not key_to_ident:
        return {}

    bests = store.prior_bests(tenant_id, set(key_to_ident.values()), exclude_meet_key=this_meet)
    if not bests:
        return {}

    snapshots: "dict[str, BridgedSnapshot]" = {}
    for swimmer_key, ident in key_to_ident.items():
        events = bests.get(ident)
        if not events:
            continue
        pb_times: dict[str, list[dict]] = {}
        for ev, info in events.items():
            pb_times[ev] = [
                {
                    "time_sec": info["time_cs"] / 100.0,
                    "date_iso": info.get("date_iso") or "",
                    "source_url": "",
                    "retrieved_at": "",
                    "meet": info.get("meet") or "",
                }
            ]
        snapshots[swimmer_key] = BridgedSnapshot(
            tiref=swimmer_key,
            pb_times=pb_times,
            fetch_ok=True,
            no_history=False,
            from_cache=True,
            source_domain=_SOURCE_LABEL,
        )
    return snapshots


def record_meet_results(
    meet,
    our_swimmer_keys,
    tenant_id: str,
    store: Optional[PBHistoryStore] = None,
) -> int:
    """Fold this meet's completed swims (our swimmers only) into the store.

    Returns rows written. DQ/NS swims (no finals time) are skipped — only real,
    completed results become future baselines.
    """
    tenant_id = (tenant_id or "").strip()
    if not tenant_id:
        return 0
    store = store or PBHistoryStore()
    this_meet = meet_key_for(meet)
    our = set(our_swimmer_keys)
    swimmers = getattr(meet, "swimmers", {}) or {}

    rows: list[tuple[str, str, str, int, Optional[str], Optional[str]]] = []
    for r in getattr(meet, "results", []) or []:
        if getattr(r, "swimmer_key", None) not in our:
            continue
        cs = getattr(r, "finals_time_cs", None)
        if not cs or cs <= 0 or getattr(r, "dq", False):
            continue
        sw = swimmers.get(r.swimmer_key)
        if sw is None:
            continue
        ident = _identity_for(sw, meet)
        if not ident:
            continue
        nkey = name_key(getattr(sw, "first_name", "") or "", getattr(sw, "last_name", "") or "")
        ev = event_key(
            getattr(r, "distance", 0), getattr(r, "stroke", ""), getattr(r, "course", "")
        )
        date = getattr(r, "swim_date", None) or getattr(meet, "start_date", None)
        rows.append((ident, nkey, ev, int(cs), date, getattr(meet, "name", None)))

    return store.record_meet(tenant_id, this_meet, rows)


def erase_subject(tenant_id: str, full_name: str, store: Optional[PBHistoryStore] = None) -> int:
    """Delete one swimmer's stored PB history within a tenant (the GDPR "forget
    me" right). Matches by order-independent name, so "First Last" / "Last, First"
    both hit. Returns rows deleted."""
    nkey = name_key(full_name or "", "")
    return (store or PBHistoryStore()).purge_subject(tenant_id, nkey)


def erase_tenant(tenant_id: str, store: Optional[PBHistoryStore] = None) -> int:
    """Delete all of a tenant's PB history (account/club deletion)."""
    return (store or PBHistoryStore()).purge_tenant(tenant_id)
