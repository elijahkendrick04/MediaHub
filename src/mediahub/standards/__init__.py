"""standards — season-current qualifying-time packs (Phase W.4).

Curated, versioned qualifying-time datasets under ``data/standards/<season>/``
(same JSON schema as ``data/quals.json``), each table carrying its source
PDF URL and curation date. Clubs pick which standards matter to them in
Organisation settings (``ClubProfile.important_standards``); the existing
deterministic ``QualifyingTimeDetector`` does the rest.

Refresh runbook: ``data/standards/README.md``.
"""

from .packs import (
    all_standards,
    available_standards_summary,
    load_standard_packs,
    standards_for_profile,
)

__all__ = [
    "all_standards",
    "available_standards_summary",
    "load_standard_packs",
    "standards_for_profile",
]
