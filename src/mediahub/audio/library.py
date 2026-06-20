"""audio/library.py — the licence-clean music + SFX catalogue (roadmap 1.8).

Reels need sound. Historically MediaHub shipped *no* audio assets and asserted
*no* rights — a music bed only played when the operator pointed
``MEDIAHUB_REEL_MUSIC_DIR`` at files they licensed themselves
(``visual/audio_mux.py``). 1.8 changes that stance deliberately: MediaHub now
ships its **own licence-clean pool** — short SFX, branded idents and simple
ambient beds that are *first-party, synthesised, and dedicated to the public
domain (CC0)* — so a club gets honest, rights-clean sound out of the box, with
every track carrying its licence, its mood/energy tags, and per-platform
usability flags.

This module is the **catalogue**: it reads the bundled manifest plus any
operator-supplied directories and exposes a queryable list of
:class:`AudioTrack`. The actual *judgement* of which track suits a given reel is
``audio/select.py`` (AI, via ``media_ai``); the deterministic content-hash
:meth:`AudioLibrary.pick` here is the honest no-key floor — a stable spread, not
a fabricated "smart" pick. The licence ledger and upload fingerprinting live in
``audio/rights.py``.

Sources, in precedence order (later wins on id collision):

1. **Bundled pool** — ``audio/assets/manifest.json`` (CC0, first-party). Shipped
   in the wheel via ``[tool.setuptools.package-data]``.
2. **Operator library** — ``MEDIAHUB_AUDIO_LIBRARY_DIR``: files plus optional
   ``<track>.json`` sidecars carrying licence/mood metadata.
3. **Legacy reel-music dir** — ``MEDIAHUB_REEL_MUSIC_DIR``: the pre-1.8 bed
   directory, folded in unchanged so existing deployments keep working. Files
   here are treated as operator-supplied (licence "operator-supplied", all
   platforms flagged unknown→allowed), with the historic ``128bpm`` filename /
   ``.bpm`` sidecar tempo convention honoured.

Everything here is deterministic and dependency-free (no DSP, no audio decode):
metadata comes from the manifest / sidecars / filename conventions, never from
inspecting the waveform.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

# The platforms a track can be flagged safe (or unsafe) for. A first-party CC0
# track is safe everywhere; an operator upload's safety depends on the licence
# they attest to (rights.py). Kept as a fixed, known set so the UI and the
# rights checks agree on the vocabulary.
PLATFORMS: tuple[str, ...] = ("instagram", "tiktok", "youtube", "facebook", "linkedin", "x")

KINDS: tuple[str, ...] = ("music", "sfx", "ident")

_AUDIO_SUFFIXES = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac"}

# Operator-declared tempo in a filename, e.g. ``anthem.128bpm.mp3`` — mirrors the
# pre-1.8 ``visual/audio_mux`` convention so legacy beds keep their tempo.
_BPM_RE = re.compile(r"(?:^|[^0-9])(\d{2,3})\s*bpm", re.IGNORECASE)
_BPM_MIN, _BPM_MAX = 40.0, 300.0


@dataclass(frozen=True)
class Licence:
    """The rights metadata that travels with every track.

    ``commercial_ok`` is the single gate the reel pipeline checks before laying a
    bed under a club's (commercial) content — an honest ``False`` keeps a track
    out of automated selection rather than risking a takedown.
    """

    name: str = "operator-supplied"
    spdx: str = ""
    url: str = ""
    attribution: str = ""
    source: str = ""
    commercial_ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "spdx": self.spdx,
            "url": self.url,
            "attribution": self.attribution,
            "source": self.source,
            "commercial_ok": self.commercial_ok,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "Licence":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            name=str(raw.get("name") or "operator-supplied"),
            spdx=str(raw.get("spdx") or ""),
            url=str(raw.get("url") or ""),
            attribution=str(raw.get("attribution") or ""),
            source=str(raw.get("source") or ""),
            commercial_ok=bool(raw.get("commercial_ok", True)),
        )


def _clamp_energy(value: Any) -> int:
    try:
        return max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return 3


def _norm_bpm(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if _BPM_MIN <= v <= _BPM_MAX else None


def _norm_platforms(value: Any) -> frozenset[str]:
    if value is None:
        return frozenset(PLATFORMS)
    if isinstance(value, str):
        items: Iterable[Any] = [value]
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = value
    else:
        return frozenset(PLATFORMS)
    out = {str(p).strip().lower() for p in items if str(p).strip()}
    return frozenset(p for p in out if p in PLATFORMS)


@dataclass(frozen=True)
class AudioTrack:
    """One catalogue entry — music bed, sound effect, or branded ident.

    ``path`` is always an absolute, resolved filesystem path. ``mood`` /
    ``energy`` / ``tags`` feed the AI selector's prompt and the UI's filters;
    ``platforms`` is the safe-to-post set; ``licence`` is the rights record.
    """

    id: str
    path: Path
    title: str
    kind: str = "music"
    mood: tuple[str, ...] = ()
    energy: int = 3
    bpm: Optional[float] = None
    duration_sec: Optional[float] = None
    tags: tuple[str, ...] = ()
    licence: Licence = field(default_factory=Licence)
    platforms: frozenset[str] = field(default_factory=lambda: frozenset(PLATFORMS))
    source: str = "bundled"  # "bundled" | "operator" | "legacy-music-dir"

    def safe_for(self, platform: str) -> bool:
        """True when this track is cleared for ``platform`` and commercially OK."""
        if not self.licence.commercial_ok:
            return False
        return str(platform).strip().lower() in self.platforms

    def to_dict(self, *, include_path: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "mood": list(self.mood),
            "energy": self.energy,
            "bpm": self.bpm,
            "duration_sec": self.duration_sec,
            "tags": list(self.tags),
            "licence": self.licence.to_dict(),
            "platforms": sorted(self.platforms),
            "source": self.source,
        }
        if include_path:
            out["path"] = str(self.path)
        return out


def _track_from_manifest(entry: dict[str, Any], assets_dir: Path) -> Optional[AudioTrack]:
    rel = str(entry.get("file") or "").strip()
    tid = str(entry.get("id") or "").strip()
    if not rel or not tid:
        return None
    path = (assets_dir / rel).resolve()
    return AudioTrack(
        id=tid,
        path=path,
        title=str(entry.get("title") or tid),
        kind=str(entry.get("kind") or "music").strip().lower(),
        mood=tuple(str(m).strip().lower() for m in (entry.get("mood") or []) if str(m).strip()),
        energy=_clamp_energy(entry.get("energy", 3)),
        bpm=_norm_bpm(entry.get("bpm")),
        duration_sec=(
            float(entry["duration_sec"])
            if isinstance(entry.get("duration_sec"), (int, float))
            else None
        ),
        tags=tuple(str(t).strip().lower() for t in (entry.get("tags") or []) if str(t).strip()),
        licence=Licence.from_dict(entry.get("licence")),
        platforms=_norm_platforms(entry.get("platforms")),
        source="bundled",
    )


def assets_dir() -> Path:
    """The bundled-pool directory (``audio/assets``), wheel-packaged."""
    return Path(__file__).resolve().parent / "assets"


def _read_bundled() -> list[AudioTrack]:
    base = assets_dir()
    manifest = base / "manifest.json"
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = raw.get("tracks") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return []
    out: list[AudioTrack] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        track = _track_from_manifest(entry, base)
        if track is not None and track.path.is_file():
            out.append(track)
    return out


def _filename_bpm(path: Path) -> Optional[float]:
    """Operator-declared tempo from the filename or a ``<track>.bpm`` sidecar."""
    m = _BPM_RE.search(path.stem)
    if m:
        v = _norm_bpm(m.group(1))
        if v is not None:
            return v
    side = path.with_name(path.name + ".bpm")
    try:
        if side.is_file():
            return _norm_bpm(side.read_text(encoding="utf-8").strip())
    except OSError:
        pass
    return None


def _track_from_file(path: Path, *, source: str) -> AudioTrack:
    """An operator-supplied file, enriched by an optional ``<file>.json`` sidecar.

    The sidecar mirrors the manifest entry shape (mood/energy/tags/licence/
    platforms); absent it the track is honestly tagged "operator-supplied" with
    no mood and every platform left to the operator's own attestation.
    """
    meta: dict[str, Any] = {}
    sidecar = path.with_suffix(path.suffix + ".json")
    try:
        if sidecar.is_file():
            loaded = json.loads(sidecar.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                meta = loaded
    except (OSError, ValueError):
        meta = {}
    return AudioTrack(
        id=f"{source}:{path.name}",
        path=path.resolve(),
        title=str(meta.get("title") or path.stem.replace("_", " ").replace("-", " ").title()),
        kind=str(meta.get("kind") or ("sfx" if "sfx" in path.stem.lower() else "music")).lower(),
        mood=tuple(str(m).strip().lower() for m in (meta.get("mood") or []) if str(m).strip()),
        energy=_clamp_energy(meta.get("energy", 3)),
        bpm=_norm_bpm(meta.get("bpm")) or _filename_bpm(path),
        duration_sec=(
            float(meta["duration_sec"])
            if isinstance(meta.get("duration_sec"), (int, float))
            else None
        ),
        tags=tuple(str(t).strip().lower() for t in (meta.get("tags") or []) if str(t).strip()),
        licence=Licence.from_dict(meta.get("licence")) if meta.get("licence") else Licence(),
        platforms=_norm_platforms(meta.get("platforms")),
        source=source,
    )


def _read_dir(directory: Path, *, source: str) -> list[AudioTrack]:
    d = Path(directory)
    if not d.is_dir():
        return []
    out: list[AudioTrack] = []
    for p in sorted(d.iterdir(), key=lambda x: x.name):
        if p.is_file() and p.suffix.lower() in _AUDIO_SUFFIXES:
            out.append(_track_from_file(p, source=source))
    return out


def _operator_dirs() -> list[tuple[Path, str]]:
    """The operator-supplied source directories, in precedence order.

    ``MEDIAHUB_AUDIO_LIBRARY_DIR`` is the 1.8 managed library; the legacy
    ``MEDIAHUB_REEL_MUSIC_DIR`` (pre-1.8 bed directory) is folded in unchanged.
    The env vars are read here as literals so they are discoverable by the env
    inventory + secrets scanners.
    """
    pairs: list[tuple[Path, str]] = []
    op = os.environ.get("MEDIAHUB_AUDIO_LIBRARY_DIR", "").strip()
    if op:
        pairs.append((Path(op), "operator"))
    legacy = os.environ.get("MEDIAHUB_REEL_MUSIC_DIR", "").strip()
    if legacy:
        pairs.append((Path(legacy), "legacy-music-dir"))
    return pairs


class AudioLibrary:
    """The merged, queryable audio catalogue.

    Build once (cheap — it only reads JSON + directory listings) and query with
    :meth:`tracks`. Construction is pure and side-effect-free; nothing here
    touches the network or decodes audio.
    """

    def __init__(self, tracks: Optional[list[AudioTrack]] = None) -> None:
        self._tracks: list[AudioTrack] = list(tracks or [])

    @classmethod
    def load(cls, *, include_operator: bool = True) -> "AudioLibrary":
        """The default library: bundled pool + (optionally) operator directories.

        Later sources override earlier ones on an id collision, so an operator can
        shadow a bundled id with their own file of the same id if they choose.
        """
        merged: dict[str, AudioTrack] = {}
        for track in _read_bundled():
            merged[track.id] = track
        if include_operator:
            for directory, source in _operator_dirs():
                for track in _read_dir(directory, source=source):
                    merged[track.id] = track
        return cls(sorted(merged.values(), key=lambda t: (t.kind, t.id)))

    def all(self) -> list[AudioTrack]:
        return list(self._tracks)

    def get(self, track_id: str) -> Optional[AudioTrack]:
        for t in self._tracks:
            if t.id == track_id:
                return t
        return None

    def tracks(
        self,
        *,
        kind: Optional[str] = None,
        mood: Optional[str] = None,
        min_energy: Optional[int] = None,
        max_energy: Optional[int] = None,
        platform: Optional[str] = None,
        commercial_only: bool = False,
    ) -> list[AudioTrack]:
        """Filtered, deterministically-ordered tracks.

        All filters are AND-combined. ``mood`` matches a single tag against the
        track's mood OR tags (case-insensitive). ``platform`` keeps only tracks
        cleared for that platform; ``commercial_only`` drops non-commercial
        licences regardless of platform.
        """
        k = (kind or "").strip().lower() or None
        md = (mood or "").strip().lower() or None
        plat = (platform or "").strip().lower() or None
        out: list[AudioTrack] = []
        for t in self._tracks:
            if k and t.kind != k:
                continue
            if md and md not in t.mood and md not in t.tags:
                continue
            if min_energy is not None and t.energy < min_energy:
                continue
            if max_energy is not None and t.energy > max_energy:
                continue
            if commercial_only and not t.licence.commercial_ok:
                continue
            if plat and not t.safe_for(plat):
                continue
            out.append(t)
        return out

    def pick(self, content_key: str, **filters: Any) -> Optional[AudioTrack]:
        """Deterministic content-hash pick from the filtered pool.

        This is the **honest no-key floor** — a stable spread across the eligible
        tracks (same key → same track), NOT a judgement. The intelligent
        mood-matched pick is ``audio/select.py`` (AI). Returns ``None`` when no
        track survives the filters.
        """
        pool = self.tracks(**filters)
        if not pool:
            return None
        digest = hashlib.sha256((content_key or "").encode("utf-8")).hexdigest()
        return pool[int(digest[:8], 16) % len(pool)]

    def summary(self) -> dict[str, Any]:
        """Explainability snapshot for manifests and the operator console."""
        by_kind: dict[str, int] = {}
        by_source: dict[str, int] = {}
        for t in self._tracks:
            by_kind[t.kind] = by_kind.get(t.kind, 0) + 1
            by_source[t.source] = by_source.get(t.source, 0) + 1
        return {
            "count": len(self._tracks),
            "by_kind": by_kind,
            "by_source": by_source,
            "ids": [t.id for t in self._tracks],
        }


def load_library(*, include_operator: bool = True) -> AudioLibrary:
    """Module-level convenience mirroring :meth:`AudioLibrary.load`."""
    return AudioLibrary.load(include_operator=include_operator)


__all__ = [
    "PLATFORMS",
    "KINDS",
    "Licence",
    "AudioTrack",
    "AudioLibrary",
    "assets_dir",
    "load_library",
]
