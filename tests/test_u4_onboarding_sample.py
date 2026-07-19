"""U.4 — first-run onboarding: the fast sample-to-first-content-pack path.

Covers the new ``POST /onboarding/sample`` route and the surfaces that
expose it (upload page, the Create page first-run nudge, the org-setup
preview), plus the sample-run banner on the review page.

The sample path runs the REAL pipeline on the bundled synthetic meet,
stamped to the signed-in org so cards come out in the user's brand. The
heavy ``_start_run`` worker is monkeypatched in these tests — we assert the
route wires it correctly (right org, PB-fetch off, hero club pre-selected)
and writes the sample marker, not that the pipeline itself runs.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest


@pytest.fixture
def world(app, web_module, tmp_path):
    return types.SimpleNamespace(app=app, wm=web_module, tmp=tmp_path)


def _save_ready_org(world, pid="my-club", name="My Club"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id=pid,
            display_name=name,
            brand_voice_summary="A friendly community club that celebrates effort.",
        )
    )
    return pid


def _pin(client, pid):
    with client.session_transaction() as sess:
        sess["active_profile_id"] = pid


def _seed_run(world, run_id, *, profile_id, sample=False, ranked=None):
    """Write a finished run JSON (+ optional sample marker) the review page
    can read for ``profile_id``."""
    runs_dir = world.tmp / "runs_v4"
    runs_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "Riverbend Autumn Sprint Gala"},
        "recognition_report": {"ranked_achievements": ranked or []},
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(data))
    if sample:
        d = runs_dir / run_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "sample.json").write_text(json.dumps({"sample": True}))


# ---------------------------------------------------------------------------
# Route: gating + happy path
# ---------------------------------------------------------------------------


def test_sample_route_requires_ready_org(world):
    """No pinned org → bounced to setup, never silently starting a run."""
    c = world.app.test_client()
    r = c.post("/onboarding/sample", follow_redirects=False)
    assert r.status_code in (301, 302, 303, 307, 308)
    assert "/organisation/setup" in r.headers.get("Location", "")


def test_sample_route_starts_run_in_user_org(world, monkeypatch):
    pid = _save_ready_org(world)
    calls = {}

    def fake_start_run(file_bytes, file_name, profile_id, use_pb_cache, fetch_pbs, **kw):
        calls.update(
            n_bytes=len(file_bytes),
            file_name=file_name,
            profile_id=profile_id,
            use_pb_cache=use_pb_cache,
            fetch_pbs=fetch_pbs,
            club_filter=kw.get("club_filter"),
        )
        return "samp00000001"

    monkeypatch.setattr(world.wm, "_start_run", fake_start_run)

    c = world.app.test_client()
    _pin(c, pid)
    r = c.post("/onboarding/sample", follow_redirects=False)

    assert r.status_code == 302
    assert "/runs/samp00000001" in r.headers["Location"]
    # Stamped to the user's org (their brand), PB web-verification off for
    # synthetic data, and the hero club pre-selected.
    assert calls["profile_id"] == pid
    assert calls["fetch_pbs"] is False
    assert calls["use_pb_cache"] is True
    assert calls["club_filter"] == world.wm._SAMPLE_MEET_CLUB == "Riverbend SC"
    assert calls["file_name"] == world.wm._SAMPLE_MEET_FILENAME
    assert calls["n_bytes"] > 0  # real bundled sample bytes, not empty
    # Marker written so the review page can explain the demo data.
    assert world.wm._run_is_sample("samp00000001") is True


def test_sample_route_honest_404_when_file_missing(world, monkeypatch):
    pid = _save_ready_org(world)
    monkeypatch.setattr(world.wm, "_SAMPLE_MEET_PDF", Path("/no/such/sample.pdf"))
    # _start_run must NOT be called when there's nothing to run.
    monkeypatch.setattr(
        world.wm,
        "_start_run",
        lambda *a, **k: pytest.fail("pipeline started with no sample file"),
    )
    c = world.app.test_client()
    _pin(c, pid)
    r = c.post("/onboarding/sample")
    assert r.status_code == 404
    assert b"Sample meet unavailable" in r.data


def test_sample_route_rejects_get(world):
    pid = _save_ready_org(world)
    c = world.app.test_client()
    _pin(c, pid)
    # POST-only state change; a GET must not start a run.
    assert c.get("/onboarding/sample").status_code == 405


# ---------------------------------------------------------------------------
# Review page: sample banner
# ---------------------------------------------------------------------------


def test_review_shows_sample_banner_for_sample_run(world):
    pid = _save_ready_org(world)
    _seed_run(world, "rsample00001", profile_id=pid, sample=True)
    c = world.app.test_client()
    _pin(c, pid)
    r = c.get("/review/rsample00001")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "the swimmers and clubs are fictional" in html
    assert "Upload real results" in html


def test_review_no_sample_banner_for_normal_run(world):
    pid = _save_ready_org(world)
    _seed_run(world, "rnormal00001", profile_id=pid, sample=False)
    c = world.app.test_client()
    _pin(c, pid)
    r = c.get("/review/rnormal00001")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "the swimmers and clubs are fictional" not in html


# ---------------------------------------------------------------------------
# Surfaces that expose the sample CTA
# ---------------------------------------------------------------------------


def test_upload_page_offers_sample_cta(world):
    pid = _save_ready_org(world)
    c = world.app.test_client()
    _pin(c, pid)
    r = c.get("/upload")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "/onboarding/sample" in html
    assert "Generate a sample pack" in html


def test_make_page_first_run_nudge_present_then_retires(world):
    pid = _save_ready_org(world)
    c = world.app.test_client()
    _pin(c, pid)

    # Brand-new org, no completed runs → first-run nudge is shown.
    r1 = c.get("/make")
    assert r1.status_code == 200
    assert "/onboarding/sample" in r1.get_data(as_text=True)

    # After a real completed run exists, the first-run nudge retires.
    conn = world.wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, 'Real Meet', 'r.hy3')",
        ("realrun00001", pid),
    )
    conn.commit()
    conn.close()

    r2 = c.get("/make")
    assert r2.status_code == 200
    assert "/onboarding/sample" not in r2.get_data(as_text=True)


def test_setup_preview_offers_sample_cta(world, monkeypatch):
    """Once brand capture has run, the setup preview's 'start creating' row
    also offers the one-click sample path."""
    pid = _save_ready_org(world, pid="preview-club", name="Preview Club")
    c = world.app.test_client()
    _pin(c, pid)
    r = c.get("/organisation/setup")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    # The preview block renders only when the pinned org is_ready(); it is.
    assert "/onboarding/sample" in html
    assert "See it on a sample meet" in html


def test_sample_cta_helper_empty_when_sample_missing(world, monkeypatch):
    """When the bundled sample isn't present, surfaces omit the option
    rather than offering a button that 404s."""
    monkeypatch.setattr(world.wm, "_SAMPLE_MEET_PDF", Path("/no/such/sample.pdf"))
    with world.app.test_request_context("/"):
        assert world.wm._sample_pack_cta() == ""
        assert world.wm._sample_pack_cta(compact=True) == ""


def test_upload_page_omits_cta_when_sample_missing(world, monkeypatch):
    pid = _save_ready_org(world)
    monkeypatch.setattr(world.wm, "_SAMPLE_MEET_PDF", Path("/no/such/sample.pdf"))
    c = world.app.test_client()
    _pin(c, pid)
    r = c.get("/upload")
    assert r.status_code == 200
    assert "/onboarding/sample" not in r.get_data(as_text=True)


# ---------------------------------------------------------------------------
# End-to-end: the bundled demo PDF must ACTUALLY run through the real pipeline.
# Every test above monkeypatches _start_run, so none of them prove the sample
# file still parses, detects and ranks. This is the feature's whole promise —
# "watch the whole engine run" — so lock it against a silent regression (a
# corrupt/regenerated PDF, or a parser/detector/ranker change that empties the
# sample pack) with a real run. Web research is stubbed so no third-party call
# fires and the run stays deterministic and offline.
# ---------------------------------------------------------------------------


def test_sample_cta_has_double_submit_guard(world):
    """The CTA button starts a real 30-90s pipeline run, so an accidental
    double-click must not queue two identical demo packs. Both CTA variants
    carry an onsubmit guard that blocks the second submit; with JS off the
    form still posts to /onboarding/sample."""
    with world.app.test_request_context("/"):
        full = world.wm._sample_pack_cta()
        compact = world.wm._sample_pack_cta(compact=True)
    for html in (full, compact):
        assert 'onsubmit="' in html
        assert "this.dataset.mhSent" in html  # blocks the 2nd submit
        assert 'action="/onboarding/sample"' in html  # still posts with JS off


def test_bundled_demo_pdf_produces_a_real_content_pack(world, monkeypatch):
    pytest.importorskip("pdfplumber")
    pdf = world.wm._SAMPLE_MEET_PDF
    if not pdf.exists():
        pytest.skip("bundled demo PDF absent on this checkout")

    # Stub the web-research boundary: meet-identity discovery calls
    # WebResearcher.search, and we must never make an outbound call for a demo.
    import mediahub.web_research.search as _search

    monkeypatch.setattr(_search.WebResearcher, "search", lambda self, q, num=5: [])

    pid = _save_ready_org(world, pid="riverbend", name=world.wm._SAMPLE_MEET_CLUB)
    run = world.wm.run_pipeline_v4(
        file_bytes=pdf.read_bytes(),
        filename=world.wm._SAMPLE_MEET_FILENAME,
        profile_id=pid,
        use_pb_cache=True,
        fetch_pbs=False,
        progress_cb=lambda _m: None,
        run_id="e2esampledemo",
        club_filter=world.wm._SAMPLE_MEET_CLUB,
    )

    # The core promise: an error-free, non-empty pack in the user's org.
    assert run.error is None, f"sample pipeline errored: {run.error}"
    assert run.cards or [], "sample pack produced zero cards"
    rr = run.recognition_report or {}
    assert rr.get("ranked_achievements") or [], "no ranked achievements"
    assert int(rr.get("n_achievements") or 0) > 0
    # Filtered to the hero club, so the pack is about Riverbend swimmers.
    assert world.wm._SAMPLE_MEET_CLUB.split()[0].lower() in (rr.get("meet_name") or "").lower()
