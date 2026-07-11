"""D-32 — the sponsor-variant page must not render + caption synchronously.

GET /runs/<run_id>/card/<card_id>/sponsor-variant used to run the full visual
pipeline plus an LLM caption call before any HTML returned (30–90s cold), said
"Generated on demand — refresh to regenerate", and printed raw
"render_failed: <exception>" text. Now:

* the GET returns the page shell immediately (branded loading state + a
  Regenerate button); the render + caption run via the background job
  (POST …/sponsor-variant-job → poll api_reel_job_status);
* fail-fast gates (tenant, sponsor configured) stay synchronous;
* failures surface plain copy — raw exception text is server-log only;
* a successful render is cached in a per-card sidecar, so the next page GET
  shows the image + caption instantly without a new job.
"""

from __future__ import annotations

import importlib
import json
import time
from pathlib import Path

import pytest


@pytest.fixture
def gated_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True
    return app, tmp_path


def _seed_run(tmp_path: Path, run_id: str, profile_id: str, sponsor: str = "Acme Sports"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id=profile_id,
            display_name="City Aquatics",
            brand_voice_summary="Inclusive community club.",
            sponsor_name=sponsor,
        )
    )
    run = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "Winter Champs", "venue": "Manchester"},
        "recognition_report": {
            "n_achievements": 1,
            "ranked_achievements": [
                {
                    "rank": 1,
                    "priority": 0.95,
                    "achievement": {
                        "swim_id": "swim-1",
                        "swimmer_name": "Emma",
                        "event": "100 Free",
                        "time": "58.21",
                        "type": "pb_confirmed",
                        "pb": True,
                        "headline": "First sub-60",
                    },
                    "factors": [],
                }
            ],
        },
    }
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(run))


def _pin(client, pid="city-aquatics"):
    client.post("/api/organisation/active", data={"profile_id": pid})


def _poll_until(client, poll_url, tries=120, delay=0.05):
    for _ in range(tries):
        j = client.get(poll_url).get_json()
        if j.get("status") in ("done", "error"):
            return j
        time.sleep(delay)
    return client.get(poll_url).get_json()


def _fake_visual(tmp_path, calls=None):
    """A fast create_visual_for_item stub whose PNG really exists (so the
    sidecar cache accepts it)."""
    png = tmp_path / "vis1.png"
    png.write_bytes(b"\x89PNG fake")

    def _fake(item, brand_kit, **kwargs):
        if calls is not None:
            calls["n"] = calls.get("n", 0) + 1
            calls["kwargs"] = kwargs
        return {
            "visuals": [
                {"id": "vis1", "format_name": "feed_portrait", "file_path": str(png)}
            ],
            "errors": [],
        }

    return _fake


def test_shell_returns_immediately_no_sync_render_or_llm(gated_app, monkeypatch):
    app, tmp = gated_app
    import mediahub.web.web as wm

    _seed_run(tmp, "run-1", "city-aquatics")
    render_calls = {"n": 0}
    caption_calls = {"n": 0}
    if wm._v8_ok:
        monkeypatch.setattr(wm, "_v8_create_visual_for_item", _fake_visual(tmp, render_calls))

    def _fake_caption(*a, **k):
        caption_calls["n"] += 1
        return "caption"

    monkeypatch.setattr("mediahub.brand.sponsor.generate_sponsor_caption", _fake_caption)
    with app.test_client() as c:
        _pin(c)
        r = c.get("/runs/run-1/card/swim-1/sponsor-variant")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        # Shell affordances: loading panels, a Regenerate button, the job URL.
        assert 'id="sv-visual"' in body
        assert 'id="sv-caption"' in body
        assert 'id="sv-regen"' in body
        assert "Regenerate" in body
        assert "/api/runs/run-1/card/swim-1/sponsor-variant-job" in body
        # The old copy and the old raw-error surface are gone.
        assert "refresh to regenerate" not in body.lower()
        assert "render_failed" not in body
    # Nothing heavy ran inside the GET.
    assert render_calls["n"] == 0
    assert caption_calls["n"] == 0


def test_job_completes_with_image_and_caption_then_page_serves_cache(
    gated_app, monkeypatch
):
    app, tmp = gated_app
    import mediahub.web.web as wm

    if not wm._v8_ok:
        pytest.skip("v8 engine unavailable")
    _seed_run(tmp, "run-2", "city-aquatics")
    calls = {}
    monkeypatch.setattr(wm, "_v8_create_visual_for_item", _fake_visual(tmp, calls))
    monkeypatch.setattr(
        "mediahub.brand.sponsor.generate_sponsor_caption",
        lambda ach, profile=None: "Emma flew — cheers Acme Sports.",
    )
    with app.test_client() as c:
        _pin(c)
        r = c.post(
            "/api/runs/run-2/card/swim-1/sponsor-variant-job",
            data="{}",
            content_type="application/json",
        )
        assert r.status_code == 202, r.get_data(as_text=True)
        body = r.get_json()
        assert body["ok"] is True and body["poll_url"]
        j = _poll_until(c, body["poll_url"])
        assert j["status"] == "done", j
        assert j["kind"] == "sponsor-variant"
        assert j["image_url"].endswith("/api/visual/vis1/png/feed_portrait")
        assert j["image_message"] == ""
        assert "cheers Acme Sports" in j["caption"]
        assert j["caption_message"] == ""
        assert calls["n"] == 1

        # The sidecar cache now serves the next page GET instantly — the
        # image + caption are inline and no new render happens.
        r2 = c.get("/runs/run-2/card/swim-1/sponsor-variant")
        page = r2.get_data(as_text=True)
        assert "/api/visual/vis1/png/feed_portrait" in page
        assert "cheers Acme Sports" in page
        assert "var autostart = false;" in page
    assert calls["n"] == 1
    # The sidecar lives under the run's own directory (DATA_DIR-derived).
    assert (tmp / "runs_v4" / "run-2" / "sponsor_variants" / "swim-1.json").exists()


def test_cold_page_autostarts_the_job(gated_app):
    app, tmp = gated_app
    _seed_run(tmp, "run-3", "city-aquatics")
    with app.test_client() as c:
        _pin(c)
        page = c.get("/runs/run-3/card/swim-1/sponsor-variant").get_data(as_text=True)
        assert "var autostart = true;" in page


def test_render_failure_surfaces_plain_copy_not_exception(gated_app, monkeypatch):
    app, tmp = gated_app
    import mediahub.web.web as wm

    if not wm._v8_ok:
        pytest.skip("v8 engine unavailable")
    _seed_run(tmp, "run-4", "city-aquatics")

    def _boom(item, brand_kit, **kwargs):
        raise RuntimeError("chromium exploded at frame 3")

    monkeypatch.setattr(wm, "_v8_create_visual_for_item", _boom)
    monkeypatch.setattr(
        "mediahub.brand.sponsor.generate_sponsor_caption",
        lambda ach, profile=None: "still a caption",
    )
    with app.test_client() as c:
        _pin(c)
        r = c.post(
            "/api/runs/run-4/card/swim-1/sponsor-variant-job",
            data="{}",
            content_type="application/json",
        )
        assert r.status_code == 202
        j = _poll_until(c, r.get_json()["poll_url"])
        # The job finishes; the failed half carries plain copy.
        assert j["status"] == "done", j
        assert j["image_url"] == ""
        assert j["image_message"] == "The graphic couldn't be rendered — try again."
        # The raw exception text never reaches the client.
        assert "chromium exploded" not in json.dumps(j)
        # The caption half is independent and still lands.
        assert j["caption"] == "still a caption"
    # A failure is never cached — the next page load retries automatically.
    assert not (tmp / "runs_v4" / "run-4" / "sponsor_variants" / "swim-1.json").exists()
    with app.test_client() as c:
        _pin(c)
        page = c.get("/runs/run-4/card/swim-1/sponsor-variant").get_data(as_text=True)
        assert "var autostart = true;" in page


def test_no_sponsor_configured_fails_fast_400(gated_app):
    app, tmp = gated_app
    _seed_run(tmp, "run-5", "city-aquatics", sponsor="")
    with app.test_client() as c:
        _pin(c)
        r = c.post(
            "/api/runs/run-5/card/swim-1/sponsor-variant-job",
            data="{}",
            content_type="application/json",
        )
        assert r.status_code == 400
        assert "No sponsor is configured" in (r.get_json().get("user_message") or "")


def test_foreign_org_job_post_404(gated_app):
    app, tmp = gated_app
    from mediahub.web.club_profile import ClubProfile, save_profile

    _seed_run(tmp, "run-6", "city-aquatics")
    save_profile(ClubProfile(profile_id="rivals", display_name="Rivals"))
    with app.test_client() as c:
        _pin(c, "rivals")
        r = c.post(
            "/api/runs/run-6/card/swim-1/sponsor-variant-job",
            data="{}",
            content_type="application/json",
        )
        assert r.status_code == 404


def test_unknown_card_404(gated_app):
    app, tmp = gated_app
    _seed_run(tmp, "run-7", "city-aquatics")
    with app.test_client() as c:
        _pin(c)
        r = c.post(
            "/api/runs/run-7/card/no-such-card/sponsor-variant-job",
            data="{}",
            content_type="application/json",
        )
        assert r.status_code == 404


def test_reel_job_status_admits_sponsor_variant_kind_with_idor_gate(gated_app):
    app, _tmp = gated_app
    import mediahub.web.web as wm

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="city-aquatics", display_name="City"))
    save_profile(ClubProfile(profile_id="rivals", display_name="Rivals"))
    wm._variant_job_save(
        {
            "id": "b" * 32,
            "kind": "sponsor-variant",
            "status": "running",
            "owner_pid": "city-aquatics",
        }
    )
    with app.test_client() as c:
        _pin(c, "city-aquatics")
        r = c.get(f"/api/reel-jobs/{'b' * 32}")
        assert r.status_code == 200
        assert r.get_json()["kind"] == "sponsor-variant"
        _pin(c, "rivals")
        assert c.get(f"/api/reel-jobs/{'b' * 32}").status_code == 404


def test_sidecar_written_atomically_for_concurrent_page_gets():
    """CON-5: a concurrent page GET must never read a torn result sidecar —
    a torn read is a cache miss, and a cache miss auto-starts a duplicate
    render job. The write goes through a unique tmp + atomic os.replace
    (the _variant_job_save idiom), never a bare write_text."""
    src = Path("src/mediahub/web/web.py").read_text(encoding="utf-8")
    assert "sidecar.write_text(" not in src
    assert '_sc_tmp = sidecar.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")' in src
    assert "os.replace(_sc_tmp, sidecar)" in src
