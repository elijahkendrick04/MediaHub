"""P0.5 — AGPL services stay behind a network boundary, never embedded.

Policy (docs/DEPENDENCY_LICENSING.md §3): AGPL-3.0 code (SearXNG, Postiz,
MinIO, MediaCMS) may run as a separate, unmodified service that MediaHub
queries over HTTP — it must never be imported into MediaHub's process or
vendored into this repo, because network-copyleft obligations would then
attach to MediaHub's own source.

The one AGPL service actually deployed today is SearXNG: the Dockerfile
installs it stock into an ISOLATED virtualenv and the app only ever talks
to it via ``requests`` (web_research/searxng_client.py). These guards keep
that boundary from eroding silently.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "mediahub"

# Python module names of known-AGPL services. Importing ANY of these
# in-process is an isolation breach regardless of how it got installed.
_AGPL_MODULES = ("searx", "postiz", "mediacms")

# Distribution names that must never appear as a MediaHub Python dependency.
# `minio` is the official client SDK (Apache-2.0) for the AGPL MinIO server —
# listed because the standing policy is "prefer cloud S3 over MinIO"; adding
# it should be a deliberate, reviewed decision, not a drive-by import.
_AGPL_DENYLIST = ("searxng", "searx", "postiz", "mediacms", "minio")


def _py_sources():
    for py in SRC.rglob("*.py"):
        if "node_modules" in py.parts:
            continue
        yield py


def test_no_agpl_module_is_imported_in_process():
    pattern = re.compile(
        r"^\s*(?:import|from)\s+(" + "|".join(_AGPL_MODULES) + r")\b",
        re.MULTILINE,
    )
    offenders = []
    for py in _py_sources():
        if pattern.search(py.read_text(encoding="utf-8", errors="ignore")):
            offenders.append(str(py.relative_to(REPO)))
    assert not offenders, (
        f"AGPL service modules imported in-process: {offenders}. "
        "Call the service over HTTP across a network boundary instead "
        "(docs/DEPENDENCY_LICENSING.md §3)."
    )


def test_no_agpl_distribution_in_dependency_manifests():
    dep_re = re.compile(
        r"^\s*[\"']?(" + "|".join(_AGPL_DENYLIST) + r")\s*[><=~!\[\"']",
        re.IGNORECASE | re.MULTILINE,
    )
    for manifest in (REPO / "requirements.txt", REPO / "pyproject.toml"):
        text = manifest.read_text(encoding="utf-8")
        m = dep_re.search(text)
        assert m is None, (
            f"{manifest.name} declares {m.group(1)!r} — AGPL services are "
            "consumed over a network boundary, never as a Python dependency "
            "(docs/DEPENDENCY_LICENSING.md §3)."
        )


def test_dockerfile_keeps_searxng_in_its_isolated_venv():
    """Every line that pip-installs SearXNG must do so through the isolated
    $SEARXNG_VENV interpreter — never the main environment's pip."""
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    assert (
        "SEARXNG_VENV" in dockerfile
    ), "Dockerfile lost the isolated SearXNG virtualenv arrangement"
    for line in dockerfile.splitlines():
        if "searxng/searxng" in line and "pip install" in line.replace("  ", " "):
            assert "SEARXNG_VENV" in line, (
                "SearXNG must be installed via $SEARXNG_VENV/bin/pip, "
                f"not the main environment: {line.strip()!r}"
            )


def test_searxng_client_is_http_only():
    """The client module reaches SearXNG exclusively over HTTP (requests +
    an endpoint env var) — belt-and-braces on top of the global import scan."""
    client = (SRC / "web_research" / "searxng_client.py").read_text(encoding="utf-8")
    assert "MEDIAHUB_SEARCH_ENDPOINT" in client
    assert not re.search(r"^\s*(?:import|from)\s+searx\b", client, re.MULTILINE)
