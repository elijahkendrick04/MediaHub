"""C-12 — the Elements page was look-don't-touch without card context, the
Stock browser's only entry was a single link on Elements, and the add-to-card
toast was a dead end.

- opened without ?run_id&card_id, Elements now explains what elements are FOR
  and routes the visitor into the card flow via Activity
- the Media library page links the licence-clean Stock browser
- the add-to-card success toast carries a link back to the card's review page
"""

from __future__ import annotations

import json

import pytest

ORG = "org-c12"


@pytest.fixture
def env(client, web_module, tmp_path):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=ORG, display_name="Test Club"))
    assert client.post("/api/organisation/active", data={"profile_id": ORG}).status_code == 200
    return {"client": client, "wm": web_module, "tmp": tmp_path}


def _seed_run_with_brief(tmp_path, run_id="run-c12", card_id="swim-1"):
    runs_dir = tmp_path / "runs_v4"
    (runs_dir / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "profile_id": ORG,
                "recognition_report": {
                    "ranked_achievements": [
                        {
                            "id": card_id,
                            "achievement": {
                                "swim_id": card_id,
                                "event": "100 Freestyle",
                                "place": "1",
                                "is_pb": True,
                                "swimmer_name": "Alex Smith",
                            },
                        }
                    ]
                },
                "cards": [{"swim_id": card_id}],
            }
        ),
        encoding="utf-8",
    )
    bdir = runs_dir / run_id / "briefs"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "cb_c12.json").write_text(
        json.dumps({"id": "cb_c12", "content_item_id": card_id, "elements": []}),
        encoding="utf-8",
    )
    return run_id, card_id


def test_browse_only_elements_page_explains_and_routes_to_card_flow(env):
    html = env["client"].get("/elements").get_data(as_text=True)
    assert "Elements are stickers and badges you add to a card" in html
    assert "/activity" in html
    # No card context → no add-to-card affordance pretending to work.
    assert "Adding to <strong>" not in html


def test_card_context_page_keeps_add_flow_and_links_back_to_card(env):
    run_id, card_id = _seed_run_with_brief(env["tmp"])
    html = env["client"].get(f"/elements?run_id={run_id}&card_id={card_id}").get_data(as_text=True)
    # Context line still there…
    assert "Adding to <strong>" in html
    # …the explainer hero is not (it's for browse-only visits)…
    assert "Elements are stickers and badges you add to a card" not in html
    # …and the add toast can route back to the card's review page.
    assert "cardUrl" in html
    assert f"/review/{run_id}" in html
    assert "Back to the card" in html


def test_media_library_links_stock_browser(env):
    if not env["wm"]._v8_ok:
        pytest.skip("V8 media engine not available")
    html = env["client"].get("/media-library").get_data(as_text=True)
    assert "Find stock photos" in html
    assert "/stock" in html
