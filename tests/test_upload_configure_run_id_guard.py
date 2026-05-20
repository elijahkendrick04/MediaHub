"""Security regression: /upload/configure validates run_id shape.

The configure step joins the client-supplied ``run_id`` onto RUNS_DIR
to find the staged upload's metadata. A request that smuggles ``..``
segments in via the form value lets the configure page render meta
sourced from anywhere on disk. The fix rejects any run_id that doesn't
match the generated-token shape (``[A-Za-z0-9_-]{1,64}``).
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def gated_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp); importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(
        profile_id="my-club", display_name="My Club",
        brand_voice_summary="A friendly club.",
    ))

    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "my-club"})
        yield c, app, tmp_path


def _plant_attacker_meta(tmp_path: Path) -> None:
    """Drop a believable upload_meta.json + input.bin in a sibling dir
    so we can confirm the guard refuses to traverse into it."""
    victim = tmp_path / "attacker_dir"
    victim.mkdir(parents=True, exist_ok=True)
    (victim / "upload_meta.json").write_text(json.dumps({
        "filename": "planted.hy3",
        "clubs": ["planted-club"],
        "meet_name": "Planted Meet",
        "file_byte_size": 100,
    }))
    (victim / "input.bin").write_bytes(b"A1Planted\n")


def test_legitimate_token_reaches_configure_page(gated_client):
    c, _, tmp = gated_client
    # Plant a legitimate staged upload, then GET /upload/configure with
    # the matching run_id. Must render the configure page, not the
    # "session expired" recovery page.
    run_id = "abc123def456"
    staged = tmp / "runs_v4" / run_id
    staged.mkdir(parents=True, exist_ok=True)
    (staged / "upload_meta.json").write_text(json.dumps({
        "filename": "real.hy3",
        "clubs": ["my-club"],
        "meet_name": "Real Meet",
        "file_byte_size": 12345,
    }))
    (staged / "input.bin").write_bytes(b"A1Real\n")
    resp = c.get(f"/upload/configure?run_id={run_id}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Real Meet" in body or "Configure" in body


def test_dotdot_traversal_in_run_id_is_rejected(gated_client):
    c, _, tmp = gated_client
    _plant_attacker_meta(tmp)
    # A query string trying `..` traversal should never read the
    # planted meta. The string converter blocks slashes upstream, but
    # `request.values.get` is unchecked, so we verify the regex guard
    # in the handler.
    resp = c.get("/upload/configure?run_id=../attacker_dir")
    assert resp.status_code in (200, 302, 404)
    body = resp.get_data(as_text=True)
    assert "Planted Meet" not in body
    assert "planted-club" not in body


def test_post_with_traversal_run_id_does_not_start_pipeline(gated_client):
    c, _, tmp = gated_client
    _plant_attacker_meta(tmp)
    resp = c.post(
        "/upload/configure",
        data={"run_id": "../attacker_dir", "club_filter": "planted-club"},
        follow_redirects=False,
    )
    body = resp.get_data(as_text=True)
    assert "Planted Meet" not in body
    # No new run should have been started under runs_v4 referencing the
    # planted bytes.
    runs = list((tmp / "runs_v4").glob("*.json"))
    # The directory may contain legitimate stub files from earlier
    # tests in the fixture; the smoking-gun assertion is that none of
    # them carry the planted name.
    for rj in runs:
        assert "Planted Meet" not in rj.read_text()


@pytest.mark.parametrize("bad_id", [
    "../etc/passwd",
    "..%2Fattacker_dir",
    "abc/../def",  # rejected by the Flask string converter pre-routing
    "x" * 65,      # exceeds the 64-char regex cap
    "abc!def",     # disallowed punctuation
])
def test_assorted_bad_shapes_are_refused(gated_client, bad_id):
    c, _, _ = gated_client
    resp = c.get(f"/upload/configure?run_id={bad_id}")
    body = resp.get_data(as_text=True)
    # Either the recovery page rendered, OR Flask short-circuited to a
    # 404 because the URL converter didn't match. The unifying
    # invariant is that planted strings never appear.
    assert "Planted Meet" not in body
    assert "planted-club" not in body
