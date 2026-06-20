"""audio/rights.py — rights discipline for the audio engine (roadmap 1.8).

Every piece of audio MediaHub touches carries a licence, and every operator
upload is fingerprinted and attested before it can be laid under a club's
content. That is the "rights discipline" half of 1.8: a small ledger
(``audio_rights`` in the shared ``data.db``) plus a deterministic fingerprint so
the same file is recognised on re-upload and a track's commercial / per-platform
usability is always answerable.

What this is and is not:

* It **is** a first-party licence ledger + an honest duplicate/match check.
* It is **not** a real third-party Content-ID service. A true acoustic match
  against the commercial catalogues is a licensed external integration; until
  one exists this is flagged-honest. The fingerprint here is deterministic and
  local: a Chromaprint acoustic hash when ``fpcalc`` is available (provider
  slot), otherwise a decoded-PCM hash (FFmpeg), otherwise a raw file-byte hash.
  Each is exact enough to catch a re-upload of the *same* file; only the
  Chromaprint tier approaches "different encode of the same recording".

Determinism + honesty: the fingerprint is reproducible, and a missing tool is
reported (in the ``method``), never silently pretended.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from mediahub.audio.library import PLATFORMS, AudioTrack, Licence

_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audio_rights (
    asset_id           TEXT PRIMARY KEY,
    profile_id         TEXT NOT NULL DEFAULT '',
    filename           TEXT NOT NULL DEFAULT '',
    fingerprint        TEXT NOT NULL DEFAULT '',
    fingerprint_method TEXT NOT NULL DEFAULT '',
    content_hash       TEXT NOT NULL DEFAULT '',
    licence_name       TEXT NOT NULL DEFAULT '',
    licence_spdx       TEXT NOT NULL DEFAULT '',
    licence_url        TEXT NOT NULL DEFAULT '',
    attribution        TEXT NOT NULL DEFAULT '',
    licence_source     TEXT NOT NULL DEFAULT '',
    commercial_ok      INTEGER NOT NULL DEFAULT 1,
    platforms          TEXT NOT NULL DEFAULT '',
    attested_by        TEXT NOT NULL DEFAULT '',
    attested_at        TEXT NOT NULL DEFAULT '',
    notes              TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audio_rights_profile ON audio_rights(profile_id);
CREATE INDEX IF NOT EXISTS idx_audio_rights_fp ON audio_rights(fingerprint);
"""

_COLUMNS = (
    "asset_id",
    "profile_id",
    "filename",
    "fingerprint",
    "fingerprint_method",
    "content_hash",
    "licence_name",
    "licence_spdx",
    "licence_url",
    "attribution",
    "licence_source",
    "commercial_ok",
    "platforms",
    "attested_by",
    "attested_at",
    "notes",
)
_COLS_SQL = ", ".join(_COLUMNS)


def _db_path() -> Path:
    """Shared ``data.db`` path, resolved from ``DATA_DIR`` at call time.

    Resolved per-call (not at import) so tests can point ``DATA_DIR`` at a
    tmp_path and get an isolated ledger.
    """
    env = os.environ.get("DATA_DIR")
    base = Path(env) if env else Path(__file__).resolve().parents[1]
    base.mkdir(parents=True, exist_ok=True)
    return base / "data.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


# ---------------------------------------------------------------------------
# Fingerprinting (deterministic; honest about which tier ran)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fingerprint:
    """A deterministic content fingerprint and the method that produced it."""

    value: str
    method: str  # "chromaprint" | "pcm" | "filebytes"


def _fpcalc_exe() -> Optional[str]:
    """The Chromaprint ``fpcalc`` binary, if the operator provides one."""
    explicit = os.environ.get("MEDIAHUB_FPCALC", "").strip()
    if explicit and Path(explicit).is_file():
        return explicit
    return shutil.which("fpcalc")


def content_hash(path: Path) -> str:
    """SHA-256 of the raw file bytes — catches an identical-file re-upload."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _pcm_hash(path: Path) -> Optional[str]:
    """SHA-256 of decoded, normalised PCM (FFmpeg) — survives a re-container.

    Decodes to mono 8 kHz signed-16 raw so two files that differ only by
    container/bitrate hash alike. ``None`` when no FFmpeg binary is available.
    """
    from mediahub.visual.reel_ffmpeg import ffmpeg_exe

    exe = ffmpeg_exe()
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [
                exe,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-ac",
                "1",
                "-ar",
                "8000",
                "-f",
                "s16le",
                "-",
            ],
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    return hashlib.sha256(proc.stdout).hexdigest()


def _chromaprint(path: Path) -> Optional[str]:
    """A Chromaprint acoustic fingerprint via ``fpcalc``, or ``None``."""
    exe = _fpcalc_exe()
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "-plain", str(path)], capture_output=True, text=True, timeout=120
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        return None
    return hashlib.sha256(out.encode("utf-8")).hexdigest()


def fingerprint(path: Path) -> Fingerprint:
    """The best available deterministic fingerprint for ``path``.

    Tiered, strongest first: Chromaprint (acoustic) → decoded-PCM → raw bytes.
    The chosen tier is reported in ``method`` so callers (and the UI) never
    mistake a weak file-byte hash for a true acoustic match.
    """
    p = Path(path)
    chroma = _chromaprint(p)
    if chroma:
        return Fingerprint(chroma, "chromaprint")
    pcm = _pcm_hash(p)
    if pcm:
        return Fingerprint(pcm, "pcm")
    return Fingerprint(content_hash(p), "filebytes")


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------


@dataclass
class RightsRecord:
    """One ledger row — a track and the rights asserted over it."""

    asset_id: str
    profile_id: str = ""
    filename: str = ""
    fingerprint: str = ""
    fingerprint_method: str = ""
    content_hash: str = ""
    licence: Licence = field(default_factory=Licence)
    platforms: tuple[str, ...] = ()
    attested_by: str = ""
    attested_at: str = ""
    notes: str = ""

    def safe_for(self, platform: str) -> bool:
        if not self.licence.commercial_ok:
            return False
        return str(platform).strip().lower() in self.platforms

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "profile_id": self.profile_id,
            "filename": self.filename,
            "fingerprint": self.fingerprint,
            "fingerprint_method": self.fingerprint_method,
            "content_hash": self.content_hash,
            "licence": self.licence.to_dict(),
            "platforms": list(self.platforms),
            "attested_by": self.attested_by,
            "attested_at": self.attested_at,
            "notes": self.notes,
        }


def _row_to_record(row: sqlite3.Row) -> RightsRecord:
    plats = tuple(p for p in (row["platforms"] or "").split(",") if p)
    return RightsRecord(
        asset_id=row["asset_id"],
        profile_id=row["profile_id"],
        filename=row["filename"],
        fingerprint=row["fingerprint"],
        fingerprint_method=row["fingerprint_method"],
        content_hash=row["content_hash"],
        licence=Licence(
            name=row["licence_name"],
            spdx=row["licence_spdx"],
            url=row["licence_url"],
            attribution=row["attribution"],
            source=row["licence_source"],
            commercial_ok=bool(row["commercial_ok"]),
        ),
        platforms=plats,
        attested_by=row["attested_by"],
        attested_at=row["attested_at"],
        notes=row["notes"],
    )


class RightsLedger:
    """CRUD over the ``audio_rights`` table. Thread-safe; index-aware queries."""

    def record(self, rec: RightsRecord) -> RightsRecord:
        """Insert or replace a rights record, stamping ``attested_at`` if unset."""
        if not rec.attested_at:
            rec.attested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        plats = ",".join(
            p for p in (str(x).strip().lower() for x in rec.platforms) if p in PLATFORMS
        )
        values = (
            rec.asset_id,
            rec.profile_id,
            rec.filename,
            rec.fingerprint,
            rec.fingerprint_method,
            rec.content_hash,
            rec.licence.name,
            rec.licence.spdx,
            rec.licence.url,
            rec.licence.attribution,
            rec.licence.source,
            1 if rec.licence.commercial_ok else 0,
            plats,
            rec.attested_by,
            rec.attested_at,
            rec.notes,
        )
        placeholders = ", ".join("?" for _ in _COLUMNS)
        with _lock, _connect() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO audio_rights ({_COLS_SQL}) VALUES ({placeholders})",
                values,
            )
        return rec

    def get(self, asset_id: str) -> Optional[RightsRecord]:
        with _lock, _connect() as conn:
            row = conn.execute(
                f"SELECT {_COLS_SQL} FROM audio_rights WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        return _row_to_record(row) if row else None

    def list_for_profile(self, profile_id: str) -> list[RightsRecord]:
        with _lock, _connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLS_SQL} FROM audio_rights WHERE profile_id = ? "
                "ORDER BY attested_at DESC",
                (profile_id,),
            ).fetchall()
        return [_row_to_record(r) for r in rows]

    def find_by_fingerprint(self, fp: str) -> list[RightsRecord]:
        if not fp:
            return []
        with _lock, _connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLS_SQL} FROM audio_rights WHERE fingerprint = ?", (fp,)
            ).fetchall()
        return [_row_to_record(r) for r in rows]

    def delete(self, asset_id: str) -> bool:
        with _lock, _connect() as conn:
            cur = conn.execute("DELETE FROM audio_rights WHERE asset_id = ?", (asset_id,))
            return cur.rowcount > 0


# ---------------------------------------------------------------------------
# High-level helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UploadCheck:
    """The result of fingerprinting an upload before it enters the ledger."""

    fingerprint: Fingerprint
    content_hash: str
    matches: tuple[RightsRecord, ...]  # existing rows with the same fingerprint

    @property
    def is_duplicate(self) -> bool:
        return bool(self.matches)


def check_upload(path: Path, *, ledger: Optional[RightsLedger] = None) -> UploadCheck:
    """Fingerprint an uploaded file and report any existing ledger matches.

    The web upload route runs this *before* recording, so it can warn "you (or
    another club) already attested this track" and reuse the prior licence.
    """
    led = ledger or RightsLedger()
    fp = fingerprint(path)
    ch = content_hash(path)
    matches = tuple(led.find_by_fingerprint(fp.value))
    return UploadCheck(fingerprint=fp, content_hash=ch, matches=matches)


def attest_upload(
    path: Path,
    *,
    asset_id: str,
    profile_id: str,
    licence: Licence,
    platforms: tuple[str, ...] = PLATFORMS,
    attested_by: str = "",
    notes: str = "",
    ledger: Optional[RightsLedger] = None,
) -> RightsRecord:
    """Fingerprint and record an operator upload with their licence attestation."""
    led = ledger or RightsLedger()
    fp = fingerprint(path)
    rec = RightsRecord(
        asset_id=asset_id,
        profile_id=profile_id,
        filename=Path(path).name,
        fingerprint=fp.value,
        fingerprint_method=fp.method,
        content_hash=content_hash(path),
        licence=licence,
        platforms=tuple(platforms),
        attested_by=attested_by,
        notes=notes,
    )
    return led.record(rec)


def record_for_track(track: AudioTrack, *, ledger: Optional[RightsLedger] = None) -> RightsRecord:
    """Seed the ledger from a bundled/operator :class:`AudioTrack` (no upload)."""
    led = ledger or RightsLedger()
    rec = RightsRecord(
        asset_id=track.id,
        profile_id="",
        filename=track.path.name,
        fingerprint="",
        fingerprint_method="",
        content_hash="",
        licence=track.licence,
        platforms=tuple(sorted(track.platforms)),
        attested_by="bundled" if track.source == "bundled" else track.source,
        notes=f"{track.kind} · {track.source}",
    )
    return led.record(rec)


def safe_for_platform(obj: Any, platform: str) -> bool:
    """True when a track/record/licence is cleared for ``platform`` commercially."""
    plat = str(platform).strip().lower()
    if isinstance(obj, Licence):
        return obj.commercial_ok and plat in PLATFORMS
    if hasattr(obj, "safe_for"):
        return bool(obj.safe_for(plat))
    return False


__all__ = [
    "Fingerprint",
    "RightsRecord",
    "RightsLedger",
    "UploadCheck",
    "content_hash",
    "fingerprint",
    "check_upload",
    "attest_upload",
    "record_for_track",
    "safe_for_platform",
]
