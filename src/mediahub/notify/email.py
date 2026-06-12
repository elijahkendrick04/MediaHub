"""Transactional email seam (PC.14) — Resend-style HTTP API behind an env key.

One narrow, dependency-free sender for the account-critical mails the
operational-trust pack needs: password resets, email verification, member
invites, and the operator's breach-notification channel (the ICO's 72-hour
clock needs a working channel, not a plan to build one). P4.5's digest
product can later ride the same seam.

Configuration (env only — see .env.example):

    RESEND_API_KEY            activates the seam (Bearer token)
    MEDIAHUB_EMAIL_FROM       required sender, e.g. "MediaHub <no-reply@yourdomain>"
    MEDIAHUB_EMAIL_ENDPOINT   optional override (default https://api.resend.com/emails;
                              any Resend-compatible POST {from,to,subject,text,html})
    MEDIAHUB_EMAIL_TIMEOUT    optional seconds (default 10)

Honesty rules:

- **Unconfigured is a clean, explicit state** — ``email_configured()`` is
  False and ``send_email`` raises :class:`EmailNotConfigured`; web routes
  surface an honest 503-style page instead of pretending mail was sent.
- Failures return/raise honestly; nothing is queued or retried silently.
- Message bodies are never logged (they carry reset links and breach
  detail); log lines carry the subject's length and the recipient count
  only.
"""

from __future__ import annotations

import logging
import os
import re

log = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "https://api.resend.com/emails"
DEFAULT_TIMEOUT = 10.0

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailNotConfigured(RuntimeError):
    """No transactional-email provider is configured on this deployment."""


class EmailSendError(RuntimeError):
    """The provider refused or failed to accept the message."""


def _api_key() -> str:
    return (os.environ.get("RESEND_API_KEY") or "").strip()


def _from_address() -> str:
    return (os.environ.get("MEDIAHUB_EMAIL_FROM") or "").strip()


def _endpoint() -> str:
    return (os.environ.get("MEDIAHUB_EMAIL_ENDPOINT") or DEFAULT_ENDPOINT).strip()


def _timeout() -> float:
    raw = (os.environ.get("MEDIAHUB_EMAIL_TIMEOUT") or "").strip()
    try:
        return max(1.0, float(raw)) if raw else DEFAULT_TIMEOUT
    except ValueError:
        return DEFAULT_TIMEOUT


def email_configured() -> bool:
    """True only when both the key and a From address are set."""
    return bool(_api_key() and _from_address())


def _clean_header(value: str) -> str:
    """Strip CR/LF so a subject or address can never smuggle extra headers."""
    return (value or "").replace("\r", " ").replace("\n", " ").strip()


def send_email(to: str, subject: str, text: str, html: str | None = None) -> bool:
    """Send one transactional email. Returns True on provider acceptance.

    Raises :class:`EmailNotConfigured` when the seam is off (callers show
    the honest unavailable state) and :class:`EmailSendError` when the
    provider rejects the message or the request fails.
    """
    if not email_configured():
        raise EmailNotConfigured(
            "Transactional email is not configured on this deployment "
            "(set RESEND_API_KEY and MEDIAHUB_EMAIL_FROM)."
        )
    recipient = _clean_header(to)
    if not _EMAIL_RE.match(recipient):
        raise EmailSendError(f"refusing to send to malformed address {recipient!r}")
    payload: dict = {
        "from": _clean_header(_from_address()),
        "to": [recipient],
        "subject": _clean_header(subject),
        "text": text or "",
    }
    if html:
        payload["html"] = html
    try:
        import requests  # noqa: PLC0415

        r = requests.post(
            _endpoint(),
            json=payload,
            headers={"Authorization": f"Bearer {_api_key()}"},
            timeout=_timeout(),
        )
    except Exception as exc:
        log.warning("transactional email request failed: %s", exc)
        raise EmailSendError(f"email provider unreachable: {exc}") from exc
    if r.status_code >= 300:
        log.warning("transactional email rejected: HTTP %s", r.status_code)
        raise EmailSendError(f"email provider returned HTTP {r.status_code}")
    return True


def send_to_many(recipients: list[str], subject: str, text: str) -> dict:
    """Send one message to many recipients individually (breach notices).

    Per-recipient isolation: one bad address must not stop the rest. Returns
    ``{"sent": n, "failed": [addresses...]}`` — honest counts the operator
    ledger records.
    """
    sent, failed = 0, []
    for addr in recipients:
        try:
            send_email(addr, subject, text)
            sent += 1
        except EmailNotConfigured:
            raise  # config is all-or-nothing; surface it immediately
        except EmailSendError:
            failed.append(addr)
    return {"sent": sent, "failed": failed}


__all__ = [
    "EmailNotConfigured",
    "EmailSendError",
    "email_configured",
    "send_email",
    "send_to_many",
]
