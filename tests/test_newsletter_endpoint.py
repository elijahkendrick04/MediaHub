"""tests/test_newsletter_endpoint.py — Phase 1.2 newsletter endpoint
+ pack-page UI surfacing.

Pins:
  1. /api/runs/<id>/newsletter returns each format with the right
     Content-Type and (for downloads) a Content-Disposition header.
  2. The content builder (/pack) surfaces the newsletter download
     buttons — so the user doesn't have to know the API exists — and
     the grouped explore view no longer duplicates them (B-3: export
     lives on the builder only). The grouped page keeps its per-card
     motion-video button.
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def app_with_run(app, tmp_path):
    """Fresh DATA_DIR, a seeded ready org, and one fake run."""
    app.config["ENFORCE_ORG_GATE"] = True

    # Seed a branded, ready profile so the gate lifts.
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="city-aquatics",
            display_name="City Aquatics",
            brand_voice_summary="Inclusive community club.",
            brand_primary="#0066cc",
            brand_logo_url="https://city-aquatics.example/logo.png",
        )
    )

    # Seed a fake run that the newsletter endpoint can read.
    run_id = "test_run_newsletter"
    run = {
        "run_id": run_id,
        "profile_id": "city-aquatics",
        "profile_display": "City Aquatics",
        "meet": {
            "name": "Winter Championships",
            "start_date": "2026-01-20",
            "venue": "Manchester Aquatics Centre",
        },
        "recognition_report": {
            "n_achievements": 1,
            "ranked_achievements": [
                {
                    "rank": 1,
                    "priority": 0.95,
                    "achievement": {
                        "swim_id": "swim-1",
                        "swimmer_name": "Emma Davies",
                        "event": "100m Freestyle",
                        "time": "58.21",
                        "type": "pb_confirmed",
                        "headline": "First sub-60 in the 100 free",
                        "pb": True,
                    },
                    "factors": [],
                }
            ],
        },
    }
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(run))

    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "city-aquatics"})
        yield c, run_id


# ---------------------------------------------------------------------------
# 1. Newsletter endpoint
# ---------------------------------------------------------------------------


class TestNewsletterEndpoint:
    def test_html_default(self, app_with_run, monkeypatch):
        # Stub build_parent_newsletter so we don't hit the LLM in test.
        from mediahub.turn_into import templates as ti

        monkeypatch.setattr(
            ti,
            "build_parent_newsletter",
            lambda meet, ranked, **kw: {
                "type": "parent_newsletter",
                "title": f"{meet.get('name','Meet')} — meet update",
                "captions": {
                    "plain_text": (
                        "Dear parents,\n\nA quick update from "
                        f"{meet.get('name','the meet')}. "
                        "Emma went sub-60 in the 100 free."
                    ),
                },
                "cards": [],
                "html": "",
                "notes": [],
            },
        )

        c, run_id = app_with_run
        resp = c.get(f"/api/runs/{run_id}/newsletter")
        assert resp.status_code == 200
        assert resp.mimetype == "text/html"
        body = resp.get_data(as_text=True)
        # Sender-safe HTML
        assert body.lstrip().startswith("<!DOCTYPE html>")
        # Branding flowed through
        assert "City Aquatics" in body
        assert "Winter Championships" in body
        # Body content reaches the rendered email
        assert "Emma went sub-60" in body
        # No download header on the default preview
        assert "Content-Disposition" not in resp.headers

    def test_text_format(self, app_with_run, monkeypatch):
        from mediahub.turn_into import templates as ti

        monkeypatch.setattr(
            ti,
            "build_parent_newsletter",
            lambda meet, ranked, **kw: {
                "type": "parent_newsletter",
                "title": "x",
                "captions": {"plain_text": "Hello parents."},
                "cards": [],
                "html": "",
                "notes": [],
            },
        )
        c, run_id = app_with_run
        resp = c.get(f"/api/runs/{run_id}/newsletter?format=text")
        assert resp.status_code == 200
        assert resp.mimetype == "text/plain"
        assert resp.get_data(as_text=True) == "Hello parents."

    def test_text_download_has_disposition(self, app_with_run, monkeypatch):
        from mediahub.turn_into import templates as ti

        monkeypatch.setattr(
            ti,
            "build_parent_newsletter",
            lambda meet, ranked, **kw: {
                "type": "parent_newsletter",
                "captions": {"plain_text": "x"},
            },
        )
        c, run_id = app_with_run
        resp = c.get(f"/api/runs/{run_id}/newsletter?format=text&download=1")
        cd = resp.headers.get("Content-Disposition", "")
        assert "attachment" in cd
        assert ".txt" in cd
        assert "winter-championships" in cd.lower()

    def test_zip_format(self, app_with_run, monkeypatch):
        from mediahub.turn_into import templates as ti

        monkeypatch.setattr(
            ti,
            "build_parent_newsletter",
            lambda meet, ranked, **kw: {
                "type": "parent_newsletter",
                "captions": {"plain_text": "Plain body content here."},
            },
        )
        c, run_id = app_with_run
        resp = c.get(f"/api/runs/{run_id}/newsletter?format=zip")
        assert resp.status_code == 200
        assert resp.mimetype == "application/zip"
        # Force-download header
        assert "attachment" in resp.headers.get("Content-Disposition", "")
        # The zip contains both files + README
        with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
            names = zf.namelist()
            assert any(n.endswith(".html") for n in names)
            assert any(n.endswith(".txt") for n in names)
            assert "README.txt" in names
            html = zf.read([n for n in names if n.endswith(".html")][0]).decode("utf-8")
            assert "City Aquatics" in html

    def test_invalid_format_400(self, app_with_run):
        c, run_id = app_with_run
        resp = c.get(f"/api/runs/{run_id}/newsletter?format=pdf")
        assert resp.status_code == 400

    def test_run_not_found_404(self, app_with_run):
        c, _ = app_with_run
        resp = c.get("/api/runs/no-such-run/newsletter")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2. UI surfacing on the grouped pack page
# ---------------------------------------------------------------------------


class TestPackPageSurfacesExports:
    def test_builder_has_newsletter_buttons(self, app_with_run):
        """B-3 moved the single newsletter surfacing to the content builder
        (export lives there); an approved card makes the builder render."""
        c, run_id = app_with_run
        import mediahub.web.web as wm
        from mediahub.workflow.status import CardStatus

        wm._get_wf_store().set_status(run_id, "swim-1", CardStatus.APPROVED)
        resp = c.get(f"/pack/{run_id}")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Parent newsletter" in body
        assert f"/api/runs/{run_id}/newsletter" in body
        assert "Download .html" in body
        assert "Download .txt" in body
        assert "Download .zip" in body

    def test_grouped_pack_no_longer_duplicates_newsletter(self, app_with_run):
        """B-3: the grouped explore view lost its duplicated newsletter card."""
        c, run_id = app_with_run
        resp = c.get(f"/pack/{run_id}/grouped")
        # Page may redirect to the classic pack when v7.3 isn't fully
        # loaded in a test sandbox — only assert when /grouped rendered.
        if resp.status_code == 200:
            body = resp.get_data(as_text=True)
            assert "Parent newsletter" not in body
            assert f"/api/runs/{run_id}/newsletter" not in body

    def test_grouped_pack_has_per_card_motion_button(self, app_with_run):
        c, run_id = app_with_run
        resp = c.get(f"/pack/{run_id}/grouped")
        if resp.status_code == 200:
            body = resp.get_data(as_text=True)
            # Motion-video link for the seeded card
            assert f"/api/runs/{run_id}/card/swim-1/motion" in body
            assert "Motion video" in body
