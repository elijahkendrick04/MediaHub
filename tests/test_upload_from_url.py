"""Step 7 — results-from-a-link product surface (web.py wiring).

The URL path converges with the file-upload path at /upload/configure. These
tests drive a monkeypatched crawler (no network/browser) and assert: URL
validation, the background job lifecycle, staged input.bin + upload_meta.json
(incl. source_url), the redirect to the EXISTING configure step, honest
job-level errors (never a 500), and the kill-switch. The file-upload path is
left byte-for-byte unchanged.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def app_mod(web_module, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RESULTS_FETCH_ENABLED", "1")
    app = web_module.create_app()
    app.config["TESTING"] = True
    return app, web_module


_EVENT_HTML = (
    "<html><body><h3>100m Free</h3><table>"
    "<tr><th>Place</th><th>Name</th><th>Club</th><th>Time</th></tr>"
    "<tr><td>1</td><td>Ada Lovelace</td><td>Brighton Swimming</td><td>1:02.34</td></tr>"
    "<tr><td>2</td><td>Bea Carr</td><td>Wigan Otters</td><td>1:03.11</td></tr>"
    "</table></body></html>"
)


def _fake_crawl_factory(wm, *, empty=False, raises=False):
    from mediahub.results_fetch.crawl import CrawlResult, FileProvenance

    def _fake(url, **kwargs):
        if raises:
            raise RuntimeError("boom in crawl")
        if empty:
            return CrawlResult(entry_url=url, pages_visited=2, kept=0, total_bytes=0)
        return CrawlResult(
            files={"agb/event1.html": _EVENT_HTML.encode()},
            provenance={
                "agb/event1.html": FileProvenance(
                    source_url=url + "event1.html",
                    tier="static",
                    trigger=None,
                    content_type="text/html",
                    fetched_at=0.0,
                )
            },
            entry_url=url,
            pages_visited=3,
            kept=1,
            total_bytes=len(_EVENT_HTML),
        )

    return _fake


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


def test_rejects_non_http_url(app_mod):
    app, wm = app_mod
    c = app.test_client()
    r = c.post("/upload/from-url", data={"url": "not-a-url"})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_rejects_loopback_host(app_mod):
    app, wm = app_mod
    c = app.test_client()
    r = c.post("/upload/from-url", data={"url": "http://127.0.0.1/secret"})
    assert r.status_code == 400  # SSRF guard refuses internal hosts up front


# ---------------------------------------------------------------------------
# Job lifecycle + staging (run the worker synchronously for determinism)
# ---------------------------------------------------------------------------


def test_job_stages_zip_with_source_url(app_mod, monkeypatch):
    app, wm = app_mod
    monkeypatch.setattr(
        "mediahub.results_fetch.crawl.crawl_results_site", _fake_crawl_factory(wm)
    )
    job_id = "abc123def456"
    wm._url_job_set(job_id, status="queued")
    wm._run_url_fetch_job(job_id, "https://results.swim.test/agb/", None)

    entry = wm._url_job_get(job_id)
    assert entry["status"] == "done"
    run_id = entry["run_id"]

    import os

    runs_dir = wm.RUNS_DIR
    assert (runs_dir / run_id / "input.bin").exists()
    meta = json.loads((runs_dir / run_id / "upload_meta.json").read_text())
    assert meta["source_url"] == "https://results.swim.test/agb/"
    assert meta["filename"].endswith(".zip")
    assert "results.swim.test" in meta["filename"]
    assert os.path.getsize(runs_dir / run_id / "input.bin") > 0


def test_status_endpoint_redirects_to_configure(app_mod, monkeypatch):
    app, wm = app_mod
    monkeypatch.setattr(
        "mediahub.results_fetch.crawl.crawl_results_site", _fake_crawl_factory(wm)
    )
    job_id = "0123456789ab"
    wm._url_job_set(job_id, status="queued")
    wm._run_url_fetch_job(job_id, "https://results.swim.test/agb/", None)

    c = app.test_client()
    r = c.get(f"/api/upload/from-url/{job_id}/status")
    assert r.status_code == 200
    payload = r.get_json()
    assert payload["status"] == "done"
    assert "/upload/configure" in payload["redirect"]
    assert wm._url_job_get(job_id)["run_id"] in payload["redirect"]


def test_job_progress_percent_reflects_live_frontier(app_mod, monkeypatch):
    """The fetching-phase percent is driven by the crawl's live ``CrawlProgress``
    (fraction of the discovered frontier read), and the status text uses the
    'page N of ~M · K with results' shape the redesigned UI parses."""
    app, wm = app_mod
    from mediahub.results_fetch.crawl import CrawlProgress, CrawlResult, FileProvenance

    def _fake(url, **kwargs):
        cb = kwargs.get("progress_cb")
        if cb is not None:
            cb(
                CrawlProgress(
                    pages_visited=8,
                    kept=6,
                    total_bytes=4096,
                    frontier_remaining=2,
                    discovered_total=10,
                )
            )
        return CrawlResult(
            files={"agb/e1.html": _EVENT_HTML.encode()},
            provenance={
                "agb/e1.html": FileProvenance(
                    source_url=url + "e1",
                    tier="static",
                    trigger=None,
                    content_type="text/html",
                    fetched_at=0.0,
                )
            },
            entry_url=url,
            pages_visited=10,
            kept=1,
            total_bytes=len(_EVENT_HTML),
        )

    monkeypatch.setattr("mediahub.results_fetch.crawl.crawl_results_site", _fake)

    calls: list[dict] = []
    orig_set = wm._url_job_set

    def _recording_set(job_id, **fields):
        calls.append(dict(fields))
        return orig_set(job_id, **fields)

    monkeypatch.setattr(wm, "_url_job_set", _recording_set)

    job_id = "abc123abc123"
    wm._url_job_set(job_id, status="queued")
    wm._run_url_fetch_job(job_id, "https://results.swim.test/agb/", None)

    fetching = [c for c in calls if c.get("phase") == "fetching"]
    assert fetching, "no fetching-phase progress was emitted"
    snap = fetching[-1]
    # 8 of 10 frontier read → ~59%, inside the fetching band, never the full bar.
    assert 8 <= snap["percent"] <= 72
    assert "page 8 of ~10" in snap["progress"]
    assert "6 with results" in snap["progress"]
    # The job still completes and the bar reaches 100 at done.
    assert wm._url_job_get(job_id)["status"] == "done"
    assert wm._url_job_get(job_id)["percent"] == 100


def test_route_starts_background_job(app_mod, monkeypatch):
    app, wm = app_mod
    monkeypatch.setattr(
        "mediahub.results_fetch.crawl.crawl_results_site", _fake_crawl_factory(wm)
    )
    # The fake test domain doesn't resolve; the route's SSRF check does real DNS,
    # so stub it true (the crawl itself is mocked and re-validates every fetch).
    monkeypatch.setattr("mediahub.web_research.safe_fetch.is_url_safe", lambda u: True)
    c = app.test_client()
    r = c.post("/upload/from-url", data={"url": "https://results.swim.test/agb/"})
    assert r.status_code == 200
    job_id = r.get_json()["job_id"]
    import re

    assert re.fullmatch(r"[0-9a-f]{12}", job_id)


def test_rate_limit_not_dodgeable_by_fresh_sessions_same_ip(app_mod, monkeypatch):
    """The crawl rate limit must key on identity/IP, NOT a client-resettable
    session value — otherwise a fresh session per request dodges the cap. With a
    constant client IP, a new test client (fresh session) each call still 429s
    once the 6/5-min budget is spent."""
    app, wm = app_mod
    monkeypatch.setattr(
        "mediahub.results_fetch.crawl.crawl_results_site", _fake_crawl_factory(wm)
    )
    monkeypatch.setattr("mediahub.web_research.safe_fetch.is_url_safe", lambda u: True)
    wm._url_fetch_rate.clear()

    codes = []
    for _ in range(8):
        # A brand-new client each iteration = a fresh (empty) session cookie.
        c = app.test_client()
        r = c.post(
            "/upload/from-url",
            data={"url": "https://results.swim.test/agb/"},
            environ_overrides={"REMOTE_ADDR": "203.0.113.7"},
        )
        codes.append(r.status_code)
    # First 6 succeed (the anonymous IP bucket), the rest are throttled.
    assert codes[:6] == [200] * 6
    assert codes[6] == 429 and codes[7] == 429


# ---------------------------------------------------------------------------
# Honest failures — job error, never a 500
# ---------------------------------------------------------------------------


def test_crawl_exception_becomes_job_error(app_mod, monkeypatch):
    app, wm = app_mod
    monkeypatch.setattr(
        "mediahub.results_fetch.crawl.crawl_results_site",
        _fake_crawl_factory(wm, raises=True),
    )
    job_id = "ffffffffffff"
    wm._url_job_set(job_id, status="queued")
    wm._run_url_fetch_job(job_id, "https://x.test/r/", None)  # must not raise
    entry = wm._url_job_get(job_id)
    assert entry["status"] == "error"
    assert entry["error"]


def test_empty_crawl_errors_clearly(app_mod, monkeypatch):
    app, wm = app_mod
    monkeypatch.setattr(
        "mediahub.results_fetch.crawl.crawl_results_site",
        _fake_crawl_factory(wm, empty=True),
    )
    job_id = "aaaaaaaaaaaa"
    wm._url_job_set(job_id, status="queued")
    wm._run_url_fetch_job(job_id, "https://x.test/r/", None)
    entry = wm._url_job_get(job_id)
    assert entry["status"] == "error"
    assert "No competition results" in entry["error"]


def test_zero_kept_landing_page_errors_with_diagnostics(app_mod, monkeypatch):
    """A crawl that records only the entry landing page (kept == 0, but files is
    non-empty so is_empty is False) must surface an honest 'no results' error —
    not silently stage the landing page — and the error must carry the entry-page
    diagnostics (tier, exact final_url, links found, links in scope) so a
    scope/discovery miss is debuggable from the status endpoint."""
    from mediahub.results_fetch.crawl import CrawlResult, FileProvenance

    def _fake(url, **kwargs):
        # One landing page recorded (is_empty False), nothing kept.
        return CrawlResult(
            files={"champs/index.html": b"<html></html>"},
            provenance={
                "champs/index.html": FileProvenance(
                    source_url=url,
                    tier="rendered",
                    trigger="js_shell",
                    content_type="text/html",
                    fetched_at=0.0,
                )
            },
            entry_url=url,
            pages_visited=1,
            kept=0,
            total_bytes=12,
            entry_tier="rendered",
            entry_final_url=url.rstrip("/") + "#results",
            entry_links_found=41,
            entry_links_in_scope=0,
        )

    monkeypatch.setattr("mediahub.results_fetch.crawl.crawl_results_site", _fake)
    job_id = "bbbbbbbbbbbb"
    wm = app_mod[1]
    wm._url_job_set(job_id, status="queued")
    wm._run_url_fetch_job(job_id, "https://meet.test/2025/champs/", None)

    entry = wm._url_job_get(job_id)
    assert entry["status"] == "error"
    err = entry["error"]
    assert "No competition results" in err
    assert "diagnostics" in err
    assert "tier=rendered" in err
    assert "https://meet.test/2025/champs#results" in err  # exact final_url
    assert "links found=41" in err
    assert "in scope=0" in err


def test_unknown_job_status_is_404(app_mod):
    app, wm = app_mod
    c = app.test_client()
    assert c.get("/api/upload/from-url/0123456789ab/status").status_code == 404
    assert c.get("/api/upload/from-url/bad/status").status_code == 400  # bad id shape


# ---------------------------------------------------------------------------
# Cross-worker job state — gunicorn runs --workers 2 (Bug A pinning test)
# ---------------------------------------------------------------------------


def test_job_state_survives_a_second_worker(app_mod):
    """A status poll that lands on a worker without the job in memory must still
    resolve it from shared disk — the crawl thread runs in one worker but the
    load-balanced /status route can hit either. Clearing the in-memory dict
    simulates that sibling worker."""
    app, wm = app_mod
    job_id = "0123456789ab"
    wm._url_job_set(job_id, status="reading", progress="Reading the site", run_id="run-xyz")

    # Simulate a second gunicorn worker: it never saw this job in its own memory.
    wm._url_jobs.clear()
    assert job_id not in wm._url_jobs

    entry = wm._url_job_get(job_id)
    assert entry is not None  # before the fix this was None → 404 / "status unknown"
    assert entry["status"] == "reading"
    assert entry["progress"] == "Reading the site"
    assert entry["run_id"] == "run-xyz"


def test_prune_reaps_stale_running_job_files(app_mod):
    """A worker crash mid-crawl leaves a 'running' status file that the
    finished-only sweep never deletes; once the dir exceeds the cap it would
    grow unbounded. Prune must also drop files whose heartbeat is quiet well
    past the stall guard, while keeping a freshly-heartbeating running job."""
    app, wm = app_mod
    d = wm._url_jobs_dir()
    d.mkdir(parents=True, exist_ok=True)
    now = wm.time.time()
    stale = now - (wm._URL_JOB_STALL_S * 2 + 60)

    # Push the dir over the cap with old 'done' files so prune actually runs.
    for i in range(wm._URL_JOBS_MAX + 5):
        (d / f"done{i:03d}00ab.json").write_text(
            json.dumps({"status": "done", "heartbeat": now - 1000}), encoding="utf-8"
        )
    # A wedged 'running' job whose heartbeat went cold long ago.
    (d / "stalerun0001.json").write_text(
        json.dumps({"status": "running", "heartbeat": stale}), encoding="utf-8"
    )
    # A genuinely alive 'running' job heartbeating right now.
    (d / "liverun00002.json").write_text(
        json.dumps({"status": "running", "heartbeat": now}), encoding="utf-8"
    )

    wm._url_jobs_files_prune()

    names = {p.name for p in d.glob("*.json")}
    assert "stalerun0001.json" not in names, "wedged running file must be reaped"
    assert "liverun00002.json" in names, "a live heartbeating job must be kept"


# ---------------------------------------------------------------------------
# Kill-switch + file-upload path unchanged
# ---------------------------------------------------------------------------


def test_kill_switch_hides_input_and_404s_route(web_module, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RESULTS_FETCH_ENABLED", "0")
    app = web_module.create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    assert "mh-url-input" not in c.get("/upload").get_data(as_text=True)
    assert c.post("/upload/from-url", data={"url": "https://x.test/"}).status_code == 404


def test_file_upload_path_still_works(app_mod):
    app, wm = app_mod
    c = app.test_client()
    # GET still renders; POST with a file still stages + redirects to configure
    assert c.get("/upload").status_code == 200
    import io

    data = {"file": (io.BytesIO(_EVENT_HTML.encode()), "meet.html")}
    r = c.post("/upload", data=data, content_type="multipart/form-data")
    assert r.status_code in (302, 303)
    assert "/upload/configure" in r.headers["Location"]
