"""Retention setting — the deployment-wide UK-legal baseline window.

``MEDIAHUB_RETENTION_DAYS`` (unset or 0 = disabled) is the single global
retention period surfaced on the Privacy page. Enforcement lives in
:mod:`mediahub.compliance.retention`: the daily scheduled purge treats this
value as a CEILING for the data-bearing artifact classes (runs, raw
uploads), and deletes aged-out runs **through the run-deletion path**, so
the full erasure cascade (PB caches, caption memory, motion cache) applies
to every aged-out run — exactly what the Privacy Notice §8 promises.
"""

from __future__ import annotations

import os


def retention_days() -> int:
    """The configured retention period in days; 0 = retention disabled."""
    raw = (os.environ.get("MEDIAHUB_RETENTION_DAYS") or "").strip()
    try:
        return max(0, int(raw)) if raw else 0
    except ValueError:
        return 0


__all__ = ["retention_days"]
