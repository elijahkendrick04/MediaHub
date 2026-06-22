"""Roadmap 1.20 Build D — the print web surface.

Exercises the print routes the way the g117 print tests do: a tmp DATA_DIR, two
orgs and a run on disk, multi-tenant isolation. The card-render (Chromium) and
the PDF colour hops aren't needed here — the testable route logic is auth,
product resolution, the deterministic preflight, the no-design gate and the
catalogue/capability surface.
"""

from __future__ import annotations

import importlib
import json
import sys
import uuid
from pathlib import Path

import pytest


def _run_payload(run_id: str, profile_id: str) -> dict:
    return {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "Spring Open", "start_date": "2026-06-06", "swimmers": {}, "results": []},
        "cards": [],
        "recognition_report": {"ranked_achievements": []},
    }


@pytest.fixture
def web_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.delenv("MEDIAHUB_FULFILMENT_PROVIDER", raising=False)
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="org-alpha",
            display_name="Org Alpha",
            club_codes=["ALPH"],
            brand_primary="#0E5BFF",
            brand_secondary="#101820",
        )
    )
    save_profile(ClubProfile(profile_id="org-beta", display_name="Org Beta"))

    run_id = "run-print-" + uuid.uuid4().hex[:8]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(_run_payload(run_id, "org-alpha")))
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name)"
        " VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-alpha", "Spring Open", "spring.hy3"),
    )
    conn.commit()
    conn.close()

    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield {"client": c, "run_id": run_id}


def _pin(client, profile_id):
    r = client.post("/api/organisation/active", data={"profile_id": profile_id})
    assert r.status_code == 200, r.get_json()


# ---------------------------------------------------------------------------
# Capability / catalogue surface
# ---------------------------------------------------------------------------


def test_print_products_catalogue(web_env):
    c = web_env["client"]
    _pin(c, "org-alpha")
    r = c.get("/api/print/products")
    assert r.status_code == 200
    body = r.get_json()
    fams = {g["family"] for g in body["families"]}
    assert {"paper", "apparel", "drinkware", "accessory"} <= fams
    assert set(body["capabilities"]) >= {"cmyk", "pdfx", "colour_modes"}
    assert body["fulfilment"]["enabled"] is False


def test_print_fulfilment_status_honest(web_env):
    c = web_env["client"]
    _pin(c, "org-alpha")
    r = c.get("/api/print/fulfilment")
    assert r.status_code == 200
    assert r.get_json()["enabled"] is False


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def test_print_center_page_renders(web_env):
    c = web_env["client"]
    _pin(c, "org-alpha")
    r = c.get("/print")
    assert r.status_code == 200
    assert b"Print" in r.data and b"merch" in r.data.lower()


def test_print_run_tool_page_access(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    ok = c.get(f"/print/{run_id}")
    assert ok.status_code == 200
    assert b"pr-product" in ok.data and b"print_center.js" in ok.data
    # cross-org cannot open the tool
    _pin(c, "org-beta")
    assert c.get(f"/print/{run_id}").status_code == 404


# ---------------------------------------------------------------------------
# Preflight (deterministic, no render)
# ---------------------------------------------------------------------------


def test_preflight_returns_report(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    r = c.post(f"/api/runs/{run_id}/card/c1/preflight?product=poster_a3")
    assert r.status_code == 200
    body = r.get_json()
    assert body["product"] == "poster_a3"
    assert "ok" in body and "violations" in body and "summary" in body


def test_preflight_unknown_product_400(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    r = c.post(f"/api/runs/{run_id}/card/c1/preflight?product=spaceship")
    assert r.status_code == 400


def test_preflight_cross_org_404(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-beta")
    r = c.post(f"/api/runs/{run_id}/card/c1/preflight?product=poster_a3")
    assert r.status_code == 404


def test_preflight_placement_selectable(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    r = c.post(f"/api/runs/{run_id}/card/c1/preflight?product=club_tee&placement=back")
    assert r.status_code == 200
    assert r.get_json()["placement"] == "back"


# ---------------------------------------------------------------------------
# Print + mockup gating (no Chromium needed — the no-design path returns first)
# ---------------------------------------------------------------------------


def test_print_no_design_returns_409(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    r = c.post(f"/api/runs/{run_id}/card/c1/print?product=poster_a3")
    assert r.status_code == 409
    assert r.get_json()["error"] == "no_design"


def test_print_bad_colour_mode_400(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    r = c.post(f"/api/runs/{run_id}/card/c1/print?product=poster_a3&colour=neon")
    assert r.status_code == 400


def test_print_unknown_product_400(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    r = c.post(f"/api/runs/{run_id}/card/c1/print?product=nope")
    assert r.status_code == 400


def test_print_cross_org_404(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-beta")
    r = c.post(f"/api/runs/{run_id}/card/c1/print?product=poster_a3")
    assert r.status_code == 404


def test_merch_mockup_no_design_409(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    r = c.post(f"/api/runs/{run_id}/card/c1/merch-mockup?product=club_tee")
    assert r.status_code == 409
