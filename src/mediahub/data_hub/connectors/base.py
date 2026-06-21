"""data_hub.connectors.base — the pull-adapter seam (roadmap 1.13).

A *connector* keeps a data-hub table fresh from a club-relevant source on a
schedule — ranking sites, the Swim England approved-systems API, a club CRM
later. Every connector returns rows plus **trust metadata** (where the data came
from, when, and how confident we are), so the provenance rule holds end-to-end:
a synced cell is stamped ``CONNECTOR`` and carries its source.

External APIs are an *optional, flag-gated* spoke behind this seam — never
required. A connector that isn't configured raises :class:`ConnectorNotConfigured`
(an honest error), exactly like the AI surfaces, rather than inventing data.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..models import DataColumn, DataWarning


class ConnectorNotConfigured(RuntimeError):
    """Raised when a connector is used before it is configured (honest error)."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SourceTrust:
    """Where a connector's data came from — stamped onto every synced cell."""

    source: str  # human label, e.g. "Swim England Rankings API"
    source_url: str = ""
    retrieved_at: str = field(default_factory=now_iso)
    confidence: str = "medium"  # high | medium | low
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at,
            "confidence": self.confidence,
            "note": self.note,
        }


@dataclass
class ConnectorResult:
    """One fetch: the columns, the rows (as cell dicts), and the trust record."""

    columns: list[DataColumn]
    rows: list[dict]  # list[dict[str, DataCell]]
    trust: SourceTrust
    warnings: list[DataWarning] = field(default_factory=list)


class Connector(ABC):
    """Base class for a pull adapter. Subclasses set the metadata + ``fetch``."""

    connector_id: str = "abstract"
    title: str = "Abstract connector"
    description: str = ""
    # Whether this connector talks to an outside network (vs an in-house source).
    external: bool = False

    def is_configured(self, params: dict | None = None) -> bool:
        """True when the connector has what it needs to fetch. Default: yes."""
        return True

    @abstractmethod
    def fetch(self, profile_id: str, params: dict | None = None) -> ConnectorResult:
        """Pull the latest rows. Raise ``ConnectorNotConfigured`` if not ready."""
        raise NotImplementedError

    def meta(self) -> dict:
        return {
            "connector_id": self.connector_id,
            "title": self.title,
            "description": self.description,
            "external": self.external,
        }


__all__ = [
    "Connector",
    "ConnectorNotConfigured",
    "ConnectorResult",
    "SourceTrust",
    "now_iso",
]
