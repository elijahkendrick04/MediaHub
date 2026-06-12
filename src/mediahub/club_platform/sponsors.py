"""
PC.8 — sponsor manager: registry helpers, deterministic rotation, and the
per-sponsor exposure report.

A club funds its MediaHub subscription from sponsor money when it can show
the sponsor real exposure ("you appeared on 14 posts this month"). Three
deterministic pieces deliver that:

1. **Registry** — ``ClubProfile.sponsors`` (list of dicts; see
   ``normalise_sponsor``). The legacy single ``sponsor_name`` field stays a
   fallback so existing profiles render unchanged.
2. **Rotation** — ``sponsor_for_card(profile, run_id, card_id)`` picks which
   active sponsor a card carries, seeded from the (run, card) identity the
   same way ``auto_variation_seed_for`` seeds card variation, so the still
   and its motion render agree and re-renders are reproducible.
3. **Exposure** — every render that actually stamps a sponsor appends to an
   append-only ledger (``DATA_DIR/sponsors/<profile_id>__exposure.jsonl``).
   ``exposure_report`` joins that ledger with ``workflow`` card states and
   the posting log to produce the monthly per-sponsor counts. The report
   only counts *recorded* renders — it never back-fills history it cannot
   prove.

Everything here is deterministic arithmetic — no AI judgement (the choice
of *which sponsor logo* goes on *which card* is a fairness/rotation rule,
not a creative call).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

_LEDGER_LOCK = threading.Lock()

VALID_TIERS = ("headline", "gold", "silver", "bronze", "partner")


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _data_dir() -> Path:
    src_root = Path(__file__).resolve().parents[2]
    return Path(os.environ.get("DATA_DIR", str(src_root)))


def _exposure_path(profile_id: str) -> Path:
    return _data_dir() / "sponsors" / f"{profile_id}__exposure.jsonl"


# ---- registry --------------------------------------------------------------


def normalise_sponsor(entry: dict) -> Optional[dict]:
    """Coerce one registry entry into the canonical shape, or None if unusable.

    Canonical keys: sponsor_id, name, logo_asset_id, tier, active_from,
    active_until, website. Dates are ISO ``YYYY-MM-DD`` strings; empty means
    an open end of the window.
    """
    if not isinstance(entry, dict):
        return None
    name = str(entry.get("name", "") or "").strip()
    if not name:
        return None
    sponsor_id = str(entry.get("sponsor_id", "") or "").strip()
    if not sponsor_id:
        sponsor_id = hashlib.sha256(name.lower().encode("utf-8")).hexdigest()[:12]
    tier = str(entry.get("tier", "") or "").strip().lower()
    if tier not in VALID_TIERS:
        tier = "partner"
    return {
        "sponsor_id": sponsor_id,
        "name": name,
        "logo_asset_id": str(entry.get("logo_asset_id", "") or "").strip(),
        "tier": tier,
        "active_from": str(entry.get("active_from", "") or "").strip(),
        "active_until": str(entry.get("active_until", "") or "").strip(),
        "website": str(entry.get("website", "") or "").strip(),
    }


def registry_for(profile) -> list[dict]:
    """The profile's normalised sponsor registry (invalid entries dropped)."""
    out = []
    for entry in getattr(profile, "sponsors", None) or []:
        s = normalise_sponsor(entry)
        if s is not None:
            out.append(s)
    return out


def active_sponsors(profile, on_date: str = "") -> list[dict]:
    """Sponsors whose active window covers ``on_date`` (default: today).

    Window comparison is plain ISO-date string ordering; an empty bound is
    open. Order is registry order (the club's own priority ordering).
    """
    day = (on_date or "").strip() or time.strftime("%Y-%m-%d", time.gmtime())
    out = []
    for s in registry_for(profile):
        if s["active_from"] and day < s["active_from"]:
            continue
        if s["active_until"] and day > s["active_until"]:
            continue
        out.append(s)
    return out


# ---- deterministic rotation -------------------------------------------------


def sponsor_rotation_seed(run_id: str, card_id: str) -> int:
    """Stable per-card seed (sha256 of the run/card identity, like
    ``auto_variation_seed_for``) so stills, motion, and re-renders agree."""
    key = f"{run_id}::{card_id}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big")


def sponsor_for_card(
    profile, run_id: str, card_id: str, on_date: str = "", *, include_legacy: bool = True
) -> Optional[dict]:
    """Which sponsor this card carries — deterministic rotation over the
    active registry. Returns None when no sponsor is active.

    With ``include_legacy`` (the default), an empty registry falls back to
    the legacy single ``sponsor_name`` field (as a synthetic entry) so
    pre-PC.8 profiles keep rendering exactly as before. The standard card
    render path passes ``include_legacy=False``: legacy profiles only ever
    showed a sponsor on the dedicated sponsor-variant surface, and that must
    not change until the club opts into the registry.
    """
    actives = active_sponsors(profile, on_date=on_date)
    if not actives:
        if include_legacy:
            legacy = str(getattr(profile, "sponsor_name", "") or "").strip()
            if legacy:
                return normalise_sponsor({"name": legacy, "tier": "partner"})
        return None
    idx = sponsor_rotation_seed(run_id, card_id) % len(actives)
    return actives[idx]


# ---- exposure ledger ---------------------------------------------------------


def record_exposure(
    profile_id: str,
    *,
    run_id: str,
    card_id: str,
    sponsor_id: str,
    sponsor_name: str,
    surface: str = "still",
) -> None:
    """Append one sponsor-stamped render to the exposure ledger (best-effort).

    Idempotent per (run, card, sponsor, surface): re-rendering the same card
    does not inflate the sponsor's counts.
    """
    if not (profile_id and run_id and card_id and sponsor_name):
        return
    rec = {
        "run_id": run_id,
        "card_id": card_id,
        "sponsor_id": sponsor_id,
        "sponsor_name": sponsor_name,
        "surface": surface,
        "recorded_at": _utc_now_iso(),
    }
    try:
        path = _exposure_path(profile_id)
        with _LEDGER_LOCK:
            existing = _read_exposures(profile_id)
            key = (run_id, card_id, sponsor_id, surface)
            if any(
                (e.get("run_id"), e.get("card_id"), e.get("sponsor_id"), e.get("surface")) == key
                for e in existing
            ):
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        # Exposure accounting must never break a render.
        return


def _read_exposures(profile_id: str) -> list[dict]:
    path = _exposure_path(profile_id)
    if not path.exists():
        return []
    out = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


# ---- exposure report ----------------------------------------------------------


def exposure_report(profile_id: str, month: str, *, workflow_store=None) -> dict:
    """Per-sponsor exposure counts for one month (``month`` = ``YYYY-MM``).

    Joins the exposure ledger (which cards carried which sponsor) with the
    workflow sidecar (approved/posted per card) and the posting log
    (publish attempts). Counts only what the ledger actually recorded.
    Returns::

        {month, profile_id, sponsors: [
            {sponsor_id, sponsor_name, cards: N, approved: N, posted: N,
             publish_attempts_ok: N, runs: [run_id, ...]},
        ]}
    """
    month = (month or "").strip()[:7]
    rows = [
        r for r in _read_exposures(profile_id) if str(r.get("recorded_at", "")).startswith(month)
    ]

    # Card status lookup, one workflow load per run.
    if workflow_store is None:
        from mediahub.workflow.store import WorkflowStore

        workflow_store = WorkflowStore(_data_dir() / "runs_v4")
    states_by_run: dict[str, dict] = {}

    def _card_status(run_id: str, card_id: str) -> str:
        if run_id not in states_by_run:
            try:
                states_by_run[run_id] = workflow_store.load(run_id)
            except Exception:
                states_by_run[run_id] = {}
            # values are CardWorkflowState objects keyed by card_id
        state = states_by_run[run_id].get(card_id)
        if state is None:
            return "queue"
        status = getattr(state, "status", "queue")
        return getattr(status, "value", str(status))

    try:
        from mediahub.publishing.posting_log import attempts_summary_for_run
    except Exception:  # pragma: no cover - posting log is optional context
        attempts_summary_for_run = None

    attempts_cache: dict[str, dict] = {}

    def _attempts_ok(run_id: str) -> int:
        if attempts_summary_for_run is None:
            return 0
        if run_id not in attempts_cache:
            try:
                attempts_cache[run_id] = attempts_summary_for_run(profile_id, run_id) or {}
            except Exception:
                attempts_cache[run_id] = {}
        return int(attempts_cache[run_id].get("ok") or 0)

    by_sponsor: dict[str, dict] = {}
    for r in rows:
        sid = str(r.get("sponsor_id", "") or "")
        agg = by_sponsor.setdefault(
            sid,
            {
                "sponsor_id": sid,
                "sponsor_name": str(r.get("sponsor_name", "") or ""),
                "cards": 0,
                "approved": 0,
                "posted": 0,
                "publish_attempts_ok": 0,
                "runs": set(),
            },
        )
        # A card may have been recorded on more than one surface (still +
        # motion); count it once per (run, card).
        card_key = (r.get("run_id"), r.get("card_id"))
        seen = agg.setdefault("_seen_cards", set())
        if card_key in seen:
            continue
        seen.add(card_key)
        agg["cards"] += 1
        agg["runs"].add(str(r.get("run_id", "")))
        status = _card_status(str(r.get("run_id", "")), str(r.get("card_id", "")))
        if status in ("approved", "posted"):
            agg["approved"] += 1
        if status == "posted":
            agg["posted"] += 1

    sponsors = []
    for agg in by_sponsor.values():
        agg.pop("_seen_cards", None)
        runs = sorted(r for r in agg.pop("runs") if r)
        agg["runs"] = runs
        agg["publish_attempts_ok"] = sum(_attempts_ok(r) for r in runs)
        sponsors.append(agg)
    sponsors.sort(key=lambda a: (-a["cards"], a["sponsor_name"].lower()))

    return {"month": month, "profile_id": profile_id, "sponsors": sponsors}
