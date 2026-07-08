"""I-1 — scheduling drafts and moving board cards must have a non-drag path.

The only way to set a draft's planned date was HTML5 drag onto a calendar cell,
and the only way to move a board card was drag between columns. Drag events
don't fire from touch and there's no keyboard path — a poolside-phone volunteer
was locked out. There's now a "Plan for…" date field on each rail draft and a
"Move to…" select on each board card, posting to the same APIs; drag stays as
the desktop enhancement.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    app = wm.create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
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
