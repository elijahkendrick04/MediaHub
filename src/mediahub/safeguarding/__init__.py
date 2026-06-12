"""safeguarding — per-athlete consent registry + enforcement (Phase W.2).

The committee objection-killer: photo OK / name OK / initials-only /
do-not-feature per athlete, enforced deterministically at content-pack
build time and again at the publish gate. When a workspace runs a
consent regime (any record on file, or enforcement switched on), an
athlete with *no* consent record defaults to the most restrictive state
— never silently featured.

Built on the W.1 athlete spine (`mediahub.athletes`); every consent
change is audited.
"""

from .consent import (
    LEVELS,
    LEVEL_LABELS,
    ConsentPolicy,
    effective_policy,
    export_csv,
    get_consent,
    import_csv,
    list_consent,
    regime_active,
    set_consent,
    set_enforce,
)

__all__ = [
    "LEVELS",
    "LEVEL_LABELS",
    "ConsentPolicy",
    "effective_policy",
    "export_csv",
    "get_consent",
    "import_csv",
    "list_consent",
    "regime_active",
    "set_consent",
    "set_enforce",
]
