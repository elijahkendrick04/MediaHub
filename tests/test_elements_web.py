"""Roadmap 1.10 build 2 — Elements browse/search/add-to-card web routes."""

from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    return app, wm, tmp_path


def _seed_run_with_brief(tmp_path, run_id="run-1", card_id="swim-1", brief_id="cb_test1"):
    runs_dir = tmp_path / "runs_v4"
    runs_dir.mkdir(parents=True, exist_ok=True)
    # _load_run reads the flat RUNS_DIR/<run_id>.json
    (runs_dir / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
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
    # briefs live in the RUNS_DIR/<run_id>/briefs/ subdir
    bdir = runs_dir / run_id / "briefs"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / f"{brief_id}.json").write_text(
        json.dumps({"id": brief_id, "content_item_id": card_id, "elements": []}),
        encoding="utf-8",
    )
    return run_id, card_id, brief_id


# ---- public browse / search ------------------------------------------------
def test_api_elements_browse(app_env):
    app, _wm, _ = app_env
    with app.test_client() as c:
        resp = c.get("/api/elements")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["elements"]
    first = data["elements"][0]
    assert "<svg" in first["svg"]
    assert "__" not in first["svg"]  # fully recoloured
    assert "semantic" in data


def test_api_elements_search_filter(app_env):
    app, _wm, _ = app_env
    with app.test_client() as c:
        resp = c.get("/api/elements?q=trophy")
    ids = [e["id"] for e in resp.get_json()["elements"]]
    assert "pictogram.trophy" in ids


def test_api_elements_kind_filter(app_env):
    app, _wm, _ = app_env
    with app.test_client() as c:
        resp = c.get("/api/elements?kind=chip")
    kinds = {e["kind"] for e in resp.get_json()["elements"]}
    assert kinds == {"chip"}


def test_api_gradients(app_env):
    app, _wm, _ = app_env
    with app.test_client() as c:
        resp = c.get("/api/elements/gradients")
    grads = resp.get_json()["gradients"]
    assert grads
    assert all(g["css"].startswith(("linear-gradient", "radial-gradient")) for g in grads)


def test_elements_page_renders(app_env):
    app, _wm, _ = app_env
    with app.test_client() as c:
        resp = c.get("/elements")
    assert resp.status_code == 200
    assert b"Elements" in resp.data
    assert b"eb-grid" in resp.data


# ---- add / list / clear on a card ------------------------------------------
def test_add_element_to_card(app_env):
    app, _wm, tmp_path = app_env
    run_id, card_id, brief_id = _seed_run_with_brief(tmp_path)
    with app.test_client() as c:
        resp = c.post(
            f"/api/runs/{run_id}/card/{card_id}/elements",
            json={"element_id": "pictogram.trophy", "x": 0.8, "y": 0.2},
        )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    # persisted onto the brief
    bpath = tmp_path / "runs_v4" / run_id / "briefs" / f"{brief_id}.json"
    saved = json.loads(bpath.read_text())
    assert saved["elements"]
    assert saved["elements"][0]["element_id"] == "pictogram.trophy"


def test_add_unknown_element_rejected(app_env):
    app, _wm, tmp_path = app_env
    run_id, card_id, _ = _seed_run_with_brief(tmp_path)
    with app.test_client() as c:
        resp = c.post(
            f"/api/runs/{run_id}/card/{card_id}/elements",
            json={"element_id": "nope.ghost"},
        )
    assert resp.status_code == 404


def test_list_and_clear_elements(app_env):
    app, _wm, tmp_path = app_env
    run_id, card_id, _ = _seed_run_with_brief(tmp_path)
    with app.test_client() as c:
        c.post(f"/api/runs/{run_id}/card/{card_id}/elements", json={"element_id": "chip.pb"})
        listed = c.get(f"/api/runs/{run_id}/card/{card_id}/elements").get_json()
        assert len(listed["elements"]) == 1
        cleared = c.post(
            f"/api/runs/{run_id}/card/{card_id}/elements", json={"clear": True}
        ).get_json()
        assert cleared["elements"] == []


def test_remove_index(app_env):
    app, _wm, tmp_path = app_env
    run_id, card_id, _ = _seed_run_with_brief(tmp_path)
    with app.test_client() as c:
        c.post(f"/api/runs/{run_id}/card/{card_id}/elements", json={"element_id": "chip.pb"})
        c.post(
            f"/api/runs/{run_id}/card/{card_id}/elements", json={"element_id": "pictogram.trophy"}
        )
        out = c.post(
            f"/api/runs/{run_id}/card/{card_id}/elements", json={"remove_index": 0}
        ).get_json()
        assert len(out["elements"]) == 1
        assert out["elements"][0]["element_id"] == "pictogram.trophy"


def test_add_without_brief_409(app_env):
    app, _wm, tmp_path = app_env
    # run exists but no brief written
    runs_dir = tmp_path / "runs_v4"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / "run-x.json").write_text(
        json.dumps({"run_id": "run-x", "cards": []}), encoding="utf-8"
    )
    with app.test_client() as c:
        resp = c.post("/api/runs/run-x/card/swim-1/elements", json={"element_id": "chip.pb"})
    assert resp.status_code == 409


def test_element_suggestions_for_card(app_env):
    app, _wm, tmp_path = app_env
    run_id, card_id, _ = _seed_run_with_brief(tmp_path)
    with app.test_client() as c:
        resp = c.get(f"/api/runs/{run_id}/card/{card_id}/element-suggestions")
    assert resp.status_code == 200
    data = resp.get_json()
    # gold (place 1) + PB context → trophy / rosette / pb chip / stopwatch
    ids = {e["id"] for e in data["elements"]}
    assert ids & {"pictogram.trophy", "badge.first", "chip.pb", "pictogram.stopwatch"}


def test_elements_page_card_context_has_add_buttons(app_env):
    app, _wm, tmp_path = app_env
    run_id, card_id, _ = _seed_run_with_brief(tmp_path)
    with app.test_client() as c:
        resp = c.get(f"/elements?run_id={run_id}&card_id={card_id}")
    assert resp.status_code == 200
    assert b"Add to card" in resp.data or b"inCard" in resp.data


def test_browser_card_builder_is_dom_safe(app_env):
    """The browse grid must not concatenate catalog metadata into innerHTML —
    org-custom name/kind/id are user-controlled, so a raw concat is stored XSS.
    Regression lock: the card builder uses textContent / setAttribute instead."""
    app, _wm, _ = app_env
    with app.test_client() as c:
        html = c.get("/elements").get_data(as_text=True)
    # safe construction present
    assert "textContent = el.name" in html
    assert "textContent = el.kind" in html
    assert "setAttribute('data-id', el.id" in html
    # the old unsafe innerHTML concatenation of user-controlled fields is gone
    assert "+ (el.name" not in html
    assert "+ (el.kind" not in html
    assert "data-id=\"' + el.id" not in html
