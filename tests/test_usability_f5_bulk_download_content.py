"""F-5 — the review bulk bar must offer postable content, not only dev JSON.

The prominent bulk "Export" returned a machine-readable JSON dump (rank,
quality_band, factors, status) — useless to a social-media volunteer, who
expects the images + captions the per-card Download button gives. The bulk bar
now leads with "Download content (.zip)" (caption + visual per card) and keeps
the JSON as a de-emphasised "Export data (JSON)" ghost button.
"""

from __future__ import annotations

import importlib
import io
import json
import uuid
import zipfile

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
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
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-test", display_name="Test Club"))
    save_profile(ClubProfile(profile_id="org-other", display_name="Other Club"))

    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        client.post("/api/organisation/active", data={"profile_id": "org-test"})
        yield {"client": client, "wm": wm, "tmp_path": tmp_path, "app": app}


def _seed_run(tmp_path, profile_id, swim_ids, *, visual_for=None):
    run_id = "run-f5-" + uuid.uuid4().hex[:8]
    # A real 1x1 PNG so the ZIP carries actual bytes for the card with a visual.
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000154a24f9f0000000049454e44ae426082"
    )
    vis_dir = tmp_path / "runs_v4" / run_id / "visuals"
    vis_dir.mkdir(parents=True, exist_ok=True)
    ranked = []
    for i, s in enumerate(swim_ids):
        ach = {
            "swim_id": s,
            "swimmer_name": f"Swimmer {i}",
            "event": "100 Free",
            "headline": f"PB for Swimmer {i}",
            "type": "pb",
            "confidence_label": "high",
        }
        ra = {"rank": i + 1, "achievement": ach, "quality_band": "elite"}
        if visual_for and s in visual_for:
            fp = vis_dir / f"{s}_story.png"
            fp.write_bytes(png)
            ra["visuals"] = [{"file_path": str(fp)}]
        ranked.append(ra)
    payload = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "F5 BULK TEST"},
        "cards": [{"card_id": f"card-{s}", "swim_id": s, "id": f"card-{s}"} for s in swim_ids],
        "recognition_report": {"ranked_achievements": ranked, "n_achievements": len(swim_ids)},
    }
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(payload))
    return run_id


def test_bulk_download_zips_caption_and_visual_per_card(env):
    run_id = _seed_run(env["tmp_path"], "org-test", ["s0", "s1", "s2"], visual_for={"s0"})
    r = env["client"].post(f"/api/runs/{run_id}/cards/bulk-download", json={"ids": ["s0", "s2"]})
    assert r.status_code == 200
    assert r.mimetype == "application/zip"
    assert "attachment" in r.headers.get("Content-Disposition", "")

    zf = zipfile.ZipFile(io.BytesIO(r.data))
    names = zf.namelist()
    # A folder per selected card, each with the ready-to-post caption.
    caption_files = [n for n in names if n.endswith("-caption.txt")]
    assert len(caption_files) == 2
    # The card with a rendered visual carries its PNG; the one without doesn't.
    assert any(n.endswith(".png") for n in names)
    assert "README.txt" in names
    # The caption is the human/headline text, not raw JSON.
    body = zf.read(caption_files[0]).decode()
    assert "Swimmer" in body
    # The unselected card (s1) never appears.
    assert not any("Swimmer 1" in zf.read(c).decode() for c in caption_files)


def test_bulk_download_empty_selection_400(env):
    run_id = _seed_run(env["tmp_path"], "org-test", ["s0"])
    r = env["client"].post(f"/api/runs/{run_id}/cards/bulk-download", json={"ids": []})
    assert r.status_code == 400


def test_bulk_download_foreign_run_404(env):
    run_id = _seed_run(env["tmp_path"], "org-other", ["s0"])
    r = env["client"].post(f"/api/runs/{run_id}/cards/bulk-download", json={"ids": ["s0"]})
    assert r.status_code == 404


def test_bulk_download_missing_cards_404(env):
    run_id = _seed_run(env["tmp_path"], "org-test", ["s0"])
    r = env["client"].post(f"/api/runs/{run_id}/cards/bulk-download", json={"ids": ["nope"]})
    assert r.status_code == 404


def test_review_bar_leads_with_content_download_json_demoted(env):
    run_id = _seed_run(env["tmp_path"], "org-test", ["s0", "s1"])
    body = env["client"].get(f"/review/{run_id}").get_data(as_text=True)
    # The postable-content action is present and prominent…
    assert f"/api/runs/{run_id}/cards/bulk-download" in body
    assert 'data-mh-bulk="download"' in body
    assert "Download content (.zip)" in body
    # …and the JSON dump is kept but relabelled + de-emphasised (ghost button).
    assert f"/api/runs/{run_id}/cards/bulk-export" in body
    assert "Export data (JSON)" in body
    assert ">Export</button>" not in body  # the bare "Export" label is gone
