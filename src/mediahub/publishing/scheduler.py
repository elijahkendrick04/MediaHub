"""the scheduler publishing client — schedule approved cards via the scheduler's API v1.

Endpoints used (https://api.bufferapp.com):

    GET  /1/profiles.json
        Returns the list of social channels ("profiles") connected to
        the authenticated the scheduler account. We surface each profile's id,
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
        On success, the scheduler returns either a single `update` dict or an
        `updates` list (one per profile_id). We normalise to a list.

Authentication: the scheduler API v1 accepts the access_token either as a query
parameter or in the POST body — we send it as `access_token=...` on the
POST body / GET query string. Authentication is operator-controlled
via the SCHEDULER_ACCESS_TOKEN environment variable.

All HTTP calls flow through `requests` (already a project dependency).
A missing or blank token raises `SchedulerAuthError` rather than silently
calling the API and getting back an opaque 4xx. Network/HTTP failures
raise `SchedulerAPIError` with a message safe to surface in the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests

from mediahub.publishing.kill_switch import assert_publishing_allowed

SCHEDULER_API_BASE = "https://api.bufferapp.com"
_DEFAULT_TIMEOUT = 15  # seconds


class SchedulerError(Exception):
    """Base class for the scheduler client errors."""


class SchedulerAuthError(SchedulerError):
    """No the scheduler access token configured, or the scheduler returned 401/403."""


class SchedulerAPIError(SchedulerError):
    """the scheduler returned a non-2xx HTTP response or a transport error.

    The string form is intended to be safe for direct display to the user.
    """


class SchedulerRateLimitError(SchedulerAPIError):
    """The scheduler returned HTTP 429 — rate limited.

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
        # the scheduler occasionally returns an HTTP-date; we don't bother
        # parsing it — just signal "rate limited, no specific wait".
        return None


@dataclass
class _PreparedToken:
    token: str

    @classmethod
    def require(cls, token: Optional[str]) -> "_PreparedToken":
        if not token or not str(token).strip():
            raise SchedulerAuthError(
                "Auto scheduling is not configured on this deployment. Contact your administrator."
            )
        return cls(token=str(token).strip())


def list_channels(token: str) -> list[dict]:
    """Return the user's connected the scheduler profiles ("channels").

    Each item has the shape::

        {
            "id":                  "<scheduler profile id>",
            "service":             "instagram" | "twitter" | "facebook" | ...,
            "service_username":    "@your_club_handle",
            "formatted_username":  "Your Club Handle",
            "avatar":              "https://...png" | None,
            "default":             bool,
        }

    Raises
    ------
    SchedulerAuthError
        Token missing/blank or rejected by the scheduler (401/403).
    SchedulerAPIError
        Any other HTTP / network failure.
    """
    prepared = _PreparedToken.require(token)
    url = f"{SCHEDULER_API_BASE}/1/profiles.json"
    try:
        resp = requests.get(
            url,
            params={"access_token": prepared.token},
            timeout=_DEFAULT_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise SchedulerAPIError(f"Could not reach the scheduler: {exc}") from exc

    if resp.status_code in (401, 403):
        raise SchedulerAuthError(
            "Auto scheduling rejected the access token on this deployment. Contact your administrator to rotate it."
        )
    if resp.status_code == 429:
        retry = _parse_retry_after(resp)
        suffix = f" Retry in {retry}s." if retry else " Try again shortly."
        raise SchedulerRateLimitError(
            "Auto scheduling rate-limit reached." + suffix,
            retry_after=retry,
        )
    if not resp.ok:
        raise SchedulerAPIError(_summarise_error(resp))

    try:
        data = resp.json()
    except ValueError as exc:
        raise SchedulerAPIError("The scheduler returned an unreadable response.") from exc

    if not isinstance(data, list):
        # the scheduler error payloads come back as a dict with 'error' or 'message'.
        raise SchedulerAPIError(_summarise_error_dict(data))

    channels: list[dict] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        channels.append(
            {
                "id": raw.get("id", ""),
                "service": raw.get("service", ""),
                "service_username": raw.get("service_username", ""),
                "formatted_username": raw.get("formatted_username")
                or raw.get("service_username", ""),
                "avatar": raw.get("avatar"),
                "default": bool(raw.get("default", False)),
            }
        )
    return channels


def schedule_post(
    token: str,
    channel_id: str,
    text: str,
    media_urls: Optional[list[str]] = None,
    scheduled_at: Optional[datetime] = None,
    alt_text: str = "",
) -> dict:
    """Create a the scheduler update on `channel_id`.

    Parameters
    ----------
    token : str
        the scheduler access token (raises SchedulerAuthError if blank).
    channel_id : str
        the scheduler profile id from list_channels()[i]["id"].
    text : str
        Caption body. Required by the scheduler's API — empty strings are rejected.
    media_urls : list[str] | None
        Optional list of media URLs. the scheduler v1 accepts a single primary
        image via `media[link]`; if multiple URLs are passed we use the
        first and ignore the rest (a richer media payload is a follow-up).
    scheduled_at : datetime | None
        UTC datetime to schedule at. If None, the scheduler adds the update to
        the channel's next available queue slot.

    Returns
    -------
    dict
        On success, a normalised dict::

            {
                "ok":          True,
                "update_id":   "<scheduler update id>",
                "channel_id":  "<echoed profile id>",
                "raw":         <original payload>,
            }

    Raises
    ------
    SchedulerAuthError
        Token missing/blank or rejected by the scheduler.
    SchedulerAPIError
        Any non-2xx response or transport failure.
    """
    assert_publishing_allowed()
    prepared = _PreparedToken.require(token)
    if not channel_id or not str(channel_id).strip():
        raise SchedulerAPIError("A scheduling channel id is required.")
    if not text or not str(text).strip():
        raise SchedulerAPIError("Caption text is required.")

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
            # W.11: result-grounded alt text rides every publish payload
            # that carries media (the scheduler's media description field).
            if alt_text and alt_text.strip():
                payload.append(("media[description]", alt_text.strip()[:500]))

    url = f"{SCHEDULER_API_BASE}/1/updates/create.json"
    try:
        resp = requests.post(url, data=payload, timeout=_DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise SchedulerAPIError(f"Could not reach the scheduler: {exc}") from exc

    if resp.status_code in (401, 403):
        raise SchedulerAuthError(
            "Auto scheduling rejected the access token on this deployment. Contact your administrator to rotate it."
        )
    if resp.status_code == 429:
        retry = _parse_retry_after(resp)
        suffix = f" Retry in {retry}s." if retry else " Try again shortly."
        raise SchedulerRateLimitError(
            "Auto scheduling rate-limit reached." + suffix,
            retry_after=retry,
        )
    if not resp.ok:
        raise SchedulerAPIError(_summarise_error(resp))

    try:
        data = resp.json()
    except ValueError as exc:
        raise SchedulerAPIError("The scheduler returned an unreadable response.") from exc

    # the scheduler's v1 success flag is *usually* boolean True but the API has
    # been observed to return truthy non-bool values (1, "true") for some
    # update kinds. Use a permissive truthy check so legitimate posts
    # aren't falsely flagged as failures. Missing key defaults to True
    # (the response shape is success-implied).
    if not isinstance(data, dict) or not bool(data.get("success", True)):
        raise SchedulerAPIError(_summarise_error_dict(data if isinstance(data, dict) else {}))

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
        raise SchedulerAPIError(
            "Auto scheduling accepted the request but did not return an update id."
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
            return f"Scheduling error ({resp.status_code}): {msg}"
    except Exception:
        pass
    return f"The scheduler returned HTTP {resp.status_code}."


def _summarise_error_dict(data: dict) -> str:
    if not isinstance(data, dict):
        return "Unexpected scheduling response."
    for key in ("message", "error", "description"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return "The scheduler returned an error."


__all__ = [
    "SCHEDULER_API_BASE",
    "SchedulerError",
    "SchedulerAuthError",
    "SchedulerAPIError",
    "SchedulerRateLimitError",
    "list_channels",
    "schedule_post",
]
