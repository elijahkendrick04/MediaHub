"""/healthz/{memory,breaker,search} must not disclose deployment internals to
anonymous callers (deep-review 2026-07 finding #29).

These three probes were public while their siblings (/healthz/deps,
/healthz/sentinel) already redact or gate their sensitive detail:

* /healthz/breaker leaked ``providers_configured`` — i.e. *which* of the
  GEMINI / ANTHROPIC keys are set on the deployment — plus the circuit-breaker
  counters.
* /healthz/memory leaked process RSS, the OOM-ceiling ratio and the in-memory
  concurrency limits.
* /healthz/search leaked which search backend is live (SearXNG vs DuckDuckGo).

The sensitive detail is now signed-in-operator only (``is_dev_operator()``),
exactly like /healthz/deps' server paths and /healthz/sentinel's audit tail.
Each endpoint stays public and keeps a minimal ``ok`` liveness boolean, so
uptime monitors are unaffected. Gating behind the operator session is only a
real boundary because operator sign-in is password-protected
(ADR-0019) — anonymous visitors cannot become the operator.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def anon_client(app):
    return app.test_client()


@pytest.fixture
def operator_client(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s["dev_operator"] = True
    return c


# ---- anonymous callers get liveness only -------------------------------

# For each endpoint: the fields that must NOT appear for an anonymous caller.
_SENSITIVE_FIELDS = {
    "/healthz/memory": (
        "rss_mb",
        "rss_peak_mb",
        "rss_pct_of_2048",
        "active_runs",
        "active_runs_running",
        "active_runs_limit",
        "turn_into_jobs",
        "turn_into_jobs_limit",
    ),
    "/healthz/breaker": (
        "gemini_breaker",
        "providers_configured",
        "fallback_available",
    ),
    "/healthz/search": (
        "engine",
        "searxng_configured",
        "searxng_reachable",
    ),
}


@pytest.mark.parametrize("path", sorted(_SENSITIVE_FIELDS))
def test_anonymous_gets_ok_and_no_internals(anon_client, path):
    resp = anon_client.get(path)
    assert resp.status_code == 200, (path, resp.status_code)
    assert resp.content_type.startswith("application/json"), resp.content_type
    data = resp.get_json()
    assert data.get("ok") is True, (path, data)
    for field in _SENSITIVE_FIELDS[path]:
        assert field not in data, f"anonymous {path} disclosed {field!r}: {data}"


# ---- the operator still gets the full diagnostic -----------------------


def test_operator_memory_keeps_internals(operator_client):
    data = operator_client.get("/healthz/memory").get_json()
    assert data["ok"] is True
    assert "rss_mb" in data
    assert "active_runs_running" in data


def test_operator_breaker_keeps_internals(operator_client):
    data = operator_client.get("/healthz/breaker").get_json()
    assert data["ok"] is True
    assert "gemini_breaker" in data
    assert "providers_configured" in data


def test_operator_search_keeps_backend(operator_client):
    data = operator_client.get("/healthz/search").get_json()
    assert data["ok"] is True
    assert data["engine"] in ("searxng", "duckduckgo")
