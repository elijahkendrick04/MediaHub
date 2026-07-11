"""E-5 — share links: no copy button, expiry invisible, run-wide tokens unrevocable.

The bulk-export share rendered a bare readonly input; the API always returned
``expires_at`` but no UI showed it; run-wide tokens (minted by the bulk-export
share button) appeared in no list — shareLoad filtered to the card's id — so
they could never be revoked; and shareRevoke ignored the response and
swallowed every error, making a failed revoke look identical to success.

Now every rendered share URL carries a Copy button and an "expires <date>"
label (bulk-export result and the card share panel); the share panel lists
whole-meet links with the same Copy/expiry/Revoke row; revoke outcomes are
surfaced via MH.toast, and no empty catch remains in shareRevoke.
"""

from __future__ import annotations

import importlib
import json
import pathlib
import uuid

import pytest

PASSWORD = "twelve-chars-long"
OWNER = "owner@cluba.org"


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-alpha", display_name="Org Alpha"))
    run_id = "run-e5-" + uuid.uuid4().hex[:8]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "profile_id": "org-alpha",
                "meet": {"name": "Alpha Invitational"},
                "cards": [{"card_id": "card-1", "id": "card-1", "swim_id": "card-1"}],
                "recognition_report": {
                    "n_swims_analysed": 1,
                    "ranked_achievements": [
                        {
                            "rank": 1,
                            "id": "card-1",
                            "achievement": {
                                "swim_id": "card-1",
                                "swimmer_name": "Adult Swimmer",
                                "event": "100 Free",
                                "headline": "A new PB",
                            },
                        }
                    ],
                },
            }
        )
    )
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-alpha", "Alpha Invitational", "a.hy3"),
    )
    conn.commit()
    conn.close()

    from mediahub.web import tenancy as t
    from mediahub.web.auth import UserStore

    UserStore().create(OWNER, PASSWORD)
    t.MembershipStore().add(OWNER, "org-alpha", role=t.ROLE_OWNER)

    app = wm.create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/login", data={"email": OWNER, "password": PASSWORD})
    c.post("/api/organisation/active", data={"profile_id": "org-alpha"})
    return {"client": c, "run_id": run_id}


# ---------------------------------------------------------------------------
# Behavioural: the API payload the new client rows depend on
# ---------------------------------------------------------------------------


def test_list_includes_run_wide_tokens_with_expiry(world):
    c, run_id = world["client"], world["run_id"]
    r1 = c.post(f"/api/runs/{run_id}/shares", json={"card_id": "card-1", "perm": "view"})
    assert r1.status_code == 201
    # An empty card_id mints a run-wide token — the same shape the
    # bulk-export share button creates.
    r2 = c.post(f"/api/runs/{run_id}/shares", json={"card_id": "", "perm": "view"})
    assert r2.status_code == 201

    listing = c.get(f"/api/runs/{run_id}/shares").get_json()
    assert listing["ok"]
    shares = listing["shares"]
    assert len(shares) == 2
    run_wide = [s for s in shares if not s["card_id"]]
    assert len(run_wide) == 1  # visible in the list → revocable from the panel
    for s in shares:
        assert s["expires_at"] > 0  # the expiry label has real data
        assert s["url"]


def test_revoke_reports_outcome_the_client_can_toast(world):
    c, run_id = world["client"], world["run_id"]
    token = c.post(
        f"/api/runs/{run_id}/shares", json={"card_id": "", "perm": "view"}
    ).get_json()["share"]["token"]

    # Unknown token: ok response but revoked=false — the client toasts this.
    r_bad = c.post(f"/api/runs/{run_id}/shares/not-a-real-token/revoke")
    assert r_bad.get_json() == {"ok": True, "revoked": False}

    r_ok = c.post(f"/api/runs/{run_id}/shares/{token}/revoke")
    assert r_ok.get_json() == {"ok": True, "revoked": True}
    left = c.get(f"/api/runs/{run_id}/shares").get_json()["shares"]
    assert all(s["token"] != token for s in left)


# ---------------------------------------------------------------------------
# Source-level: the share panel JS (plain string inside _card_creative_js)
# ---------------------------------------------------------------------------

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


def test_share_rows_have_copy_and_expiry():
    assert "function shareRowEl(cardId, s)" in _SRC
    assert "'expires ' + new Date(s.expires_at * 1000).toLocaleDateString()" in _SRC
    assert "navigator.clipboard.writeText(inp.value)" in _SRC


def test_share_panel_lists_whole_meet_links():
    assert "var wholeMeet = shares.filter(function(s){ return !s.card_id; });" in _SRC
    assert "Whole-meet links (from bulk export)" in _SRC


def test_share_revoke_surfaces_failures_no_empty_catch():
    # The old fire-and-forget chain is gone…
    assert ".then(function(r){return r.json();}).then(function(){ shareLoad(cardId); }).catch(function(){});" not in _SRC
    # …replaced by an outcome read + toast on every failure path.
    assert "res.j.revoked === false" in _SRC
    assert "Could not revoke that link" in _SRC
    assert "Could not revoke the link" in _SRC and "network error" in _SRC


def test_share_load_catch_is_not_silent():
    assert "Could not load share links" in _SRC


# ---------------------------------------------------------------------------
# Source-level: bulk_export.js (plain static file)
# ---------------------------------------------------------------------------

_BX = pathlib.Path("src/mediahub/web/static/js/bulk_export.js").read_text(encoding="utf-8")


def test_bulk_export_share_result_has_copy_and_expiry():
    assert 'cp.textContent = "Copy";' in _BX
    assert "navigator.clipboard.writeText(inp.value)" in _BX
    assert '"expires " + new Date(j.expires_at * 1000).toLocaleDateString()' in _BX
    # The old bare-input-only rendering is gone.
    assert "display:block;margin-top:8px;width:100%;max-width:520px" not in _BX
