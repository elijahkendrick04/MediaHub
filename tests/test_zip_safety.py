"""Security regression: ZIP-bomb defences on uploaded meet results.

These tests make sure a hostile uploader cannot pass a compression bomb
through ``interpret_document`` / ``ingest`` and OOM the worker. They run
entirely in-memory with no corpus dependencies.
"""
from __future__ import annotations

import io
import zipfile

import pytest

from mediahub.interpreter import interpret_document
from mediahub.interpreter._zip_safety import (
    MAX_COMPRESSION_RATIO,
    MAX_MEMBER_UNCOMPRESSED_BYTES,
    MAX_TOTAL_UNCOMPRESSED_BYTES,
    MAX_ZIP_MEMBERS,
    UnsafeZipError,
    safe_infolist,
    safe_iter_members,
    safe_member_names,
)


def _benign_zip(payload: bytes = b"A1Hello\nB1Bye\n", name: str = "a.hy3") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, payload)
    return buf.getvalue()


def _bomb_zip(uncompressed_bytes: int, name: str = "results.hy3") -> bytes:
    """Build a deflate-encoded bomb whose member declares ``uncompressed_bytes``."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        with zf.open(name, "w", force_zip64=True) as fp:
            chunk = b"A" * (256 * 1024)
            written = 0
            while written < uncompressed_bytes:
                fp.write(chunk)
                written += len(chunk)
    return buf.getvalue()


def test_safe_infolist_accepts_benign_zip():
    with zipfile.ZipFile(io.BytesIO(_benign_zip())) as zf:
        members = safe_infolist(zf)
    assert [m.filename for m in members] == ["a.hy3"]


def test_safe_infolist_rejects_oversized_member():
    bomb = _bomb_zip(MAX_MEMBER_UNCOMPRESSED_BYTES + 1024)
    with zipfile.ZipFile(io.BytesIO(bomb)) as zf:
        members = safe_infolist(zf)
    assert members == []
    with zipfile.ZipFile(io.BytesIO(bomb)) as zf:
        # iteration also yields nothing
        assert list(safe_iter_members(zf)) == []


def test_safe_infolist_rejects_too_many_members():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(MAX_ZIP_MEMBERS + 4):
            zf.writestr(f"f{i}.hy3", b"A1A\n")
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
        with pytest.raises(UnsafeZipError):
            safe_infolist(zf)


def test_safe_infolist_rejects_high_compression_ratio():
    # ZIP_STORED uncompressed file with a forged-but-believable ratio is
    # already impossible (size == size). To exercise the ratio gate we
    # build a deflate member where the uncompressed:compressed ratio
    # exceeds the cap. The bomb at the per-member size limit naturally
    # has a ratio well above MAX_COMPRESSION_RATIO so the size gate
    # covers it; here we want to assert ratio kicks in for SMALL members
    # that wouldn't trip the absolute size cap.
    # 1 MB of zeros, deflate ratio ~5000:1 — well above 200:1.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr("small.hy3", b"\x00" * (1024 * 1024))
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
        info = zf.infolist()[0]
        # Confirm the ratio is in fact > MAX_COMPRESSION_RATIO; otherwise
        # the gate isn't being exercised.
        assert info.file_size // max(info.compress_size, 1) > MAX_COMPRESSION_RATIO
        members = safe_infolist(zf)
    assert members == []


def test_safe_member_names_matches_infolist():
    with zipfile.ZipFile(io.BytesIO(_benign_zip())) as zf:
        assert safe_member_names(zf) == [m.filename for m in safe_infolist(zf)]


def test_interpret_document_handles_zip_bomb_without_oom():
    """End-to-end: a 1 GB-decompressing ZIP must not crash the parser.

    Pre-fix this allocated ~3.5 GB of RSS; the safe path returns an
    InterpretedMeet with zero events instead.
    """
    bomb = _bomb_zip(MAX_TOTAL_UNCOMPRESSED_BYTES * 2, name="results.hy3")
    # Should complete in well under a second and return an empty meet.
    meet = interpret_document(bomb, hint="zip")
    assert sum(len(ev.swims) for ev in meet.events) == 0
