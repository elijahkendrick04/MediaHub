"""mediahub/notify/channels.py — notification channel adapters.

Provider-agnostic delivery behind one ``Channel`` interface: **ntfy** (push to
phone/desktop) and a generic **webhook** (Slack / Discord / any JSON endpoint).
Both are thin HTTP POSTs over the existing ``requests`` dependency — MediaHub
bundles no daemon and adds no infrastructure. Each channel is configured by env
and is **inert when unconfigured**, so notifications are OFF by default and cost
nothing until an operator opts in.

ntfy is dual Apache-2.0 / GPLv2 and used **unmodified over its public HTTP API**
(or a self-hosted instance) — MediaHub only sends it messages, so there is no
copyleft concern. Never hard-code a public ntfy topic: anyone who knows a topic
can read it, so the topic is operator-supplied and there is no default.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 8.0


def _timeout() -> float:
    raw = os.environ.get("MEDIAHUB_NOTIFY_TIMEOUT", "").strip()
    try:
        return max(1.0, float(raw)) if raw else DEFAULT_TIMEOUT
    except ValueError:
        return DEFAULT_TIMEOUT


def _header_safe(value: str) -> str:
    """Strip CR/LF so a title/tag can never inject extra HTTP headers."""
    return (value or "").replace("\r", " ").replace("\n", " ").strip()


def _latin1_header(value: str) -> str:
    """Make a header value survive ``requests``' Latin-1 header encoding.

    ``requests`` encodes header values as Latin-1 and raises on any character
    outside it — club names routinely carry emoji/diacritics, which would make
    the push fail (caught + logged, never delivered). Return the value unchanged
    when it is already Latin-1 clean; otherwise RFC 2047-encode it
    (``=?utf-8?...?=``, pure ASCII) so a decoding client shows the full title,
    falling back to an ASCII-stripped form if encoding fails. CR/LF stripping is
    the caller's job (``_header_safe``)."""
    v = value or ""
    try:
        v.encode("latin-1")
        return v
    except UnicodeEncodeError:
        pass
    try:
        from email.header import Header  # noqa: PLC0415

        return Header(v, "utf-8").encode()
    except Exception:
        return v.encode("ascii", "ignore").decode("ascii").strip()


@dataclass
class Notification:
    """A single notification, mapped onto each channel's wire format."""

    title: str
    message: str
    priority: str = "default"  # ntfy scale: min | low | default | high | urgent
    tags: tuple[str, ...] = ()
    click_url: Optional[str] = None
    extra: dict = field(default_factory=dict)


class Channel:
    name = "channel"

    def configured(self) -> bool:
        raise NotImplementedError

    def send(self, n: Notification) -> bool:
        raise NotImplementedError


class NtfyChannel(Channel):
    """Push notifications via ntfy (https://ntfy.sh or a self-hosted server)."""

    name = "ntfy"

    def _server(self) -> str:
        return os.environ.get("MEDIAHUB_NTFY_SERVER", "https://ntfy.sh").strip().rstrip("/")

    def _topic(self) -> str:
        # No default — a guessable public topic would leak notifications.
        return os.environ.get("MEDIAHUB_NTFY_TOPIC", "").strip()

    def _token(self) -> str:
        return os.environ.get("MEDIAHUB_NTFY_TOKEN", "").strip()

    def configured(self) -> bool:
        return bool(self._topic())

    def send(self, n: Notification) -> bool:
        topic = self._topic()
        if not topic:
            return False
        try:
            import requests  # noqa: PLC0415

            headers = {
                "Title": _latin1_header(_header_safe(n.title)),
                "Priority": _header_safe(n.priority) or "default",
            }
            if n.tags:
                headers["Tags"] = _header_safe(",".join(n.tags))
            if n.click_url:
                headers["Click"] = _header_safe(n.click_url)
            token = self._token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
            r = requests.post(
                f"{self._server()}/{topic}",
                data=n.message.encode("utf-8"),
                headers=headers,
                timeout=_timeout(),
            )
            ok = r.status_code < 300
            if not ok:
                log.warning("ntfy returned HTTP %s", r.status_code)
            return ok
        except Exception as e:
            log.warning("ntfy send failed: %s", e)
            return False


class WebhookChannel(Channel):
    """Generic JSON webhook (Slack / Discord / any endpoint that accepts a POST).

    Sends a structured body plus a ``text`` field so Slack/Discord-style
    receivers render it without any extra mapping."""

    name = "webhook"

    def _url(self) -> str:
        return os.environ.get("MEDIAHUB_NOTIFY_WEBHOOK", "").strip()

    def configured(self) -> bool:
        return bool(self._url())

    def send(self, n: Notification) -> bool:
        url = self._url()
        if not url:
            return False
        text = n.title + "\n" + n.message + (f"\n{n.click_url}" if n.click_url else "")
        payload = {
            "title": n.title,
            "message": n.message,
            "priority": n.priority,
            "tags": list(n.tags),
            "url": n.click_url,
            "text": text,  # Slack renders this key
            "content": text[:2000],  # Discord requires this key (2000-char cap)
        }
        try:
            import requests  # noqa: PLC0415

            r = requests.post(url, json=payload, timeout=_timeout())
            ok = r.status_code < 300
            if not ok:
                log.warning("notify webhook returned HTTP %s", r.status_code)
            return ok
        except Exception as e:
            log.warning("notify webhook send failed: %s", e)
            return False


def all_channels() -> list[Channel]:
    """Every known channel (configured or not)."""
    return [NtfyChannel(), WebhookChannel()]


__all__ = ["Notification", "Channel", "NtfyChannel", "WebhookChannel", "all_channels"]
