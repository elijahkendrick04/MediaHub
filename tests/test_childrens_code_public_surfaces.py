"""PC.12 — Children's Code pass, pinned (docs/compliance/CHILDRENS_CODE_PASS.md).

The public surfaces (/wall, embed, feeds, card PNGs, /try) must stay
tracker-free and cookie-free for anonymous visitors, and the bundled demo
sample must stay synthetic — the public demo never ships a real child's
name again (finding F1).
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def wall_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="org-a",
            display_name="Org A SC",
            public_wall_enabled=True,
            public_wall_token="token-org-a-secret",
        )
    )
    runs_dir = tmp_path / "runs_v4"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / "run-a-1.json").write_text(
        json.dumps(
            {
                "profile_id": "org-a",
                "meet_name": "Spring Gala 2026",
                "recognition_report": {
                    "ranked_achievements": [
                        {
                            "achievement": {
                                "swim_id": "swim-1",
                                "swimmer_name": "Alice Smith",
                                "event": "100m Freestyle",
                                "time": "59.10",
                            }
                        }
                    ]
                },
            }
        )
    )
    vdir = runs_dir / "run-a-1" / "visuals" / "brief-a"
    vdir.mkdir(parents=True)
    (vdir / "visual.json").write_text(json.dumps({"content_item_id": "swim-1"}))
    (vdir / "feed_portrait.png").write_bytes(b"\x89PNG fake")

    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    WorkflowStore(runs_dir).set_status("run-a-1", "swim-1", CardStatus.APPROVED)

    app = wm.create_app()
    app.config["TESTING"] = True
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        ("run-a-1", "org-a", "Spring Gala 2026", "gala.hy3"),
    )
    conn.commit()
    conn.close()
    return app


def test_public_wall_surfaces_set_no_cookie(wall_app):
    """An anonymous wall visit must be stateless: no Set-Cookie header on
    the page, embed, feeds, or the card image (Children's Code std 5/8/12)."""
    c = wall_app.test_client()
    for path in (
        "/wall/token-org-a-secret",
        "/wall/token-org-a-secret/embed",
        "/wall/token-org-a-secret/feed.json",
        "/wall/token-org-a-secret/feed.rss",
        "/wall/token-org-a-secret/card/run-a-1/swim-1.png",
    ):
        r = c.get(path)
        assert r.status_code == 200, path
        assert "Set-Cookie" not in r.headers, f"{path} set a cookie on an anonymous visit"


def test_public_wall_has_no_third_party_resources(wall_app):
    """No analytics, no CDN scripts/fonts — everything first-party."""
    c = wall_app.test_client()
    for path in ("/wall/token-org-a-secret", "/wall/token-org-a-secret/embed"):
        html = c.get(path).get_data(as_text=True)
        for fragment in ("googletagmanager", "google-analytics", "fonts.googleapis", "gstatic", "<script src=\"http"):
            assert fragment not in html, f"{path} references third-party resource {fragment}"


def test_demo_sample_is_synthetic():
    """The /try sample must be the generated fictional meet — the real meet
    PDF (real under-18 swimmers) must never come back to samples/."""
    assert not (REPO / "samples" / "MISM-2024-Results.pdf").exists(), (
        "samples/ ships on the public demo surface and must hold synthetic "
        "data only — real fixtures belong in sample_data/"
    )
    sample = REPO / "samples" / "demo-meet-results.pdf"
    assert sample.exists()
    raw = sample.read_bytes()
    assert b"SYNTHETIC DEMO DATA" in raw, (
        "the bundled demo sample must carry its synthetic-data marker "
        "(regenerate with scripts/make_demo_sample.py)"
    )


def test_web_points_at_the_synthetic_sample():
    src = (REPO / "src" / "mediahub" / "web" / "web.py").read_text(encoding="utf-8")
    assert 'samples" / "demo-meet-results.pdf"' in src
    assert "MISM-2024-Results.pdf" not in src


def test_childrens_code_pass_is_recorded():
    doc = REPO / "docs" / "compliance" / "CHILDRENS_CODE_PASS.md"
    assert doc.exists(), "the Children's Code pass must stay checked in (PC.12 exit)"
    text = doc.read_text(encoding="utf-8")
    for surface in ("/wall", "embed", "feed.json", "/try"):
        assert surface in text
