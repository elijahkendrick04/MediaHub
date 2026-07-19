"""mediahub/log_sentinel/render_api.py — minimal Render REST API client.

Talks to https://api.render.com/v1 for exactly three things the sentinel needs:

* ``fetch_log_lines`` — page through the service's recent logs
  (``GET /v1/logs`` with ``ownerId`` + ``resource``; forward direction).
* ``restart_service`` — ``POST /v1/services/{id}/restart`` (the only mutating
  call the v1 playbook can make, and only when auto-fix is explicitly enabled).
* ``service_details`` — ``GET /v1/services/{id}``, used to derive ``ownerId``
  and to power the CLI ``check`` command.

Configuration is env-only and **inert when unset** (the sentinel idles):

    RENDER_API_KEY      Render API key (dashboard → Account Settings → API Keys).
    RENDER_SERVICE_ID   the ``srv-…`` id of the MediaHub service to watch.
    RENDER_OWNER_ID     optional; derived from the service when unset.
    RENDER_API_BASE     optional override (tests); default https://api.render.com/v1.

The API key is a secret: it is read from the environment, sent only in the
``Authorization`` header, and never logged, persisted, or echoed in errors.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

DEFAULT_BASE = "https://api.render.com/v1"
DEFAULT_TIMEOUT = 20.0
MAX_PAGES_PER_POLL = 5  # bound work per tick; the cursor catches up next tick


class RenderApiUnavailable(RuntimeError):
    """Raised when the Render API can't be reached or rejects a request."""


@dataclass(frozen=True)
class LogLine:
    """One log line as returned by Render's List logs endpoint."""

    epoch: float  # parsed timestamp (0.0 when unparseable)
    timestamp: str  # raw RFC3339 string as Render sent it
    message: str


def api_key() -> Optional[str]:
    v = os.environ.get("RENDER_API_KEY", "").strip()
    return v or None


def service_id() -> Optional[str]:
    v = os.environ.get("RENDER_SERVICE_ID", "").strip()
    return v or None


def is_configured() -> bool:
    """True when both the API key and the service id are present."""
    return bool(api_key() and service_id())


def _base() -> str:
    return os.environ.get("RENDER_API_BASE", DEFAULT_BASE).strip().rstrip("/")


def _timeout() -> float:
    raw = os.environ.get("RENDER_API_TIMEOUT", "").strip()
    try:
        return max(3.0, float(raw)) if raw else DEFAULT_TIMEOUT
    except ValueError:
        return DEFAULT_TIMEOUT


def _request(method: str, path: str, *, params=None, json_body=None):
    key = api_key()
    if not key:
        raise RenderApiUnavailable("RENDER_API_KEY is not configured")
    try:
        import requests  # noqa: PLC0415
    except Exception as e:  # pragma: no cover - requests is a hard dep
        raise RenderApiUnavailable(f"requests unavailable: {e}") from e
    try:
        r = requests.request(
            method,
            f"{_base()}{path}",
            params=params,
            json=json_body,
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout=_timeout(),
        )
    except Exception as e:
        raise RenderApiUnavailable(f"Render API transport error: {e}") from e
    return r


def _check(r, what: str) -> dict:
    if r.status_code == 429:
        raise RenderApiUnavailable(f"{what}: Render API rate limited (HTTP 429)")
    if r.status_code >= 400:
        # Body text can carry details but never the key — safe to surface trimmed.
        raise RenderApiUnavailable(f"{what}: HTTP {r.status_code} {str(r.text)[:200]}")
    try:
        return r.json()
    except Exception as e:
        raise RenderApiUnavailable(f"{what}: non-JSON response: {e}") from e


def service_details() -> dict:
    sid = service_id()
    if not sid:
        raise RenderApiUnavailable("RENDER_SERVICE_ID is not configured")
    return _check(_request("GET", f"/services/{sid}"), "service details")


_owner_lock = threading.Lock()
_owner_cache: Optional[str] = None


def owner_id() -> str:
    """The workspace id required by ``GET /v1/logs`` (env, else derived once)."""
    global _owner_cache
    env = os.environ.get("RENDER_OWNER_ID", "").strip()
    if env:
        return env
    with _owner_lock:
        if _owner_cache:
            return _owner_cache
        details = service_details()
        derived = str(details.get("ownerId") or "").strip()
        if not derived:
            raise RenderApiUnavailable("could not derive ownerId from service details")
        _owner_cache = derived
        return derived


def _parse_epoch(raw: str) -> float:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        # A naive timestamp is UTC (Render logs UTC); without this .timestamp()
        # would interpret it in the host's LOCAL zone and skew the boundary cursor.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def _rfc3339(epoch: float) -> str:
    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


# Render's docs describe startTime/endTime as date-time; send RFC3339 first and
# fall back to epoch seconds if the API ever rejects it. Remember what worked.
_time_style = {"style": "rfc3339"}


def _time_param(epoch: float) -> object:
    return _rfc3339(epoch) if _time_style["style"] == "rfc3339" else int(epoch)


def fetch_log_lines(since_epoch: float, *, limit: int = 100) -> tuple[list[LogLine], float]:
    """Fetch service logs strictly after ``since_epoch``, oldest-first.

    Returns ``(lines, newest_epoch)`` where ``newest_epoch`` is the cursor for
    the next poll (unchanged when no new lines). Pages at most
    ``MAX_PAGES_PER_POLL`` pages per call so a single tick stays bounded.
    """
    sid = service_id()
    if not sid:
        raise RenderApiUnavailable("RENDER_SERVICE_ID is not configured")
    oid = owner_id()
    lines: list[LogLine] = []
    newest = since_epoch
    start = since_epoch
    end = time.time()
    skipped_unparsed = 0
    for _page in range(MAX_PAGES_PER_POLL):
        params = {
            "ownerId": oid,
            "resource": [sid],
            "direction": "forward",
            "limit": max(1, min(100, int(limit))),
            "startTime": _time_param(start),
            "endTime": _time_param(end),
        }
        r = _request("GET", "/logs", params=params)
        if r.status_code in (400, 422) and _time_style["style"] == "rfc3339":
            # Some param-validation failures mean the API wanted epoch seconds.
            _time_style["style"] = "epoch"
            params["startTime"] = _time_param(start)
            params["endTime"] = _time_param(end)
            r = _request("GET", "/logs", params=params)
        data = _check(r, "list logs")
        batch = data.get("logs") or []
        for item in batch:
            if not isinstance(item, dict):
                continue
            msg = str(item.get("message") or item.get("text") or "")
            ts_raw = str(item.get("timestamp") or item.get("ts") or "")
            epoch = _parse_epoch(ts_raw)
            if not epoch:
                # Unparseable timestamp (epoch 0.0): it can't be deduped against
                # the boundary cursor and never advances it, so appending it would
                # re-detect the SAME line every poll (alert spam on a Render
                # timestamp-format change). Skip it; count for one warning.
                skipped_unparsed += 1
                continue
            if epoch <= since_epoch:
                continue  # boundary duplicate from the previous poll
            lines.append(LogLine(epoch=epoch, timestamp=ts_raw, message=msg))
            if epoch > newest:
                newest = epoch
        if not data.get("hasMore"):
            break
        nxt = data.get("nextStartTime")
        nxt_epoch = _parse_epoch(str(nxt)) if nxt else 0.0
        if nxt_epoch <= 0:
            break
        start = nxt_epoch
    if skipped_unparsed:
        log.warning(
            "log_sentinel: skipped %d log line(s) with an unparseable timestamp "
            "(Render log timestamp format may have changed)",
            skipped_unparsed,
        )
    lines.sort(key=lambda ln: ln.epoch)
    return lines, newest


def restart_service() -> dict:
    """``POST /v1/services/{id}/restart`` — returns the API's JSON (or {})."""
    sid = service_id()
    if not sid:
        raise RenderApiUnavailable("RENDER_SERVICE_ID is not configured")
    r = _request("POST", f"/services/{sid}/restart")
    if r.status_code >= 400:
        raise RenderApiUnavailable(f"restart: HTTP {r.status_code} {str(r.text)[:200]}")
    try:
        return r.json() if r.text else {}
    except Exception:
        return {}


__all__ = [
    "RenderApiUnavailable",
    "LogLine",
    "api_key",
    "service_id",
    "is_configured",
    "owner_id",
    "service_details",
    "fetch_log_lines",
    "restart_service",
    "MAX_PAGES_PER_POLL",
]
