"""mediahub/webhooks/registry.py — the per-org webhook endpoint registry.

A club registers subscriber URLs and which events each should receive. Unlike an
API token, the signing ``secret`` is a *shared* HMAC key: the receiver needs it
to verify deliveries, so it is stored in usable form and revealed to the owner
(it is not a password). It can be rolled, and an endpoint can be deactivated or
deleted — all tenant-scoped.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

# Reuse the project's single SSRF blocklist (same door deep research uses).
from ..web_research.safe_fetch import _ip_is_blocked, _resolved_ips

from . import _db
from .events import validate_events

_ID_PREFIX = "whe_"
_SECRET_PREFIX = "whsec_"
_SECRET_BYTES = 24


def _new_secret() -> str:
    return _SECRET_PREFIX + secrets.token_hex(_SECRET_BYTES)


def _url_ssrf_error(url: str) -> Optional[str]:
    """Registration-time SSRF guard: refuse endpoint URLs whose host is (or
    resolves to) an internal/reserved address — loopback, RFC-1918, link-local
    (incl. cloud metadata), multicast, unspecified.

    A host that does not resolve right now is allowed through: delivery
    re-validates the resolved IP on every attempt, which is the enforcement
    that actually matters (and defeats later DNS changes).
    """
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return "url could not be parsed"
    if not host:
        return "url must include a host"
    for ip_text in _resolved_ips(host):
        if _ip_is_blocked(ip_text):
            return "url host is a private or internal address, which is not allowed"
    return None


@dataclass
class WebhookEndpoint:
    id: str
    profile_id: str
    url: str
    secret: str
    events: list[str] = field(default_factory=list)
    description: str = ""
    active: bool = True
    created_by: str = ""
    created_at: str = ""
    last_delivery_at: Optional[str] = None

    def to_public_dict(self, *, include_secret: bool = False) -> dict:
        d = {
            "id": self.id,
            "url": self.url,
            "events": list(self.events),
            "description": self.description,
            "active": self.active,
            "created_at": self.created_at,
            "last_delivery_at": self.last_delivery_at,
        }
        if include_secret:
            d["secret"] = self.secret
        return d


def _row(r) -> WebhookEndpoint:
    return WebhookEndpoint(
        id=r["id"],
        profile_id=r["profile_id"],
        url=r["url"],
        secret=r["secret"],
        events=(r["events"] or "").split(),
        description=r["description"] or "",
        active=bool(r["active"]),
        created_by=r["created_by"] or "",
        created_at=r["created_at"] or "",
        last_delivery_at=r["last_delivery_at"],
    )


class EndpointStore:
    def create(
        self,
        profile_id: str,
        url: str,
        *,
        events=None,
        description: str = "",
        created_by: str = "",
    ) -> WebhookEndpoint:
        profile_id = (profile_id or "").strip()
        url = (url or "").strip()
        if not profile_id:
            raise ValueError("profile_id is required")
        if not (url.startswith("https://") or url.startswith("http://")):
            raise ValueError("url must be an absolute http(s) URL")
        ssrf_error = _url_ssrf_error(url)
        if ssrf_error:
            raise ValueError(ssrf_error)
        ep = WebhookEndpoint(
            id=_ID_PREFIX + uuid.uuid4().hex[:16],
            profile_id=profile_id,
            url=url,
            secret=_new_secret(),
            events=validate_events(events) or [],
            description=(description or "").strip()[:200],
            active=True,
            created_by=(created_by or "").strip(),
            created_at=_db.now(),
        )
        conn = _db.connect()
        try:
            conn.execute(
                "INSERT INTO webhook_endpoints (id, profile_id, url, secret, events, "
                "description, active, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    ep.id,
                    ep.profile_id,
                    ep.url,
                    ep.secret,
                    " ".join(ep.events),
                    ep.description,
                    1,
                    ep.created_by,
                    ep.created_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return ep

    def get(self, endpoint_id: str) -> Optional[WebhookEndpoint]:
        conn = _db.connect()
        try:
            r = conn.execute(
                "SELECT * FROM webhook_endpoints WHERE id=?", (endpoint_id,)
            ).fetchone()
            return _row(r) if r else None
        finally:
            conn.close()

    def list_for_profile(
        self, profile_id: str, *, active_only: bool = False, event: Optional[str] = None
    ) -> list[WebhookEndpoint]:
        conn = _db.connect()
        try:
            q = "SELECT * FROM webhook_endpoints WHERE profile_id=?"
            if active_only:
                q += " AND active=1"
            q += " ORDER BY created_at DESC"
            rows = conn.execute(q, (profile_id,)).fetchall()
        finally:
            conn.close()
        eps = [_row(r) for r in rows]
        if event:
            eps = [e for e in eps if event in e.events]
        return eps

    def set_active(self, endpoint_id: str, profile_id: str, active: bool) -> bool:
        conn = _db.connect()
        try:
            cur = conn.execute(
                "UPDATE webhook_endpoints SET active=? WHERE id=? AND profile_id=?",
                (1 if active else 0, endpoint_id, profile_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def roll_secret(self, endpoint_id: str, profile_id: str) -> Optional[str]:
        new = _new_secret()
        conn = _db.connect()
        try:
            cur = conn.execute(
                "UPDATE webhook_endpoints SET secret=? WHERE id=? AND profile_id=?",
                (new, endpoint_id, profile_id),
            )
            conn.commit()
            return new if cur.rowcount > 0 else None
        finally:
            conn.close()

    def delete(self, endpoint_id: str, profile_id: str) -> bool:
        conn = _db.connect()
        try:
            cur = conn.execute(
                "DELETE FROM webhook_endpoints WHERE id=? AND profile_id=?",
                (endpoint_id, profile_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def touch_delivery(self, endpoint_id: str) -> None:
        conn = _db.connect()
        try:
            conn.execute(
                "UPDATE webhook_endpoints SET last_delivery_at=? WHERE id=?",
                (_db.now(), endpoint_id),
            )
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()


__all__ = ["WebhookEndpoint", "EndpointStore"]
