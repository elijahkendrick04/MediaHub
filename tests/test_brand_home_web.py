"""Roadmap 1.12 build 3 — brand-platform web surface.

Covers the brand home page, multi-kit CRUD + default + palette-file import
routes, access control, and the per-card Brand Check / Assist API (honest-error
without a provider).
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, cp, tmp_path


def _seed_profile(cp, pid="brandclub"):
    prof = cp.ClubProfile(
        profile_id=pid,
        display_name="Brand Club",
        brand_primary="#0E2A47",
        brand_secondary="#C9A227",
    )
    cp.save_profile(prof)
    return prof


def _signin(client, pid="brandclub"):
    with client.session_transaction() as s:
        s["active_profile_id"] = pid


# ---- brand home page ---------------------------------------------------


def test_brand_home_renders_with_synthesised_primary(app_client):
    client, cp, _ = app_client
    _seed_profile(cp)
    _signin(client)
    html = client.get("/brand").get_data(as_text=True)
    assert "Brand platform" in html
    assert "Brand kits" in html
    assert "Primary" in html  # the synthesised primary kit's role badge


def test_brand_home_requires_signin(app_client):
    client, _cp, _ = app_client
    r = client.get("/brand")
    assert r.status_code in (301, 302)
    assert "/sign-in" in r.headers.get("Location", "") or "sign" in r.headers.get("Location", "")


# ---- kit CRUD ----------------------------------------------------------


def test_create_kit(app_client):
    client, cp, _ = app_client
    _seed_profile(cp)
    _signin(client)
    r = client.post(
        "/api/brand/kits",
        data={"name": "Acme co-brand", "role": "sponsor", "primary": "#ff0000"},
    )
    assert r.status_code in (301, 302)
    prof = cp.load_profile("brandclub")
    names = [k.get("name") for k in prof.brand_kits]
    assert "Acme co-brand" in names


def test_create_kit_requires_name(app_client):
    client, cp, _ = app_client
    _seed_profile(cp)
    _signin(client)
    r = client.post("/api/brand/kits", data={"name": "  ", "role": "sponsor"})
    # redirects back with an error; no kit created
    assert r.status_code in (301, 302)
    prof = cp.load_profile("brandclub")
    assert prof.brand_kits == []


def test_update_kit_palette_and_locks(app_client):
    client, cp, _ = app_client
    _seed_profile(cp)
    _signin(client)
    client.post("/api/brand/kits", data={"name": "Gala", "role": "event"})
    prof = cp.load_profile("brandclub")
    from mediahub.brand.kits import list_kits

    kid = next(k.kit_id for k in list_kits(prof) if k.name == "Gala")
    r = client.post(
        f"/api/brand/kits/{kid}",
        data={"name": "Gala 2026", "primary": "#123456", "lock": ["palette"]},
    )
    assert r.status_code in (301, 302)
    prof2 = cp.load_profile("brandclub")
    kit = next(k for k in list_kits(prof2) if k.kit_id == kid)
    assert kit.name == "Gala 2026"
    assert kit.palette.get("primary") == "#123456"
    assert kit.locks == ["palette"]


def test_set_default_kit(app_client):
    client, cp, _ = app_client
    _seed_profile(cp)
    _signin(client)
    client.post("/api/brand/kits", data={"name": "Gala", "role": "event"})
    prof = cp.load_profile("brandclub")
    from mediahub.brand.kits import list_kits

    kid = next(k.kit_id for k in list_kits(prof) if k.name == "Gala")
    client.post(f"/api/brand/kits/{kid}/default")
    prof2 = cp.load_profile("brandclub")
    assert prof2.default_kit_id == kid


def test_delete_kit_and_primary_protection(app_client):
    client, cp, _ = app_client
    _seed_profile(cp)
    _signin(client)
    client.post("/api/brand/kits", data={"name": "Gala", "role": "event"})
    prof = cp.load_profile("brandclub")
    from mediahub.brand.kits import list_kits, primary_kit

    kid = next(k.kit_id for k in list_kits(prof) if k.name == "Gala")
    # delete the event kit
    client.post(f"/api/brand/kits/{kid}/delete")
    prof2 = cp.load_profile("brandclub")
    assert all(k.kit_id != kid for k in list_kits(prof2))
    # primary cannot be deleted
    prim = primary_kit(prof2).kit_id
    client.post(f"/api/brand/kits/{prim}/delete")
    prof3 = cp.load_profile("brandclub")
    assert any(k.role == "primary" for k in list_kits(prof3))


def test_kit_routes_reject_anonymous(app_client):
    client, cp, _ = app_client
    _seed_profile(cp)
    # not signed in → no active profile → 404 (anti-enumeration)
    r = client.post("/api/brand/kits", data={"name": "X", "role": "sponsor"})
    assert r.status_code == 404


# ---- palette-file import ----------------------------------------------


def test_palette_import_json(app_client):
    client, cp, _ = app_client
    _seed_profile(cp)
    _signin(client)
    client.post("/api/brand/kits", data={"name": "Imported", "role": "event"})
    prof = cp.load_profile("brandclub")
    from mediahub.brand.kits import list_kits

    kid = next(k.kit_id for k in list_kits(prof) if k.name == "Imported")
    import io

    payload = json.dumps(["#112233", "#445566", "#778899"]).encode("utf-8")
    r = client.post(
        f"/api/brand/kits/{kid}/palette/import",
        data={"palette_file": (io.BytesIO(payload), "theme.json")},
        content_type="multipart/form-data",
    )
    assert r.status_code in (301, 302)
    prof2 = cp.load_profile("brandclub")
    kit = next(k for k in list_kits(prof2) if k.kit_id == kid)
    assert kit.palette.get("primary") == "#112233"
    assert kit.palette.get("secondary") == "#445566"


# ---- per-card Brand Check API -----------------------------------------


def _seed_run_with_brief(cp, tmp_path, pid="brandclub", run_id="run-bc", card_id="swim_1"):
    runs = tmp_path / "runs_v4"
    (runs / run_id / "briefs").mkdir(parents=True, exist_ok=True)
    (runs / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "profile_id": pid,
                "meet": {"name": "County Champs"},
                "recognition_report": {"meet_name": "County Champs", "ranked_achievements": []},
            }
        ),
        encoding="utf-8",
    )
    from mediahub.creative_brief.generator import CreativeBrief

    brief = CreativeBrief(
        id="cb_test1",
        content_item_id=card_id,
        profile_id=pid,
        achievement_summary="",
        objective="",
        primary_hook="NEW PB",
        confidence_label="NEW PB",
        tone="data-led",
        layout_template="split_diagonal_hero",
        inspiration_pattern_id="",
        image_treatment="cutout",
        text_hierarchy=[],
        brand_instructions="",
        sponsor_instructions=None,
        sourced_asset_ids=[],
        safety_notes=[],
        why_this_design="",
        text_layers={"headline_line1": "PB"},
        palette={"primary": "#0E5BFF", "secondary": "#101820", "accent": "#F4D58D"},
        format_priority=["story"],
    )
    (runs / run_id / "briefs" / "cb_test1.json").write_text(
        json.dumps(brief.to_dict()), encoding="utf-8"
    )
    return run_id, card_id


def test_card_brand_check_returns_report(app_client):
    client, cp, tmp_path = app_client
    _seed_profile(cp)
    _signin(client)
    run_id, card_id = _seed_run_with_brief(cp, tmp_path)
    r = client.get(f"/api/runs/{run_id}/card/{card_id}/brand-check")
    assert r.status_code == 200
    body = r.get_json()
    assert "passed" in body and "findings" in body
    checks = {f["check"] for f in body["findings"]}
    assert checks == {"palette", "contrast", "fonts", "logo"}


def test_card_brand_check_no_brief_is_404(app_client):
    client, cp, tmp_path = app_client
    _seed_profile(cp)
    _signin(client)
    # run exists but no brief for this card
    (tmp_path / "runs_v4" / "run-x.json").write_text(
        json.dumps({"run_id": "run-x", "profile_id": "brandclub", "recognition_report": {}}),
        encoding="utf-8",
    )
    r = client.get("/api/runs/run-x/card/ghost/brand-check")
    assert r.status_code == 404


def test_card_brand_advise_honest_error_without_provider(app_client):
    client, cp, tmp_path = app_client
    _seed_profile(cp)
    _signin(client)
    run_id, card_id = _seed_run_with_brief(cp, tmp_path)
    r = client.post(f"/api/runs/{run_id}/card/{card_id}/brand-check/advise")
    assert r.status_code == 200
    assert r.get_json()["available"] is False


def test_card_brand_autofix_honest_error_without_provider(app_client):
    client, cp, tmp_path = app_client
    _seed_profile(cp)
    _signin(client)
    run_id, card_id = _seed_run_with_brief(cp, tmp_path)
    r = client.post(f"/api/runs/{run_id}/card/{card_id}/brand-check/autofix")
    assert r.status_code == 200
    body = r.get_json()
    assert body["available"] is False
    assert body["changed"] is False
