"""data_hub.connectors.builtin — the shipped connectors (roadmap 1.13).

* :class:`CsvUrlConnector` — an in-house, first-party connector: it pulls a CSV
  from a URL the operator configures and parses it deterministically (reusing
  the data hub's own importer). No third party is required.
* :class:`SwimEnglandRankingsConnector` — the *seam* for the official Swim
  England approved-systems / Rankings API (founder task F.5). It is registered
  but **flag-gated**: until a key is configured it honest-errors with
  :class:`ConnectorNotConfigured`, never inventing times.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from ..portability import import_bytes
from .base import Connector, ConnectorNotConfigured, ConnectorResult, SourceTrust


class CsvUrlConnector(Connector):
    """Pull a CSV from a configured URL and parse it into rows (in-house)."""

    connector_id = "csv_url"
    title = "CSV from a link"
    description = "Keep a table in sync with a CSV published at a web address."
    external = True  # it fetches over the network, but it's our own code + format

    def __init__(self, fetcher: Optional[Callable[[str], bytes]] = None):
        # ``fetcher`` is injectable so this is offline-testable.
        self._fetcher = fetcher

    def is_configured(self, params: dict | None = None) -> bool:
        return bool((params or {}).get("url"))

    def _fetch_bytes(self, url: str) -> bytes:
        if self._fetcher is not None:
            return self._fetcher(url)
        import requests

        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        return resp.content

    def fetch(self, profile_id: str, params: dict | None = None) -> ConnectorResult:
        params = params or {}
        url = str(params.get("url") or "").strip()
        if not url:
            raise ConnectorNotConfigured("This connector needs a CSV URL to fetch from.")
        try:
            data = self._fetch_bytes(url)
        except Exception as exc:  # noqa: BLE001 — surface the real fetch error
            raise ConnectorNotConfigured(f"Could not fetch the CSV ({exc}).") from exc

        result = import_bytes(data, params.get("filename", "feed.csv"))
        if result.table is None:
            raise ConnectorNotConfigured("The fetched CSV could not be read.")
        trust = SourceTrust(
            source=params.get("source") or "CSV link",
            source_url=url,
            confidence="medium",
            note="Imported from an operator-configured CSV feed.",
        )
        return ConnectorResult(
            columns=result.table.columns,
            rows=result.table.rows,
            trust=trust,
            warnings=result.table.warnings,
        )


class SwimEnglandRankingsConnector(Connector):
    """Seam for the official Swim England Rankings API (flag-gated, F.5).

    Registered so the surface exists, but disabled until a key is configured —
    it never fabricates verified times.
    """

    connector_id = "swim_england_rankings"
    title = "Swim England Rankings (official)"
    description = "Verified swim times from the Swim England approved-systems API."
    external = True

    ENV_KEY = "MEDIAHUB_SWIM_ENGLAND_API_KEY"

    def is_configured(self, params: dict | None = None) -> bool:
        return bool(os.environ.get(self.ENV_KEY))

    def fetch(self, profile_id: str, params: dict | None = None) -> ConnectorResult:
        if not self.is_configured(params):
            raise ConnectorNotConfigured(
                "The Swim England Rankings API isn't connected yet. An operator must "
                f"set {self.ENV_KEY} once access is granted (founder task F.5)."
            )
        # The live integration is gated on the F.5 approval; until then there is
        # no offline data path here (honest, not fabricated).
        raise ConnectorNotConfigured(
            "Swim England Rankings access is approved but the live fetch is not yet "
            "implemented for this deployment."
        )


__all__ = ["CsvUrlConnector", "SwimEnglandRankingsConnector"]
