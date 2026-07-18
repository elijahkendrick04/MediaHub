"""D-27 — the planner's AI buttons must show a real loading treatment.

"Generate plan", "Interpret & fill in" and the analytics "AI performance digest"
carry data-loader-text for the shared loader, but the loader only binds to form
submit events and these are type=button onclick handlers outside any form — so
the intended loading treatment never fired (multi-second AI work with only a tiny
status span). The handlers now drive MH.showLoader/hideLoader directly.
"""

from __future__ import annotations


def _page(client, path):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    with client.session_transaction() as s:
        s["active_profile_id"] = "club-a"
    return client.get(path).get_data(as_text=True)


def test_plan_handlers_drive_the_loader(client):
    html = _page(client, "/plan")
    # Both planner AI handlers now show and hide the loader from data-loader-text.
    assert html.count("MH.showLoader(btn.dataset.loaderText") >= 2
    assert "MH.hideLoader()" in html


def test_analytics_digest_drives_the_loader(client):
    html = _page(client, "/plan/analytics")
    assert "MH.showLoader(btn.dataset.loaderText" in html
    assert "MH.hideLoader()" in html
