"""
pb_history — the accumulating per-club PB baseline.

Every uploaded results file feeds a per-tenant best-times store; "is this a PB?"
is then answered against the club's OWN real past results — deterministic,
instant, free, network-free, and more accurate every upload. This is the
scalable PB baseline (returning swimmers never touch the web). It is NOT
seed-time inference — every stored time is a real swum result.

See docs/adr/0025-accumulating-pb-history-baseline.md for the rationale.
"""

from .service import (
    erase_subject,
    erase_tenant,
    load_history_snapshots,
    meet_key_for,
    record_meet_results,
)
from .store import PBHistoryStore

__all__ = [
    "PBHistoryStore",
    "load_history_snapshots",
    "record_meet_results",
    "meet_key_for",
    "erase_subject",
    "erase_tenant",
]
