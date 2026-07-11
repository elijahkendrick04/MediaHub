"""B-2 — the Content builder's twelve overlapping export affordances collapse
to ONE primary per card plus ONE pack-level disclosure.

Before: every card row had "⬇ Download .zip" (live even with nothing rendered,
shipping a caption-only ZIP), and the page scattered a newsletter card
(4 links), a certificates card (2 links) and a bottom row of 5 more export
buttons. Now:

* per card, ONE primary — "Download post (graphic + caption)" on the existing
  per-card ZIP route (E-3 semantics) — honestly disabled until that card has a
  rendered graphic;
* pack-level, ONE disclosure — "Export pack (N approved cards)…" — holding the
  two pack ZIPs (plain-English labels, no "manifest" in customer copy), Bulk
  export & convert, Print & merch, Print this page, both certificate exports
  and the newsletter links;
* every pack-level export sits under the same rendered-count gate the two
  ZIPs already had (aria-disabled until a graphic exists).

Presentation surgery only — no export route changed.
"""

from __future__ import annotations

import importlib
import json
import pathlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _run_payload(profile_id: str, n: int = 3) -> dict:
    return {
        "run_id": "r1",
        "profile_id": profile_id,
        "meet_name": "Test Open",
        "meet": {"name": "Test Open"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "id": f"swim-{i + 1}",
                    "rank": i + 1,
                    "priority": 0.9 - i * 0.1,
                    "achievement": {
                        "swim_id": f"swim-{i + 1}",
                        "swimmer_name": f"Swimmer {i + 1}",
                        "event": "100m Freestyle",
                        "headline": "PB set",
                        "type": "pb",
                        "confidence_label": "high",
                        "time": "59.80",
                    },
                }
                for i in range(n)
            ]
        },
    }


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.media_library.store as mls
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    mls._default_store = None
    app = wm.create_app()
    app.config["TESTING"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    (wm.RUNS_DIR / "r1.json").write_text(json.dumps(_run_payload("alpha")), encoding="utf-8")
    return app, wm, tmp_path


def _approve(tmp_path, *card_ids):
    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    ws = WorkflowStore(Path(tmp_path / "runs_v4"))
    for cid in card_ids:
        ws.set_status("r1", cid, CardStatus.APPROVED)


def _seed_visual(wm, card_id: str, brief_id: str) -> None:
    vdir = wm.RUNS_DIR / "r1" / "visuals" / brief_id
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "feed_portrait.png").write_bytes(PNG)
    (vdir / "visual.json").write_text(
        json.dumps(
            {
                "id": f"vis_{brief_id}",
                "content_item_id": card_id,
                "visual_ids": {f"vis_{brief_id}": "feed_portrait"},
                "layout_template": "story_card",
                "why_this_design": "seeded design",
                "sourced_asset_ids": [],
            }
        ),
        encoding="utf-8",
    )


def _page(app):
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "alpha"})
        resp = c.get("/pack/r1")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def _disclosure(page: str) -> str:
    assert 'id="mh-export-pack"' in page
    return page.split('id="mh-export-pack"', 1)[1].split("</details>", 1)[0]


# ---------------------------------------------------------------------------
# Per-card: one primary, honestly gated
# ---------------------------------------------------------------------------


class TestPerCardPrimary:
    def test_disabled_until_the_card_has_a_rendered_graphic(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1")
        page = _page(app)
        assert "Download post (graphic + caption)" in page
        assert 'href="/api/runs/r1/card/swim-1/download" aria-disabled="true"' in page
        assert "No graphic yet" in page
        # The old always-live label is gone from the builder rows.
        assert "&#x2B07; Download .zip" not in page

    def test_goes_live_once_rendered(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1")
        _seed_visual(wm, "swim-1", "cb_a")
        page = _page(app)
        assert 'href="/api/runs/r1/card/swim-1/download" aria-disabled="true"' not in page
        assert "Download post (graphic + caption)" in page
        assert "ready to post manually" in page

    def test_gate_is_per_card_not_per_pack(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1", "swim-2")
        _seed_visual(wm, "swim-1", "cb_a")
        page = _page(app)
        # swim-1 rendered → live; swim-2 not rendered → still gated.
        assert 'href="/api/runs/r1/card/swim-1/download" aria-disabled="true"' not in page
        assert 'href="/api/runs/r1/card/swim-2/download" aria-disabled="true"' in page


# ---------------------------------------------------------------------------
# Pack-level: one disclosure holding every export
# ---------------------------------------------------------------------------


class TestExportDisclosure:
    def test_label_carries_live_approved_count(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1", "swim-2")
        assert "Export pack (2 approved cards)" in _page(app)

    def test_label_singular_for_one_card(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1")
        page = _page(app)
        assert "Export pack (1 approved card)" in page
        assert "Export pack (1 approved cards)" not in page

    def test_every_pack_export_lives_inside_the_disclosure(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1")
        body = _disclosure(_page(app))
        for label in (
            "Every format, organised for posting (.zip)",
            "Just the images (.zip)",
            "Bulk export &amp; convert",
            "Print &amp; merch",
            "Print this page",
            "Download certificates (.zip of PDFs)",
            "Print-shop pack (bleed + crop marks)",
            "Parent newsletter",
            "Preview HTML",
            "Download .html",
            "Download .txt",
            "Download .zip",
        ):
            assert label in body, label

    def test_zip_labels_are_plain_english_no_manifest(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1")
        body = _disclosure(_page(app))
        assert "manifest" not in body.lower()
        assert "Download every format + manifest" not in _page(app)
        assert "Download all visuals (.zip)" not in _page(app)

    def test_render_gate_extends_to_every_export(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1")
        body = _disclosure(_page(app))
        # Nothing rendered: the 10 export anchors are aria-disabled (2 pack
        # ZIPs + bulk + print tool + 2 certificates + 4 newsletter) and the
        # browser-print button is disabled.
        assert body.count('aria-disabled="true"') == 10
        assert 'onclick="window.print()" disabled' in body
        assert "No graphics rendered yet" in body

    def test_render_gate_lifts_once_a_graphic_exists(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1")
        _seed_visual(wm, "swim-1", "cb_a")
        body = _disclosure(_page(app))
        assert 'aria-disabled="true"' not in body
        assert 'onclick="window.print()" disabled' not in body


# ---------------------------------------------------------------------------
# Source-level: the scattered blocks are gone, routes untouched
# ---------------------------------------------------------------------------

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


def test_old_scattered_export_blocks_are_gone():
    assert "Download every format + manifest" not in _SRC
    assert "Download all visuals (.zip)" not in _SRC
    assert "Print for the noticeboard" not in _SRC
    assert 'id="mh-export-pack"' in _SRC
    assert "Download post (graphic + caption)" in _SRC


def test_certificates_job_client_still_wired_inside_disclosure():
    # The disclosure move must not detach the D-12 certificates job client.
    body = _SRC.split('id="mh-export-pack"', 1)[1].split("</details>", 1)[0]
    assert 'onclick="return mhCertificatesJob(this)"' in body
    assert 'id="mh-certs-status"' in body
