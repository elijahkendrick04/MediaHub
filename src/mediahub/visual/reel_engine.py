"""Engine selection seam for motion-graphic / reel rendering.

Reads ``MEDIAHUB_REEL_ENGINE`` to select the render backend.
Default: ``'remotion'`` — the Node/Remotion pipeline; behaviour is
byte-identical to the pre-seam code when the variable is unset.

Currently registered engines
-----------------------------
remotion  Production-ready Node/Remotion render pipeline (default).
satori    Future Satori+FFmpeg path; raises :exc:`ReelEngineUnavailable`
          until it ships.  Never emits a fake/placeholder asset —
          CLAUDE.md requires an honest error instead.
"""

from __future__ import annotations

import os

_VALID_ENGINES: frozenset[str] = frozenset({"remotion", "satori"})
_DEFAULT_ENGINE: str = "remotion"


class ReelEngineUnavailable(RuntimeError):
    """Raised when the configured render engine cannot service the request.

    Callers must surface this as an honest operator error and must never
    substitute a fake or placeholder asset.
    """


def select_reel_engine() -> str:
    """Return the active render-engine name.

    Reads ``MEDIAHUB_REEL_ENGINE``, strips whitespace, normalises to
    lowercase, and returns the engine name.  Returns ``'remotion'`` when
    the variable is unset or blank so the default render path is
    byte-identical to the pre-seam behaviour.

    Raises :exc:`ReelEngineUnavailable` for unrecognised values so the
    operator sees an honest configuration error rather than a silent
    wrong-engine render.
    """
    raw = os.environ.get("MEDIAHUB_REEL_ENGINE", "").strip().lower()
    if not raw:
        return _DEFAULT_ENGINE
    if raw not in _VALID_ENGINES:
        raise ReelEngineUnavailable(
            f"MEDIAHUB_REEL_ENGINE={raw!r} is not a recognised engine. "
            f"Valid choices: {sorted(_VALID_ENGINES)}. "
            "Unset the variable or set it to 'remotion' to use the "
            "production Remotion renderer."
        )
    return raw


def reel_engine_status() -> dict:
    """Return a diagnostics dict suitable for health / observability surfaces.

    Keys
    ----
    configured         Raw value of ``MEDIAHUB_REEL_ENGINE`` (empty string
                       when the variable is unset).
    active             Resolved engine name, e.g. ``'remotion'``.  When the
                       configured value is unrecognised this echoes the raw
                       value verbatim so the operator can see the bad input.
    remotion_available ``True`` when both ``node`` is on PATH and Remotion's
                       ``node_modules`` are present alongside the render script.
    satori_available   Always ``False`` until the Satori engine ships.
    available_engines  List of engine names that would succeed right now.
    """
    import shutil
    from pathlib import Path as _Path

    configured = os.environ.get("MEDIAHUB_REEL_ENGINE", "").strip()
    try:
        active = select_reel_engine()
    except ReelEngineUnavailable:
        active = configured  # surface bad value verbatim

    node_ok = shutil.which("node") is not None
    remotion_dir = _Path(__file__).resolve().parents[1] / "remotion"
    remotion_ok = node_ok and (remotion_dir / "node_modules" / "remotion").exists()
    satori_ok = False  # not yet implemented

    available: list[str] = []
    if remotion_ok:
        available.append("remotion")

    return {
        "configured": configured,
        "active": active,
        "remotion_available": remotion_ok,
        "satori_available": satori_ok,
        "available_engines": available,
    }


__all__ = [
    "select_reel_engine",
    "reel_engine_status",
    "ReelEngineUnavailable",
]
