"""Data-subject rights engine — erasure cascades and account export.

See README.md in this package. The web layer calls these from the Privacy
page routes; tests pin that erasure genuinely removes data from every store
that holds it (UK GDPR Art. 17 — see docs/COMPLIANCE_AUDIT.md finding 1.6).
"""

from .corrections import (  # noqa: F401
    TAKEDOWN_CHECKLIST,
    list_corrections,
    open_correction,
    resolve_correction,
)
from .erasure import (  # noqa: F401
    AthleteErasureReport,
    erase_account,
    erase_athlete,
    run_deletion_cascade,
)
from .export import account_export  # noqa: F401
from .org_lifecycle import delete_org, org_export_zip  # noqa: F401

__all__ = [
    "AthleteErasureReport",
    "TAKEDOWN_CHECKLIST",
    "account_export",
    "delete_org",
    "erase_account",
    "erase_athlete",
    "list_corrections",
    "open_correction",
    "org_export_zip",
    "resolve_correction",
    "run_deletion_cascade",
]
