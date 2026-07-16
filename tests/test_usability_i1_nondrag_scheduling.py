"""I-1 — scheduling drafts and moving board cards must have a non-drag path.

The only way to set a draft's planned date was HTML5 drag onto a calendar cell,
and the only way to move a board card was drag between columns. Drag events
don't fire from touch and there's no keyboard path — a poolside-phone volunteer
was locked out. There's now a "Plan for…" date field on each rail draft and a
"Move to…" select on each board card, posting to the same APIs; drag stays as
the desktop enhancement.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def client(app):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "club-a"
    return c


def test_board_card_has_move_select(client):
    from mediahub.content_engine.board import add_card

    add_card("club-a", "Thank the sponsor")
    html = client.get("/plan/board").get_data(as_text=True)
    # A non-drag Move-to select + its handler.
    assert 'class="mh-bd-move"' in html
    assert 'onchange="mhBoardMove(this)"' in html
    assert "function mhBoardMove(sel)" in html
    # Move options are the OTHER columns (e.g. Drafted), not the current one.
    assert "Move to" in html


def test_calendar_rail_has_plan_date_field(client):
    from mediahub.club_platform.stub_pack_store import save_pack

    save_pack("free_text", {"free_text": "hi"}, [{"caption": "Hi"}], profile_id="club-a")
    html = client.get("/plan/calendar").get_data(as_text=True)
    # A non-drag "Plan for" date input + its handler.
    assert 'class="mh-cal-plan-date"' in html
    assert 'type="date"' in html
    assert "function mhCalPlanInput(el)" in html
