"""H-13 — a brand kit can be chosen per run at the configure step.

Before: runs always resolved the org's default kit (`_resolved_kit_for_run`),
and the configure form offered only raw one-off colour pickers — using a
sponsor/event kit for one meet meant flipping the org-wide default back and
forth.

Now: when the org has two or more kits, the configure form carries a
"Brand kit for these results" select (default = the org's current default
kit; hidden entirely for single-kit orgs) with the resolved kit's name and
palette swatches beside it. The choice is persisted with the run's brand-kit
config (``brand_kit_id`` in ``data/brand_kits/<run_id>.json``) and
``_resolved_kit_for_run`` prefers it when present and valid — an unknown or
deleted kit id, or an old run without the key, falls back to the default kit
exactly as before.
"""

from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    for sub in ("runs_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    return app, cp, wm, tmp_path


def _seed_two_kit_profile(cp, pid="brandclub"):
    """A profile with its primary livery + one sponsor kit (2 kits total)."""
    from mediahub.brand.kits import BrandKitRef, upsert_kit

    prof = cp.ClubProfile(
        profile_id=pid,
        display_name="Brand Club",
        brand_primary="#0E2A47",
        brand_secondary="#C9A227",
    )
    sponsor = BrandKitRef(
        kit_id="kit-sponsor",
        name="Acme Gala",
        role="sponsor",
        palette={"primary": "#112233", "secondary": "#445566", "accent": "#778899"},
    )
    upsert_kit(prof, sponsor)
    cp.save_profile(prof)
    return prof


def _signin(client, pid="brandclub"):
    with client.session_transaction() as s:
        s["active_profile_id"] = pid


def _stage_upload(wm, run_id="stagedcfg1"):
    """A staged upload the configure step can render/POST against."""
    tmp_dir = wm.RUNS_DIR / run_id
    tmp_dir.mkdir(parents=True, exist_ok=True)
    (tmp_dir / "input.bin").write_bytes(b"fake meet results bytes")
    (tmp_dir / "upload_meta.json").write_text(
        json.dumps(
            {
                "filename": "meet.hy3",
                "profile_id": None,
                "use_cache": True,
                "fetch_pbs": True,
                "display_name": "",
                "clubs": ["Brand Club", "Other SC"],
                "meet_name": "Spring Open",
                "n_events": 4,
                "file_byte_size": 4096,
            }
        ),
        encoding="utf-8",
    )
    return run_id


def _post_configure(client, staged_id, extra=None):
    data = {"run_id": staged_id, "club_filter": "Brand Club"}
    data.update(extra or {})
    return client.post("/upload/configure", data=data)


# ---- configure form ------------------------------------------------------


class TestConfigureFormKitSelect:
    def test_select_rendered_for_two_kit_org(self, app_env):
        app, cp, wm, _tmp = app_env
        _seed_two_kit_profile(cp)
        with app.test_client() as c:
            _signin(c)
            staged = _stage_upload(wm)
            body = c.get(f"/upload/configure?run_id={staged}").get_data(as_text=True)
        assert 'name="brand_kit_id"' in body
        assert 'id="run-config-kit"' in body
        assert "Brand kit for these results" in body
        # Both kits listed by name; the default is marked and preselected.
        assert "Acme Gala" in body
        assert "(default)" in body
        assert 'value="primary" selected' in body
        # Resolved kit name + palette swatches beside the select.
        assert 'id="mh-kit-choice-name"' in body
        assert 'id="mh-kit-choice-sw"' in body
        # The sponsor option carries its own palette data for the swatches.
        assert 'data-primary="#112233"' in body

    def test_select_hidden_for_single_kit_org(self, app_env):
        app, cp, wm, _tmp = app_env
        prof = cp.ClubProfile(profile_id="solo", display_name="Solo SC")
        cp.save_profile(prof)
        with app.test_client() as c:
            _signin(c, "solo")
            staged = _stage_upload(wm)
            body = c.get(f"/upload/configure?run_id={staged}").get_data(as_text=True)
        assert 'name="brand_kit_id"' not in body
        assert "Brand kit for these results" not in body


# ---- persistence on POST -------------------------------------------------


class TestConfigurePostPersistsChoice:
    def _run_and_read_kit_json(self, app_env, extra):
        app, cp, wm, tmp_path = app_env
        _seed_two_kit_profile(cp)
        with app.test_client() as c:
            _signin(c)
            staged = _stage_upload(wm)
            # Keep the pipeline thread out of the test — we only care about
            # what the configure POST persists for the new run.
            import unittest.mock as mock

            with mock.patch.object(wm, "_spawn_run_thread", lambda **kw: None):
                r = _post_configure(c, staged, extra)
        assert r.status_code in (302, 303)
        new_run_id = r.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
        kit_path = tmp_path / "data" / "brand_kits" / f"{new_run_id}.json"
        assert kit_path.exists(), "per-run brand kit JSON missing"
        return json.loads(kit_path.read_text())

    def test_valid_kit_id_is_persisted(self, app_env):
        payload = self._run_and_read_kit_json(app_env, {"brand_kit_id": "kit-sponsor"})
        assert payload["brand_kit_id"] == "kit-sponsor"

    def test_unknown_kit_id_degrades_to_default(self, app_env):
        payload = self._run_and_read_kit_json(app_env, {"brand_kit_id": "not-a-kit"})
        assert payload["brand_kit_id"] == ""

    def test_no_choice_posts_empty(self, app_env):
        payload = self._run_and_read_kit_json(app_env, {})
        assert payload["brand_kit_id"] == ""


# ---- resolution ----------------------------------------------------------


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


def _write_run_kit_json(tmp_path, run_id, payload):
    kits_dir = tmp_path / "data" / "brand_kits"
    kits_dir.mkdir(parents=True, exist_ok=True)
    (kits_dir / f"{run_id}.json").write_text(json.dumps(payload), encoding="utf-8")


class TestResolvedKitForRun:
    """Observed through the brand-check API, whose report names the kit
    (`kit_id`) the run resolved — the same resolver the approval gate uses."""

    def _check_kit_id(self, app_env, run_kit_payload):
        app, cp, wm, tmp_path = app_env
        _seed_two_kit_profile(cp)
        with app.test_client() as c:
            _signin(c)
            run_id, card_id = _seed_run_with_brief(cp, tmp_path)
            if run_kit_payload is not None:
                _write_run_kit_json(tmp_path, run_id, run_kit_payload)
            r = c.get(f"/api/runs/{run_id}/card/{card_id}/brand-check")
        assert r.status_code == 200, r.get_data(as_text=True)
        return r.get_json()["kit_id"]

    def test_chosen_kit_wins(self, app_env):
        kit_id = self._check_kit_id(
            app_env,
            {"display_name": "Brand Club", "brand_kit_id": "kit-sponsor"},
        )
        assert kit_id == "kit-sponsor"

    def test_old_run_without_key_uses_default(self, app_env):
        # Pre-H-13 file shape: no brand_kit_id key at all.
        kit_id = self._check_kit_id(app_env, {"display_name": "Brand Club"})
        assert kit_id == "primary"

    def test_deleted_kit_falls_back_to_default(self, app_env):
        kit_id = self._check_kit_id(
            app_env,
            {"display_name": "Brand Club", "brand_kit_id": "kit-deleted-long-ago"},
        )
        assert kit_id == "primary"

    def test_no_run_kit_json_at_all_uses_default(self, app_env):
        kit_id = self._check_kit_id(app_env, None)
        assert kit_id == "primary"


class TestKitDrivesSubmittedColours:
    def test_kit_change_writes_the_colour_inputs(self):
        """SRV-3: picking a kit must update the three colour inputs the form
        actually submits (the run renders from those), not just the preview
        swatches — only on a user change, never the initial paint.
        NOTE: this JS lives in an f-string region, so literal braces are
        doubled in the source text."""
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1] / "src" / "mediahub" / "web" / "web.py"
        ).read_text(encoding="utf-8")
        assert "function kitPaint(fromUser) {{" in src
        assert "if (pri && cols[0]) pri.value = cols[0];" in src
        assert "if (sec && cols[1]) sec.value = cols[1];" in src
        assert "if (acc && cols[2]) acc.value = cols[2];" in src
        assert "kitSel.addEventListener('change', function(){{ kitPaint(true); }});" in src
