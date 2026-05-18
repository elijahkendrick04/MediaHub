#!/bin/bash
# MediaHub SessionStart hook for Claude Code on the web.
#
# The remote container ships Node/Python/system libs and a prebaked
# Playwright Chromium binary at /opt/pw-browsers, but it does NOT ship:
#   1. The `playwright` Python package (so `from playwright.sync_api ...`
#      fails — every /healthz/deps probe and graphic_renderer call breaks)
#   2. MediaHub's pip deps from requirements.txt
#   3. MediaHub itself installed in editable mode
#   4. The Remotion node_modules under src/mediahub/remotion (so motion
#      and reel routes return "infra_missing")
#
# This hook installs all four so a fresh session boots ready to render
# graphics and motion. Idempotent: each step short-circuits if already
# satisfied, so re-runs are cheap.
set -euo pipefail

# Only do work in the remote (Claude Code on the web) container; local
# devs control their own venv via `make install` + `make playwright`.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

log() { printf '[session-start] %s\n' "$*"; }

# ---------------------------------------------------------------------------
# 1. Persist env vars for the rest of the session.
# ---------------------------------------------------------------------------
# Playwright looks here for Chromium. The web container prebakes
# /opt/pw-browsers/chromium-1194 (Playwright 1.56's revision).
{
  echo "export PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers"
  echo "export PYTHONPATH=\"$CLAUDE_PROJECT_DIR/src\""
} >> "$CLAUDE_ENV_FILE"
export PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
export PYTHONPATH="$CLAUDE_PROJECT_DIR/src"

# ---------------------------------------------------------------------------
# 2. Install Python deps.
# ---------------------------------------------------------------------------
# pyproject.toml's [render] extra pins playwright>=1.56,<1.58 because
# the bundled Chromium revision must match what's installed on disk.
# We tighten to <1.57 here so the install picks 1.56.x, which matches
# the prebaked /opt/pw-browsers/chromium-1194 and avoids a ~300 MB
# Chromium download on every session boot. If the prebaked revision
# ever changes, the fallback below catches the mismatch and downloads
# the matching Chromium on demand.

# Ubuntu's apt ships some Python packages (blinker, cffi) without the
# RECORD metadata pip needs to uninstall them, so a clean upgrade fails
# with "Cannot uninstall X 1.7.0". --ignore-installed lets pip overwrite
# them. Without this, Flask 3.x install fails (blinker) and rembg's
# onnxruntime / cryptography import fails at runtime (cffi).
log "clearing apt-vs-pip conflicts (blinker, cffi)"
pip install --quiet --no-input --ignore-installed blinker cffi

log "installing Python deps from requirements.txt"
pip install --quiet --no-input -r requirements.txt

# Force the playwright wheel into the 1.56 window if pip resolved it
# higher (requirements.txt allows up to <1.58). Re-running with a
# satisfied constraint is a no-op.
log "pinning playwright to the version that matches prebaked Chromium"
pip install --quiet --no-input 'playwright>=1.56,<1.57'

log "installing MediaHub + dev extras in editable mode"
pip install --quiet --no-input -e '.[dev]'

# ---------------------------------------------------------------------------
# 3. Verify Chromium is reachable; download only if it isn't.
# ---------------------------------------------------------------------------
EXPECTED_EXE="$(python - <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    print(p.chromium.executable_path or "")
PY
)"
if [ -n "$EXPECTED_EXE" ] && [ -f "$EXPECTED_EXE" ]; then
  log "Chromium already present at $EXPECTED_EXE"
else
  log "Chromium missing at '$EXPECTED_EXE' — running playwright install chromium"
  python -m playwright install chromium
fi

# ---------------------------------------------------------------------------
# 4. Remotion node_modules — required for /motion + /reel routes.
# ---------------------------------------------------------------------------
REMOTION_DIR="$CLAUDE_PROJECT_DIR/src/mediahub/remotion"
if [ -d "$REMOTION_DIR/node_modules/remotion" ]; then
  log "Remotion node_modules already present"
else
  log "installing Remotion node_modules"
  (cd "$REMOTION_DIR" && npm install --no-audit --no-fund --loglevel=error)
fi

log "done."
