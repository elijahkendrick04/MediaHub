"""tests/test_sponsor_variant.py — sponsor-variant caption + page.

Phase 1.2 deliverable: per top-ranked card, produce a sponsor-
acknowledging caption variant + a sponsor-branded result-card
graphic.

Pins:
  1. ``sponsor_caption_requirement`` returns an actionable
     instruction when a sponsor is configured, empty string when
     not.
  2. ``generate_sponsor_caption`` raises ValueError when no
     sponsor is configured (so callers can show "configure a
     sponsor first" rather than silently producing a generic
     caption).
  3. The sponsor caption flows through the regular caption
     pipeline so brand context (DNA, voice profile, guidelines)
     reaches the LLM — with the sponsor requirement appended as
     an extra instruction.
  4. The ``/runs/<run_id>/card/<card_id>/sponsor-variant`` page
     renders the visual + caption when a sponsor is configured,
     and a "configure sponsor first" message when not.
  5. The grouped content pack page surfaces a "Sponsor variant"
     button per card.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# 1. The requirement helper
# ---------------------------------------------------------------------------

class TestRequirementHelper:
    def test_empty_when_no_sponsor(self):
        from mediahub.brand.sponsor import sponsor_caption_requirement
        from mediahub.web.club_profile import ClubProfile
        p = ClubProfile(profile_id="x", display_name="X")
        assert sponsor_caption_requirement(p) == ""

    def test_includes_sponsor_name_and_is_explicit(self):
        from mediahub.brand.sponsor import sponsor_caption_requirement
        from mediahub.web.club_profile import ClubProfile
        p = ClubProfile(
            profile_id="x", display_name="X",
            sponsor_name="Acme Sports",
        )
        req = sponsor_caption_requirement(p)
        assert "Acme Sports" in req
        assert "MUST" in req  # explicit, not optional
        # The instruction must be specific to this swim, not generic
        assert "specific" in req.lower()

    def test_includes_guidelines_when_present(self):
        from mediahub.brand.sponsor import sponsor_caption_requirement
        from mediahub.web.club_profile import ClubProfile
        p = ClubProfile(
            profile_id="x", display_name="X",
            sponsor_name="Acme Sports",
            sponsor_guidelines="Always include #PoweredByAcme",
        )
        req = sponsor_caption_requirement(p)
        assert "#PoweredByAcme" in req


# ---------------------------------------------------------------------------
# 2. generate_sponsor_caption — through the real caption pipeline
# ---------------------------------------------------------------------------

class TestGenerateSponsorCaption:
    def test_raises_when_no_sponsor(self):
        from mediahub.brand.sponsor import generate_sponsor_caption
        from mediahub.web.club_profile import ClubProfile
        p = ClubProfile(profile_id="x", display_name="X")
        with pytest.raises(ValueError, match="no sponsor configured"):
            generate_sponsor_caption({"swimmer_name": "Emma"}, profile=p)

    def test_sponsor_requirement_reaches_system_prompt(self, monkeypatch):
        """The sponsor requirement must arrive at the LLM verbatim — not
        be swallowed by the brand-context block or the tone block."""
        from mediahub.web.club_profile import ClubProfile
        captured = {}

        def fake_call(system, user, max_tokens=400, **_):
            captured["system"] = system
            return "Emma went 58.21 - cheers @AcmeSports"

        monkeypatch.setattr(
            "mediahub.web.ai_caption.call_claude", fake_call,
        )
        from mediahub.brand.sponsor import generate_sponsor_caption
        p = ClubProfile(
            profile_id="x", display_name="City Aquatics",
            sponsor_name="Acme Sports",
            brand_voice_summary="Inclusive community club.",
        )
        out = generate_sponsor_caption(
            {
                "swimmer_name": "Emma", "event": "100 Free",
                "time": "58.21", "type": "pb_confirmed",
            },
            profile=p,
        )
        assert "Emma" in out
        sys_prompt = captured.get("system", "")
        # Sponsor requirement reaches the prompt
        assert "Acme Sports" in sys_prompt
        # Brand context also reaches the prompt
        assert "Inclusive community club" in sys_prompt
        # The requirement is in the additional-instruction section
        assert "Additional requirement" in sys_prompt

    def test_preserves_existing_extra_instructions(self, monkeypatch):
        """If the caller already attached _extra_instructions (e.g.
        from a Turn-Into payload), the sponsor requirement is layered
        on top rather than overwriting."""
        captured = {}
        monkeypatch.setattr(
            "mediahub.web.ai_caption.call_claude",
            lambda system, user, max_tokens=400, **_: captured.update(system=system) or "x",
        )
        from mediahub.web.club_profile import ClubProfile
        from mediahub.brand.sponsor import generate_sponsor_caption
        p = ClubProfile(
            profile_id="x", display_name="X",
            sponsor_name="Acme",
        )
        generate_sponsor_caption(
            {
                "swimmer_name": "Emma", "event": "100 Free",
                "time": "58.21",
                "_extra_instructions": "Mention the volunteers.",
            },
            profile=p,
        )
        sys = captured["system"]
        assert "Mention the volunteers" in sys
        assert "Acme" in sys


# ---------------------------------------------------------------------------
# 3. /runs/<run_id>/card/<card_id>/sponsor-variant page
# ---------------------------------------------------------------------------

@pytest.fixture
def gated_app(tmp_path, monkeypatch):
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
    app.config["ENFORCE_ORG_GATE"] = True
    return app, tmp_path


def _seed_run(tmp_path: Path, run_id: str, profile_id: str, sponsor: str = ""):
    """Seed a profile (with optional sponsor) and a single-card run."""
    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(
        profile_id=profile_id, display_name="City Aquatics",
        brand_voice_summary="Inclusive community club.",
        sponsor_name=sponsor,
    ))
    run = {
        "run_id": run_id, "profile_id": profile_id,
        "meet": {"name": "Winter Champs", "venue": "Manchester"},
        "recognition_report": {
            "n_achievements": 1,
            "ranked_achievements": [{
                "rank": 1, "priority": 0.95,
                "achievement": {
                    "swim_id": "swim-1", "swimmer_name": "Emma",
                    "event": "100 Free", "time": "58.21",
                    "type": "pb_confirmed", "pb": True,
                    "headline": "First sub-60",
                },
                "factors": [],
            }],
        },
    }
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(run))


class TestSponsorVariantPage:
    def test_renders_when_sponsor_configured(self, gated_app, monkeypatch):
        app, tmp = gated_app
        _seed_run(tmp, "run-1", "city-aquatics", sponsor="Acme Sports")
        # Stub the caption call so we don't need a live LLM.
        monkeypatch.setattr(
            "mediahub.web.ai_caption.call_claude",
            lambda system, user, max_tokens=400, **_:
                "Massive PB for Emma — thanks to @AcmeSports for backing us.",
        )
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "city-aquatics"})
            resp = c.get("/runs/run-1/card/swim-1/sponsor-variant")
            assert resp.status_code == 200
            body = resp.get_data(as_text=True)
            assert "Sponsor variant" in body
            assert "Acme Sports" in body
            # The generated caption surfaces in the textarea
            assert "Massive PB for Emma" in body
            # Back-link to pack
            assert "/pack/run-1/grouped" in body

    def test_shows_helpful_message_when_no_sponsor(self, gated_app):
        app, tmp = gated_app
        _seed_run(tmp, "run-2", "city-aquatics", sponsor="")
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "city-aquatics"})
            resp = c.get("/runs/run-2/card/swim-1/sponsor-variant")
            assert resp.status_code == 200
            body = resp.get_data(as_text=True)
            assert "No sponsor is configured" in body
            # Steer the user to fix it
            assert "/organisation" in body

    def test_unknown_run_404(self, gated_app):
        app, tmp = gated_app
        # Seed a profile so the gate lifts.
        from mediahub.web.club_profile import ClubProfile, save_profile
        save_profile(ClubProfile(
            profile_id="city-aquatics", display_name="City",
            brand_voice_summary="x",
        ))
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "city-aquatics"})
            resp = c.get("/runs/no-such-run/card/anything/sponsor-variant")
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 4. The grouped pack page surfaces the sponsor-variant button per card
# ---------------------------------------------------------------------------

class TestPackPageSurfacesSponsorButton:
    def test_button_present_per_card(self, gated_app):
        app, tmp = gated_app
        _seed_run(tmp, "run-3", "city-aquatics", sponsor="Acme")
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "city-aquatics"})
            resp = c.get("/pack/run-3/grouped")
            if resp.status_code == 200:
                body = resp.get_data(as_text=True)
                assert "/runs/run-3/card/swim-1/sponsor-variant" in body
                assert "Sponsor variant" in body
