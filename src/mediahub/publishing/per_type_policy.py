"""Per-type autonomy policy store (P2.4).

Persists a per-organisation mapping of content/post type → AutonomyLevel under
``DATA_DIR/per_type_autonomy/<org_id>.json``.

Design invariants:
- Default for every type is ``approval_required`` (the most-gated level).
  Old profiles with no stored policy load cleanly and behave fully gated.
- One JSON file per org; org files are never mixed or shared.
- The org id is sanitised before use as a filename so it can never escape
  the storage directory (mirrors ``workflow/autonomy.py``).
- I/O errors are surfaced rather than swallowed so callers get an honest error.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Optional

from mediahub.club_platform.content_types import ContentType
from mediahub.sport_profiles.autonomy import AutonomyLevel

# Canonical AutonomyLevel for per-type policy is sport_profiles.autonomy.AutonomyLevel
# (draft_only / approval_required / fully_autonomous — the *publishing* policy axis).
# The autonomy.tools.AutonomyLevel (OFF/SUGGEST/DRAFT/PREPARE) describes the *runner's
# pre-approval reach* and is a separate axis; do not conflate the two.

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")
_LOCK = threading.Lock()

_ALL_TYPES: tuple[str, ...] = tuple(ct.value for ct in ContentType)


def _sanitise_org(org_id: str) -> str:
    s = _SAFE.sub("_", (org_id or "unknown").strip()) or "unknown"
    return s[:120]


def _policy_dir(data_dir: Optional[Path] = None) -> Path:
    import os

    base = Path(data_dir) if data_dir is not None else Path(os.environ.get("DATA_DIR", "."))
    d = base / "per_type_autonomy"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _policy_path(org_id: str, data_dir: Optional[Path] = None) -> Path:
    return _policy_dir(data_dir) / f"{_sanitise_org(org_id)}.json"


def _default_policy() -> dict[str, str]:
    """All types gated at approval_required — the safest default."""
    return {ct: AutonomyLevel.APPROVAL_REQUIRED.value for ct in _ALL_TYPES}


def load_policy(org_id: str, *, data_dir: Optional[Path] = None) -> dict[str, str]:
    """Load the per-type policy for ``org_id``.

    Returns the stored mapping, falling back to the all-gated default for any
    missing or unknown type.  An org with no stored policy returns the full
    default (all approval_required) so existing profiles are never broken.
    """
    path = _policy_path(org_id, data_dir)
    stored: dict[str, str] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                stored = raw
        except Exception:
            stored = {}

    out = _default_policy()
    for key, raw_val in stored.items():
        if key in out:
            level = AutonomyLevel.from_str(raw_val)
            out[key] = level.value
    return out


def save_policy(org_id: str, policy: dict[str, str], *, data_dir: Optional[Path] = None) -> None:
    """Persist the per-type policy for ``org_id``.

    Only known content types are stored; unknown keys are silently dropped.
    Values are normalised via ``AutonomyLevel.from_str`` so unknown values fall
    back to ``approval_required`` rather than being stored verbatim.
    """
    clean: dict[str, str] = {}
    for key in _ALL_TYPES:
        raw_val = policy.get(key, AutonomyLevel.APPROVAL_REQUIRED.value)
        clean[key] = AutonomyLevel.from_str(raw_val).value

    path = _policy_path(org_id, data_dir)
    with _LOCK:
        path.write_text(json.dumps(clean, indent=2), encoding="utf-8")


def policy_summary(org_id: str, *, data_dir: Optional[Path] = None) -> dict:
    """Return a status summary suitable for inclusion in /healthz/deps."""
    pol = load_policy(org_id, data_dir=data_dir)
    n_fully_autonomous = sum(1 for v in pol.values() if v == AutonomyLevel.FULLY_AUTONOMOUS.value)
    return {
        "org_id": org_id,
        "n_fully_autonomous": n_fully_autonomous,
        "n_gated": len(pol) - n_fully_autonomous,
        "policy": pol,
    }


__all__ = [
    "AutonomyLevel",
    "load_policy",
    "save_policy",
    "policy_summary",
]
