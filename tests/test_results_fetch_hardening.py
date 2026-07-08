"""Step 8 — provenance + hardening for results-from-a-link.

Covers the per-session rate limit, the source_url provenance round-trip (the
sidecar _start_run writes and _run_source_url reads), and the invariant that a
re-fetch stages a brand-new run rather than mutating a finished one.
"""

from __future__ import annotations

import importlib
import json
import re

import pytest


@pytest.fixture
def app_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_RESULTS_FETCH_ENABLED", "1")
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    app.secret_key = "test"
    return app, wm


def _make_zip_html() -> bytes:
    import io
    import zipfile

    html = (
        "<html><body><table><tr><th>Place</th><th>Name</th><th>Time</th></tr>"
        "<tr><td>1</td><td>Ada</td><td>1:02.34</td></tr></table></body></html>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("event1.html", html)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------


def test_rate_limit_returns_429(app_mod, monkeypatch):
    app, wm = app_mod
    monkeypatch.setattr("mediahub.web_research.safe_fetch.is_url_safe", lambda u: True)

    # Keep the started jobs from doing real network work.
    from mediahub.results_fetch.crawl import CrawlResult

    monkeypatch.setattr(
        "mediahub.results_fetch.crawl.crawl_results_site",
        lambda url, **kw: CrawlResult(entry_url=url),
    )

    c = app.test_client()
    statuses = []
    for _ in range(wm._URL_FETCH_RATE_MAX + 2):
        r = c.post("/upload/from-url", data={"url": "https://results.example.org/x/"})
        statuses.append(r.status_code)
    assert statuses[: wm._URL_FETCH_RATE_MAX] == [200] * wm._URL_FETCH_RATE_MAX
    assert 429 in statuses[wm._URL_FETCH_RATE_MAX :]


# ---------------------------------------------------------------------------
# source_url provenance round-trip
# ---------------------------------------------------------------------------


def test_run_source_url_reads_sidecar(app_mod):
    app, wm = app_mod
    run_dir = wm.RUNS_DIR / "abc123abc123"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "source_url.txt").write_text("https://results.example.org/meet/", encoding="utf-8")
    assert wm._run_source_url("abc123abc123") == "https://results.example.org/meet/"
    # absent sidecar → None (a normal file upload)
    (wm.RUNS_DIR / "deadbeefdead").mkdir(parents=True, exist_ok=True)
    assert wm._run_source_url("deadbeefdead") is None


def test_stage_carries_source_url_into_meta(app_mod):
    app, wm = app_mod
    rid = wm._stage_results_zip(_make_zip_html(), "https://results.example.org/meet/2026/", None)
    meta = json.loads((wm.RUNS_DIR / rid / "upload_meta.json").read_text())
    assert meta["source_url"] == "https://results.example.org/meet/2026/"
    assert (wm.RUNS_DIR / rid / "input.bin").exists()


def test_refetch_stages_a_distinct_run(app_mod):
    """A re-fetch must be a NEW run, never a mutation of the previous one."""
    app, wm = app_mod
    url = "https://results.example.org/meet/"
    rid1 = wm._stage_results_zip(_make_zip_html(), url, None)
    rid2 = wm._stage_results_zip(_make_zip_html(), url, None)
    assert rid1 != rid2
    assert (wm.RUNS_DIR / rid1 / "input.bin").exists()
    assert (wm.RUNS_DIR / rid2 / "input.bin").exists()
    # both carry the same origin, independently
    for rid in (rid1, rid2):
        meta = json.loads((wm.RUNS_DIR / rid / "upload_meta.json").read_text())
        assert meta["source_url"] == url


# ---------------------------------------------------------------------------
# Fuzzy club pre-select (Step 7.5)
# ---------------------------------------------------------------------------


def test_best_club_match(app_mod):
    app, wm = app_mod
    clubs = ["City of Leeds", "Otter Swimming Club", "Manchester Aquatics"]
    # exact / case-insensitive
    assert wm._best_club_match(clubs, "otter swimming club") == "Otter Swimming Club"
    # abbreviation ("SC" ↔ "Swimming Club") still resolves
    assert wm._best_club_match(clubs, "Otter SC") == "Otter Swimming Club"
    # substring ("Leeds" ↔ "City of Leeds")
    assert wm._best_club_match(clubs, "Leeds") == "City of Leeds"
    # nothing close enough → no auto-pick (user chooses)
    assert wm._best_club_match(clubs, "Edinburgh Penguins") == ""
    # empty / no clubs are safe
    assert wm._best_club_match([], "Otter") == ""
    assert wm._best_club_match(clubs, "") == ""


def test_configure_preselects_fuzzy_club(app_mod):
    app, wm = app_mod
    import mediahub.web.club_profile as cp
    from mediahub.web.club_profile import ClubProfile

    cp.save_profile(ClubProfile(profile_id="p1", display_name="Otter Swimming Club"))

    rid = "stagedrun001"
    rdir = wm.RUNS_DIR / rid
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "input.bin").write_bytes(b"PK\x03\x04dummy")
    (rdir / "upload_meta.json").write_text(
        json.dumps(
            {
                "clubs": ["City of Leeds", "Otter SC"],
                "meet_name": "Spring Open",
                "n_events": 5,
                "file_byte_size": 9999,
            }
        )
    )

    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "p1"
    body = c.get(f"/upload/configure?run_id={rid}").get_data(as_text=True)
    assert '<option value="Otter SC" selected>' in body
    # and the non-matching club is NOT pre-selected
    assert '<option value="City of Leeds" selected>' not in body


def test_configure_warns_when_no_club_matches(app_mod):
    """The pre-select and its no-match warning now both flow from the single
    shared _best_club_match matcher (the inline SequenceMatcher duplicate was
    removed): an org that matches nothing in the file gets no auto-pick and the
    honest 'none of the clubs … match' heads-up."""
    app, wm = app_mod
    import mediahub.web.club_profile as cp
    from mediahub.web.club_profile import ClubProfile

    cp.save_profile(ClubProfile(profile_id="p9", display_name="Edinburgh Penguins"))
    rid = "stagedrun009"
    rdir = wm.RUNS_DIR / rid
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "input.bin").write_bytes(b"PK\x03\x04dummy")
    (rdir / "upload_meta.json").write_text(
        json.dumps({"clubs": ["City of Leeds", "Otter SC"], "meet_name": "Spring Open"})
    )
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "p9"
    body = c.get(f"/upload/configure?run_id={rid}").get_data(as_text=True)
    # No club is auto-picked — assert neither detected club's option is selected.
    # (Checking the specific club options rather than a bare " selected>" scan,
    # which now also matches the chrome's interface-language <select>.)
    assert '<option value="City of Leeds" selected>' not in body
    assert '<option value="Otter SC" selected>' not in body
    assert "none of the clubs in this" in body
    assert "Edinburgh Penguins" in body


def test_configure_offers_free_text_when_no_clubs_detected(app_mod):
    """A distance-event page can yield zero club names; the club field must
    fall back to a free-text input so the run is never blocked on an empty
    required <select> with nothing to pick."""
    app, wm = app_mod
    rid = "noclubrun001"
    rdir = wm.RUNS_DIR / rid
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "input.bin").write_bytes(b"PK\x03\x04dummy")
    (rdir / "upload_meta.json").write_text(
        json.dumps(
            {
                "clubs": [],  # nothing club-shaped survived the parse
                "meet_name": "1500m Freestyle Final",
                "n_events": 1,
                "file_byte_size": 9999,
            }
        )
    )
    c = app.test_client()
    body = c.get(f"/upload/configure?run_id={rid}").get_data(as_text=True)
    # Free-text input, not an empty dropdown.
    assert '<input type="text" name="club_filter"' in body
    assert '<select name="club_filter"' not in body
    assert "couldn" in body  # the "couldn't read club names" helper note


# ---------------------------------------------------------------------------
# AI-read provenance (Step 8) — read from the mirror's _provenance.json
# ---------------------------------------------------------------------------


def _zip_with_provenance(ai_extractions: list) -> bytes:
    import io
    import zipfile

    prov = {
        "entry_url": "https://results.example.org/x/",
        "counters": {},
        "files": [],
        "ai_extractions": ai_extractions,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("_provenance.json", json.dumps(prov))
        zf.writestr("results.ai.csv", b"place,name,mark\n1,Ada,58.21\n")
    return buf.getvalue()


def test_run_ai_read_sources_reads_provenance(app_mod):
    app, wm = app_mod
    rid = "airead00abcd"
    rdir = wm.RUNS_DIR / rid
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "input.bin").write_bytes(
        _zip_with_provenance(
            [
                {
                    "source_url": "https://results.example.org/r1",
                    "model": "gemini",
                    "tables": 2,
                    "confidence": 0.81,
                }
            ]
        )
    )
    out = wm._run_ai_read_sources(rid)
    assert len(out) == 1 and out[0]["tables"] == 2 and out[0]["model"] == "gemini"
    # a file-upload run (no input.bin) → empty, never raises
    assert wm._run_ai_read_sources("nope00000000") == []


# ---------------------------------------------------------------------------
# Re-fetch route (Step 8)
# ---------------------------------------------------------------------------


def test_refetch_route_starts_new_job(app_mod, monkeypatch):
    app, wm = app_mod
    monkeypatch.setattr("mediahub.web_research.safe_fetch.is_url_safe", lambda u: True)
    from mediahub.results_fetch.crawl import CrawlResult

    monkeypatch.setattr(
        "mediahub.results_fetch.crawl.crawl_results_site",
        lambda url, **kw: CrawlResult(entry_url=url),
    )
    rid = "haslink00001"
    rdir = wm.RUNS_DIR / rid
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "source_url.txt").write_text("https://results.example.org/meet/", encoding="utf-8")
    c = app.test_client()
    r = c.post(f"/runs/{rid}/refetch")
    assert r.status_code == 200
    assert re.fullmatch(r"[0-9a-f]{12}", r.get_json()["job_id"])


# ---------------------------------------------------------------------------
# CSRF: the paste-a-link + re-fetch POSTs are multipart/no-body and live
# OUTSIDE /api/, so with CSRF enforced (the production posture) they must carry
# the X-CSRF-Token header. Without it the before-request guard returns an HTML
# 403 page that the JSON-expecting frontend chokes on with
# "Unexpected token '<', "<h1>Reques"... is not valid JSON". The other tests
# in this file run with CSRF off (TESTING default), so they never saw this.
# ---------------------------------------------------------------------------

_CSRF_TOK = "tok-regression-0123456789ab"


def _enforce_csrf(app):
    app.config["ENFORCE_CSRF"] = True


def test_upload_page_injects_real_csrf_into_link_fetch(app_mod):
    """The rendered 'paste a results link' card must carry a real token, not
    the literal __CSRF__ placeholder, and must send it as X-CSRF-Token."""
    app, wm = app_mod
    c = app.test_client()
    with c.session_transaction() as s:
        s["_csrf"] = _CSRF_TOK
    body = c.get("/upload").get_data(as_text=True)
    assert "__CSRF__" not in body  # placeholder was substituted
    assert "X-CSRF-Token" in body
    assert _CSRF_TOK in body


def test_upload_poller_treats_unknown_as_terminal(app_mod):
    """The url-fetch progress poller must not spin forever on status 'unknown'
    (job gone after a restart/prune): it treats a short streak of 'unknown' as a
    terminal failure and caps consecutive network errors, rather than re-polling
    'Reading the site…' indefinitely."""
    app, wm = app_mod
    html = app.test_client().get("/upload").get_data(as_text=True)
    # The poller branches on the 'unknown' status and fails after a short streak.
    assert "j.status === 'unknown'" in html
    assert "unknownStreak" in html
    # Consecutive network failures are capped (no infinite catch-retry loop).
    assert "errStreak" in html
    # A human-readable terminal message for the lost fetch.
    assert "find this fetch any more" in html


def test_from_url_blocked_without_csrf_but_works_with_header(app_mod, monkeypatch):
    app, wm = app_mod
    _enforce_csrf(app)
    monkeypatch.setattr("mediahub.web_research.safe_fetch.is_url_safe", lambda u: True)
    from mediahub.results_fetch.crawl import CrawlResult

    monkeypatch.setattr(
        "mediahub.results_fetch.crawl.crawl_results_site",
        lambda url, **kw: CrawlResult(entry_url=url),
    )
    c = app.test_client()
    with c.session_transaction() as s:
        s["_csrf"] = _CSRF_TOK

    # No token → blocked (the production failure the user hit).
    blocked = c.post("/upload/from-url", data={"url": "https://results.swimming.org/x/"})
    assert blocked.status_code == 403

    # With the header the frontend now sends → JSON job id, fetch starts.
    ok = c.post(
        "/upload/from-url",
        data={"url": "https://results.swimming.org/x/"},
        headers={"X-CSRF-Token": _CSRF_TOK},
    )
    assert ok.status_code == 200
    assert re.fullmatch(r"[0-9a-f]{12}", ok.get_json()["job_id"])


def test_refetch_blocked_without_csrf_but_works_with_header(app_mod, monkeypatch):
    app, wm = app_mod
    _enforce_csrf(app)
    monkeypatch.setattr("mediahub.web_research.safe_fetch.is_url_safe", lambda u: True)
    from mediahub.results_fetch.crawl import CrawlResult

    monkeypatch.setattr(
        "mediahub.results_fetch.crawl.crawl_results_site",
        lambda url, **kw: CrawlResult(entry_url=url),
    )
    rid = "haslink00003"
    rdir = wm.RUNS_DIR / rid
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "source_url.txt").write_text("https://results.swimming.org/meet/", encoding="utf-8")
    c = app.test_client()
    with c.session_transaction() as s:
        s["_csrf"] = _CSRF_TOK

    assert c.post(f"/runs/{rid}/refetch").status_code == 403
    ok = c.post(f"/runs/{rid}/refetch", headers={"X-CSRF-Token": _CSRF_TOK})
    assert ok.status_code == 200
    assert re.fullmatch(r"[0-9a-f]{12}", ok.get_json()["job_id"])


# ---------------------------------------------------------------------------
# Org-ready gate must content-negotiate: a fetch() to the non-/api/ link
# endpoints (Accept: application/json) gets a JSON 409, never an HTML sign-in
# page (which the frontend would choke on with
# "Unexpected token '<', "<!DOCTYPE "... is not valid JSON").
# ---------------------------------------------------------------------------


def test_from_url_returns_json_409_when_org_not_ready(app_mod):
    app, wm = app_mod
    app.config["ENFORCE_ORG_GATE"] = True  # production posture: gate is live
    c = app.test_client()
    # No ready org pinned. A browser navigation would be redirected to HTML,
    # but a JSON Accept fetch must get a structured 409 it can render inline.
    r = c.post(
        "/upload/from-url",
        data={"url": "https://results.swimming.org/x/"},
        headers={"Accept": "application/json"},
    )
    assert r.status_code == 409
    body = r.get_json()
    assert body["error"] == "organisation_not_ready"
    assert "setup_url" in body
    # And a plain browser POST (HTML Accept) still redirects, unchanged.
    html = c.post("/upload/from-url", data={"url": "https://results.swimming.org/x/"})
    assert html.status_code in (301, 302)


def test_status_endpoint_reports_percent(app_mod):
    """The poll payload carries a numeric percent so the upload page can drive
    its live progress bar."""
    app, wm = app_mod
    job_id = "abcdef012345"
    wm._url_job_set(
        job_id, status="running", phase="fetching", progress="Fetched 5 pages", percent=15
    )
    c = app.test_client()
    r = c.get(f"/api/upload/from-url/{job_id}/status")
    assert r.status_code == 200
    body = r.get_json()
    assert body["percent"] == 15
    assert body["status"] == "running"


def test_status_reports_stall_when_heartbeat_goes_quiet(app_mod):
    """A crawl that hangs (or whose worker is recycled) stops updating its
    heartbeat; the poll must then report a terminal error instead of showing
    'Reading the site…' forever."""
    app, wm = app_mod
    job_id = "feedface0001"
    wm._url_job_set(
        job_id, status="running", phase="fetching", progress="Reading the site…", percent=8
    )
    # Force the heartbeat ancient → stalled.
    with wm._url_jobs_lock:
        wm._url_jobs[job_id]["heartbeat"] = 1.0
    c = app.test_client()
    body = c.get(f"/api/upload/from-url/{job_id}/status").get_json()
    assert body["status"] == "error"
    # F-3: the stalled-crawl message is now customer-facing copy (no operator
    # env-var jargon) that still terminates the poll and points at the fallback.
    err = body["error"].lower()
    assert "didn't finish" in err or "did not finish" in err
    assert "upload" in err  # steers the volunteer to upload the file directly


def test_status_stays_running_when_heartbeat_fresh(app_mod):
    app, wm = app_mod
    job_id = "feedface0002"
    wm._url_job_set(
        job_id, status="running", phase="fetching", progress="Fetched 3 pages", percent=15
    )
    c = app.test_client()
    body = c.get(f"/api/upload/from-url/{job_id}/status").get_json()
    assert body["status"] == "running"  # recent heartbeat → not stalled


def test_refetch_route_rejects_non_link_run(app_mod):
    app, wm = app_mod
    rid = "nolink000001"
    (wm.RUNS_DIR / rid).mkdir(parents=True, exist_ok=True)  # no source_url.txt
    c = app.test_client()
    r = c.post(f"/runs/{rid}/refetch")
    assert r.status_code == 400


def test_refetch_route_404_when_disabled(app_mod, monkeypatch):
    app, wm = app_mod
    monkeypatch.setenv("MEDIAHUB_RESULTS_FETCH_ENABLED", "0")
    rid = "haslink00002"
    rdir = wm.RUNS_DIR / rid
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "source_url.txt").write_text("https://results.example.org/meet/", encoding="utf-8")
    c = app.test_client()
    assert c.post(f"/runs/{rid}/refetch").status_code == 404


# ---------------------------------------------------------------------------
# Review page surfaces the provenance (Source chip + AI-read marker + re-fetch)
# ---------------------------------------------------------------------------


def test_review_shows_source_and_ai_read(app_mod):
    app, wm = app_mod
    rid = "reviewrun001"
    rdir = wm.RUNS_DIR / rid
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "source_url.txt").write_text(
        "https://results.swimming.org/champs/2026/", encoding="utf-8"
    )
    (rdir / "input.bin").write_bytes(
        _zip_with_provenance(
            [
                {
                    "source_url": "https://results.swimming.org/champs/2026/r1",
                    "model": "gemini",
                    "tables": 1,
                    "confidence": 0.74,
                }
            ]
        )
    )
    (wm.RUNS_DIR / f"{rid}.json").write_text(
        json.dumps(
            {
                "meet": {
                    "name": "Spring Champs",
                    "start_date": "2026-03-01",
                    "end_date": "2026-03-02",
                    "course": "SCM",
                    "venue": "Pool",
                },
                "cards": [],
                "trust": {},
                "parse_warnings": [],
                "self_check": {},
                "detector_summary": {},
                "dispatch_log": {},
                "recognition_report": {},
                "profile_display": "Otter SC",
                "our_swim_count": 0,
                "file_name": "champs.zip",
            }
        )
    )
    c = app.test_client()
    body = c.get(f"/review/{rid}").get_data(as_text=True)
    # Source chip → host + link to the full URL
    assert "results.swimming.org" in body
    assert 'href="https://results.swimming.org/champs/2026/"' in body
    # AI-read marker
    assert "AI-read from page" in body
    # one-click re-fetch button
    assert "Re-fetch latest results" in body
    assert f"/runs/{rid}/refetch" in body
