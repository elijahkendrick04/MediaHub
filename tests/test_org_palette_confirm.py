"""tests/test_org_palette_confirm.py — palette confirmation flow.

The first-run setup page now offers a "Override the AI's pick" form
that lets the user nail down the brand colours manually after the AI
has had a go. Covered:

  1. The capture endpoint runs the unified palette resolver across every
     source the user supplied (link palette signals + guidelines doc +
     uploaded logos) — not just the website link.
  2. POST /organisation/setup/palette stores the manual override into
     ClubProfile.brand_palette_manual.
  3. The tickbox controls whether a 4th colour is persisted.
  4. Blank fields clear the override so the AI's pick resurfaces.
  5. The setup-page GET renders the confirmation form when a profile
     is ready.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def isolated_profiles(tmp_path, monkeypatch):
    """Same isolation as test_org_setup_gate but exposed as a
    standalone fixture so this test file is independent."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv(
        "SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles")
    )
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    import importlib
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)
    yield tmp_path


@pytest.fixture
def client(isolated_profiles):
    import mediahub.web.web as wm
    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, app


def _seed_profile_via_capture(c, monkeypatch, *, palette_extracted=None,
                              brand_signals=None):
    from mediahub.brand import social_dna
    monkeypatch.setattr(
        social_dna, "capture_from_socials",
        lambda **kw: {
            "brand_voice_summary": "Friendly community club.",
            "brand_keywords": ["community"],
            "brand_palette_extracted": palette_extracted or {"primary": "#0066cc"},
            "brand_logo_url": "",
            "brand_typography_hint": "sans",
            "brand_phrases_to_avoid": [],
            "brand_phrases_to_use": [],
            "brand_source_url": kw.get("website_url", ""),
            "brand_captured_at": "2026-05-17T12:00:00+00:00",
            "brand_capture_status": "ok",
            "voice_profile": {},
            "social_links_status": {"website": "ok"},
            "captions_captured": 0,
            "link_capture_state": {},
            "brand_palette_signals": brand_signals or {
                "website": ["#0066cc", "#ffffff"],
            },
        },
    )
    # Suppress the operating-profile LLM call so the test doesn't hit
    # the network even when an API key happens to be set.
    monkeypatch.setattr(
        "mediahub.brand.derived.derive_operating_profile",
        lambda profile: {
            "tone_prose": {}, "achievement_priorities": {},
            "type_phrases": {}, "artefact_voice": {}, "status": "ok",
        },
    )
    return c.post(
        "/organisation/setup/capture",
        data={
            "display_name": "Demo Club",
            "website_url": "https://demo-club.example",
        },
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# 1. The capture step runs the unified resolver, not website-only
# ---------------------------------------------------------------------------

class TestUnifiedResolveOnCapture:
    def test_capture_pulls_colours_from_logos_and_guidelines(
        self, client, monkeypatch, tmp_path,
    ):
        c, _ = client
        # Stub the LLM so the resolver picks a deterministic palette.
        # Every hex it returns MUST be drawn from the source universe;
        # the validator drops hallucinated colours.
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
        monkeypatch.setattr(
            "mediahub.media_ai.llm.generate_json",
            lambda prompt, *, system, max_tokens, fallback: {
                "primary": "#ff8800",
                "secondary": "#0066cc",
                "accent": "#ffffff",
                "reasoning": "Orange dominated the logos; navy was in the guidelines.",
            },
        )

        _seed_profile_via_capture(
            c, monkeypatch,
            palette_extracted={"primary": "#0066cc"},
            brand_signals={"website": ["#0066cc", "#ffffff"],
                           "instagram": ["#ff8800"]},
        )

        from mediahub.web.club_profile import load_profile
        prof = load_profile("demo-club")
        assert prof is not None
        # The resolver's pick should have replaced / merged onto the
        # website-only website palette.
        assert prof.brand_palette_extracted.get("primary") == "#ff8800"
        assert prof.brand_palette_extracted.get("secondary") == "#0066cc"
        assert prof.brand_palette_extracted.get("accent") == "#ffffff"
        assert prof.brand_palette_reasoning.startswith("Orange dominated")
        # Sources dict carries every captured signal
        sources = prof.brand_palette_sources or {}
        assert any("website" in k for k in sources)
        assert any("instagram" in k for k in sources)


# ---------------------------------------------------------------------------
# 2 + 3 + 4. POST /organisation/setup/palette
# ---------------------------------------------------------------------------

class TestPaletteOverrideRoute:
    def test_manual_override_lands_on_profile(self, client, monkeypatch):
        c, _ = client
        _seed_profile_via_capture(c, monkeypatch)

        # Disable LLM so the re-resolve path that runs when fields are
        # blank is deterministic.
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: False)

        resp = c.post(
            "/organisation/setup/palette",
            data={
                "palette_primary": "#aa0000",
                "palette_secondary": "#00aa00",
                "palette_accent": "#0000aa",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (301, 302, 303, 307, 308)
        assert "/organisation/setup" in resp.headers.get("Location", "")

        from mediahub.web.club_profile import load_profile
        prof = load_profile("demo-club")
        assert prof is not None
        manual = prof.brand_palette_manual
        assert manual.get("primary") == "#aa0000"
        assert manual.get("secondary") == "#00aa00"
        assert manual.get("accent") == "#0000aa"
        # No tickbox means no 4th colour
        assert "fourth" not in manual
        # Legacy brand_primary should mirror the manual pick so the
        # BrandKit fallback renders the same colours.
        assert prof.brand_primary == "#aa0000"
        assert prof.brand_secondary == "#00aa00"

    def test_tickbox_persists_fourth_colour(self, client, monkeypatch):
        c, _ = client
        _seed_profile_via_capture(c, monkeypatch)
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: False)

        c.post(
            "/organisation/setup/palette",
            data={
                "palette_primary": "#111111",
                "palette_secondary": "#222222",
                "palette_accent": "#333333",
                "palette_use_fourth": "on",
                "palette_fourth": "#444444",
            },
        )

        from mediahub.web.club_profile import load_profile
        prof = load_profile("demo-club")
        assert prof.brand_palette_use_fourth is True
        assert prof.brand_palette_manual.get("fourth") == "#444444"

    def test_fourth_dropped_when_tickbox_off(self, client, monkeypatch):
        """Even if a hex was posted, no tickbox => no 4th colour."""
        c, _ = client
        _seed_profile_via_capture(c, monkeypatch)
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: False)

        c.post(
            "/organisation/setup/palette",
            data={
                "palette_primary": "#111111",
                "palette_fourth": "#444444",  # but no tickbox
            },
        )
        from mediahub.web.club_profile import load_profile
        prof = load_profile("demo-club")
        assert prof.brand_palette_use_fourth is False
        assert "fourth" not in prof.brand_palette_manual

    def test_unticking_fourth_clears_extracted_fourth(
        self, client, monkeypatch,
    ):
        """Bug regression: once the AI surfaced a fourth colour and the
        user later unticks the box, the stale ``extracted.fourth`` must
        be dropped from the profile so the next render doesn't keep
        rendering a fourth swatch."""
        c, _ = client
        _seed_profile_via_capture(c, monkeypatch)
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: False)

        # 1. Tick the box + supply a fourth — AI extracted fourth too.
        from mediahub.web.club_profile import load_profile, save_profile
        prof = load_profile("demo-club")
        prof.brand_palette_extracted = {
            "primary": "#111111", "secondary": "#222222",
            "accent": "#333333", "fourth": "#444444",
        }
        save_profile(prof)

        # 2. Now POST a manual override with the tickbox OFF (and all
        # three core slots populated so the re-resolve branch is
        # SKIPPED). The bug was: the stale extracted fourth lingered.
        c.post(
            "/organisation/setup/palette",
            data={
                "palette_primary": "#aaaaaa",
                "palette_secondary": "#bbbbbb",
                "palette_accent": "#cccccc",
                # No palette_use_fourth
            },
        )
        prof = load_profile("demo-club")
        assert prof.brand_palette_use_fourth is False
        assert "fourth" not in prof.brand_palette_extracted, (
            "stale extracted.fourth must be dropped when tickbox is off"
        )

    def test_blank_fields_clear_override_and_keep_ai_pick(
        self, client, monkeypatch,
    ):
        c, _ = client
        _seed_profile_via_capture(c, monkeypatch)
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: False)

        # First override
        c.post(
            "/organisation/setup/palette",
            data={
                "palette_primary": "#aa0000",
                "palette_secondary": "#00aa00",
                "palette_accent": "#0000aa",
            },
        )
        from mediahub.web.club_profile import load_profile
        first = load_profile("demo-club")
        assert first.brand_palette_manual.get("primary") == "#aa0000"

        # Now clear them all (the form lets the user "leave any field
        # blank to fall back to the AI's pick")
        c.post(
            "/organisation/setup/palette",
            data={
                "palette_primary": "",
                "palette_secondary": "",
                "palette_accent": "",
            },
        )
        second = load_profile("demo-club")
        # The manual dict should be empty now …
        assert second.brand_palette_manual == {}
        # … and the effective brand kit should fall back to the AI's pick.
        kit = second.get_brand_kit()
        assert kit.primary_colour  # not empty


# ---------------------------------------------------------------------------
# 4b. POST /organisation/setup/palette/reorder — swap colours between roles
# ---------------------------------------------------------------------------

class TestPaletteReorderRoute:
    def _seed_confirmed_palette(self, c, monkeypatch):
        """Capture, then pin a known three-colour manual palette."""
        _seed_profile_via_capture(c, monkeypatch)
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: False)
        c.post(
            "/organisation/setup/palette",
            data={
                "palette_primary": "#111111",
                "palette_secondary": "#222222",
                "palette_accent": "#333333",
            },
        )

    def test_explicit_order_swaps_primary_and_secondary(self, client, monkeypatch):
        c, _ = client
        self._seed_confirmed_palette(c, monkeypatch)

        resp = c.post(
            "/organisation/setup/palette/reorder",
            data={"order": "secondary,primary,accent"},
            follow_redirects=False,
        )
        assert resp.status_code in (301, 302, 303, 307, 308)
        assert "/organisation/setup" in resp.headers.get("Location", "")

        from mediahub.web.club_profile import load_profile
        prof = load_profile("demo-club")
        manual = prof.brand_palette_manual
        assert manual.get("primary") == "#222222"
        assert manual.get("secondary") == "#111111"
        assert manual.get("accent") == "#333333"
        # Legacy mirrors track the swap so the BrandKit fallback agrees.
        assert prof.brand_primary == "#222222"
        assert prof.brand_secondary == "#111111"

    def test_no_order_cycles_forward(self, client, monkeypatch):
        c, _ = client
        self._seed_confirmed_palette(c, monkeypatch)

        c.post("/organisation/setup/palette/reorder", data={})

        from mediahub.web.club_profile import load_profile
        prof = load_profile("demo-club")
        manual = prof.brand_palette_manual
        # Forward cycle: primary's colour walks to secondary, last wraps round.
        assert manual.get("secondary") == "#111111"
        assert manual.get("accent") == "#222222"
        assert manual.get("primary") == "#333333"

    def test_reorder_recomputes_derived_palette(self, client, monkeypatch):
        c, _ = client
        self._seed_confirmed_palette(c, monkeypatch)

        # Prime a stale derived palette seeded off the OLD primary.
        from mediahub.web.club_profile import load_profile, save_profile
        prof = load_profile("demo-club")
        kit = prof.get_brand_kit()
        kit.ensure_derived_palette(force=True)
        prof.brand_kit = kit.to_dict()
        save_profile(prof)
        old_seed = (prof.brand_kit.get("derived_palette") or {}).get("seed_hex")
        assert old_seed  # sanity

        # Swap primary -> #222222; derived palette must re-seed.
        c.post(
            "/organisation/setup/palette/reorder",
            data={"order": "secondary,primary,accent"},
        )
        prof = load_profile("demo-club")
        new_seed = (prof.brand_kit.get("derived_palette") or {}).get("seed_hex")
        assert new_seed == "#222222"
        assert new_seed != old_seed

    def test_fourth_not_fabricated_when_opted_out(self, client, monkeypatch):
        """A reorder must never introduce a 4th colour the org didn't pick."""
        c, _ = client
        self._seed_confirmed_palette(c, monkeypatch)

        # Stale order naming a 4th slot is a no-op on a 3-colour palette.
        c.post(
            "/organisation/setup/palette/reorder",
            data={"order": "fourth,primary,secondary,accent"},
        )
        from mediahub.web.club_profile import load_profile
        prof = load_profile("demo-club")
        assert prof.brand_palette_use_fourth is False
        assert "fourth" not in prof.brand_palette_manual
        # Untouched, since the bad order is rejected.
        assert prof.brand_palette_manual.get("primary") == "#111111"

    def test_no_active_profile_redirects(self, client, monkeypatch):
        c, _ = client
        # No capture → no profile. Should redirect, not 500.
        resp = c.post(
            "/organisation/setup/palette/reorder",
            data={"order": "secondary,primary,accent"},
            follow_redirects=False,
        )
        assert resp.status_code in (301, 302, 303, 307, 308)

    def test_fourth_colour_participates_when_opted_in(self, client, monkeypatch):
        c, _ = client
        _seed_profile_via_capture(c, monkeypatch)
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: False)
        # Opt into a fourth colour and pin all four.
        c.post(
            "/organisation/setup/palette",
            data={
                "palette_primary": "#111111",
                "palette_secondary": "#222222",
                "palette_accent": "#333333",
                "palette_use_fourth": "on",
                "palette_fourth": "#444444",
            },
        )
        # Cycle all four forward one role.
        c.post("/organisation/setup/palette/reorder", data={})

        from mediahub.web.club_profile import load_profile
        prof = load_profile("demo-club")
        manual = prof.brand_palette_manual
        assert prof.brand_palette_use_fourth is True
        assert manual.get("primary") == "#444444"
        assert manual.get("secondary") == "#111111"
        assert manual.get("accent") == "#222222"
        assert manual.get("fourth") == "#333333"


# ---------------------------------------------------------------------------
# 5. Setup-page GET renders the confirmation form
# ---------------------------------------------------------------------------

class TestSetupPageRendersForm:
    def test_form_appears_when_profile_is_ready(self, client, monkeypatch):
        c, _ = client
        _seed_profile_via_capture(c, monkeypatch)

        resp = c.get("/organisation/setup")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # The override form must be on the page
        assert 'name="palette_primary"' in body
        assert 'name="palette_secondary"' in body
        assert 'name="palette_accent"' in body
        # Tickbox + 4th colour are present (hidden until ticked)
        assert 'name="palette_use_fourth"' in body
        assert 'name="palette_fourth"' in body
        # The form POSTs to the confirmation endpoint
        assert "/organisation/setup/palette" in body

    def test_reorder_control_appears_with_multiple_colours(
        self, client, monkeypatch,
    ):
        c, _ = client
        # >=2 colours so the "Arrange brand colours" control renders.
        _seed_profile_via_capture(
            c, monkeypatch,
            palette_extracted={
                "primary": "#0066cc", "secondary": "#ff8800",
                "accent": "#222222",
            },
        )

        resp = c.get("/organisation/setup")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Arrange brand colours" in body
        assert "/organisation/setup/palette/reorder" in body
        # The cycle button submits an `order` permutation.
        assert 'name="order"' in body

    def test_reorder_control_hidden_with_single_colour(
        self, client, monkeypatch,
    ):
        c, _ = client
        # Only one colour → nothing to rearrange → control omitted.
        _seed_profile_via_capture(
            c, monkeypatch, palette_extracted={"primary": "#0066cc"},
        )
        resp = c.get("/organisation/setup")
        body = resp.get_data(as_text=True)
        assert "/organisation/setup/palette/reorder" not in body
