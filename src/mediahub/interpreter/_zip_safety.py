"""Defensive limits for ZIP-wrapped meet results.

A Hytek `.zip` export legitimately contains a handful of small `.hy3` /
`.cl2` / `.sd3` text files. We cap members and uncompressed size so a
malicious uploader can't pass a compression bomb (a few-MB ZIP that
decompresses to gigabytes of memory) and crash the worker.

The limits are intentionally generous compared to real-world files —
the biggest legitimate HY3 we've observed in production is ~4 MB
uncompressed for a multi-session championship; we allow up to 64 MB
per member and 128 MB total. Anything beyond that is far outside the
operational envelope and is treated as hostile input.
"""

from __future__ import annotations

import logging
import zipfile
from typing import Iterable

log = logging.getLogger(__name__)

MAX_ZIP_MEMBERS = 64
MAX_MEMBER_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200  # legit Hytek .zip rarely exceeds ~30:1


class UnsafeZipError(ValueError):
    """Raised when a ZIP fails our pre-extraction safety checks."""


def safe_infolist(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Return the ZIP's infolist after enforcing per-archive limits.

    Inspects compressed/uncompressed sizes declared in the central
    directory only — no bytes are read. Members are bounded by both an
    absolute uncompressed size cap and a compression-ratio cap so a
    tiny entry that claims a small uncompressed size but is actually a
    nested bomb still gets rejected. Returns the safe subset; raises
    :class:`UnsafeZipError` if the archive is wholly hostile.
    """
    members = zf.infolist()
    if len(members) > MAX_ZIP_MEMBERS:
        raise UnsafeZipError(f"ZIP contains {len(members)} members (limit {MAX_ZIP_MEMBERS})")
    safe: list[zipfile.ZipInfo] = []
    total = 0
    for info in members:
        if info.is_dir():
            continue
        usize = info.file_size
        csize = info.compress_size or 1
        if usize > MAX_MEMBER_UNCOMPRESSED_BYTES:
            log.warning(
                "ZIP member %r rejected: uncompressed %d > limit %d",
                info.filename,
                usize,
                MAX_MEMBER_UNCOMPRESSED_BYTES,
            )
            continue
        if csize > 0 and (usize // csize) > MAX_COMPRESSION_RATIO:
            log.warning(
                "ZIP member %r rejected: compression ratio %.1f > %d",
                info.filename,
                usize / csize,
                MAX_COMPRESSION_RATIO,
            )
            continue
        if total + usize > MAX_TOTAL_UNCOMPRESSED_BYTES:
            log.warning(
                "ZIP member %r rejected: total uncompressed would exceed %d",
                info.filename,
                MAX_TOTAL_UNCOMPRESSED_BYTES,
            )
            continue
        total += usize
        safe.append(info)
    return safe


def safe_read_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """Read a member's bytes after a final-decompression-time size check.

    `safe_infolist` trusts the central directory; this catches the
    edge case where a member's actual decompressed length exceeds the
    declared `file_size`. We stream through `zf.open` and stop as soon
    as we exceed the per-member cap.
    """
    cap = MAX_MEMBER_UNCOMPRESSED_BYTES
    out = bytearray()
    with zf.open(info, "r") as fp:
        while True:
            remaining = cap - len(out)
            if remaining <= 0:
                raise UnsafeZipError(
                    f"ZIP member {info.filename!r} exceeded {cap} bytes during read"
                )
            chunk = fp.read(min(64 * 1024, remaining + 1))
            if not chunk:
                break
            out.extend(chunk)
            if len(out) > cap:
                raise UnsafeZipError(
                    f"ZIP member {info.filename!r} exceeded {cap} bytes during read"
                )
    return bytes(out)


def safe_member_names(zf: zipfile.ZipFile) -> list[str]:
    """Convenience: like ``zf.namelist()`` but only safe-to-read members."""
    return [info.filename for info in safe_infolist(zf)]


def safe_iter_members(
    zf: zipfile.ZipFile,
    names: Iterable[str] | None = None,
) -> Iterable[tuple[str, bytes]]:
    """Yield ``(name, bytes)`` for safe members, respecting the total cap."""
    safe_set = {info.filename: info for info in safe_infolist(zf)}
    iter_names = list(names) if names is not None else list(safe_set.keys())
    total = 0
    for name in iter_names:
        info = safe_set.get(name)
        if info is None:
            continue
        if total + info.file_size > MAX_TOTAL_UNCOMPRESSED_BYTES:
            log.warning(
                "ZIP iteration halted at %r: total cap %d would be exceeded",
                name,
                MAX_TOTAL_UNCOMPRESSED_BYTES,
            )
            return
        try:
            data = safe_read_member(zf, info)
        except UnsafeZipError as exc:
            log.warning("ZIP read aborted for %r: %s", name, exc)
            continue
        total += len(data)
        yield name, data
