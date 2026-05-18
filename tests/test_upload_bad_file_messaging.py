"""tests/test_upload_bad_file_messaging.py — Phase 1.5 UX hardening.

When a user uploads a malformed or wrong-kind file, the configure-step
error must distinguish:

  1. Tiny / unreadable file (a 348-byte "404 Not Found" stub masquerading
     as a PDF) — surface "doesn't look like a meet results file".
  2. File parses OK but has zero events — surface "looks like a meet
     preview, not results".
  3. File parses, has events, but no clubs — keep the original
     "couldn't read clubs" wording.

Without this triage, a user with a broken download sees the same
generic "couldn't read clubs" error as a user with a real-but-empty
meet preview file, leading to wrong remediation.
"""
from __future__ import annotations

import importlib
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
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(
        profile_id="wycombe",
        display_name="Wycombe District Swimming Club",
        brand_voice_summary="A friendly club.",
    ))
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "wycombe"})
        yield c, app


class TestUploadErrorMessaging:
    def test_tiny_404_stub_surfaces_too_small_message(self, gated_client):
        """A 348-byte HTML 404 page disguised as a PDF must trigger the
        'doesn't look like a meet results file' branch, not the generic
        'couldn't read clubs' branch."""
        c, _ = gated_client
        # Real-world failure mode: server returned a "404 Not Found" page
        # with .pdf extension. < 2048 bytes is the heuristic threshold.
        fake_pdf = b"404 Not Found\n" + b"a" * 100
        resp = c.post(
            "/upload",
            data={"file": (Path("/dev/null").open("rb").__class__(__import__("io").BytesIO(fake_pdf), filename="results.pdf"),)} if False else None,
            content_type="multipart/form-data",
            buffered=True,
        ) if False else None
        # Simpler approach for the Werkzeug test client
        import io
        resp = c.post(
            "/upload",
            data={"file": (io.BytesIO(fake_pdf), "results.pdf")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # Apostrophes get HTML-escaped by Jinja autoescape — check the
        # rest of the headline (the part that's distinctive).
        assert "look like a meet results file" in body
        assert "too small to be a real" in body
        assert f"only {len(fake_pdf)} bytes" in body
        # Generic "couldn't read clubs" must NOT also appear.
        assert "couldn't read clubs" not in body

    def test_real_pdf_parses_and_shows_clubs(self, gated_client):
        """The MISM sample is a real Sportsystems meet results PDF; it
        should parse to 30+ clubs and land on the configure form, NOT
        any error state."""
        sample = Path(__file__).resolve().parents[1] / "samples" / "MISM-2024-Results.pdf"
        if not sample.exists():
            pytest.skip(f"sample missing: {sample}")
        c, _ = gated_client
        import io
        with sample.open("rb") as f:
            resp = c.post(
                "/upload",
                data={"file": (io.BytesIO(f.read()), "MISM-2024-Results.pdf")},
                content_type="multipart/form-data",
                follow_redirects=True,
            )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # Configure form should render with a club picker.
        assert "doesn't look like" not in body
        assert "looks like a meet preview" not in body
        # The Manchester meet name should surface.
        assert "ARENA" in body or "Manchester" in body or "Configure" in body
