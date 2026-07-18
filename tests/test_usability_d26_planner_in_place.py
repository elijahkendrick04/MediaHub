"""D-26 — planner micro-interactions update the DOM in place (no page reloads).

Every mutation on the three planner surfaces — calendar drop / "Plan for…" /
unschedule, board add / move / delete / promote, analytics log / remove — used
to end in location.reload(): the page flashed, scroll position was lost, and
the analytics form forgot every picked value after each log. The handlers now
update the DOM in place. The POST endpoints are unchanged, the change is
applied optimistically, and a failed POST reverts the DOM and MH.toasts the
reason. The D-24 blackout warning became an inline banner that stays (see
test_usability_d24_blackout_warning_persists.py for its own pins).
"""

from __future__ import annotations

import pytest


@pytest.fixture
def client(app):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A", org_type="swimming_club"))
    app.config.update(TESTING=True, SECRET_KEY="x")
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "club-a"
    return c


def _js_block(html: str, marker: str) -> str:
    """The planner page's own script block, from its config object onward."""
    seg = html[html.index(marker) :]
    return seg[: seg.index("</script>")]


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


def test_calendar_mutations_have_no_reload_and_revert_on_error(client):
    from mediahub.club_platform.stub_pack_store import save_pack, set_planned_date

    save_pack("free_text", {"free_text": "hi"}, [{"caption": "Hi"}], profile_id="club-a")
    planned = save_pack("free_text", {"free_text": "yo"}, [{"caption": "Yo"}], profile_id="club-a")
    set_planned_date(planned["pack_id"], "2026-06-10")

    html = client.get("/plan/calendar?m=2026-06").get_data(as_text=True)
    assert "location.reload" not in html

    block = _js_block(html, "var MH_CAL_SCHEDULE_URL")
    # Optimistic move + revert machinery.
    assert "function mhCalChipSync(chip, date, warned)" in block
    assert "if (undo) undo();" in block
    # Failure surfaces through MH.toast, success through the status line.
    assert "MH.toast(j.error || 'Could not update the plan.', 'error')" in block
    assert "'Unscheduled — back in the side rail.'" in block


def test_calendar_rail_cards_ship_the_planned_chip_affordances(client):
    """A rail card scheduled in place (no re-render) must already carry the
    hidden unschedule control and blackout flag the server would have rendered
    on a planned chip."""
    from mediahub.club_platform.stub_pack_store import save_pack

    save_pack("free_text", {"free_text": "hi"}, [{"caption": "Hi"}], profile_id="club-a")
    html = client.get("/plan/calendar").get_data(as_text=True)
    marker = 'class="mh-cal-draft mh-cal-rail-card"'
    card_chunk = html[html.index(marker) : html.index("</aside>")]
    # The rail's copy of both controls ships hidden (it is unscheduled).
    assert 'class="mh-cal-warnflag"' in card_chunk
    assert 'class="mh-cal-unplan"' in card_chunk
    assert "hidden" in card_chunk


def test_calendar_revert_uses_the_server_confirmed_prev_date(client):
    """JS2-1 (D-26 follow-up) — mhCalPlanInput fires on change, when the input
    already holds the NEW date, so the revert snapshot must come from
    data-prev (stamped server-side, advanced only on a successful POST),
    never from input.value."""
    from mediahub.club_platform.stub_pack_store import save_pack, set_planned_date

    save_pack("free_text", {"free_text": "hi"}, [{"caption": "Hi"}], profile_id="club-a")
    planned = save_pack("free_text", {"free_text": "yo"}, [{"caption": "Yo"}], profile_id="club-a")
    set_planned_date(planned["pack_id"], "2026-06-10")

    html = client.get("/plan/calendar?m=2026-06").get_data(as_text=True)
    # Server stamps the truth: the planned chip's input carries its confirmed
    # date; the unscheduled rail card's carries the empty string.
    assert 'value="2026-06-10" data-prev="2026-06-10"' in html
    assert 'data-prev=""' in html

    block = _js_block(html, "var MH_CAL_SCHEDULE_URL")
    # The snapshot reads data-prev — the pre-mutation input.value read is gone.
    assert "prevInput.dataset.prev || ''" in block
    assert "prevInput ? (prevInput.value || '')" not in block
    # data-prev only advances once the server confirms the move, and the
    # failure path reverts through mhCalChipSync (which restores input.value).
    assert "prevInput.dataset.prev = date || '';" in block
    assert block.index("if (!j.ok)") < block.index("prevInput.dataset.prev = date || '';")
    # Drag drops route through the same mhCalSchedule bookkeeping.
    assert "mhCalSchedule(packId, date)" in block


def test_calendar_schedule_endpoint_unchanged(client):
    from mediahub.club_platform.stub_pack_store import save_pack

    saved = save_pack("free_text", {"free_text": "hi"}, [{"caption": "Hi"}], profile_id="club-a")
    r = client.post(
        "/api/plan/calendar/schedule", json={"pack_id": saved["pack_id"], "date": "2026-06-09"}
    )
    body = r.get_json()
    assert r.status_code == 200 and body["ok"] is True
    assert body["planned_date"] == "2026-06-09"


# ---------------------------------------------------------------------------
# Board
# ---------------------------------------------------------------------------


def test_board_mutations_have_no_reload_and_revert_on_error(client):
    from mediahub.content_engine.board import add_card

    add_card("club-a", "Thank the sponsor")
    html = client.get("/plan/board").get_data(as_text=True)
    assert "location.reload" not in html

    block = _js_block(html, "var MH_BD = ")
    # In-place machinery: build a card, move it between columns, recount.
    assert "function mhBoardCardEl(card)" in block
    assert "function mhBoardMoveTo(cardId, column)" in block
    assert "function mhBoardRecount()" in block
    # Optimistic changes revert when the POST fails.
    assert "if (fail) fail();" in block
    assert "parent.insertBefore(card, next);" in block
    assert "MH.toast(msg, 'error')" in block
    # I-1's non-drag "Move to…" select still routes through the same path.
    assert "mhBoardMoveTo(sel.getAttribute('data-card'), sel.value)" in block
    # Promote swaps the card's actions to real draft links in place.
    assert "MH_BD.draft.replace('__PACK__'" in block


def test_board_endpoints_unchanged(client):
    r = client.post("/api/plan/board/add", json={"title": "Kit launch"})
    body = r.get_json()
    assert r.status_code == 200 and body["ok"] is True
    cid = body["card"]["id"]
    moved = client.post(
        "/api/plan/board/move", json={"card_id": cid, "column": "approved"}
    ).get_json()
    assert moved["card"]["column"] == "approved"
    promoted = client.post("/api/plan/board/promote", json={"card_id": cid}).get_json()
    assert promoted["ok"] is True and promoted["pack_id"]
    assert client.post("/api/plan/board/delete", json={"card_id": cid}).get_json()["ok"] is True


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


def test_analytics_log_appends_in_place_and_keeps_the_form(client):
    html = client.get("/plan/analytics").get_data(as_text=True)
    assert "location.reload" not in html

    block = _js_block(html, "var MH_AN = ")
    # The logged row is appended in place with the server's engagement number.
    assert "function mhAnAppendRow(m, eng)" in block
    assert "mhAnAppendRow(j.metric" in block
    # Only the metric counts reset — post type / platform / draft / date keep
    # their picked values so logging a run of posts is painless.
    assert "if (el) el.value = '0';" in block
    assert "getElementById('mh-an-type').value = ''" not in block
    assert "getElementById('mh-an-platform').value = ''" not in block
    assert "getElementById('mh-an-date').value = ''" not in block
    # Remove is optimistic with a revert + MH.toast on failure.
    assert "parent.insertBefore(row, next);" in block
    assert "MH.toast('Could not remove that row.', 'error')" in block
    # The append helper builds rows from data via textContent, never HTML.
    assert "textContent" in block


def test_analytics_record_response_carries_engagement(client):
    r = client.post(
        "/api/plan/analytics/record",
        json={
            "post_type": "pb_spotlight",
            "posted_date": "2026-06-10",
            "metrics": {"likes": 10, "comments": 2},
        },
    )
    body = r.get_json()
    assert r.status_code == 200 and body["ok"] is True
    # likes + 2×comments (the store's fixed deterministic weights) = 14.
    assert body["engagement"] == 14
    assert body["metric"]["id"]


def test_analytics_delete_treats_error_bodies_as_failures(client):
    """JS2-2 (D-26 follow-up) — bodies like {"error": "No organisation
    active."} carry no ok key; mhAnDelete must restore the removed row for
    them too, matching the sibling handlers."""
    html = client.get("/plan/analytics").get_data(as_text=True)
    block = _js_block(html, "var MH_AN = ")
    assert "if (!j || j.ok === false || j.error)" in block
    # The lax check that let {error:...} fall through to success is gone.
    assert "if (!j || j.ok === false) {" not in block


def test_analytics_delete_endpoint_unchanged(client):
    rec = client.post(
        "/api/plan/analytics/record",
        json={"post_type": "pb_spotlight", "posted_date": "2026-06-10", "metrics": {"likes": 3}},
    ).get_json()
    r = client.post("/api/plan/analytics/delete", json={"id": rec["metric"]["id"]})
    assert r.status_code == 200 and r.get_json()["ok"] is True
