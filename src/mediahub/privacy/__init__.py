"""Data-subject rights engine — erasure cascades and account export.

See README.md in this package. The web layer calls these from the Privacy
page routes; tests pin that erasure genuinely removes data from every store
that holds it (UK GDPR Art. 17 — see docs/COMPLIANCE_AUDIT.md finding 1.6).
"""

from .erasure import (  # noqa: F401
    AthleteErasureReport,
    erase_account,
    erase_athlete,
    run_deletion_cascade,
)
from .export import account_export  # noqa: F401

__all__ = [
    "AthleteErasureReport",
    "account_export",
    "erase_account",
    "erase_athlete",
    "run_deletion_cascade",
]
