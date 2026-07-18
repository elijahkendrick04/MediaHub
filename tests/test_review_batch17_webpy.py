"""Review batch 17 — web.py fixes (IDOR owner-binding + storage-scan dedup).

Pins three findings from the deep code review:

* **#30 (IDOR)** — ``GET /api/upload/from-url/<job_id>/status`` now binds the
  from-url crawl job to its creating session's active org and refuses a foreign
  or unknown id with a 404 that is indistinguishable from a nonexistent job.
  Mirrors the owner gate the sibling reel/variant/export job routes already
  enforce. The creator polling their own job still works, and pre-existing
  ownerless jobs stay readable by a signed-out session (the sibling posture).
* **#20 (cleanup)** — the storage-inventory scan is factored into one
  ``_storage_counts()`` helper used by both the /privacy page and the
  Settings → Privacy & data section, so both surfaces render identical numbers.

Finding #19 (nested run.json fallback blocks) was deliberately left in place —
see the review report for the rationale (each block is a corrupt-flat-but-
nested-present recovery that ``_load_run`` intentionally declines to provide).
"""

from __future__ import annotations

import re

import pytest


@pytest.fixture
def app_mod(web_module, tmp_path, monkeypatch):
    # Read live inside ``_results_url_enabled()`` (a function body, not at import),
    # so setting it here — before the request — suffices; monkeypatch auto-undoes.
    monkeypatch.setenv("MEDIAHUB_RESULTS_FETCH_ENABLED", "1")

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-alpha", display_name="Org Alpha"))
    save_profile(ClubProfile(profile_id="org-beta", display_name="Org Beta"))

    app = web_module.create_app()
    app.config["TESTING"] = True
    return app, web_module, tmp_path


def _pin(client, profile_id):
    """Pin an org as the session's active profile via the real set-active API."""
    r = client.post("/api/organisation/active", data={"profile_id": profile_id})
    assert r.status_code == 200, r.get_json()


# ---------------------------------------------------------------------------
# #30 — from-url job status is owner-bound (IDOR fix)
# ---------------------------------------------------------------------------


def test_start_url_fetch_job_records_owner(app_mod, monkeypatch):
    """Job creation stamps the creating session's active org onto the entry."""
    app, wm, _ = app_mod
    # No thread network: the worker is irrelevant to owner-binding.
    monkeypatch.setattr(wm, "_run_url_fetch_job", lambda *a, **k: None)

    job_id = wm._start_url_fetch_job("https://x.test/r/", "org-alpha")
    assert wm._url_job_get(job_id)["owner_pid"] == "org-alpha"

    # A signed-out creator (no active org) records the empty-owner sentinel,
    # exactly like the sibling job routes (`_active_profile_id() or ""`).
    job_id2 = wm._start_url_fetch_job("https://x.test/r/", None)
    assert wm._url_job_get(job_id2)["owner_pid"] == ""


def test_owner_can_poll_own_job(app_mod):
    """The creator polling their own job still gets the full payload."""
    app, wm, _ = app_mod
    wm._url_job_set(
        "aaaaaaaaaaaa",
        status="done",
        run_id="run-alpha-xyz",
        progress="done",
        percent=100,
        owner_pid="org-alpha",
    )
    c = app.test_client()
    _pin(c, "org-alpha")
    r = c.get("/api/upload/from-url/aaaaaaaaaaaa/status")
    assert r.status_code == 200
    payload = r.get_json()
    assert payload["status"] == "done"
    assert "run-alpha-xyz" in payload["redirect"]


def test_foreign_profile_gets_404_and_no_leak(app_mod):
    """A DIFFERENT org must not learn the job exists, its progress, or run_id."""
    app, wm, _ = app_mod
    wm._url_job_set(
        "bbbbbbbbbbbb",
        status="done",
        run_id="run-alpha-secret",
        progress="Reading the site — page 9 of ~12",
        percent=100,
        owner_pid="org-alpha",
    )
    c = app.test_client()
    _pin(c, "org-beta")
    r = c.get("/api/upload/from-url/bbbbbbbbbbbb/status")
    assert r.status_code == 404
    body = r.get_data(as_text=True)
    # Indistinguishable from a nonexistent id — no existence/progress/run_id leak.
    assert r.get_json() == {"status": "unknown"}
    assert "run-alpha-secret" not in body
    assert "Reading the site" not in body


def test_unknown_job_id_is_404(app_mod):
    """A well-formed but unknown job id is 404 (bad-shape id stays 400)."""
    app, wm, _ = app_mod
    c = app.test_client()
    _pin(c, "org-alpha")
    assert c.get("/api/upload/from-url/0123456789ab/status").status_code == 404
    assert c.get("/api/upload/from-url/notahexid/status").status_code == 400


def test_ownerless_job_tolerated_for_signed_out_but_gated_for_signed_in(app_mod):
    """Pre-existing ownerless jobs (older shape) match the sibling posture:
    readable by a signed-out session, refused to a signed-in org."""
    app, wm, _ = app_mod
    # No owner_pid key at all — the legacy on-disk shape.
    wm._url_job_set("cccccccccccc", status="done", run_id="run-legacy", progress="p", percent=100)

    # Signed-out session (no active org → "") matches the empty owner → 200.
    anon = app.test_client()
    assert anon.get("/api/upload/from-url/cccccccccccc/status").status_code == 200

    # A signed-in org does NOT match an ownerless job → 404 (sibling behaviour).
    signed = app.test_client()
    _pin(signed, "org-alpha")
    assert signed.get("/api/upload/from-url/cccccccccccc/status").status_code == 404


def test_route_end_to_end_owner_gate(app_mod, monkeypatch):
    """Full path: creator starts a job through the route and can poll it; a
    foreign org polling the same job id is refused."""
    app, wm, _ = app_mod
    monkeypatch.setattr(wm, "_run_url_fetch_job", lambda *a, **k: None)
    monkeypatch.setattr("mediahub.web_research.safe_fetch.is_url_safe", lambda u: True)

    creator = app.test_client()
    _pin(creator, "org-alpha")
    r = creator.post("/upload/from-url", data={"url": "https://results.swim.test/agb/"})
    assert r.status_code == 200
    job_id = r.get_json()["job_id"]
    assert re.fullmatch(r"[0-9a-f]{12}", job_id)

    # Creator polls their own job — not 404.
    assert creator.get(f"/api/upload/from-url/{job_id}/status").status_code == 200

    # A different org guessing the id is refused.
    intruder = app.test_client()
    _pin(intruder, "org-beta")
    assert intruder.get(f"/api/upload/from-url/{job_id}/status").status_code == 404


# ---------------------------------------------------------------------------
# #20 — storage-inventory scan factored into one helper
# ---------------------------------------------------------------------------


def test_storage_counts_shape(app_mod):
    app, wm, _ = app_mod
    counts = wm._storage_counts()
    assert set(counts) == {"n_runs", "n_files", "n_uploads", "n_cache"}
    assert all(isinstance(v, int) for v in counts.values())


def test_storage_counts_reflects_disk(app_mod):
    app, wm, tmp_path = app_mod
    runs_dir = tmp_path / "runs_v4"
    (runs_dir / "r1.json").write_text("{}", encoding="utf-8")
    (runs_dir / "r2.json").write_text("{}", encoding="utf-8")
    (runs_dir / "r3.json").write_text("{}", encoding="utf-8")
    (tmp_path / "uploads_v4" / "u1.bin").write_text("x", encoding="utf-8")
    (tmp_path / "uploads_v4" / "u2.bin").write_text("x", encoding="utf-8")
    cache_dir = tmp_path / ".cache" / "pb_lookup"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "c1.json").write_text("{}", encoding="utf-8")

    counts = wm._storage_counts()
    assert counts["n_files"] == 3
    assert counts["n_uploads"] == 2
    assert counts["n_cache"] == 1


def test_storage_counts_failsoft_on_missing_dir(app_mod, monkeypatch):
    """A missing UPLOADS_DIR must degrade to 0, never raise."""
    app, wm, tmp_path = app_mod
    import shutil

    shutil.rmtree(tmp_path / "uploads_v4")
    counts = wm._storage_counts()
    assert counts["n_uploads"] == 0


def test_privacy_page_renders_via_helper(app_mod, monkeypatch):
    """The /privacy inventory renders the numbers from _storage_counts()."""
    app, wm, _ = app_mod
    monkeypatch.setattr(
        wm,
        "_storage_counts",
        lambda: {"n_runs": 4242, "n_files": 1337, "n_uploads": 909, "n_cache": 77},
    )
    c = app.test_client()
    _pin(c, "org-alpha")  # inventory card renders for signed-in sessions
    body = c.get("/privacy").get_data(as_text=True)
    for sentinel in ("4242", "1337", "909", "77"):
        assert sentinel in body


def test_settings_privacy_section_renders_via_helper(app_mod, monkeypatch):
    """The Settings → Privacy & data section renders the SAME helper's numbers,
    proving both surfaces share one scan."""
    app, wm, _ = app_mod
    monkeypatch.setattr(
        wm,
        "_storage_counts",
        lambda: {"n_runs": 5151, "n_files": 2468, "n_uploads": 808, "n_cache": 33},
    )
    c = app.test_client()
    _pin(c, "org-alpha")
    body = c.get("/settings/privacy").get_data(as_text=True)
    for sentinel in ("5151", "2468", "808", "33"):
        assert sentinel in body
