"""audio/consent.py — consent gate + audit for voice cloning/changer (1.8).

Voice *cloning* and *voice changer* are powerful and easy to misuse, so the
parity plan is explicit: they are **off by default, enabled per-organisation
only with the recorded consent of the voice's owner, and audited**. This module
is that gate. It does not synthesise anything — it records who consented to what,
answers "is this feature allowed for this org right now?", and keeps an immutable
audit trail (grants and revocations are both rows).

The clone/changer synthesis backends are separate provider slots; before any of
them runs it must call :func:`require_consent`, which raises
:class:`ConsentRequired` unless an active, un-revoked grant exists. Default state
— no rows — means every consent-gated feature is disabled, which is the safe
posture.

Storage is the shared ``data.db`` (resolved from ``DATA_DIR`` at call time, like
``audio/rights.py``), so a test pointing ``DATA_DIR`` at a tmp dir gets an
isolated ledger.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# The consent-gated features. Kept as a fixed vocabulary so the UI and the gate
# agree and an unknown feature can never be "accidentally enabled".
FEATURES: tuple[str, ...] = ("clone", "changer")

_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audio_voice_consent (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id   TEXT NOT NULL,
    feature      TEXT NOT NULL,
    voice_owner  TEXT NOT NULL DEFAULT '',
    consent_ref  TEXT NOT NULL DEFAULT '',
    granted_by   TEXT NOT NULL DEFAULT '',
    granted_at   TEXT NOT NULL,
    revoked_at   TEXT NOT NULL DEFAULT '',
    notes        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_voice_consent_profile
    ON audio_voice_consent(profile_id, feature);
"""

_COLUMNS = (
    "id",
    "profile_id",
    "feature",
    "voice_owner",
    "consent_ref",
    "granted_by",
    "granted_at",
    "revoked_at",
    "notes",
)
_COLS_SQL = ", ".join(_COLUMNS)


class ConsentRequired(RuntimeError):
    """A consent-gated voice feature was invoked without an active grant."""


def _db_path() -> Path:
    env = os.environ.get("DATA_DIR")
    base = Path(env) if env else Path(__file__).resolve().parents[1]
    base.mkdir(parents=True, exist_ok=True)
    return base / "data.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm_feature(feature: str) -> str:
    f = str(feature or "").strip().lower()
    if f not in FEATURES:
        raise ValueError(f"unknown consent feature {feature!r} (valid: {list(FEATURES)})")
    return f


@dataclass
class ConsentRecord:
    """One consent grant (and, if ``revoked_at`` is set, its revocation)."""

    id: int
    profile_id: str
    feature: str
    voice_owner: str = ""
    consent_ref: str = ""
    granted_by: str = ""
    granted_at: str = ""
    revoked_at: str = ""
    notes: str = ""

    @property
    def active(self) -> bool:
        return not self.revoked_at

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "profile_id": self.profile_id,
            "feature": self.feature,
            "voice_owner": self.voice_owner,
            "consent_ref": self.consent_ref,
            "granted_by": self.granted_by,
            "granted_at": self.granted_at,
            "revoked_at": self.revoked_at,
            "active": self.active,
            "notes": self.notes,
        }


def _row(r: sqlite3.Row) -> ConsentRecord:
    return ConsentRecord(
        id=r["id"],
        profile_id=r["profile_id"],
        feature=r["feature"],
        voice_owner=r["voice_owner"],
        consent_ref=r["consent_ref"],
        granted_by=r["granted_by"],
        granted_at=r["granted_at"],
        revoked_at=r["revoked_at"],
        notes=r["notes"],
    )


class ConsentStore:
    """Grant / revoke / query voice-feature consent. Thread-safe."""

    def grant(
        self,
        profile_id: str,
        feature: str,
        *,
        voice_owner: str = "",
        consent_ref: str = "",
        granted_by: str = "",
        notes: str = "",
    ) -> ConsentRecord:
        """Record consent for ``feature`` for an org. Enables the feature."""
        feat = _norm_feature(feature)
        if not profile_id:
            raise ValueError("profile_id is required to grant consent")
        ts = _now()
        with _lock, _connect() as conn:
            cur = conn.execute(
                "INSERT INTO audio_voice_consent "
                "(profile_id, feature, voice_owner, consent_ref, granted_by, granted_at, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (profile_id, feat, voice_owner, consent_ref, granted_by, ts, notes),
            )
            new_id = int(cur.lastrowid)
        return ConsentRecord(
            id=new_id,
            profile_id=profile_id,
            feature=feat,
            voice_owner=voice_owner,
            consent_ref=consent_ref,
            granted_by=granted_by,
            granted_at=ts,
            notes=notes,
        )

    def revoke(self, profile_id: str, feature: str, *, by: str = "") -> int:
        """Revoke all active grants for ``feature``. Returns rows revoked.

        Revocation stamps ``revoked_at`` rather than deleting, so the audit trail
        keeps both the grant and the revocation.
        """
        feat = _norm_feature(feature)
        ts = _now()
        note_suffix = f" [revoked by {by}]" if by else ""
        with _lock, _connect() as conn:
            cur = conn.execute(
                "UPDATE audio_voice_consent SET revoked_at = ?, notes = notes || ? "
                "WHERE profile_id = ? AND feature = ? AND revoked_at = ''",
                (ts, note_suffix, profile_id, feat),
            )
            return int(cur.rowcount)

    def is_enabled(self, profile_id: str, feature: str) -> bool:
        """True iff an active (un-revoked) grant exists. Default: False."""
        try:
            feat = _norm_feature(feature)
        except ValueError:
            return False
        if not profile_id:
            return False
        with _lock, _connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM audio_voice_consent "
                "WHERE profile_id = ? AND feature = ? AND revoked_at = '' LIMIT 1",
                (profile_id, feat),
            ).fetchone()
        return row is not None

    def active(self, profile_id: str) -> list[ConsentRecord]:
        with _lock, _connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLS_SQL} FROM audio_voice_consent "
                "WHERE profile_id = ? AND revoked_at = '' ORDER BY granted_at DESC",
                (profile_id,),
            ).fetchall()
        return [_row(r) for r in rows]

    def history(self, profile_id: str) -> list[ConsentRecord]:
        """The full audit trail for an org — grants and revocations."""
        with _lock, _connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLS_SQL} FROM audio_voice_consent "
                "WHERE profile_id = ? ORDER BY granted_at DESC, id DESC",
                (profile_id,),
            ).fetchall()
        return [_row(r) for r in rows]


def require_consent(profile_id: str, feature: str, *, store: Optional[ConsentStore] = None) -> None:
    """Raise :class:`ConsentRequired` unless ``feature`` is enabled for the org.

    The guard every clone/changer backend must call before synthesising.
    """
    st = store or ConsentStore()
    if not st.is_enabled(profile_id, feature):
        raise ConsentRequired(
            f"voice feature {feature!r} is not enabled for this organisation. "
            "It is off by default and requires recorded consent of the voice "
            "owner (grant it on the Audio settings surface)."
        )


__all__ = [
    "FEATURES",
    "ConsentRequired",
    "ConsentRecord",
    "ConsentStore",
    "require_consent",
]
