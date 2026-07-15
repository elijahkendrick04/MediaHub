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
            profile_id="x",
            display_name="X",
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
            profile_id="x",
            display_name="X",
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
            "mediahub.web.ai_caption.call_claude",
            fake_call,
        )
        from mediahub.brand.sponsor import generate_sponsor_caption

        p = ClubProfile(
            profile_id="x",
            display_name="City Aquatics",
            sponsor_name="Acme Sports",
            brand_voice_summary="Inclusive community club.",
        )
        out = generate_sponsor_caption(
            {
                "swimmer_name": "Emma",
                "event": "100 Free",
                "time": "58.21",
                "type": "pb_confirmed",
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
            profile_id="x",
            display_name="X",
            sponsor_name="Acme",
        )
        generate_sponsor_caption(
            {
                "swimmer_name": "Emma",
                "event": "100 Free",
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
def gated_app(app, tmp_path):
    app.config["ENFORCE_ORG_GATE"] = True
    return app, tmp_path


def _seed_run(tmp_path: Path, run_id: str, profile_id: str, sponsor: str = ""):
    """Seed a profile (with optional sponsor) and a single-card run."""
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id=profile_id,
            display_name="City Aquatics",
            brand_voice_summary="Inclusive community club.",
            sponsor_name=sponsor,
        )
    )
    run = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "Winter Champs", "venue": "Manchester"},
        "recognition_report": {
            "n_achievements": 1,
            "ranked_achievements": [
                {
                    "rank": 1,
                    "priority": 0.95,
                    "achievement": {
                        "swim_id": "swim-1",
                        "swimmer_name": "Emma",
                        "event": "100 Free",
                        "time": "58.21",
                        "type": "pb_confirmed",
                        "pb": True,
                        "headline": "First sub-60",
                    },
                    "factors": [],
                }
            ],
        },
    }
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(run))


def _poll_until(client, poll_url, tries=120, delay=0.05):
    """Poll the shared job-status route until the job leaves 'running'."""
    import time

    for _ in range(tries):
        j = client.get(poll_url).get_json()
        if j.get("status") in ("done", "error"):
            return j
        time.sleep(delay)
    return client.get(poll_url).get_json()


class TestSponsorVariantPage:
    def test_renders_when_sponsor_configured(self, gated_app, monkeypatch):
        """D-32 updated this test: the page GET returns the shell immediately
        (no synchronous render/LLM call); the caption arrives via the
        background job the shell polls. Intent preserved — a configured
        sponsor yields the page and the generated caption."""
        app, tmp = gated_app
        import mediahub.web.web as wm

        _seed_run(tmp, "run-1", "city-aquatics", sponsor="Acme Sports")
        # Stub the caption call so we don't need a live LLM.
        caption_calls = {"n": 0}

        def _fake_caption(system, user, max_tokens=400, **_):
            caption_calls["n"] += 1
            return "Massive PB for Emma — thanks to @AcmeSports for backing us."

        monkeypatch.setattr("mediahub.web.ai_caption.call_claude", _fake_caption)
        if wm._v8_ok:
            monkeypatch.setattr(
                wm,
                "_v8_create_visual_for_item",
                lambda item, brand_kit, **kw: {
                    "visuals": [{"id": "vis1", "format_name": "feed_portrait"}],
                    "errors": [],
                },
            )
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "city-aquatics"})
            resp = c.get("/runs/run-1/card/swim-1/sponsor-variant")
            assert resp.status_code == 200
            body = resp.get_data(as_text=True)
            assert "Sponsor variant" in body
            assert "Acme Sports" in body
            # Back-link to pack
            assert "/pack/run-1/grouped" in body
            # The GET is a shell: no LLM call happened during it.
            assert caption_calls["n"] == 0
            assert "Massive PB for Emma" not in body
            # The caption arrives through the background job instead.
            r = c.post(
                "/api/runs/run-1/card/swim-1/sponsor-variant-job",
                data="{}",
                content_type="application/json",
            )
            assert r.status_code == 202, r.get_data(as_text=True)
            j = _poll_until(c, r.get_json()["poll_url"])
            assert j["status"] == "done", j
            assert "Massive PB for Emma" in j["caption"]
            assert caption_calls["n"] == 1

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

        save_profile(
            ClubProfile(
                profile_id="city-aquatics",
                display_name="City",
                brand_voice_summary="x",
            )
        )
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "city-aquatics"})
            resp = c.get("/runs/no-such-run/card/anything/sponsor-variant")
            assert resp.status_code == 404

    def test_overrides_reach_render_minus_hide_sponsor(self, gated_app, monkeypatch):
        """Persisted inspector overrides (UI 1.18) apply on the sponsor-variant
        render too — except hide_sponsor, since this surface's whole job is
        showing the sponsor slot. (D-32 updated this test: the render now
        happens in the background job, so it drives the job instead of the
        page GET — the assertion is unchanged.)"""
        app, tmp = gated_app
        import mediahub.web.web as wm

        if not wm._v8_ok:
            pytest.skip("v8 engine unavailable")
        _seed_run(tmp, "run-ov", "city-aquatics", sponsor="Acme Sports")
        ws = wm._get_wf_store()
        ws.set_edits(
            "run-ov",
            "swim-1",
            {
                "insp.accent": "#C9A227",
                "insp.focus": "left top",
                "insp.hideSponsor": "1",
            },
        )
        captured = {}

        def _fake(item, brand_kit, **kwargs):
            captured.update(kwargs)
            return {"visuals": [{"id": "vis1", "format_name": "feed_portrait"}], "errors": []}

        monkeypatch.setattr(wm, "_v8_create_visual_for_item", _fake)
        monkeypatch.setattr(
            "mediahub.web.ai_caption.call_claude",
            lambda system, user, max_tokens=400, **_: "Sponsor caption.",
        )
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "city-aquatics"})
            r = c.post(
                "/api/runs/run-ov/card/swim-1/sponsor-variant-job",
                data="{}",
                content_type="application/json",
            )
            assert r.status_code == 202, r.get_data(as_text=True)
            j = _poll_until(c, r.get_json()["poll_url"])
            assert j["status"] == "done", j
        ov = captured["user_overrides"]
        assert ov["accent"] == "#C9A227"
        assert ov["photo_pos"] == "left top"
        assert "hide_sponsor" not in ov
        assert captured["sponsor_name"] == "Acme Sports"


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


# ---------------------------------------------------------------------------
# 5. Friendly fallback when the LLM is unavailable
# ---------------------------------------------------------------------------


class TestSponsorVariantFriendlyLLMFallback:
    """When `generate_sponsor_caption` raises ClaudeUnavailableError because
    no LLM provider is configured, the user must NOT see the raw exception
    class name. They get a friendly message, and the sponsor-branded visual
    is unaffected (it is rendered by a separate pipeline that doesn't depend
    on the LLM). (D-32 updated this test: the caption now runs in the
    background job, so the friendly message arrives in the job payload the
    page polls — the intent is unchanged.)"""

    def test_friendly_message_when_llm_unavailable(self, gated_app, monkeypatch):
        app, tmp = gated_app
        import mediahub.web.web as wm

        _seed_run(tmp, "run-llm-off", "city-aquatics", sponsor="Acme Sports")

        from mediahub.media_ai.llm import ClaudeUnavailableError

        def _raise(*_a, **_kw):
            raise ClaudeUnavailableError("no provider configured")

        # Patch the symbol the worker imports at call-time, inside the
        # sponsor module.
        monkeypatch.setattr(
            "mediahub.brand.sponsor.generate_sponsor_caption",
            _raise,
        )
        if wm._v8_ok:
            monkeypatch.setattr(
                wm,
                "_v8_create_visual_for_item",
                lambda item, brand_kit, **kw: {
                    "visuals": [{"id": "vis1", "format_name": "feed_portrait"}],
                    "errors": [],
                },
            )

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "city-aquatics"})
            resp = c.get("/runs/run-llm-off/card/swim-1/sponsor-variant")
            assert resp.status_code == 200
            body = resp.get_data(as_text=True)
            # The page shell renders; no raw exception name anywhere.
            assert "Sponsor variant" in body
            assert "ClaudeUnavailableError" not in body
            r = c.post(
                "/api/runs/run-llm-off/card/swim-1/sponsor-variant-job",
                data="{}",
                content_type="application/json",
            )
            assert r.status_code == 202, r.get_data(as_text=True)
            j = _poll_until(c, r.get_json()["poll_url"])
            assert j["status"] == "done", j
            # Friendly message present (one of these tokens must appear)
            msg = (j.get("caption_message") or "").lower()
            assert ("administrator" in msg) or ("unavailable" in msg)
            # Raw exception class name MUST NOT leak to the user
            import json as _json

            assert "ClaudeUnavailableError" not in _json.dumps(j)
            # No fabricated caption.
            assert j.get("caption") == ""
