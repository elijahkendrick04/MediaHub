"""Buffer publishing client — schedule approved cards via Buffer's API v1.

Endpoints used (https://api.bufferapp.com):

    GET  /1/profiles.json
        Returns the list of social channels ("profiles") connected to
        the authenticated Buffer account. We surface each profile's id,
        service (instagram / twitter / facebook / linkedin / etc.),
        formatted_username, and avatar so the UI can render checkboxes.

    POST /1/updates/create.json
        Creates a new update. We pass:
            text             — the caption body
            profile_ids[]    — repeated for each selected channel
            scheduled_at     — UNIX timestamp (seconds) for when to post;
                               omitted means the update goes to the top of
                               the channel's queue at its next slot
            media[link]      — single media URL (image), optional
        On success, Buffer returns either a single `update` dict or an
        `updates` list (one per profile_id). We normalise to a list.

Authentication: Buffer API v1 accepts the access_token either as a query
parameter or in the POST body — we send it as `access_token=...` on the
POST body / GET query string. Authentication is operator-controlled
via the BUFFER_ACCESS_TOKEN environment variable.

All HTTP calls flow through `requests` (already a project dependency).
A missing or blank token raises `BufferAuthError` rather than silently
calling the API and getting back an opaque 4xx. Network/HTTP failures
raise `BufferAPIError` with a message safe to surface in the UI.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests


BUFFER_API_BASE = "https://api.bufferapp.com"
_DEFAULT_TIMEOUT = 15  # seconds


class BufferError(Exception):
    """Base class for Buffer client errors."""


class BufferAuthError(BufferError):
    """No Buffer access token configured, or Buffer returned 401/403."""


class BufferAPIError(BufferError):
    """Buffer returned a non-2xx HTTP response or a transport error.

    The string form is intended to be safe for direct display to the user.
    """


class BufferRateLimitError(BufferAPIError):
    """Buffer returned HTTP 429 — rate limited.

    Carries an optional ``retry_after`` seconds value parsed from the
    Retry-After response header so callers can tell the user when to
    try again instead of silently retrying.
    """

    def __init__(self, message: str, *, retry_after: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after


def _parse_retry_after(resp: "requests.Response") -> Optional[int]:
    """Parse the ``Retry-After`` header. Returns seconds or None."""
    raw = (resp.headers or {}).get("Retry-After") if resp is not None else None
    if not raw:
        return None
    try:
        return max(1, int(float(raw)))
    except (TypeError, ValueError):
        # Buffer occasionally returns an HTTP-date; we don't bother
        # parsing it — just signal "rate limited, no specific wait".
        return None


@dataclass
class _PreparedToken:
    token: str

    @classmethod
    def require(cls, token: Optional[str]) -> "_PreparedToken":
        if not token or not str(token).strip():
            raise BufferAuthError(
                "Buffer is not configured on this deployment. Contact your administrator."
            )
        return cls(token=str(token).strip())


def list_channels(token: str) -> list[dict]:
    """Return the user's connected Buffer profiles ("channels").

    Each item has the shape::

        {
            "id":                  "<buffer profile id>",
            "service":             "instagram" | "twitter" | "facebook" | ...,
            "service_username":    "@swansea_uni_swim",
            "formatted_username":  "Swansea Uni Swim",
            "avatar":              "https://...png" | None,
            "default":             bool,
        }

    Raises
    ------
    BufferAuthError
        Token missing/blank or rejected by Buffer (401/403).
    BufferAPIError
        Any other HTTP / network failure.
    """
    prepared = _PreparedToken.require(token)
    url = f"{BUFFER_API_BASE}/1/profiles.json"
    try:
        resp = requests.get(
            url,
            params={"access_token": prepared.token},
            timeout=_DEFAULT_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise BufferAPIError(f"Could not reach Buffer: {exc}") from exc

    if resp.status_code in (401, 403):
        raise BufferAuthError(
            "Buffer rejected the access token on this deployment. Contact your administrator to rotate it."
        )
    if resp.status_code == 429:
        retry = _parse_retry_after(resp)
        suffix = f" Retry in {retry}s." if retry else " Try again shortly."
        raise BufferRateLimitError(
            "Buffer rate-limit reached." + suffix,
            retry_after=retry,
        )
    if not resp.ok:
        raise BufferAPIError(_summarise_error(resp))

    try:
        data = resp.json()
    except ValueError as exc:
        raise BufferAPIError("Buffer returned an unreadable response.") from exc

    if not isinstance(data, list):
        # Buffer error payloads come back as a dict with 'error' or 'message'.
        raise BufferAPIError(_summarise_error_dict(data))

    channels: list[dict] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        channels.append({
            "id": raw.get("id", ""),
            "service": raw.get("service", ""),
            "service_username": raw.get("service_username", ""),
            "formatted_username": raw.get("formatted_username")
                                  or raw.get("service_username", ""),
            "avatar": raw.get("avatar"),
            "default": bool(raw.get("default", False)),
        })
    return channels


def schedule_post(
    token: str,
    channel_id: str,
    text: str,
    media_urls: Optional[list[str]] = None,
    scheduled_at: Optional[datetime] = None,
) -> dict:
    """Create a Buffer update on `channel_id`.

    Parameters
    ----------
    token : str
        Buffer access token (raises BufferAuthError if blank).
    channel_id : str
        Buffer profile id from list_channels()[i]["id"].
    text : str
        Caption body. Required by Buffer's API — empty strings are rejected.
    media_urls : list[str] | None
        Optional list of media URLs. Buffer v1 accepts a single primary
        image via `media[link]`; if multiple URLs are passed we use the
        first and ignore the rest (a richer media payload is a follow-up).
    scheduled_at : datetime | None
        UTC datetime to schedule at. If None, Buffer adds the update to
        the channel's next available queue slot.

    Returns
    -------
    dict
        On success, a normalised dict::

            {
                "ok":          True,
                "update_id":   "<buffer update id>",
                "channel_id":  "<echoed profile id>",
                "raw":         <original payload>,
            }

    Raises
    ------
    BufferAuthError
        Token missing/blank or rejected by Buffer.
    BufferAPIError
        Any non-2xx response or transport failure.
    """
    prepared = _PreparedToken.require(token)
    if not channel_id or not str(channel_id).strip():
        raise BufferAPIError("A Buffer channel id is required.")
    if not text or not str(text).strip():
        raise BufferAPIError("Caption text is required.")

    payload: list[tuple[str, str]] = [
        ("access_token", prepared.token),
        ("text", str(text).strip()),
        ("profile_ids[]", str(channel_id).strip()),
    ]
    if scheduled_at is not None:
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
        payload.append(("scheduled_at", str(int(scheduled_at.timestamp()))))
    if media_urls:
        first = next((u for u in media_urls if u and str(u).strip()), None)
        if first:
            payload.append(("media[link]", str(first).strip()))
            payload.append(("media[photo]", str(first).strip()))

    url = f"{BUFFER_API_BASE}/1/updates/create.json"
    try:
        resp = requests.post(url, data=payload, timeout=_DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise BufferAPIError(f"Could not reach Buffer: {exc}") from exc

    if resp.status_code in (401, 403):
        raise BufferAuthError(
            "Buffer rejected the access token on this deployment. Contact your administrator to rotate it."
        )
    if resp.status_code == 429:
        retry = _parse_retry_after(resp)
        suffix = f" Retry in {retry}s." if retry else " Try again shortly."
        raise BufferRateLimitError(
            "Buffer rate-limit reached." + suffix,
            retry_after=retry,
        )
    if not resp.ok:
        raise BufferAPIError(_summarise_error(resp))

    try:
        data = resp.json()
    except ValueError as exc:
        raise BufferAPIError("Buffer returned an unreadable response.") from exc

    if not isinstance(data, dict) or not data.get("success", True) is True:
        raise BufferAPIError(_summarise_error_dict(data if isinstance(data, dict) else {}))

    update_id = ""
    updates = data.get("updates") if isinstance(data, dict) else None
    if isinstance(updates, list) and updates:
        first_update = updates[0]
        if isinstance(first_update, dict):
            update_id = str(first_update.get("id", ""))
    if not update_id:
        single = data.get("update") if isinstance(data, dict) else None
        if isinstance(single, dict):
            update_id = str(single.get("id", ""))

    if not update_id:
        raise BufferAPIError(
            "Buffer accepted the request but did not return an update id."
        )

    return {
        "ok": True,
        "update_id": update_id,
        "channel_id": str(channel_id).strip(),
        "raw": data,
    }


def _summarise_error(resp: "requests.Response") -> str:
    """Convert a non-2xx Response into a UI-safe message."""
    try:
        payload = resp.json()
        msg = _summarise_error_dict(payload if isinstance(payload, dict) else {})
        if msg:
            return f"Buffer error ({resp.status_code}): {msg}"
    except Exception:
        pass
    return f"Buffer returned HTTP {resp.status_code}."


def _summarise_error_dict(data: dict) -> str:
    if not isinstance(data, dict):
        return "Unexpected Buffer response."
    for key in ("message", "error", "description"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return "Buffer returned an error."


__all__ = [
    "BUFFER_API_BASE",
    "BufferError",
    "BufferAuthError",
    "BufferAPIError",
    "BufferRateLimitError",
    "list_channels",
    "schedule_post",
]
