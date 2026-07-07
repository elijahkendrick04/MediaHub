"""Build resilience: the network-dependent, fail-loud Docker steps retry.

The 2026-06-22 Render deploy died at the Piper-voice fetch on a single
``SSL: UNEXPECTED_EOF_WHILE_READING`` with no retry. ``scripts/retry.sh`` is the
shell analog of the Python retry added to ``fetch_piper_voice._get``: it wraps
the other fail-loud build steps (the rembg model preload, ``playwright
install``, the Remotion ``npm install``, and the SearXNG install) so one
transient blip can't red a whole image build — while staying loud-fail once the
attempts are spent.

Fast and hermetic: the shell helper is exercised directly with toy commands, and
the Dockerfile is asserted (text-level) to route those steps through it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RETRY = REPO / "scripts" / "retry.sh"
DOCKERFILE = (REPO / "Dockerfile").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(
    shutil.which("sh") is None, reason="POSIX sh not available in this environment"
)


def _run_retry(args):
    return subprocess.run(
        ["sh", str(RETRY), *args], capture_output=True, text=True
    )


def test_retry_script_exists_and_is_executable():
    assert RETRY.exists(), "scripts/retry.sh must exist"
    # Committed with the exec bit so a plain Dockerfile COPY keeps it runnable.
    assert RETRY.stat().st_mode & 0o111, "retry.sh must be executable"


def test_retry_returns_immediately_on_first_success():
    r = _run_retry(["-s", "0", "true"])
    assert r.returncode == 0, r.stderr


def test_retry_succeeds_after_transient_failures(tmp_path):
    # A command that fails twice then succeeds, driven by a counter file.
    counter = tmp_path / "n"
    flaky = tmp_path / "flaky.sh"
    flaky.write_text(
        "#!/bin/sh\n"
        f'n=$(cat "{counter}" 2>/dev/null || echo 0)\n'
        "n=$((n + 1))\n"
        f'echo "$n" > "{counter}"\n'
        '[ "$n" -ge 3 ]\n'  # exit 0 only on the 3rd invocation
    )
    flaky.chmod(0o755)
    r = _run_retry(["-n", "5", "-s", "0", "sh", str(flaky)])
    assert r.returncode == 0, r.stderr
    assert counter.read_text().strip() == "3"  # recovered on exactly the 3rd try


def test_retry_gives_up_loudly_with_the_commands_status():
    r = _run_retry(["-n", "3", "-s", "0", "sh", "-c", "exit 7"])
    assert r.returncode == 7, r.stderr  # propagates the wrapped command's status
    assert "after 3 attempt" in r.stderr  # and says so, loudly


def test_retry_does_not_loop_forever_and_counts_attempts(tmp_path):
    counter = tmp_path / "n"
    flaky = tmp_path / "always_fail.sh"
    flaky.write_text(
        "#!/bin/sh\n"
        f'n=$(cat "{counter}" 2>/dev/null || echo 0)\n'
        f'echo "$((n + 1))" > "{counter}"\n'
        "exit 1\n"
    )
    flaky.chmod(0o755)
    r = _run_retry(["-n", "4", "-s", "0", "sh", str(flaky)])
    assert r.returncode == 1
    assert counter.read_text().strip() == "4"  # tried exactly `attempts` times


def test_retry_errors_when_no_command_given():
    r = _run_retry(["-n", "2", "-s", "0"])
    assert r.returncode == 2


def test_dockerfile_routes_failloud_network_steps_through_retry():
    """Each named network-dependent step must run via the retry wrapper, and the
    wrapper must be on PATH before the first step that needs it."""
    assert "COPY scripts/retry.sh /usr/local/bin/retry" in DOCKERFILE
    assert 'retry python -c "from rembg import new_session' in DOCKERFILE
    assert "retry playwright install --with-deps chromium" in DOCKERFILE
    # npm ci (not npm install): the remotion lockfile is now committed, so the
    # deploy installs it verbatim for reproducible builds (audit item sub_43-1).
    assert "retry npm ci --no-audit --no-fund" in DOCKERFILE
    # Both SearXNG network installs (requirements + git) go through retry.
    assert DOCKERFILE.count('retry "$SEARXNG_VENV/bin/pip" install') >= 2

    # The retry COPY must precede the rembg/Playwright steps that use it.
    copy_at = DOCKERFILE.index("COPY scripts/retry.sh /usr/local/bin/retry")
    rembg_at = DOCKERFILE.index('retry python -c "from rembg import new_session')
    assert copy_at < rembg_at, "retry must be copied before the steps that call it"
