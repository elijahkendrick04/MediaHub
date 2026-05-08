"""
engine_v4/adapters/__init__.py

Adapter registry and detect_adapter dispatcher.

Usage:
    from engine_v4.adapters import detect_adapter, get_adapter

    adapter_id = detect_adapter(file_bytes, filename)
    adapter = get_adapter(adapter_id)
    meet = adapter.parse(file_bytes, filename)
"""
from __future__ import annotations

from typing import Optional

from .sportsystems_pdf import SportSystemsPDFAdapter

# Also expose the existing HY3 adapter so callers can import from here
try:
    from swim_content_v4.adapters.hy3 import HY3Adapter as _HY3Adapter
    _hy3_available = True
except ImportError:
    _hy3_available = False
    _HY3Adapter = None


ADAPTER_CLASSES = {
    "sportsystems_pdf": SportSystemsPDFAdapter,
}
if _hy3_available and _HY3Adapter is not None:
    ADAPTER_CLASSES["hy3"] = _HY3Adapter

# Singleton instances
ADAPTERS: dict[str, object] = {k: v() for k, v in ADAPTER_CLASSES.items()}


def detect_adapter(file_bytes: bytes, filename: str) -> Optional[str]:
    """
    Inspect file bytes + filename to pick the best adapter.

    Returns the adapter id string (e.g. 'sportsystems_pdf', 'hy3'),
    or None if no adapter claims confidence > 0.
    """
    # Fast path: extension-based hints
    name_lower = filename.lower()
    if name_lower.endswith(".hy3") and "hy3" in ADAPTERS:
        return "hy3"
    if name_lower.endswith(".pdf"):
        return "sportsystems_pdf"

    # Confidence scoring fallback
    best_score = 0.0
    best_id = None
    for adapter_id, adapter in ADAPTERS.items():
        try:
            score = adapter.can_parse(file_bytes, filename)
        except Exception:
            score = 0.0
        if score > best_score:
            best_score = score
            best_id = adapter_id

    return best_id if best_score > 0.0 else None


def get_adapter(adapter_id: str):
    """Return the adapter instance for a given id, or None."""
    return ADAPTERS.get(adapter_id)


__all__ = [
    "SportSystemsPDFAdapter",
    "ADAPTERS",
    "ADAPTER_CLASSES",
    "detect_adapter",
    "get_adapter",
]
