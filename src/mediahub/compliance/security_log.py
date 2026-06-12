"""Structured security & accountability event log (PII-minimised).

One append-only JSONL stream under ``DATA_DIR/security_log/`` recording the
events a regulator, an auditor, or an incident responder needs a timeline
for: logins and failures, exports, erasures, role changes, publish actions.

PII rules:
- **data subjects (athletes) are pseudonymised** — a salted hash, never the
  name. The log proves "an erasure happened for subject X at time T"
  without re-storing what was just erased.
- **actors** (club users / operator) are recorded as given — accountability
  for who did what is the point of the log. Actor identifiers fall under
  the operator's own ROPA entry (B3) and the retention schedule.
- free-text fields are length-capped; never log credentials, tokens, or
  upload contents.

The pseudonymisation salt is per-deployment (random, persisted 0600) so
hashes are stable for correlation within one deployment but useless taken
off-box.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()


def _data_dir() -> Path:
    src_root = Path(__file__).resolve().parents[1]
    return Path(os.environ.get("DATA_DIR", str(src_root)))


def _log_dir() -> Path:
    return _data_dir() / "security_log"


def _salt() -> bytes:
    path = _log_dir() / ".pseudonym_salt"
    try:
        if path.exists():
            return path.read_bytes()
    except OSError:
        pass
    salt = secrets.token_bytes(16)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(salt)
        os.chmod(path, 0o600)
    except OSError:
        pass
    return salt


def pseudonymise(value: str) -> str:
    """Stable per-deployment pseudonym for a data-subject identifier."""
    norm = " ".join((value or "").strip().lower().split())
    if not norm:
        return ""
    return hashlib.sha256(_salt() + norm.encode("utf-8")).hexdigest()[:16]


def record_event(
    event: str,
    *,
    actor: str = "",
    subject: str = "",
    profile_id: str = "",
    detail: str = "",
    outcome: str = "ok",
) -> None:
    """Append one security event. Never raises — logging must not break the app."""
    try:
        rec = {
            "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "event": str(event)[:64],
            "actor": str(actor or "")[:200],
            "subject_pseudonym": pseudonymise(subject) if subject else "",
            "profile_id": str(profile_id or "")[:80],
            "detail": str(detail or "")[:500],
            "outcome": str(outcome or "ok")[:32],
        }
        with _LOCK:
            d = _log_dir()
            d.mkdir(parents=True, exist_ok=True)
            path = d / "events.jsonl"
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        _alert_hook(rec)
    except Exception:
        pass


# Events that should also raise an operator notification when a channel is
# configured (notify package; payloads carry NO athlete personal data —
# DATA_MAP flow F7 rule).
_ALERT_EVENTS = {"login_lockout", "dsr_erasure", "breach_opened", "publish_blocked_consent"}


def _alert_hook(rec: dict) -> None:
    if rec.get("event") not in _ALERT_EVENTS:
        return
    try:
        from mediahub.notify import notify  # noqa: PLC0415

        notify(
            f"MediaHub security event: {rec['event']}",
            f"profile={rec.get('profile_id', '')} outcome={rec.get('outcome', '')}",
            priority="high",
            tags=("security",),
        )
    except Exception:
        pass


def read_events(limit: int = 500) -> list[dict]:
    path = _log_dir() / "events.jsonl"
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
