"""F-1 — the internal word "run" must not pervade the customer-facing chrome.

A club volunteer thinks in results/meets, not pipeline runs. The landing hero,
the Activity toggle, the empty states and the delete confirms now say
"results"; "run"/"Runs (DB)" stays only on operator/developer surfaces.
(Owner decision: customer-facing vocabulary is "Results".)
"""

from __future__ import annotations

import pytest

ORG = "club-a"


@pytest.fixture
def client(app):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=ORG, display_name="Club A"))
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = ORG
    return c


def test_activity_empty_state_uses_results(client):
    html = client.get("/activity").get_data(as_text=True)
    assert "No results yet for this organisation" in html
    assert "No runs yet for this organisation" not in html


def test_delete_confirm_uses_results(client):
    # The global run-delete JS confirm no longer says "Delete this run".
    html = client.get("/activity").get_data(as_text=True)
    assert "Delete this run?" not in html


def test_operator_run_labels_are_preserved():
    # "run"/"Runs (DB)" stays on operator/developer surfaces (source-level guard).
    import pathlib

    src = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")
    assert "Runs (DB)" in src  # operator status/settings stat panels keep it
