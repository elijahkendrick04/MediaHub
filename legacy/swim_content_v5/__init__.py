"""
swim_content_v5 — Achievement Intelligence Layer (V7.3 deprecation shim).

This package is renamed; use 'recognition' for the generic engine and
'recognition_swim' for swimming detectors.

Old import paths still work via these re-exports.
"""
from __future__ import annotations

import warnings as _warnings
# Don't emit the warning at import time as it breaks a lot of existing imports;
# the shim is silent to keep backward compat clean.

__version__ = "5.0.0"

# All the modules are still here and importable directly
# e.g. from swim_content_v5.schema import Achievement  ← still works
