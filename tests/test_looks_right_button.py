"""Stage E — "Looks right — start creating" button contract tests.

The button is the user-visible trigger for the cascade. Tests:
  - It carries data-mh-cascade="finalise" so the JS handler picks it up.
  - It retains its href so no-JS users still navigate.
  - The cascade JS handler is embedded in the page.
  - The handler attaches to <a data-mh-cascade> only — no other elements.
  - The handler respects modifier keys (right-click, ctrl+click).
"""

from __future__ import annotations

import importlib
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
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, wm, cp


def _seed_with_brand_capture(cp_module):
    """Build a profile that's complete enough for organisation_setup to
    render the 'What MediaHub learned' card with the Looks Right button."""
    from mediahub.web.club_profile import ClubProfile

    pid = "swim-button"
    prof = ClubProfile(profile_id=pid, display_name="Swim Button Club")
    prof.brand_primary = "#06D6A0"
    prof.brand_secondary = "#0E2A47"
    # The preview card requires brand voice signals captured.
    prof.brand_voice_summary = "Concise, energetic, community-first."
    prof.brand_keywords = ["swim", "club", "community"]
    prof.brand_palette_extracted = {"primary": "#06D6A0", "secondary": "#0E2A47"}
    prof.brand_source_url = "https://example.org"
    prof.brand_kit = {
        "profile_id": pid,
        "display_name": "Swim Button Club",
        "primary_colour": "#06D6A0",
        "secondary_colour": "#0E2A47",
    }
    cp_module.save_profile(prof)
    return prof


class TestButtonInRenderedPage:
    def test_organisation_setup_renders_button(self, app_client):
        client, wm, cp = app_client
        prof = _seed_with_brand_capture(cp)
        with client.session_transaction() as sess:
            sess["active_profile_id"] = prof.profile_id
        r = client.get("/organisation/setup")
        assert r.status_code == 200, r.get_data(as_text=True)[:500]
        body = r.get_data(as_text=True)
        # The button text is the user-visible label
        assert "Looks right" in body
        assert "start creating" in body

    def test_button_has_cascade_data_attribute(self, app_client):
        client, wm, cp = app_client
        prof = _seed_with_brand_capture(cp)
        with client.session_transaction() as sess:
            sess["active_profile_id"] = prof.profile_id
        body = client.get("/organisation/setup").get_data(as_text=True)
        # The button must carry data-mh-cascade for the JS handler.
        # Allow either single quotes or double quotes around the value.
        assert 'data-mh-cascade="finalise"' in body or "data-mh-cascade='finalise'" in body, (
            "button missing data-mh-cascade='finalise' attribute"
        )

    def test_button_retains_href(self, app_client):
        """No-JS users must still get to /make via the button's href —
        graceful degradation."""
        client, wm, cp = app_client
        prof = _seed_with_brand_capture(cp)
        with client.session_transaction() as sess:
            sess["active_profile_id"] = prof.profile_id
        body = client.get("/organisation/setup").get_data(as_text=True)
        # Find the button and check it has a valid href.
        import re

        m = re.search(
            r'<a[^>]*class="btn"[^>]*data-mh-cascade="finalise"[^>]*>',
            body,
        )
        assert m, "Looks Right button not found in expected form"
        tag = m.group(0)
        assert "href=" in tag and 'href=""' not in tag, f"button must have non-empty href: {tag}"


class TestCascadeJSHandler:
    def test_handler_embedded_in_every_page(self, app_client):
        """The cascade JS lives in _layout() so every page has it
        (the click handler is global; only [data-mh-cascade] elements
        actually trigger it)."""
        client, _, _ = app_client
        # /healthz/usage is operator-only; sign in so its full template renders.
        with client.session_transaction() as sess:
            sess["dev_operator"] = True
        for route in ("/status", "/healthz/usage"):
            body = client.get(route).get_data(as_text=True)
            assert "data-mh-cascade" in body, f"{route}: cascade handler not embedded"
            assert "/api/organisation/finalise" in body, (
                f"{route}: finalise URL not in client-side handler"
            )

    def test_handler_uses_view_transitions_pattern(self, app_client):
        """The handler must POST to finalise then navigate. Since
        cross-doc View Transitions are triggered by the @view-transition
        CSS rule (not by JS), the handler doesn't need to call
        document.startViewTransition directly — it just navigates."""
        client, _, _ = app_client
        body = client.get("/status").get_data(as_text=True)
        # Sanity: the handler references location.assign (or .href) so
        # the navigation actually happens.
        assert "location.assign" in body or "location.href" in body, (
            "cascade handler doesn't navigate"
        )

    def test_handler_respects_modifier_keys(self, app_client):
        """Right-click / ctrl+click / middle-click should NOT be
        intercepted — let the user open the link in a new tab."""
        client, _, _ = app_client
        body = client.get("/status").get_data(as_text=True)
        # Verify the handler checks for modifier keys before
        # intercepting.
        for guard in ("ctrlKey", "metaKey", "shiftKey", "button"):
            assert guard in body, f"cascade handler missing modifier-key guard: {guard}"

    def test_finalise_post_sets_json_content_type_to_dodge_csrf(self, app_client):
        """The finalise POST must declare ``Content-Type: application/json``.

        The app's CSRF guard exempts JSON writes by content-type; without it the
        same-origin POST carried no CSRF token and was silently rejected 403, so
        the derived palette was never persisted on "Looks right". Pin the marker
        on the fetch that targets the finalise endpoint.
        """
        import re

        client, _, _ = app_client
        body = client.get("/status").get_data(as_text=True)
        # Target the quoted fetch URL (the handler comment also names the
        # endpoint, so match the trailing quote to land on the real call).
        m = re.search(r"/api/organisation/finalise['\"]", body)
        assert m, "finalise fetch missing from cascade handler"
        # Inspect the fetch options object that follows so a Content-Type
        # elsewhere on the page can't mask a regression here.
        block = body[m.start() : m.start() + 600]
        assert re.search(r"['\"]Content-Type['\"]\s*:\s*['\"]application/json", block), (
            "finalise POST must set Content-Type: application/json (CSRF-exempt marker)"
        )

    def test_finalise_csrf_contract_old_shape_blocked_json_shape_succeeds(self, app_client):
        """End-to-end CSRF contract under production enforcement: the OLD call
        shape (no Content-Type, no token) is rejected 403 — exactly QA-006's
        silent failure — while the fixed JSON-content-type shape is exempt and
        the finalise actually runs (the derived palette is persisted)."""
        client, wm, cp = app_client
        client.application.config["ENFORCE_CSRF"] = True  # mirror production
        prof = _seed_with_brand_capture(cp)
        with client.session_transaction() as sess:
            sess["active_profile_id"] = prof.profile_id

        # Old shape (Accept only) → CSRF 403, the reported regression.
        r_old = client.post("/api/organisation/finalise", headers={"Accept": "application/json"})
        assert r_old.status_code == 403
        assert r_old.get_json().get("error") == "csrf"

        # Fixed shape (JSON content-type) → exempt, finalise runs to success.
        r_new = client.post(
            "/api/organisation/finalise",
            data="{}",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        assert r_new.status_code == 200, r_new.get_data(as_text=True)[:300]
        assert r_new.get_json().get("seed_hex"), (
            "finalise did not persist/return the derived palette"
        )


class TestThemeSeedStyleBlock:
    def test_seed_style_block_appears_when_org_active(self, app_client):
        client, wm, cp = app_client
        prof = _seed_with_brand_capture(cp)
        with client.session_transaction() as sess:
            sess["active_profile_id"] = prof.profile_id
        body = client.get("/status").get_data(as_text=True)
        # The override <style id="mh-theme-seed"> block must appear.
        assert 'id="mh-theme-seed"' in body or "id='mh-theme-seed'" in body, (
            "missing <style id='mh-theme-seed'> per-org override block"
        )
        # The seed value within the override should be a valid hex.
        import re

        m = re.search(
            r'<style id="mh-theme-seed">[^<]*--mh-brand-seed:\s*(#[0-9A-Fa-f]{6,8})',
            body,
        )
        assert m, "override block doesn't declare a valid --mh-brand-seed"

    def test_seed_style_block_uses_default_when_no_org(self, app_client):
        """Phase 1.6 Stage J2 update: when no profile is pinned, the
        override block STILL appears — it now carries the generic-
        default theme (#0E2A47 navy) so the engine runs end-to-end
        for unconfigured deployments too. Use MEDIAHUB_ADAPTIVE_THEME=0
        to suppress the block entirely (see test_adaptive_theme_flag.py)."""
        client, _, _ = app_client
        body = client.get("/status").get_data(as_text=True)
        # Stage J2: override block present, carrying generic-default seed.
        assert 'id="mh-theme-seed"' in body, (
            "Stage J2 default-theme override missing on unconfigured page"
        )
        assert "#0E2A47" in body, "expected the generic-default seed (#0E2A47) in the override"
