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

import json
import pathlib
import re
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
def app_env(app, web_module, tmp_path):
    import mediahub.media_library.store as mls

    mls._default_store = None

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    (web_module.RUNS_DIR / "r1.json").write_text(
        json.dumps(_run_payload("alpha")), encoding="utf-8"
    )
    return app, web_module, tmp_path


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


# ---------------------------------------------------------------------------
# JS2-3 / SRV2-1 follow-up: the gates come alive after an in-page render
# ---------------------------------------------------------------------------


class TestInPageUnGate:
    def test_enable_helper_exists_and_lifts_both_gate_levels(self):
        assert "window.mhExportGatesEnable = function(cardId)" in _SRC
        helper = _SRC.split("window.mhExportGatesEnable = function(cardId)", 1)[1].split(
            "</script>", 1
        )[0]
        # Per-card gate: this card's marked controls.
        assert "getElementById('pc-' + cardId)" in helper
        # Pack-level gates + the gate note.
        assert "#mh-export-pack a[data-mh-export-gate]" in helper
        assert "#mh-export-note[data-mh-export-note-gated]" in helper
        # It removes exactly what the gate stamped and restores the real title.
        assert "removeAttribute('aria-disabled')" in helper
        assert "data-mh-title-ready" in helper

    def test_create_graphic_success_path_calls_the_helper(self):
        body = _SRC.split("function createGraphic(btn, createUrl", 1)[1].split("\nfunction ", 1)[0]
        assert "if (window.mhExportGatesEnable) window.mhExportGatesEnable(cardId);" in body
        # Guarded call — never a bare invocation that breaks the grouped page.
        assert body.count("window.mhExportGatesEnable(") == body.count(
            "if (window.mhExportGatesEnable) window.mhExportGatesEnable("
        )

    def test_pack_page_ships_the_helper_script(self):
        assert "_PACK_EXPORT_GATE_JS = " in _SRC
        assert "{_PACK_EXPORT_GATE_JS}" in _SRC

    def test_gated_controls_carry_the_gate_marker(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1")
        page = _page(app)
        # Per-card download anchor.
        assert 'data-mh-export-gate="card"' in page
        # Pack-level: the three gate variants all stamp their marker.
        body = _disclosure(page)
        assert body.count('data-mh-export-gate="attr"') == 8
        assert body.count('data-mh-export-gate="plain"') == 2
        assert body.count('data-mh-export-gate="btn"') == 1
        assert 'data-mh-export-note-gated="1"' in body

    def test_markers_absent_once_rendered(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1")
        _seed_visual(wm, "swim-1", "cb_a")
        page = _page(app)
        assert "data-mh-export-gate=" not in _disclosure(page)
        assert 'data-mh-export-note-gated="1"' not in page


# ---------------------------------------------------------------------------
# JS2-5 / SRV2-3 follow-up: exactly one title attribute per control
# ---------------------------------------------------------------------------


def _control_tags(page: str) -> list[str]:
    start = page.index('id="mh-export-pack"')
    end = page.index("</details>", start)
    return re.findall(r"<(?:a|button)\b[^>]*>", page[start:end])


class TestSingleTitleAttribute:
    def test_no_duplicate_titles_when_gated(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1")
        tags = _control_tags(_page(app))
        assert tags
        for tag in tags:
            assert tag.count(' title="') <= 1, tag
        # Every gated control still shows the gate tooltip.
        gated = [t for t in tags if "data-mh-export-gate" in t]
        assert len(gated) == 11
        for tag in gated:
            assert "No graphics rendered yet" in tag, tag

    def test_no_duplicate_titles_once_rendered(self, app_env, tmp_path):
        app, wm, _ = app_env
        _approve(tmp_path, "swim-1")
        _seed_visual(wm, "swim-1", "cb_a")
        tags = _control_tags(_page(app))
        assert tags
        for tag in tags:
            assert tag.count(' title="') <= 1, tag
        # The controls' own tooltips render directly in the live state.
        joined = "".join(tags)
        assert "grouped per card and ready to post" in joined
        assert "ready for a professional print shop" in joined
        assert "data-mh-title-ready" not in joined
