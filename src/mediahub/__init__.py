"""MediaHub — sport content automation. Reorganised in V9.

This package re-homes the live MediaHub source under a single namespace:
- src/mediahub/<name>/  is the live, supported code
- legacy/<name>/        is the read-only historical code preserved verbatim

Compatibility shims:
1. We register `mediahub.<name>` under the legacy bare top-level name
   (e.g. `import recognition` resolves to `mediahub.recognition`).
2. We add `<repo_root>/legacy/` to sys.path so `swim_content`, `swim_content_v5`,
   `swim_content_pb`, and `engine_v4` keep importing from their preserved
   sources without modification.
"""
from __future__ import annotations

import sys as _sys
from importlib import import_module as _imp
from pathlib import Path as _Path

# --- 1. Add legacy/ to sys.path so historical packages still import. ---
_THIS = _Path(__file__).resolve()
# repo layout: <root>/src/mediahub/__init__.py → root is parents[2]
_ROOT = _THIS.parents[2]
_LEGACY = _ROOT / "legacy"
if _LEGACY.exists() and str(_LEGACY) not in _sys.path:
    _sys.path.append(str(_LEGACY))

# --- 2. Alias mediahub.<name> as a top-level legacy name. ---
_LEGACY_ALIASES = (
    "recognition",
    "recognition_swim",
    "canonical",
    "interpreter",
    "voice",
    "brand",
    "workflow",
    "club_platform",
    "pb_discovery",
    "context_engine",
    "media_ai",
    "media_library",
    "media_requirements",
    "venue_search",
    "inspiration",
    "creative_brief",
    "graphic_renderer",
    "content_pack",
    "content_pack_visual",
    "web_research",
    "history",
)

for _name in _LEGACY_ALIASES:
    try:
        _mod = _imp(f"mediahub.{_name}")
        _sys.modules.setdefault(_name, _mod)
    except Exception:  # noqa: BLE001
        pass

# Also alias mediahub.web back as `swim_content_v4` for any legacy module that
# still imports it by that name (these mostly live in legacy/, where we don't
# rewrite imports).
try:
    _web = _imp("mediahub.web")
    _sys.modules.setdefault("swim_content_v4", _web)
except Exception:  # noqa: BLE001
    pass
