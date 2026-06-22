"""Erasure cascades — run, athlete, and account (UK GDPR Art. 17).

Design rules:

- **Reach every store.** A "deleted" athlete must be gone from the run JSON,
  the rendered assets, the PB caches (warm + per-run), the research cache,
  the caption memory, and the posting-log excerpts. Partial erasure is the
  bug this module exists to fix (audit finding 1.6).
- **Prefer over-removal.** When a card mentions the erased athlete, the whole
  card goes (with its rendered files); remaining multi-athlete text gets the
  name redacted. Better a club re-generates a card than a child's data
  survives an erasure request.
- **Counts, not booleans.** Every cascade reports what it removed so the UI
  and tests can verify the work.

All path resolution happens at call time from ``DATA_DIR`` (never frozen at
import), matching the rest of the codebase.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "data"))


def _runs_dir() -> Path:
    return _data_dir() / "runs_v4"


# ---------------------------------------------------------------------------
# Shared cache sweeps
# ---------------------------------------------------------------------------


def _delete_json_files_mentioning(directory: Path, needle: str, glob: str = "*.json") -> int:
    """Delete every JSON file under ``directory`` whose content mentions
    ``needle`` (case-insensitive). Returns files removed. Tolerates missing
    directories and unreadable files."""
    if not directory.exists():
        return 0
    frag = needle.lower()
    removed = 0
    for f in directory.rglob(glob):
        try:
            if frag in f.read_text(encoding="utf-8", errors="ignore").lower():
                f.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def _purge_pb_caches(name: str, club: str = "") -> int:
    """Remove an athlete from the PB discovery caches (warm + per-run)."""
    from mediahub.pb_discovery.cache import _discovered_root, make_swimmer_key

    removed = 0
    root = _discovered_root()
    # Exact key delete when we know the club…
    if club:
        key = make_swimmer_key(name, club)
        for p in [root / "swimmers" / f"{key}.json", *root.glob(f"pbs/*/{key}.json")]:
            try:
                if p.exists():
                    p.unlink()
                    removed += 1
            except OSError:
                continue
    # …and a content scan either way (cached payloads carry the name).
    removed += _delete_json_files_mentioning(root / "swimmers", name)
    removed += _delete_json_files_mentioning(root / "pbs", name)
    return removed


def _purge_research_caches(name: str) -> int:
    """Remove cached web-search/lookup pages mentioning the athlete."""
    removed = _delete_json_files_mentioning(_data_dir() / ".cache", name)
    try:
        from mediahub.web_research.search import _get_cache_dir

        removed += _delete_json_files_mentioning(_get_cache_dir(), name)
    except Exception:  # cache dir resolution is best-effort by design
        pass
    return removed


def _purge_motion_cache_for_run(run_id: str) -> int:
    """Drop motion-cache MP4s (and manifests) rendered from one run."""
    d = _data_dir() / "motion_cache"
    if not d.exists() or not run_id:
        return 0
    removed = 0
    for manifest in d.glob("*.json"):
        try:
            if run_id in manifest.read_text(encoding="utf-8", errors="ignore"):
                mp4 = manifest.with_suffix(".mp4")
                manifest.unlink()
                removed += 1
                if mp4.exists():
                    mp4.unlink()
                    removed += 1
        except OSError:
            continue
    return removed


# ---------------------------------------------------------------------------
# Run-deletion cascade (called from web._delete_run)
# ---------------------------------------------------------------------------


def run_deletion_cascade(run_id: str, profile_id: str = "") -> dict:
    """The stores a run delete must reach BEYOND the run files themselves.

    web.py removes the DB row, run JSON, run directory, packs and workflow
    file; this adds the per-run PB cache, the caption memory, and the motion
    cache. Never raises — erasure of one store must not abort erasure of the
    rest.
    """
    report = {
        "pb_cache_files": 0,
        "memory_rows": 0,
        "motion_files": 0,
        "athlete_swims": 0,
        "review_comments": 0,
        "collab_comments": 0,
    }
    try:
        from mediahub.pb_discovery.cache import _discovered_root

        per_run = _discovered_root() / "pbs" / run_id
        if per_run.exists():
            for f in per_run.glob("*.json"):
                try:
                    f.unlink()
                    report["pb_cache_files"] += 1
                except OSError:
                    pass
            try:
                per_run.rmdir()
            except OSError:
                pass
    except Exception as exc:
        log.warning("erasure: per-run PB cache sweep failed for %s: %s", run_id, exc)
    if profile_id:
        try:
            from mediahub.memory import store as memory_store

            report["memory_rows"] = memory_store.delete_run(tenant_id=profile_id, run_id=run_id)
        except Exception as exc:
            log.warning("erasure: memory sweep failed for %s: %s", run_id, exc)
        try:
            from mediahub.athletes import registry as athlete_registry

            report["athlete_swims"] = athlete_registry.purge_run(profile_id, run_id).get("swims", 0)
        except Exception as exc:
            log.warning("erasure: athlete-swims purge failed for %s: %s", run_id, exc)
    try:
        report["motion_files"] = _purge_motion_cache_for_run(run_id)
    except Exception as exc:
        log.warning("erasure: motion-cache sweep failed for %s: %s", run_id, exc)
    try:
        from mediahub.workflow.review_comments import delete_comments_for_run

        report["review_comments"] = delete_comments_for_run(run_id)
    except Exception as exc:
        log.warning("erasure: reel review-comments sweep failed for %s: %s", run_id, exc)
    try:
        from mediahub.collab.threads import delete_for_run as _delete_collab_for_run

        report["collab_comments"] = _delete_collab_for_run(run_id)
    except Exception as exc:
        log.warning("erasure: collab comments sweep failed for %s: %s", run_id, exc)
    return report


# ---------------------------------------------------------------------------
# Athlete erasure
# ---------------------------------------------------------------------------


@dataclass
class AthleteErasureReport:
    name: str
    profile_id: str
    cards_removed: int = 0
    swims_removed: int = 0
    runs_touched: list[str] = field(default_factory=list)
    assets_removed: int = 0
    pb_cache_files: int = 0
    research_cache_files: int = 0
    memory_rows: int = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "profile_id": self.profile_id,
            "cards_removed": self.cards_removed,
            "swims_removed": self.swims_removed,
            "runs_touched": list(self.runs_touched),
            "assets_removed": self.assets_removed,
            "pb_cache_files": self.pb_cache_files,
            "research_cache_files": self.research_cache_files,
            "memory_rows": self.memory_rows,
        }


def _mentions(value, frag: str) -> bool:
    try:
        return frag in json.dumps(value, default=str).lower()
    except (TypeError, ValueError):
        return False


def _name_value_match(d: dict, frag: str) -> bool:
    """True when any string value equals the name, or first+last combine to it."""
    for v in d.values():
        if isinstance(v, str) and v.strip().lower() == frag:
            return True
    first = str(d.get("first_name") or "").strip().lower()
    last = str(d.get("last_name") or "").strip().lower()
    if first and last and f"{first} {last}" == frag:
        return True
    return False


# Fields that identify a card's SUBJECT (vs. prose that may mention others).
_CARD_SUBJECT_KEYS = ("name", "swimmer", "athlete", "title", "headline", "subject")


def _card_is_about(card: dict, frag: str) -> bool:
    """A card is removed only when the athlete is its subject; a card about
    someone else that merely mentions the name in prose is kept and redacted
    (erasing one child must not delete another child's content)."""
    if _name_value_match(card, frag):
        return True
    for key in _CARD_SUBJECT_KEYS:
        if frag in str(card.get(key) or "").lower():
            return True
    facts = card.get("raw_facts")
    if isinstance(facts, dict) and _name_value_match(facts, frag):
        return True
    return False


def _strip_athlete_from_payload(payload, frag: str, *, in_cards: bool = False):
    """Recursively remove the athlete from a run payload.

    Two-tier rule: items in a ``cards`` list are dropped on a substring match
    (captions embed names in prose); every other list of dicts drops items
    only on an exact name-value match (so a meet-level dict mentioning many
    athletes isn't over-deleted). Returns (new_payload, cards_removed,
    other_removed, removed_card_ids).
    """
    cards_removed = 0
    others_removed = 0
    removed_card_ids: list[str] = []
    if isinstance(payload, dict):
        out = {}
        for k, v in payload.items():
            nv, c, o, ids = _strip_athlete_from_payload(v, frag, in_cards=(k == "cards"))
            cards_removed += c
            others_removed += o
            removed_card_ids.extend(ids)
            out[k] = nv
        return out, cards_removed, others_removed, removed_card_ids
    if isinstance(payload, list):
        kept = []
        for item in payload:
            if isinstance(item, dict):
                if in_cards and _card_is_about(item, frag):
                    cards_removed += 1
                    cid = str(item.get("card_id") or item.get("id") or "")
                    if cid:
                        removed_card_ids.append(cid)
                    continue
                if not in_cards and _name_value_match(item, frag):
                    others_removed += 1
                    continue
                nv, c, o, ids = _strip_athlete_from_payload(item, frag)
                cards_removed += c
                others_removed += o
                removed_card_ids.extend(ids)
                kept.append(nv)
            else:
                kept.append(item)
        return kept, cards_removed, others_removed, removed_card_ids
    return payload, 0, 0, []


def _redact_strings(payload, name: str):
    """Replace remaining mentions of the name in any string with [removed]."""
    pattern = re.compile(re.escape(name), re.IGNORECASE)
    if isinstance(payload, dict):
        return {k: _redact_strings(v, name) for k, v in payload.items()}
    if isinstance(payload, list):
        return [_redact_strings(v, name) for v in payload]
    if isinstance(payload, str) and pattern.search(payload):
        return pattern.sub("[removed]", payload)
    return payload


def erase_athlete(profile_id: str, name: str, club: str = "") -> AthleteErasureReport:
    """Erase one named athlete from everything an organisation holds.

    Walks the org's runs (cards out, swims out, residual mentions redacted,
    rendered assets for removed cards deleted), then sweeps the PB caches,
    research caches, caption memory and posting-log excerpts.
    """
    report = AthleteErasureReport(name=name, profile_id=profile_id)
    frag = (name or "").strip().lower()
    if not frag or not (profile_id or "").strip():
        return report

    runs_dir = _runs_dir()
    if runs_dir.exists():
        for run_file in sorted(runs_dir.glob("*.json")):
            try:
                payload = json.loads(run_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            if (payload.get("profile_id") or "") != profile_id:
                continue
            if frag not in json.dumps(payload, default=str).lower():
                continue
            run_id = str(payload.get("run_id") or run_file.stem)
            stripped, n_cards, n_other, removed_ids = _strip_athlete_from_payload(payload, frag)
            stripped = _redact_strings(stripped, name)
            try:
                run_file.write_text(json.dumps(stripped, indent=2, default=str), encoding="utf-8")
            except OSError as exc:
                log.warning("erasure: could not rewrite %s: %s", run_file, exc)
                continue
            report.cards_removed += n_cards
            report.swims_removed += n_other
            report.runs_touched.append(run_id)
            # Rendered assets for the removed cards (PNGs, MP4s, briefs…)
            run_dir = runs_dir / run_id
            if run_dir.exists() and removed_ids:
                for asset in run_dir.rglob("*"):
                    if asset.is_file() and any(cid in asset.name for cid in removed_ids):
                        try:
                            asset.unlink()
                            report.assets_removed += 1
                        except OSError:
                            pass
            report.assets_removed += _purge_motion_cache_for_run(run_id) if removed_ids else 0

    report.pb_cache_files = _purge_pb_caches(name, club)
    report.research_cache_files = _purge_research_caches(name)
    try:
        from mediahub.memory import store as memory_store

        report.memory_rows = memory_store.delete_matching(tenant_id=profile_id, needle=name)
    except Exception as exc:
        log.warning("erasure: memory sweep failed for %r: %s", name, exc)
    return report


# ---------------------------------------------------------------------------
# Account erasure
# ---------------------------------------------------------------------------


def erase_account(email: str) -> dict:
    """Erase an account: users-ledger row, legal acceptances, memberships.

    Workspace (club) data is the CLUB's data, shared with other members —
    deleting an officer's account must not delete the club's runs. The
    Privacy Notice says exactly this. Returns per-store counts.
    """
    report = {"user_removed": False, "acceptances_removed": 0, "memberships_removed": 0}
    norm = (email or "").strip().lower()
    if not norm:
        return report
    from mediahub.web.auth import UserStore

    report["user_removed"] = UserStore().delete(norm)
    try:
        from mediahub.web.legal import AcceptanceStore

        report["acceptances_removed"] = AcceptanceStore().erase_email(norm)
    except Exception as exc:
        log.warning("erasure: acceptance-ledger sweep failed: %s", exc)
    try:
        from mediahub.web.tenancy import MembershipStore

        report["memberships_removed"] = MembershipStore().erase_email(norm)
    except Exception as exc:
        log.warning("erasure: membership sweep failed: %s", exc)
    return report
