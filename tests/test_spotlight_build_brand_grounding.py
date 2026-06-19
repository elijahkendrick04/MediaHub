"""tests/test_spotlight_build_brand_grounding.py — pin the canonical brand
context into the spotlight composite-post system prompt.

PR #106 added basic brand context (org name, voice summary, keywords,
tone notes) inline. That hand-rolled assembly silently skipped half the
profile's voice fields — phrases_to_use, phrases_to_avoid, voice_profile
(preferred_swimmer_address, openers/closers), brand_guidelines, and the
non-negotiable mandatory_rules — so the composite caption could still
read sport-generic even when the org had populated those fields.

This module pins the fix:

  1. The spotlight_build endpoint must route brand context through
     ``brand.context.brand_context_for_llm`` (the same canonical helper
     single-card captions use), not its own local stub.
  2. Every meaningful brand field on the active profile must surface
     in the system prompt the LLM sees.
  3. Pure unit on the helper: tone_notes is included (it was the one
     field PR #106 had but the canonical helper didn't).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))


# ---------------------------------------------------------------------------
# Unit: the canonical helper now picks up tone_notes too.
# ---------------------------------------------------------------------------

def test_brand_context_for_llm_includes_tone_notes():
    """Freeform user-typed brand voice notes were the one signal PR #106
    surfaced inline but the canonical helper still ignored. Pin the
    extension: tone_notes lands in the prompt every tool sees."""
    from mediahub.brand.context import brand_context_for_llm
    from mediahub.web.club_profile import ClubProfile

    p = ClubProfile(
        profile_id="x",
        display_name="City Aquatics",
        tone_notes=(
            "Use the swimmer's first name. Never refer to them as 'the "
            "swimmer'. Drop the announcer-voice — we're a club, not a "
            "broadcaster."
        ),
    )
    out = brand_context_for_llm(p)
    assert "Use the swimmer's first name" in out
    assert "announcer-voice" in out


# ---------------------------------------------------------------------------
# Endpoint integration: /spotlight/<run>/<sw>/build feeds the canonical
# brand context to the LLM and persists the saved pack.
# ---------------------------------------------------------------------------

@pytest.fixture
def gated_app(tmp_path, monkeypatch):
    """Spin up the Flask app with an isolated DATA_DIR and a populated
    active profile carrying every voice signal we care about."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR",
                       str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    for env in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(env, raising=False)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(
        profile_id="acmeswim",
        display_name="ACME Aquatics",
        short_name="ACME",
        country="United Kingdom",
        sponsor_name="Acme Sports",
        brand_voice_summary=(
            "Bold, hyped, irreverent club voice. Talks to the squad."
        ),
        brand_keywords=["bold", "hungry", "earned", "grit"],
        brand_phrases_to_use=["Squad up.", "Earned it."],
        brand_phrases_to_avoid=["thoughts and prayers", "blessed"],
        tone_notes=(
            "Use the swimmer's first name. Drop the announcer-voice."
        ),
        voice_profile={
            "sentence_length_avg": 8,
            "emoji_rate_per_caption": 0.0,
            "preferred_swimmer_address": "first_name",
        },
        brand_guidelines={
            "summary": "Warm but bold. Never cynical.",
            "tone_dos": ["Celebrate effort"],
            "tone_donts": ["Compare swimmers"],
            "prohibited_words": ["loser"],
        },
        brand_guidelines_mandatory_rules=[
            "Never publish a swimmer's age without consent.",
        ],
    ))

    app = wm.create_app()
    app.config["TESTING"] = True
    return app


def _synthetic_run_with_achievements(run_id: str, runs_dir: Path) -> dict:
    """Persist a minimal run JSON with one swimmer who has three
    medal-gold achievements, plus the workflow sidecar approving all
    three. This skips the full pipeline (parsing/recognition is covered
    elsewhere) and isolates the spotlight build path."""
    import json
    swimmer_id = "acme:Lane,Lara"
    swimmer_name = "Lara Lane"
    achievements = []
    for ev, time, cid_suffix in [
        ("400m Freestyle (LC)", "4:26.95", "400FRLC"),
        ("200m Freestyle (LC)", "2:07.71", "200FRLC"),
        ("100m Freestyle (LC)", "0:59.83", "100FRLC"),
    ]:
        achievements.append({
            "achievement": {
                "swim_id":      f"{swimmer_id}:{cid_suffix}:gold",
                "swimmer_id":   swimmer_id,
                "swimmer_name": swimmer_name,
                "event":        ev,
                "time":         time,
                "place":        1,
                "type":         "medal_gold",
                "headline": (
                    f"{swimmer_name} wins gold in {ev} — {time}"
                ),
                "pb": False,
            },
            "priority":      9.0,
            "quality_band":  "elite",
        })
    run_data = {
        "run_id":     run_id,
        "started_at": "2025-01-01T00:00:00Z",
        "finished_at": "2025-01-01T00:01:00Z",
        "file_name":  "test.pdf",
        "meet":       {"name": "Test Invitational"},
        "recognition_report": {
            "meet_name": "Test Invitational",
            "ranked_achievements": achievements,
        },
    }
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{run_id}.json").write_text(json.dumps(run_data))

    # Workflow sidecar: approve all three achievements.
    from mediahub.workflow.store import WorkflowStore
    from mediahub.workflow.status import CardStatus
    ws = WorkflowStore(runs_dir)
    for ra in achievements:
        cid = ra["achievement"]["swim_id"]
        ws.set_status(run_id, cid, CardStatus.APPROVED)

    return run_data


def test_spotlight_build_grounds_prompt_in_canonical_brand_context(
    gated_app, tmp_path, monkeypatch
):
    """End-to-end through the Flask endpoint: hit /spotlight/<run>/<sw>/build,
    capture the system prompt routed into ai_core.ask, assert every
    brand signal we populated lands in it.

    This is the regression test for PR #106's incomplete grounding."""
    captured = {}

    def _stub_ask(system, user, max_tokens=600, **kw):
        captured["system"] = system
        captured["user"] = user
        return "STUBBED CAPTION"

    # The endpoint imports `ask` from mediahub.ai_core at call time, so
    # patching the package attribute is enough.
    import mediahub.ai_core as ai_core_pkg
    monkeypatch.setattr(ai_core_pkg, "ask", _stub_ask)

    run_id = "synth_run"
    runs_dir = tmp_path / "runs_v4"
    run = _synthetic_run_with_achievements(run_id, runs_dir)
    swimmer_key = run["recognition_report"][
        "ranked_achievements"
    ][0]["achievement"]["swimmer_id"]

    with gated_app.test_client() as c:
        with c.session_transaction() as sess:
            sess["active_profile_id"] = "acmeswim"
        url = f"/spotlight/{run_id}/{swimmer_key}/build"
        resp = c.post(url, follow_redirects=False)

    assert resp.status_code == 302, (
        f"expected redirect to /drafts/<id>, got {resp.status_code}: "
        f"{resp.get_data(as_text=True)[:240]}"
    )
    assert "/drafts/" in (resp.headers.get("Location") or ""), (
        f"redirect target not /drafts/: {resp.headers.get('Location')}"
    )

    sys_prompt = captured.get("system", "")
    assert sys_prompt, "spotlight_build never called ask()"

    # Identity — org name + sponsor + country must reach the prompt.
    assert "ACME Aquatics" in sys_prompt
    assert "Acme Sports" in sys_prompt
    assert "United Kingdom" in sys_prompt

    # Captured DNA — keywords, phrases_to_use, phrases_to_avoid.
    assert "Bold, hyped" in sys_prompt
    assert "Squad up" in sys_prompt
    assert "Earned it" in sys_prompt
    assert "thoughts and prayers" in sys_prompt
    assert "off-brand" in sys_prompt or "never use" in sys_prompt.lower()

    # tone_notes — the one PR-#106-only signal.
    assert "Drop the announcer-voice" in sys_prompt

    # Voice profile — preferred_swimmer_address + emoji policy.
    assert "first name" in sys_prompt.lower()
    assert "does NOT use emoji" in sys_prompt or "no emoji" in sys_prompt.lower()

    # Brand guidelines — summary, do's/don'ts, prohibited words.
    assert "Warm but bold" in sys_prompt
    assert "Celebrate effort" in sys_prompt
    assert "Compare swimmers" in sys_prompt
    assert "loser" in sys_prompt

    # Mandatory rules — must be marked as non-negotiable at the top.
    assert "Never publish a swimmer's age" in sys_prompt
    assert "NON-NEGOTIABLE" in sys_prompt

    # The brief still carries the swimmer's first name explicitly so the
    # LLM has a name to address even when the address rule is in the
    # system prompt.
    brief = captured.get("user", "")
    assert "Lara Lane" in brief
    assert "Test Invitational" in brief
    # Three approved achievements must each appear as a bullet.
    assert "400m Freestyle" in brief
    assert "200m Freestyle" in brief
    assert "100m Freestyle" in brief


def test_spotlight_build_renders_saved_pack(gated_app, tmp_path, monkeypatch):
    """After build, the /drafts/<pack_id> page renders 200 with the
    composed caption present — i.e. the persisted stub-pack envelope
    plumbs through to the view route end-to-end."""
    def _stub_ask(system, user, **kw):
        return "Lara took the meet by the throat."

    import mediahub.ai_core as ai_core_pkg
    monkeypatch.setattr(ai_core_pkg, "ask", _stub_ask)

    run_id = "synth_run_2"
    runs_dir = tmp_path / "runs_v4"
    run = _synthetic_run_with_achievements(run_id, runs_dir)
    swimmer_key = run["recognition_report"][
        "ranked_achievements"
    ][0]["achievement"]["swimmer_id"]

    with gated_app.test_client() as c:
        with c.session_transaction() as sess:
            sess["active_profile_id"] = "acmeswim"
        r1 = c.post(f"/spotlight/{run_id}/{swimmer_key}/build",
                    follow_redirects=False)
        assert r1.status_code == 302
        loc = r1.headers["Location"]
        r2 = c.get(loc)
        assert r2.status_code == 200
        html = r2.get_data(as_text=True)
        assert "Lara took the meet by the throat" in html


def test_spotlight_build_renders_content_builder_surface(
    gated_app, tmp_path, monkeypatch
):
    """After build, the saved spotlight pack opens the mode-aware *Content
    builder* (the single composite post — one caption + one graphic + one reel
    from the approved moments) with the full live toolbar, not the standalone
    spotlight builder and not the generic saved-draft card layout."""
    def _stub_ask(system, user, **kw):
        return "Lara took the meet by the throat."

    import mediahub.ai_core as ai_core_pkg
    monkeypatch.setattr(ai_core_pkg, "ask", _stub_ask)

    run_id = "synth_run_3"
    runs_dir = tmp_path / "runs_v4"
    run = _synthetic_run_with_achievements(run_id, runs_dir)
    swimmer_key = run["recognition_report"][
        "ranked_achievements"
    ][0]["achievement"]["swimmer_id"]

    with gated_app.test_client() as c:
        with c.session_transaction() as sess:
            sess["active_profile_id"] = "acmeswim"
        r1 = c.post(f"/spotlight/{run_id}/{swimmer_key}/build",
                    follow_redirects=False)
        assert r1.status_code == 302
        loc = r1.headers["Location"]
        r2 = c.get(loc)
        assert r2.status_code == 200
        html = r2.get_data(as_text=True)

        # It IS the Content builder (eyebrow + title), retiring the standalone
        # "Spotlight builder", and not the generic stub-draft layout.
        assert "Content builder" in html
        assert "Spotlight builder" not in html
        assert "draft card generated" not in html  # render_cards_html marker

        # Full live toolbar: the four caption tone tabs (wired to the pack-scoped
        # caption endpoint), Regenerate, Assist, Create graphic, and the reel.
        for tone_key in ("ai", "warm-club", "hype", "data-led"):
            assert f'data-tone="{tone_key}"' in html
        assert "Regenerate caption" in html
        assert "Assist" in html
        assert "Create graphic" in html
        assert "/create-graphic" in html
        assert "Generate reel" in html
        assert "/reel-job" in html
        # Full toolbar parity with the meet-recap Content builder: Reformat + Copilot.
        assert "Reformat" in html
        assert "/reformat" in html
        assert "Copilot" in html
        assert "/assistant" in html

        # Composite caption + a route back to the spotlight to re-pick moments.
        assert "Lara took the meet by the throat" in html
        assert f"/spotlight/{run_id}/" in html


def test_composite_builder_toolbar_endpoints(gated_app, tmp_path, monkeypatch):
    """The composite Content builder's toolbar endpoints — live caption (tone),
    inline assist, and the reel job — are pack-scoped and reuse the spotlight
    compose / caption-assist / reel engine. AI is honest-errored when no
    provider is configured (never a fabricated caption)."""
    import mediahub.ai_core as ai_core_pkg
    monkeypatch.setattr(
        ai_core_pkg, "ask", lambda system, user, **kw: "Lara owned the pool today."
    )

    run_id = "synth_run_ep"
    runs_dir = tmp_path / "runs_v4"
    run = _synthetic_run_with_achievements(run_id, runs_dir)
    swimmer_key = run["recognition_report"][
        "ranked_achievements"
    ][0]["achievement"]["swimmer_id"]

    with gated_app.test_client() as c:
        with c.session_transaction() as sess:
            sess["active_profile_id"] = "acmeswim"
        r1 = c.post(f"/spotlight/{run_id}/{swimmer_key}/build", follow_redirects=False)
        assert r1.status_code == 302
        pack_id = r1.headers["Location"].rstrip("/").split("/")[-1]

        # No provider configured → honest non-fabricated error, not a stub caption.
        r_nokey = c.post(f"/api/drafts/{pack_id}/card/0/caption?tone=hype")
        assert r_nokey.status_code == 200
        assert r_nokey.get_json()["live"] is False

        # With AI available, a tone tab recomposes the SAME approved moments live.
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
        r_cap = c.post(f"/api/drafts/{pack_id}/card/0/caption?tone=hype")
        assert r_cap.status_code == 200
        body = r_cap.get_json()
        assert body["live"] is True
        assert body["caption"] == "Lara owned the pool today."
        assert body["tone"] == "hype"

        # Inline assist revises the current caption (engine stubbed).
        monkeypatch.setattr(
            "mediahub.web.caption_assist.assist_caption", lambda *a, **k: "Lara owned it."
        )
        r_as = c.post(
            f"/api/drafts/{pack_id}/card/0/caption/assist",
            json={
                "current_caption": "Lara owned the pool today.",
                "transform": "shorter",
                "tone": "hype",
            },
        )
        assert r_as.status_code == 200
        assert r_as.get_json()["caption"] == "Lara owned it."

        # The reel job kicks off from the approved moments (render stubbed) and
        # returns a pollable job — the composite reel, not a per-card story.
        import mediahub.visual.motion as _motion
        monkeypatch.setattr(_motion, "render_meet_reel", lambda *a, **k: str(a[2]))
        r_reel = c.post(f"/api/drafts/{pack_id}/card/0/reel-job")
        assert r_reel.status_code == 202
        rj = r_reel.get_json()
        assert rj["job_id"] and rj["poll_url"]

        # Reformat + Copilot need the composite design first → honest 409 before
        # a graphic exists (never a fabricated/blank render), and the copilot
        # suggestion chips are always available.
        r_rf = c.post(f"/api/drafts/{pack_id}/card/0/reformat?format=ig_square")
        assert r_rf.status_code == 409
        r_cp = c.post(
            f"/api/drafts/{pack_id}/card/0/assistant", json={"message": "make it navy"}
        )
        assert r_cp.status_code == 409
        r_sg = c.get(f"/api/drafts/{pack_id}/card/0/assistant/suggestions")
        assert r_sg.status_code == 200
        assert "suggestions" in r_sg.get_json()


def test_spotlight_graphic_item_strips_entry_url_and_dedupes():
    """The results-from-a-link flow leaves an ``entry_url: https://…`` meet
    placeholder, and the recognition headline bakes it into achievement text.
    The spotlight graphic must never print that URL, must drop the empty meet
    tile rather than label a URL 'EVENT', and must collapse duplicate moments."""
    from mediahub.web.web import (
        _clean_meet_label,
        _strip_source_suffix,
        _stub_card_to_graphic_item,
    )

    url = "entry_url: https://results.swimming.org/swimming/results/2026/agbchamps/"
    # Unit: the two display sanitizers.
    assert _clean_meet_label(url) == ""
    assert _clean_meet_label("AGB Champs 2026") == "AGB Champs 2026"
    assert (
        _strip_source_suffix(f"Amy Crowley wins gold in 50m Breaststroke (LC) at {url}!")
        == "Amy Crowley wins gold in 50m Breaststroke (LC)"
    )

    item = _stub_card_to_graphic_item(
        "free_text",
        {"caption": "Great swim."},
        {
            "source": "athlete_spotlight",
            "swimmer_name": "Amy Crowley",
            "meet_name": url,
            "n_approved": 2,
            "results_lines": "50m Breaststroke (LC)\n50m Breaststroke (LC)",
        },
    )
    gt = item["graphic_text"]
    blob = repr(gt) + repr(item.get("meet_name"))
    # No crawl URL anywhere on the card…
    assert "entry_url" not in blob and "http" not in blob
    # …no meet/event tile labelled with the URL (we have no real meet)…
    assert "meet" not in gt["stats"] and "event" not in gt["stats"]
    # …and the duplicate moment collapses to one bullet.
    assert gt["bullets"] == ["50m Breaststroke (LC)"]
    assert gt["stats"].get("athlete") == "Amy Crowley"
    assert gt["stats"].get("moments") == "2 approved"
