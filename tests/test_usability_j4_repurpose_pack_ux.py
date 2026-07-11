"""J-4 — the Repurpose-pack output page was a dead end.

The pack view offered only "Save edits" per piece — no way to copy a caption
or download the newsletter HTML; "Regenerate pack" fired a native confirm()
into a sync fetch that surfaced failures via raw alert(); and the feature was
named three different ways ("Turn this meet into more" / "Repurpose pack" /
"Turn-Into pack"), with items called "artefacts".

Now every caption block carries a one-click Copy button (the page-local
copyText idiom the grouped page uses), the newsletter piece gets a
"Download HTML" button that hands over the exact engine-produced source,
Regenerate runs through MH.confirm with a busy button and an inline styled
status/error line, and the one user-facing name is "Repurpose pack" with
items called "pieces". Internal route/symbol names are unchanged.
"""

from __future__ import annotations

import importlib
import json
import pathlib
import uuid

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

    save_profile(ClubProfile(profile_id="org-alpha", display_name="Org Alpha"))

    run_id = "run-j4-" + uuid.uuid4().hex[:8]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "profile_id": "org-alpha",
                "profile_display": "Org Alpha",
                "meet": {
                    "name": "Spring Open 2026",
                    "start_date": "2026-04-10",
                    "end_date": "2026-04-11",
                    "course": "LC",
                    "venue": "Demo Pool",
                },
                "cards": [],
                "recognition_report": {
                    "meet_name": "Spring Open 2026",
                    "n_swims_analysed": 18,
                    "n_achievements": 2,
                    "ranked_achievements": [
                        {
                            "rank": 1,
                            "quality_band": "elite",
                            "priority": 0.92,
                            "safe_to_post": {"level": "safe", "reason": "ok"},
                            "achievement": {
                                "swim_id": "swim-1",
                                "swimmer_name": "Alice Lee",
                                "swimmer_id": "s1",
                                "event": "100m Freestyle",
                                "time": "57.95",
                                "headline": "New PB in 100 Free",
                                "type": "pb_confirmed",
                                "raw_facts": {"time_str": "57.95"},
                            },
                        },
                        {
                            "rank": 2,
                            "quality_band": "strong",
                            "priority": 0.80,
                            "safe_to_post": {"level": "safe", "reason": "ok"},
                            "achievement": {
                                "swim_id": "swim-2",
                                "swimmer_name": "Bob Khan",
                                "swimmer_id": "s2",
                                "event": "200m Backstroke",
                                "time": "2:08.10",
                                "headline": "Silver medal",
                                "type": "medal_silver",
                                "raw_facts": {},
                            },
                        },
                    ],
                },
            }
        )
    )
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name,"
        " file_name) VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-alpha", "Spring Open 2026", "spring.hy3"),
    )
    conn.commit()
    conn.close()

    # The Content builder only renders once something is approved.
    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    WorkflowStore(tmp_path / "runs_v4").set_status(run_id, "swim-1", CardStatus.APPROVED)

    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.post("/api/organisation/active", data={"profile_id": "org-alpha"})
        assert r.status_code == 200
        yield {"client": c, "run_id": run_id, "wm": wm}


@pytest.fixture
def pack_page(env):
    """Generate a deterministic Repurpose pack and return its rendered view."""
    c = env["client"]
    r = c.post(f"/api/runs/{env['run_id']}/turn-into", json={"deterministic": True})
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"]
    r2 = c.get(data["pack_url"])
    assert r2.status_code == 200
    return r2.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Behavioural: the rendered pack view
# ---------------------------------------------------------------------------


def test_every_caption_block_has_a_copy_button(pack_page):
    # Each editable caption textarea carries an id the Copy button targets.
    assert "copyText(this,'ti-cap-" in pack_page
    assert 'id="ti-cap-' in pack_page
    # The page-local copy helper is present (clipboard + execCommand fallback).
    assert "function copyText(btn, taId)" in pack_page


def test_newsletter_piece_offers_download_html(pack_page):
    # The deterministic pack always includes the parent newsletter, whose
    # exact engine-produced HTML rides a hidden textarea into a Blob download.
    assert "Download HTML" in pack_page
    assert "function tiDownloadHtml(idx)" in pack_page
    assert 'id="ti-html-' in pack_page
    assert "repurpose-pack-newsletter.html" in pack_page


def test_regenerate_uses_styled_confirm_busy_state_and_inline_error(pack_page):
    # MH.confirm replaces the native confirm(); the button gets a busy state
    # and failures land in an inline live-region status, not alert().
    assert "MH.confirm(" in pack_page
    assert "tiRegenerate(this)" in pack_page
    assert 'id="ti-regen-status"' in pack_page
    assert 'role="status"' in pack_page
    # The old dead ends are gone.
    assert "confirm('Generate a fresh" not in pack_page
    assert "alert('Regenerate failed" not in pack_page
    # The error surface prefers the plain-English message fields.
    assert "j.user_message || j.message || j.error" in pack_page


def test_one_name_and_pieces_vocabulary(pack_page):
    # The one user-facing name.
    assert "Repurpose pack" in pack_page
    assert "Turn-Into" not in pack_page
    # Items are "pieces" in every visible string; internal data attributes
    # (data-artefact, artefact_index) are deliberately unchanged.
    assert "pieces" in pack_page
    assert "Why this piece?" in pack_page
    assert "Skipped pieces" in pack_page  # sponsor piece skipped (no sponsor)
    assert "Skipped artefacts" not in pack_page
    assert "Why this artefact?" not in pack_page
    assert "No artefacts generated." not in pack_page


def test_builder_card_uses_the_one_name(env):
    r = env["client"].get(f"/pack/{env['run_id']}")
    assert r.status_code == 200
    page = r.get_data(as_text=True)
    assert "Repurpose pack" in page
    assert "Turn this meet into more" not in page
    assert "Drafting every piece with live AI" in page
    assert "Drafting every artefact" not in page


# ---------------------------------------------------------------------------
# Source-level: strings the rendered fixtures can't reach
# ---------------------------------------------------------------------------

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


def test_no_native_dialogs_left_in_the_pack_view_script():
    assert "confirm('Generate a fresh Turn-Into pack?" not in _SRC
    assert "alert('Regenerate failed" not in _SRC


def test_empty_state_and_prior_pack_rows_say_pieces():
    assert "No pieces generated." in _SRC
    assert "No artefacts generated." not in _SRC
    # The builder card's "previously generated" rows count pieces.
    assert '{_n} {"piece" if _n == 1 else "pieces"}' in _SRC
