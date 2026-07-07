"""mediahub/webhooks/delivery.py — sign, send, record, and retry deliveries.

``emit(event, profile_id, data)`` fans an event out to every active endpoint
subscribed to it: each gets a durable ``webhook_deliveries`` row and an immediate
best-effort attempt on a daemon thread (so emitting never blocks the request).
A failed attempt is left ``pending`` with an exponential ``next_attempt_at``;
``deliver_pending`` (run from the scheduler) re-attempts due rows up to a bound,
then marks them ``failed``. The full attempt history is kept for the audit log
and the management UI.

The HTTP POST is isolated behind ``_http_post`` so tests can drive the engine
without real network calls — the same "test the engine directly" posture the
scheduler uses.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import _db
from . import events as _events
from .registry import EndpointStore
from .signing import HEADER, signature_header

log = logging.getLogger(__name__)

# Retry delays (seconds) after attempts 1..5; attempt 1 is immediate. Six total.
_BACKOFF = [30, 120, 600, 3600, 21600]
MAX_ATTEMPTS = 1 + len(_BACKOFF)


def _timeout() -> float:
    raw = os.environ.get("MEDIAHUB_WEBHOOK_TIMEOUT", "").strip()
    try:
        return max(1.0, float(raw)) if raw else 10.0
    except ValueError:
        return 10.0


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _http_post(url: str, body: bytes, headers: dict) -> tuple[Optional[int], Optional[str]]:
    """POST a signed body. Returns (status_code, error). Isolated for testing.

    SSRF-guarded at every attempt: the destination host is resolved, refused if
    any resulting IP is internal/reserved, and the connection is pinned to the
    validated IP (Host header + TLS SNI keep the original hostname) so a
    rebinding resolver cannot swap in an internal address after the check.
    Redirects are never followed.
    """
    try:
        import urllib3  # noqa: PLC0415
        from urllib.parse import urlparse  # noqa: PLC0415

        from ..web_research.safe_fetch import resolve_safe_ip  # noqa: PLC0415

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return None, "refused: endpoint URL must be http(s)"
        host = parsed.hostname or ""
        ip_text = resolve_safe_ip(host)
        if ip_text is None:
            return None, "refused: endpoint host is not allowed (SSRF guard)"
        default_port = 443 if parsed.scheme == "https" else 80
        port = parsed.port or default_port
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        host_hdr = f"[{host}]" if ":" in host else host
        if port != default_port:
            host_hdr += f":{port}"
        send_headers = dict(headers)
        send_headers["Host"] = host_hdr
        pool_timeout = urllib3.Timeout(connect=_timeout(), read=_timeout())
        if parsed.scheme == "https":
            pool = urllib3.HTTPSConnectionPool(
                ip_text,
                port=port,
                timeout=pool_timeout,
                server_hostname=host,  # SNI + certificate name for the real host
                assert_hostname=host,
                retries=False,
            )
        else:
            # nosemgrep: python.lang.security.audit.network.http-not-https-connection.http-not-https-connection
            # Cleartext pool is reached ONLY when the operator-configured webhook
            # URL is http:// (the https branch above uses HTTPSConnectionPool with
            # SNI + cert checks). We never downgrade an https target — the scheme
            # is preserved from the validated URL; we only pin the resolved IP.
            pool = urllib3.HTTPConnectionPool(
                ip_text, port=port, timeout=pool_timeout, retries=False
            )
        try:
            r = pool.urlopen(
                "POST",
                path,
                body=body,
                headers=send_headers,
                redirect=False,
                retries=False,
            )
            status = int(r.status)
            return status, (None if status < 300 else f"HTTP {status}")
        finally:
            pool.close()
    except Exception as e:  # network / DNS / TLS — a retryable transport error
        return None, str(e)[:300]


def _next_delay(attempts: int) -> Optional[int]:
    idx = attempts - 1
    return _BACKOFF[idx] if 0 <= idx < len(_BACKOFF) else None


def deliver_now(delivery_id: str) -> bool:
    """Attempt one delivery. Updates its row (delivered / pending+retry / failed).
    Returns True iff it was delivered."""
    conn = _db.connect()
    try:
        row = conn.execute("SELECT * FROM webhook_deliveries WHERE id=?", (delivery_id,)).fetchone()
        if row is None or row["status"] == "delivered":
            return row is not None and row["status"] == "delivered"
        ep = EndpointStore().get(row["endpoint_id"])
        if ep is None or not ep.active:
            conn.execute(
                "UPDATE webhook_deliveries SET status='failed', next_attempt_at=NULL, "
                "error=? WHERE id=?",
                ("endpoint removed or inactive", delivery_id),
            )
            conn.commit()
            return False
        body = row["payload_json"].encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            HEADER: signature_header(ep.secret, body),
            "X-MediaHub-Event": row["event"],
            "X-MediaHub-Delivery": delivery_id,
        }
        code, error = _http_post(ep.url, body, headers)
        attempts = int(row["attempts"]) + 1
        ts = _iso(_now_dt())
        if error is None:
            conn.execute(
                "UPDATE webhook_deliveries SET status='delivered', attempts=?, "
                "response_code=?, error=NULL, last_attempt_at=?, next_attempt_at=NULL, "
                "delivered_at=? WHERE id=?",
                (attempts, code, ts, ts, delivery_id),
            )
            conn.commit()
            EndpointStore().touch_delivery(ep.id)
            return True
        delay = _next_delay(attempts)
        if delay is None:
            conn.execute(
                "UPDATE webhook_deliveries SET status='failed', attempts=?, response_code=?, "
                "error=?, last_attempt_at=?, next_attempt_at=NULL WHERE id=?",
                (attempts, code, error, ts, delivery_id),
            )
        else:
            nxt = _iso(_now_dt() + timedelta(seconds=delay))
            conn.execute(
                "UPDATE webhook_deliveries SET status='pending', attempts=?, response_code=?, "
                "error=?, last_attempt_at=?, next_attempt_at=? WHERE id=?",
                (attempts, code, error, ts, nxt, delivery_id),
            )
        conn.commit()
        return False
    finally:
        conn.close()


def _enqueue(conn, endpoint_id: str, profile_id: str, event: str, payload: dict) -> str:
    delivery_id = "whd_" + uuid.uuid4().hex[:16]
    payload = dict(payload)
    payload["id"] = delivery_id  # stamp the envelope with its delivery id
    conn.execute(
        "INSERT INTO webhook_deliveries (id, endpoint_id, profile_id, event, payload_json, "
        "status, attempts, created_at, next_attempt_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            delivery_id,
            endpoint_id,
            profile_id,
            event,
            json.dumps(payload),
            "pending",
            0,
            _db.now(),
            _db.now(),
        ),
    )
    return delivery_id


def emit(event: str, profile_id: str, payload: dict, *, background: bool = True) -> list[str]:
    """Fan ``event`` out to the org's subscribed active endpoints.

    Returns the created delivery ids. Best-effort and never raises — a webhook
    problem must never break the run/approval/export that triggered it."""
    try:
        if not _events.is_known(event):
            return []
        endpoints = EndpointStore().list_for_profile(profile_id, active_only=True, event=event)
        if not endpoints:
            return []
        conn = _db.connect()
        ids: list[str] = []
        try:
            for ep in endpoints:
                ids.append(_enqueue(conn, ep.id, profile_id, event, payload))
            conn.commit()
        finally:
            conn.close()
        for did in ids:
            if background:
                threading.Thread(
                    target=_safe_deliver, args=(did,), daemon=True, name="webhook-deliver"
                ).start()
            else:
                _safe_deliver(did)
        return ids
    except Exception:
        log.warning("webhook emit failed for event=%s", event, exc_info=True)
        return []


def _safe_deliver(delivery_id: str) -> None:
    try:
        deliver_now(delivery_id)
    except Exception:
        log.warning("webhook delivery %s raised", delivery_id, exc_info=True)


def deliver_pending(params: Optional[dict] = None, *, limit: int = 200) -> int:
    """Scheduler handler: re-attempt every due pending delivery. Returns the
    number attempted. Safe to call repeatedly / concurrently."""
    conn = _db.connect()
    try:
        rows = conn.execute(
            "SELECT id FROM webhook_deliveries WHERE status='pending' "
            "AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
            "ORDER BY created_at ASC LIMIT ?",
            (_db.now(), limit),
        ).fetchall()
        ids = [r["id"] for r in rows]
    finally:
        conn.close()
    for did in ids:
        _safe_deliver(did)
    return len(ids)


class DeliveryStore:
    """Read access to the delivery log + manual redelivery (for the UI/API)."""

    def list_for_endpoint(self, endpoint_id: str, *, limit: int = 50) -> list[dict]:
        conn = _db.connect()
        try:
            rows = conn.execute(
                "SELECT id, event, status, attempts, response_code, error, created_at, "
                "last_attempt_at, delivered_at FROM webhook_deliveries "
                "WHERE endpoint_id=? ORDER BY created_at DESC LIMIT ?",
                (endpoint_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def redeliver(self, delivery_id: str, profile_id: str) -> bool:
        """Re-queue a delivery for an immediate attempt (tenant-scoped)."""
        conn = _db.connect()
        try:
            cur = conn.execute(
                "UPDATE webhook_deliveries SET status='pending', next_attempt_at=? "
                "WHERE id=? AND profile_id=?",
                (_db.now(), delivery_id, profile_id),
            )
            conn.commit()
            ok = cur.rowcount > 0
        finally:
            conn.close()
        if ok:
            _safe_deliver(delivery_id)
        return ok


__all__ = ["emit", "deliver_now", "deliver_pending", "DeliveryStore", "MAX_ATTEMPTS"]
