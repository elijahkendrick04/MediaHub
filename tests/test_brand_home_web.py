"""Roadmap 1.12 build 3 — brand-platform web surface.

Covers the brand home page, multi-kit CRUD + default + palette-file import
routes, access control, and the per-card Brand Check / Assist API (honest-error
without a provider).
"""

from __future__ import annotations

import json
import re

import pytest


@pytest.fixture
def app_client(web_module, tmp_path, monkeypatch):
    # DATA_DIR isolation + one-time web.py import come from the autouse
    # ``_isolate_data_dir`` fixture in conftest.py.
    import mediahub.web.club_profile as cp

    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    app = web_module.create_app()
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


def test_card_brand_check_cross_tenant_is_404_not_403(app_client):
    """Anti-IDOR house norm: a foreign org's run must answer exactly like a
    missing one (404 run_not_found), never 403 — a 403 confirms the run id
    exists (enumeration signal)."""
    client, cp, tmp_path = app_client
    _seed_profile(cp)
    _signin(client)
    run_id, card_id = _seed_run_with_brief(cp, tmp_path, pid="some-other-org")
    r = client.get(f"/api/runs/{run_id}/card/{card_id}/brand-check")
    assert r.status_code == 404, r.status_code
    assert r.get_json()["error"] == "run_not_found"


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


# ---- audit regressions (brand platform, 2026-07) -----------------------


def _make_kit(client, cp, name="Gala", role="event", pid="brandclub"):
    """Create a kit via the route and return its id."""
    client.post("/api/brand/kits", data={"name": name, "role": role})
    from mediahub.brand.kits import list_kits

    return next(k.kit_id for k in list_kits(cp.load_profile(pid)) if k.name == name)


def test_resweep_js_carries_csrf_token_and_ok_guard(app_client):
    """F1/F5: the resweep preview/apply fetches must send the CSRF token (or
    they 403 in production) and reject on a non-ok status (or an error renders
    as a benign 'No cards would change')."""
    client, cp, _ = app_client
    _seed_profile(cp)
    _signin(client)
    html = client.get("/brand").get_data(as_text=True)
    assert "mh-resweep" in html
    # the two fetches carry the token via the X-CSRF-Token header
    assert "X-CSRF-Token" in html
    assert "'X-CSRF-Token':CSRF" in html
    # and reject on a non-2xx status instead of parsing an error body as data
    assert "if(!r.ok)" in html


def test_resweep_csrf_enforced_needs_token(app_client):
    """F1: with CSRF enforced (production posture), a tokenless resweep POST is
    blocked, but the header the fixed JS now sends passes."""
    client, cp, _ = app_client
    _seed_profile(cp)
    _signin(client)
    kid = _make_kit(client, cp)
    client.application.config["ENFORCE_CSRF"] = True
    client.get("/brand")  # mint the session CSRF token
    with client.session_transaction() as s:
        tok = s.get("_csrf")
    # browser-style fetch WITHOUT the header (the old behaviour) is blocked
    assert client.post(f"/api/brand/kits/{kid}/resweep/preview").status_code == 403
    # with the X-CSRF-Token header (what the fixed JS sends) it is accepted
    r = client.post(f"/api/brand/kits/{kid}/resweep/preview", headers={"X-CSRF-Token": tok})
    assert r.status_code == 200
    assert "n_affected" in r.get_json()


def _primary_edit_form(html):
    m = re.search(r'<form[^>]*action="[^"]*/api/brand/kits/primary"[^>]*>(.*?)</form>', html, re.S)
    assert m, "primary kit edit form not found"
    return m.group(0)


def test_edit_form_unset_slots_disabled_and_noop_save_preserves_palette(app_client):
    """F2: an unset colour slot must render its picker disabled (so the browser
    won't submit the on-brand fallback) and a no-op save must round-trip the
    palette unchanged — never fabricate an accent/fourth the club never chose."""
    client, cp, _ = app_client
    _seed_profile(cp)  # primary + secondary only
    _signin(client)
    from mediahub.brand.kits import list_kits, primary_kit

    before = primary_kit(cp.load_profile("brandclub")).palette
    assert set(before) == {"primary", "secondary"}
    form = _primary_edit_form(client.get("/brand").get_data(as_text=True))
    # simulate the browser: submit each colour input only when NOT disabled
    submitted = {}
    for im in re.finditer(
        r'<input type="color" name="(primary|secondary|accent|fourth)" '
        r'value="(#[0-9a-fA-F]{6})"([^>]*)>',
        form,
    ):
        slot, val, rest = im.group(1), im.group(2), im.group(3)
        if "disabled" not in rest:
            submitted[slot] = val
    # the two unset slots (accent/fourth) are disabled -> not submitted
    assert set(submitted) == {"primary", "secondary"}
    client.post("/api/brand/kits/primary", data={"name": "Primary brand", **submitted})
    after = next(k for k in list_kits(cp.load_profile("brandclub")) if k.role == "primary").palette
    assert after == before  # no fabricated accent/fourth


def test_edit_form_can_still_set_a_new_colour(app_client):
    """F2 guard: the fix must not stop a user from setting a slot explicitly."""
    client, cp, _ = app_client
    _seed_profile(cp)
    _signin(client)
    from mediahub.brand.kits import list_kits

    client.post(
        "/api/brand/kits/primary",
        data={"name": "Primary brand", "primary": "#0e2a47", "accent": "#abcdef"},
    )
    kit = next(k for k in list_kits(cp.load_profile("brandclub")) if k.role == "primary")
    assert kit.palette.get("accent") == "#abcdef"


def _bind(cp, pid, owner_email="owner@x.com"):
    from mediahub.web import tenancy as tn

    tn.MembershipStore().add(owner_email, pid, role=tn.ROLE_OWNER, status=tn.STATUS_ACTIVE)


def test_brand_home_read_only_for_non_owner_member(app_client):
    """F3: a bound-org member who is not an owner sees a read-only /brand — no
    create/edit/import/resweep controls that would dead-end in a 404 — while
    still viewing the kits."""
    client, cp, _ = app_client
    _seed_profile(cp, pid="orgb")
    _bind(cp, "orgb")
    from mediahub.web import tenancy as tn

    tn.MembershipStore().add("viewer@x.com", "orgb", role=tn.ROLE_VIEWER, status=tn.STATUS_ACTIVE)
    with client.session_transaction() as s:
        s["active_profile_id"] = "orgb"
        s["user_email"] = "viewer@x.com"
    html = client.get("/brand").get_data(as_text=True)
    assert "Brand kits" in html  # read-only content still shown
    for control in ("+ New kit", "Edit kit", "Import palette file", "Preview re-render impact"):
        assert control not in html, control
    # and the mutating route refuses the non-admin
    assert client.post("/api/brand/kits", data={"name": "X", "role": "sponsor"}).status_code == 404


def test_brand_home_shows_controls_for_owner(app_client):
    """F3 guard: an owner of a bound org still sees the full admin surface."""
    client, cp, _ = app_client
    _seed_profile(cp, pid="orgc")
    _bind(cp, "orgc", owner_email="boss@x.com")
    with client.session_transaction() as s:
        s["active_profile_id"] = "orgc"
        s["user_email"] = "boss@x.com"
    html = client.get("/brand").get_data(as_text=True)
    assert "+ New kit" in html
    assert "Preview re-render impact" in html


def test_brand_check_overlong_run_id_is_404_not_500(app_client):
    """F4: a run_id longer than the OS filename limit must not 500 (uncaught
    OSError leaking the internal path) — it answers like a missing run."""
    client, cp, _ = app_client
    _seed_profile(cp)
    _signin(client)
    long_id = "a" * 3000
    r = client.get(f"/api/runs/{long_id}/card/c1/brand-check")
    assert r.status_code == 404
    assert r.get_json()["error"] == "run_not_found"


def test_create_kit_cannot_mint_second_primary(app_client):
    """F6: a hand-crafted create with role=primary (or an invalid role) must not
    become a second, undeletable primary kit."""
    client, cp, _ = app_client
    _seed_profile(cp)
    _signin(client)
    from mediahub.brand.kits import list_kits

    for bad_role in ("primary", "wizard"):
        client.post(
            "/api/brand/kits",
            data={"name": f"Kit {bad_role}", "role": bad_role, "primary": "#abcdef"},
        )
    kits = list_kits(cp.load_profile("brandclub"))
    assert len([k for k in kits if k.role == "primary"]) == 1
    # the created kits are deletable (not primary)
    from mediahub.brand.kits import delete_kit

    prof = cp.load_profile("brandclub")
    for k in list_kits(prof):
        if k.name.startswith("Kit "):
            assert k.role != "primary"
