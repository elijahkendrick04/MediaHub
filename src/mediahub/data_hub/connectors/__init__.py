"""data_hub.connectors — keep tables fresh from club-relevant sources (1.13).

Connectors are pull adapters with trust metadata, normalised into the data hub
with ``CONNECTOR`` provenance. External APIs sit behind this seam, flag-gated and
honest-erroring when not configured — never required, never fabricated.
"""

from __future__ import annotations

from .base import Connector, ConnectorNotConfigured, ConnectorResult, SourceTrust
from .registry import (
    get,
    list_connectors,
    register,
    register_refresh_task,
    run_connector,
    sync_connector,
)

__all__ = [
    "Connector",
    "ConnectorNotConfigured",
    "ConnectorResult",
    "SourceTrust",
    "get",
    "list_connectors",
    "register",
    "run_connector",
    "sync_connector",
    "register_refresh_task",
]
