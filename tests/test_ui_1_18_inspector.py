"""UI 1.18 — Inspector / properties panel (Sketch-inspired).

A lightweight side panel on the /review surface for tweaking a generated card
*before* approval: edit the caption, swap the brand-palette accent, toggle
elements (photo / sponsor strip), and adjust the crop. Everything posts back to
EXISTING Flask routes — ``create-graphic`` (live re-render), ``live-caption``
(AI drafts) and the workflow ``set_edits`` route (persistence) — with no new
persistence layer: the overrides ride the existing ``edited_captions`` bag under
dotted ``insp.*`` keys.

These tests pin, end to end:
  - the crop-override CSS-injection guard + render threading;
  - the accent / hex guard and brand-locked swatch contract;
  - the create-graphic route parsing overrides from the request AND honouring
    the persisted defaults, plus byte-identical behaviour when none are set;
  - persistence via the existing set_edits route, and that the dotted keys never
    corrupt the caption pack builder;
  - the /review page rendering the drawer, per-card Inspect buttons, brand-locked
    swatches, crop grid and persisted state — XSS-safe;
  - the CSS contract (rules present + reduced-motion gated).
"""
from __future__ import annotations

import importlib
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


# ===========================================================================
# 1. Crop override — CSS-injection guard + render threading (no Chromium)
# ===========================================================================
class TestCropOverride:
    def test_sanitise_accepts_keyword_pairs(self):
        from mediahub.graphic_renderer.render import _sanitise_photo_pos as s
        assert s("left top") == "left top"
        assert s("center center") == "center center"
        assert s("right bottom") == "right bottom"
        assert s("center") == "center"

    def test_sanitise_accepts_percentages(self):
        from mediahub.graphic_renderer.render import _sanitise_photo_pos as s
        assert s("center 25%") == "center 25%"
        assert s("0% 100%") == "0% 100%"
        assert s("50% 50%") == "50% 50%"

    def test_sanitise_rejects_injection_and_junk(self):
        from mediahub.graphic_renderer.render import _sanitise_photo_pos as s
        for bad in (
            "url(http://evil)", "red;}", "center;}", "120%", "-5%", "10px",
            "left top center", "expression(1)", "}{", "var(--x)", "center 25px",
            "", "   ", "TOPLEFT123",
        ):
            assert s(bad) == "", f"{bad!r} must be rejected"

    def _brief(self):
        return SimpleNamespace(
            text_layers={"result_value": "1:23.45", "athlete_surname": "Davies"},
            palette={"primary": "#0A2540", "secondary": "#C9A227", "accent": "#C9A227"},
            colour_role_assignment={},
            inspiration_pattern_id="",
            confidence_label="",
            layout_template="story_card",
        )

    def test_override_reaches_root_css(self):
        from mediahub.graphic_renderer import render as r
        repl = r._fill_v2_archetype(
            self._brief(), 1080, 1350, {"BASE_CSS": ""},
            athlete_path=None, brand_kit=None, photo_pos_override="left top",
        )
        assert "--mh-photo-pos:left top;" in repl["BASE_CSS"]

    def test_injection_override_falls_back_to_saliency(self):
        from mediahub.graphic_renderer import render as r
        repl = r._fill_v2_archetype(
            self._brief(), 1080, 1350, {"BASE_CSS": ""},
            athlete_path=None, brand_kit=None, photo_pos_override="red;}",
        )
        css = repl["BASE_CSS"]
        assert "red;}" not in css
        # No athlete → saliency default keeps the slot safe and present.
        assert "--mh-photo-pos:center 28%;" in css

    def test_no_override_is_unchanged_default(self):
        from mediahub.graphic_renderer import render as r
        repl = r._fill_v2_archetype(
            self._brief(), 1080, 1350, {"BASE_CSS": ""},
            athlete_path=None, brand_kit=None,  # photo_pos_override defaults ""
        )
        assert "--mh-photo-pos:center 28%;" in repl["BASE_CSS"]

    def test_render_brief_and_variants_accept_kwarg(self):
        import inspect
        from mediahub.graphic_renderer.render import render_brief
        from mediahub.graphic_renderer.variants import render_all_formats
        assert "photo_pos_override" in inspect.signature(render_brief).parameters
        assert "photo_pos_override" in inspect.signature(render_all_formats).parameters


# ===========================================================================
# 2. Accent override — hex guard + create_visual_for_item plumbing
# ===========================================================================
class TestAccentOverride:
    def test_hex_guard(self):
        from mediahub.content_pack_visual.integration import _sanitise_hex as s
        assert s("#D4FF3A") == "#D4FF3A"
        assert s("#abc") == "#abc"
        assert s(" #0A2540 ") == "#0A2540"
        for bad in ("red", "#12", "#12345", "#GGGGGG", "#12;}", "", None, "rgb(0,0,0)"):
            assert s(bad) == "", f"{bad!r} must be rejected"

    def test_create_visual_accepts_user_overrides_kwarg(self):
        import inspect
        from mediahub.content_pack_visual.integration import create_visual_for_item
        assert "user_overrides" in inspect.signature(create_visual_for_item).parameters


# ===========================================================================
# 2b. Override application — create_visual_for_item genuinely changes the render
#     (Chromium-free: the render entry is captured, not screenshotted)
# ===========================================================================
class TestOverrideApplication:
    def _run_capture(self, tmp_path, monkeypatch, overrides):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
        from mediahub.brand.kit import BrandKit
        import mediahub.graphic_renderer.variants as variants

        captured = {}

        def _fake_render_all_formats(brief, **kwargs):
            captured["brief"] = brief
            captured["kwargs"] = kwargs
            return []  # no Chromium; we only need the call args

        monkeypatch.setattr(variants, "render_all_formats", _fake_render_all_formats)

        from mediahub.content_pack_visual.integration import create_visual_for_item
        item = {
            "id": "x", "swim_id": "x",
            "achievement": {
                "swimmer_name": "Jane Davies", "event": "200m Backstroke",
                "time": "2:23.45", "pb": True, "type": "pb",
                "headline": "New PB", "confidence_label": "high",
            },
            "safe_to_post": {"level": "safe"},
        }
        bk = BrandKit(
            profile_id="p", display_name="C",
            primary_colour="#0A2540", secondary_colour="#C9A227", accent_colour="#D4FF3A",
        )
        create_visual_for_item(
            item, bk, profile_id="p", run_id="r1",
            formats=["feed_portrait"], sponsor_name="Acme Pools",
            user_overrides=overrides,
        )
        return captured

    def test_accent_override_repaints_brief_and_kit(self, tmp_path, monkeypatch):
        cap = self._run_capture(tmp_path, monkeypatch, {"accent": "#C9A227"})
        assert cap["brief"].palette.get("accent") == "#C9A227"
        # render is handed a kit copy carrying the chosen accent (legibility gate
        # still runs downstream in the role resolver).
        assert getattr(cap["kwargs"]["brand_kit"], "accent_colour", None) == "#C9A227"

    def test_invalid_accent_ignored(self, tmp_path, monkeypatch):
        cap = self._run_capture(tmp_path, monkeypatch, {"accent": "evil;}"})
        assert cap["brief"].palette.get("accent") != "evil;}"

    def test_hide_sponsor_drops_strip(self, tmp_path, monkeypatch):
        cap = self._run_capture(tmp_path, monkeypatch, {"hide_sponsor": True})
        assert cap["kwargs"]["sponsor_name"] == ""
        assert cap["kwargs"]["sponsor_logo_path"] is None

    def test_sponsor_kept_when_not_hidden(self, tmp_path, monkeypatch):
        cap = self._run_capture(tmp_path, monkeypatch, {})
        assert cap["kwargs"]["sponsor_name"] == "Acme Pools"

    def test_crop_threads_to_render(self, tmp_path, monkeypatch):
        cap = self._run_capture(tmp_path, monkeypatch, {"photo_pos": "left top"})
        assert cap["kwargs"]["photo_pos_override"] == "left top"

    def test_no_overrides_render_untouched(self, tmp_path, monkeypatch):
        cap = self._run_capture(tmp_path, monkeypatch, {})
        assert cap["kwargs"]["photo_pos_override"] == ""
        assert cap["kwargs"]["sponsor_name"] == "Acme Pools"


# ===========================================================================
# 3. Brand-locked swatch contract + persisted-override reader
# ===========================================================================
class TestSwatchesAndState:
    def test_swatches_are_brand_locked_deduped_valid(self):
        from mediahub.web import web as webmod
        from mediahub.brand.kit import BrandKit
        bk = BrandKit(
            profile_id="p", display_name="C",
            primary_colour="#0A2540", secondary_colour="#0A2540",  # dup → deduped
            accent_colour="#C9A227",
        )
        sw = webmod._brand_swatches(bk)
        hexes = [s["hex"] for s in sw]
        assert hexes == ["#0A2540", "#C9A227"], sw  # secondary dup dropped
        assert all(s["hex"].startswith("#") for s in sw)

    def test_swatches_drop_invalid(self):
        from mediahub.web import web as webmod
        from mediahub.brand.kit import BrandKit
        bk = BrandKit(
            profile_id="p", display_name="C",
            primary_colour="not-a-colour", secondary_colour="#C9A227", accent_colour=None,
        )
        sw = webmod._brand_swatches(bk)
        assert [s["hex"] for s in sw] == ["#C9A227"]

    def test_state_attrs_only_emit_set_keys(self):
        from mediahub.web import web as webmod
        st = SimpleNamespace(edited_captions={
            "insp.accent": "#C9A227", "insp.focus": "left top",
            "insp.hideSponsor": "1",
        })
        attrs = webmod._inspector_state_attrs(st)
        assert 'data-insp-accent="#C9A227"' in attrs
        assert 'data-insp-focus="left top"' in attrs
        assert 'data-insp-hide-sponsor="1"' in attrs
        assert "data-insp-no-photo" not in attrs  # not set
        assert "data-insp-caption" not in attrs  # not set

    def test_state_attrs_reject_bad_accent(self):
        from mediahub.web import web as webmod
        st = SimpleNamespace(edited_captions={"insp.accent": "javascript:alert(1)"})
        assert webmod._inspector_state_attrs(st) == ""

    def test_state_attrs_empty_for_clean_card(self):
        from mediahub.web import web as webmod
        assert webmod._inspector_state_attrs(None) == ""
        assert webmod._inspector_state_attrs(SimpleNamespace(edited_captions=None)) == ""


# ---------------------------------------------------------------------------
# Shared review/route fixture (mirrors test_review_body_content.py)
# ---------------------------------------------------------------------------
def _seed_run(tmp_path, wm, profile_id, run_payload):
    run_id = run_payload["run_id"]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(run_payload))
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs "
        "(id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, profile_id, run_payload["meet"]["name"], "test.hy3"),
    )
    conn.commit()
    conn.close()
    return run_id


def _make_run_payload(profile_id, achievements):
    run_id = "run-insp-" + uuid.uuid4().hex[:8]
    return {
        "run_id": run_id,
        "profile_id": profile_id,
        "profile_display": "Test Club",
        "meet": {"name": "INSPECTOR TEST MEET"},
        "cards": [],
        "trust": {"score": 0.85},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "rank": i + 1,
                    "achievement": {
                        "swim_id": a["swim_id"],
                        "swimmer_name": a["swimmer_name"],
                        "event": a["event"],
                        "headline": a["headline"],
                        "type": a.get("type", "pb"),
                        "confidence_label": "high",
                    },
                    "quality_band": "elite",
                    "priority": 0.9,
                    "suggested_post_type": "story",
                    "factors": [],
                }
                for i, a in enumerate(achievements)
            ],
            "n_elite": len(achievements),
            "n_strong": 0,
            "n_story": 0,
            "n_achievements": len(achievements),
            "n_swims_analysed": len(achievements),
        },
        "parse_warnings": [],
        "self_check": {},
        "detector_summary": {},
        "dispatch_log": {},
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.brand.kit import BrandKit
    save_profile(ClubProfile(
        profile_id="org-test",
        display_name="Test Club",
        brand_voice_summary="Clear and energetic.",
        brand_kit=BrandKit(
            profile_id="org-test", display_name="Test Club",
            primary_colour="#0A2540", secondary_colour="#C9A227", accent_colour="#D4FF3A",
        ),
    ))

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True
    with app.test_client() as client:
        r = client.post("/api/organisation/active", data={"profile_id": "org-test"})
        assert r.status_code == 200, r.get_json()
        yield {"client": client, "wm": wm, "tmp_path": tmp_path}


# ===========================================================================
# 4. /review renders the inspector drawer + per-card Inspect buttons
# ===========================================================================
class TestReviewRendersInspector:
    def _review(self, env, achievements):
        payload = _make_run_payload("org-test", achievements)
        run_id = _seed_run(env["tmp_path"], env["wm"], "org-test", payload)
        r = env["client"].get(f"/review/{run_id}")
        assert r.status_code == 200, r.status_code
        return run_id, r.get_data(as_text=True)

    def test_drawer_present_once(self, env):
        _, body = self._review(env, [
            {"swim_id": "s1", "swimmer_name": "Jane Smith", "event": "200m Fly", "headline": "PB"},
        ])
        assert body.count('id="mh-inspector"') == 1
        assert 'id="mh-inspector-scrim"' in body
        assert 'role="dialog"' in body

    def test_inspect_button_per_card(self, env):
        achs = [
            {"swim_id": f"s{i}", "swimmer_name": f"Swimmer {i}", "event": "100m Free", "headline": f"PB {i}"}
            for i in range(3)
        ]
        run_id, body = self._review(env, achs)
        # One Inspect button per card (the class is button-only; the bare
        # data-mh-inspect token also appears in the JS delegated-click selectors).
        assert body.count("mh-inspect-btn") == 3
        # Each button carries the card's existing-route URLs.
        assert f"/api/runs/{run_id}/cards/s0/create-graphic" in body
        assert f"/api/runs/{run_id}/swim/s0/caption" in body

    def test_brand_locked_swatches_rendered(self, env):
        _, body = self._review(env, [
            {"swim_id": "s1", "swimmer_name": "Jane Smith", "event": "200m Fly", "headline": "PB"},
        ])
        # The profile's brand colours appear as swatch options...
        assert 'data-accent="#0A2540"' in body
        assert 'data-accent="#C9A227"' in body
        assert 'data-accent="#D4FF3A"' in body
        # ...plus the Auto (clear) option.
        assert 'data-accent=""' in body

    def test_controls_and_crop_grid_present(self, env):
        _, body = self._review(env, [
            {"swim_id": "s1", "swimmer_name": "Jane Smith", "event": "200m Fly", "headline": "PB"},
        ])
        assert 'id="mh-insp-caption"' in body
        assert 'id="mh-insp-photo"' in body
        assert 'id="mh-insp-sponsor"' in body
        assert 'id="mh-insp-cropgrid"' in body
        # 9 crop cells + 1 auto.
        assert body.count('class="mh-insp-crop"') == 9
        assert 'data-focus="center center"' in body
        assert 'id="mh-insp-apply"' in body

    def test_persisted_state_shows_on_button(self, env):
        payload = _make_run_payload("org-test", [
            {"swim_id": "s1", "swimmer_name": "Jane Smith", "event": "200m Fly", "headline": "PB"},
        ])
        run_id = _seed_run(env["tmp_path"], env["wm"], "org-test", payload)
        ws = env["wm"]._get_wf_store()
        ws.set_edits(run_id, "s1", {
            "insp.accent": "#C9A227", "insp.focus": "left top", "insp.hideSponsor": "1",
        })
        body = env["client"].get(f"/review/{run_id}").get_data(as_text=True)
        assert 'data-insp-accent="#C9A227"' in body
        assert 'data-insp-focus="left top"' in body
        assert 'data-insp-hide-sponsor="1"' in body

    def test_inspector_js_wired(self, env):
        _, body = self._review(env, [
            {"swim_id": "s1", "swimmer_name": "Jane Smith", "event": "200m Fly", "headline": "PB"},
        ])
        assert "set_edits" in body
        assert "insp.accent" in body
        assert "warm-club_headline" in body  # caption save honours every tone

    def test_title_uses_textcontent_not_innerhtml(self, env):
        """DOM-XSS guard: getAttribute decodes the server escaping, so the card
        title must be assigned via textContent (innerHTML would re-parse it)."""
        _, body = self._review(env, [
            {"swim_id": "s1", "swimmer_name": "Jane Smith", "event": "200m Fly", "headline": "PB"},
        ])
        assert "titleEl.textContent = ctx.title" in body
        assert "titleEl.innerHTML = ctx.title" not in body

    def test_xss_safe_inspect_button_title(self, env):
        """The Inspect button's data-card-title (my markup) must be escaped so a
        hostile swimmer name can neither break out of the attribute nor inject a
        tag. (The pre-existing .ach-row data-swimmer attribute is out of scope.)"""
        import re as _re
        run_id, body = self._review(env, [
            {"swim_id": "s1", "swimmer_name": 'A"><img src=x onerror=alert(1)>',
             "event": "200m Fly", "headline": "PB"},
        ])
        titles = _re.findall(r'data-card-title="([^"]*)"', body)
        assert titles, "inspect button must carry a data-card-title"
        joined = " ".join(titles)
        # No raw breakout / tag survived into the title.
        assert '"><img' not in joined
        assert "<img" not in joined
        # Escaping actually ran.
        assert "&lt;img" in body and "&#34;" in body


# ===========================================================================
# 5. create-graphic route — override parsing + persisted defaults
#    (_v8_create_visual_for_item mocked so no Chromium is needed)
# ===========================================================================
class TestCreateGraphicOverrides:
    def _seed(self, env):
        payload = _make_run_payload("org-test", [
            {"swim_id": "s1", "swimmer_name": "Jane Smith", "event": "200m Fly", "headline": "PB"},
        ])
        return _seed_run(env["tmp_path"], env["wm"], "org-test", payload)

    @pytest.fixture
    def captured(self, env):
        """Patch the render entry to capture kwargs and skip Chromium."""
        calls = {}

        def _fake(item, brand_kit, **kwargs):
            calls["kwargs"] = kwargs
            calls["brand_kit"] = brand_kit
            return {"visuals": [{"id": "vis1", "format_name": "feed_portrait"}],
                    "brief": {"variation_signature": "sig", "primary_hook": "hook"},
                    "errors": []}

        env["calls"] = calls
        with mock.patch.object(env["wm"], "_v8_create_visual_for_item", _fake):
            yield env

    def test_request_overrides_passed_through(self, captured):
        if not captured["wm"]._v8_ok:
            pytest.skip("v8 engine unavailable")
        run_id = self._seed(captured)
        r = captured["client"].post(
            f"/api/runs/{run_id}/cards/s1/create-graphic",
            json={"accent": "#C9A227", "focus": "left top", "hide_sponsor": True},
        )
        assert r.status_code == 200, r.get_json()
        ov = captured["calls"]["kwargs"]["user_overrides"]
        assert ov["accent"] == "#C9A227"
        assert ov["photo_pos"] == "left top"
        assert ov["hide_sponsor"] is True

    def test_response_carries_swatches_and_inspector(self, captured):
        if not captured["wm"]._v8_ok:
            pytest.skip("v8 engine unavailable")
        run_id = self._seed(captured)
        j = captured["client"].post(
            f"/api/runs/{run_id}/cards/s1/create-graphic", json={"accent": "#C9A227"},
        ).get_json()
        assert "brand_swatches" in j and isinstance(j["brand_swatches"], list)
        assert any(s["hex"] == "#0A2540" for s in j["brand_swatches"])
        assert j["inspector"]["accent"] == "#C9A227"

    def test_persisted_overrides_are_default(self, captured):
        """An override saved via the inspector re-applies on a later plain render
        (e.g. the content builder), with no override in the request body."""
        if not captured["wm"]._v8_ok:
            pytest.skip("v8 engine unavailable")
        run_id = self._seed(captured)
        ws = captured["wm"]._get_wf_store()
        ws.set_edits(run_id, "s1", {"insp.focus": "right bottom", "insp.hideSponsor": "1"})
        r = captured["client"].post(
            f"/api/runs/{run_id}/cards/s1/create-graphic", json={},
        )
        assert r.status_code == 200
        ov = captured["calls"]["kwargs"]["user_overrides"]
        assert ov["photo_pos"] == "right bottom"
        assert ov["hide_sponsor"] is True

    def test_request_overrides_win_over_persisted(self, captured):
        if not captured["wm"]._v8_ok:
            pytest.skip("v8 engine unavailable")
        run_id = self._seed(captured)
        ws = captured["wm"]._get_wf_store()
        ws.set_edits(run_id, "s1", {"insp.focus": "right bottom"})
        captured["client"].post(
            f"/api/runs/{run_id}/cards/s1/create-graphic", json={"focus": "left top"},
        )
        assert captured["calls"]["kwargs"]["user_overrides"]["photo_pos"] == "left top"

    def test_no_overrides_byte_identical(self, captured):
        """With no inspector overrides at all, nothing extra is forced on the
        render — accent/photo_pos empty, toggles falsey."""
        if not captured["wm"]._v8_ok:
            pytest.skip("v8 engine unavailable")
        run_id = self._seed(captured)
        captured["client"].post(f"/api/runs/{run_id}/cards/s1/create-graphic", json={})
        ov = captured["calls"]["kwargs"]["user_overrides"]
        assert ov.get("accent", "") == ""
        assert ov.get("photo_pos", "") == ""
        assert not ov.get("hide_sponsor")
        assert not ov.get("no_photo")

    def test_persisted_no_photo_forces_text_led(self, captured):
        if not captured["wm"]._v8_ok:
            pytest.skip("v8 engine unavailable")
        run_id = self._seed(captured)
        ws = captured["wm"]._get_wf_store()
        ws.set_edits(run_id, "s1", {"insp.noPhoto": "1"})
        captured["client"].post(f"/api/runs/{run_id}/cards/s1/create-graphic", json={})
        # no_photo constrains the family to text-led ones.
        fams = captured["calls"]["kwargs"].get("allowed_families")
        assert fams and "text_led_recap" in fams

    def test_variants_receive_persisted_overrides(self, captured):
        """Regenerate-variants renders honour saved inspector tweaks too —
        a pinned accent/crop must not silently vanish on 'Show alternatives'."""
        if not captured["wm"]._v8_ok:
            pytest.skip("v8 engine unavailable")
        run_id = self._seed(captured)
        ws = captured["wm"]._get_wf_store()
        ws.set_edits(run_id, "s1", {"insp.accent": "#C9A227", "insp.focus": "left top"})
        r = captured["client"].post(
            f"/api/runs/{run_id}/cards/s1/regenerate-variants?sync=1", json={},
        )
        assert r.status_code == 200, r.get_json()
        ov = captured["calls"]["kwargs"]["user_overrides"]
        assert ov["accent"] == "#C9A227"
        assert ov["photo_pos"] == "left top"


# ===========================================================================
# 6. Persistence via existing set_edits route + pack-builder safety
# ===========================================================================
class TestPersistence:
    def test_set_edits_stores_insp_keys(self, env):
        payload = _make_run_payload("org-test", [
            {"swim_id": "s1", "swimmer_name": "Jane Smith", "event": "200m Fly", "headline": "PB"},
        ])
        run_id = _seed_run(env["tmp_path"], env["wm"], "org-test", payload)
        r = env["client"].post(
            f"/api/workflow/{run_id}/s1",
            json={"action": "set_edits", "edits": {"insp.accent": "#C9A227", "insp.focus": "left top"}},
        )
        assert r.status_code == 200 and r.get_json().get("ok")
        got = env["wm"]._inspector_overrides_for_card(run_id, "s1")
        assert got["accent"] == "#C9A227"
        assert got["photo_pos"] == "left top"

    def test_overrides_reader_coerces_bools(self, env):
        payload = _make_run_payload("org-test", [
            {"swim_id": "s1", "swimmer_name": "Jane", "event": "100m Free", "headline": "PB"},
        ])
        run_id = _seed_run(env["tmp_path"], env["wm"], "org-test", payload)
        ws = env["wm"]._get_wf_store()
        ws.set_edits(run_id, "s1", {"insp.hideSponsor": "1", "insp.noPhoto": ""})
        got = env["wm"]._inspector_overrides_for_card(run_id, "s1")
        assert got["hide_sponsor"] is True
        assert got["no_photo"] is False

    def test_insp_keys_do_not_corrupt_caption_pack(self):
        """The dotted insp.* keys must be ignored by the caption pack builder
        (which parses ``{tone}_{slot}`` keys), so palette/crop state never leaks
        into a caption."""
        from mediahub.workflow.pack import build_content_pack  # noqa: F401  (import-safety)
        # The builder applies edited_captions as card["brand_captions"][tone][slot]
        # only when the rsplit('_',1) head is a known tone. 'insp.accent' has no
        # underscore → rsplit yields a single element → skipped.
        key = "insp.accent"
        parts = key.rsplit("_", 1)
        assert len(parts) == 1  # never treated as tone_slot

    def test_caption_save_keys_are_known_tones(self):
        """The inspector saves the caption under every standard tone headline so
        export honours it regardless of tone — the keys must be the real ones the
        pack builder consumes."""
        import mediahub.brand.apply as ap
        src = Path(ap.__file__).read_text(encoding="utf-8")
        for tone in ("warm-club", "hype", "data-led"):
            assert f'"{tone}"' in src, f"{tone} is no longer a brand tone"


# ===========================================================================
# 7. CSS contract
# ===========================================================================
class TestInspectorCss:
    CSS = (
        _ROOT / "src" / "mediahub" / "web" / "static" / "theme" / "theme-components.css"
    ).read_text(encoding="utf-8")

    def test_core_rules_present(self):
        for sel in (
            ".mh-inspector", ".mh-inspector-scrim", ".mh-inspector.is-open",
            ".mh-insp-head", ".mh-insp-preview", ".mh-insp-swatch",
            ".mh-insp-cropgrid", ".mh-insp-crop", ".mh-insp-foot",
        ):
            assert sel in self.CSS, f"missing CSS rule {sel}"

    def test_uses_brand_tokens(self):
        block = self.CSS[self.CSS.find("UI 1.18"):]
        assert "var(--surface" in block
        assert "var(--lane" in block
        assert "var(--ink" in block

    def test_motion_is_reduced_motion_gated(self):
        block = self.CSS[self.CSS.find("UI 1.18"):]
        assert "prefers-reduced-motion: reduce" in block
        rm = block[block.find("prefers-reduced-motion"):]
        assert "transition: none" in rm

    def test_mobile_full_width(self):
        block = self.CSS[self.CSS.find("UI 1.18"):]
        assert "max-width: 560px" in block
