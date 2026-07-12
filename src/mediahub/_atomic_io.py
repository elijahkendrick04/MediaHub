"""Atomic file writes + cross-process locking.

Small shared primitives for the JSON state sidecars scattered across the app
(run records, workflow/approval sidecars, provenance manifests, revisions).
Under ``gunicorn --workers 2`` on a shared disk two hazards apply:

* **torn read** — a reader catching a half-written file. Eliminated by writing to
  a *unique* same-dir temp file and ``os.replace``-ing it into place, so a reader
  always sees either the whole old file or the whole new one (``os.replace`` is an
  atomic rename within a filesystem).
* **lost update** — two processes doing read-modify-write concurrently, last
  writer wins. Guarded by an advisory ``fcntl.flock`` held around the whole
  load -> mutate -> save (POSIX; a no-op on the rare non-POSIX dev box, where the
  caller's in-process lock still applies).

Several packages already carry their own private copy of the tmp+replace idiom
(``club_platform.stub_pack_store``, ``email_design.store``, ``pb_discovery.cache``,
``log_sentinel.state``); new call sites should prefer these shared helpers.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from pathlib import Path
from typing import Any, Iterator

try:  # POSIX only; the deployment target is Linux
    import fcntl

    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - non-POSIX dev fallback
    _HAVE_FCNTL = False


def unique_tmp(path: Path) -> Path:
    """A per-writer temp sibling of ``path`` (same dir, so ``os.replace`` stays an
    atomic same-filesystem rename). pid + thread id keeps two concurrent writers
    to the same target off each other's temp file — a shared ``.tmp`` name would
    let them clobber."""
    return path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident():x}.tmp")


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write ``text`` to ``path`` atomically (unique temp in the same dir + rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = unique_tmp(path)
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            if tmp.exists():
                tmp.unlink()


def atomic_write_json(path: Path, data: Any, *, indent: int = 2, **dumps_kw: Any) -> None:
    """``json.dumps`` ``data`` and write it to ``path`` atomically."""
    atomic_write_text(path, json.dumps(data, indent=indent, **dumps_kw))


@contextlib.contextmanager
def cross_process_lock(lock_path: Path) -> Iterator[None]:
    """Hold an exclusive advisory lock on ``lock_path`` for the duration of the block.

    Best-effort: a no-op when ``fcntl`` is unavailable. The lock file is only
    ``flock``-ed, never written, so it is safe to leave on disk between runs.
    """
    if not _HAVE_FCNTL:
        yield
        return
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


__all__ = ["atomic_write_text", "atomic_write_json", "cross_process_lock", "unique_tmp"]
