"""SEQ-2 — Tier B: design-spec director batch, candidate pool, compliance, rank.

Covers the roadmap Appendix A SEQ-2 verification surface:
  * the batch director emits N schema-valid, mutually-distinct DesignSpecs
    (mocked LLM — no live call);
  * a deliberately malformed LLM response still yields legal, renderable
    candidates (PAR-4 normalisation);
  * with no provider configured the pool falls back to the deterministic
    Tier A archetype walk — never a fabricated card, never empty-handed;
  * every candidate carries an explainable deterministic compliance score
    and the shortlist is ranked legibility-first;
  * the director's colour-role assignment is honoured ONLY when the
    reassigned set clears the APCA gate;
  * the create-graphic route returns the shortlist additively with the
    legacy single-visual fields populated from the top candidate, and the
    classic response shape is unchanged when the param is absent.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief import ai_director
from mediahub.creative_brief.design_spec import normalise
from mediahub.creative_brief.generator import CreativeBrief, apply_design_spec
from mediahub.graphic_renderer.archetypes import TOKEN_ROLES, list_archetypes


NAVY_GOLD = BrandKit(
    profile_id="tier-b-club",
    display_name="Tier B Swimming Club",
    primary_colour="#0E2A47",
    secondary_colour="#C9A227",
)

ITEM = {
    "id": "swim-tb-1",
    "swim_id": "swim-tb-1",
    "achievement": {
        "swim_id": "swim-tb-1",
        "swimmer_name": "Aderyn Vaughan",
        "event_name": "100m Butterfly",
        "result_time": "1:02.34",
        "post_angle": "new_pb",
        "raw_facts": {"time_str": "1:02.34", "drop_seconds": 0.42},
    },
    "post_angle": "new_pb",
    "meet_name": "Tier B Invitational",
    "safe_to_post": {"level": "safe"},
}


def _spec_json(archetype: str, **over) -> dict:
    d = {
        "archetype": archetype,
        "colour_roles": {
            "ground": "primary",
            "surface": "surface",
            "headline": "on_primary",
            "accent": "accent",
        },
        "focal_element": "big_number",
        "crop_intent": "centered",
        "hero_stat": "pb_delta",
        "secondary_stats": ["placing"],
        "headline_hook": "FLY LIKE THAT",
        "accent_treatment": "underline",
        "logo_lockup": "icon",
        "mood": "electric",
        "motion_intent": "snap_in_then_settle",
        "rationale": "The PB drop is the story; lead with the delta.",
    }
    d.update(over)
    return d


# ---------------------------------------------------------------------------
# ai_design_specs — the batch director (mocked provider)
# ---------------------------------------------------------------------------


def test_batch_director_emits_n_distinct_validated_specs():
    names = list_archetypes()
    payload = json.dumps(
        [
            _spec_json(names[0]),
            _spec_json(names[1], hero_stat="placing", mood="calm"),
            _spec_json(names[2], hero_stat="final_time"),
            _spec_json(names[1]),  # duplicate archetype → dropped client-side
        ]
    )
    with mock.patch("mediahub.ai_core.ask", return_value=payload):
        specs = ai_director.ai_design_specs(
            content_item=ITEM,
            brand_kit=NAVY_GOLD,
            archetypes=names,
            token_roles=list(TOKEN_ROLES),
            count=3,
        )
    assert specs is not None and len(specs) == 3
    assert len({s.archetype for s in specs}) == 3
    for s in specs:
        assert s.archetype in names
        assert s.colour_roles.ground in TOKEN_ROLES


def test_batch_director_normalises_hallucinated_values():
    names = list_archetypes()
    payload = json.dumps(
        [
            _spec_json(
                names[2],
                colour_roles={"ground": "#FF00FF", "surface": "neon", "headline": 7},
                mood="ultra-mega-hype",
                hero_stat="vibes",
            ),
            # Invented archetype → normalises to the catalog default (names[0]),
            # which stays distinct from names[2] so both survive dedupe.
            _spec_json("invented_archetype_9000"),
        ]
    )
    with mock.patch("mediahub.ai_core.ask", return_value=payload):
        specs = ai_director.ai_design_specs(
            content_item=ITEM,
            brand_kit=NAVY_GOLD,
            archetypes=names,
            token_roles=list(TOKEN_ROLES),
            count=2,
        )
    assert specs is not None and len(specs) == 2
    # Every hallucinated value normalised to a legal one.
    assert specs[0].colour_roles.ground in TOKEN_ROLES
    assert specs[0].mood == "neutral"
    assert specs[0].hero_stat == "final_time"
    assert specs[1].archetype in names


def test_batch_director_returns_none_on_garbage_and_no_provider():
    names = list_archetypes()
    with mock.patch("mediahub.ai_core.ask", return_value="sorry, no JSON here"):
        assert (
            ai_director.ai_design_specs(
                content_item=ITEM,
                brand_kit=NAVY_GOLD,
                archetypes=names,
                token_roles=list(TOKEN_ROLES),
            )
            is None
        )
    from mediahub.ai_core import ProviderNotConfigured

    with mock.patch("mediahub.ai_core.ask", side_effect=ProviderNotConfigured("no key")):
        assert (
            ai_director.ai_design_specs(
                content_item=ITEM,
                brand_kit=NAVY_GOLD,
                archetypes=names,
                token_roles=list(TOKEN_ROLES),
            )
            is None
        )


def test_director_catalog_is_briefed_from_archetype_notes():
    """PAR-7's purpose: each archetype's authored notes feed the director.

    The system prompt's catalog lines must come from the ``<name>.notes.md``
    when-to-pick passages — not collapse to the static fallback ("a distinct
    layout.") for archetypes missing from the hardcoded guide dict.
    """
    names = list_archetypes()
    prompt = ai_director._design_spec_system_prompt(names, list(TOKEN_ROLES))
    # no archetype may fall through to the generic fallback line
    assert "a distinct layout." not in prompt
    # spot-check notes-derived briefings reach the prompt verbatim-ish
    assert "head-to-head" in prompt  # duo_athlete_split's when-to-pick
    assert "ceremonial" in prompt  # centered_medal_spotlight's when-to-pick
    # and every archetype has its own catalog line
    for name in names:
        assert f"- {name}: " in prompt


# ---------------------------------------------------------------------------
# apply_design_spec — the single spec→brief mapping
# ---------------------------------------------------------------------------


def _bare_brief(**over) -> CreativeBrief:
    base = dict(
        id="cb_test",
        content_item_id="swim-tb-1",
        profile_id="tier-b-club",
        achievement_summary="Aderyn Vaughan — 100m Butterfly — 1:02.34",
        objective="celebrate",
        primary_hook="NEW PB",
        confidence_label="NEW PB",
        tone="hype",
        layout_template="individual_hero",
        inspiration_pattern_id="p1",
        image_treatment="cutout",
        text_hierarchy=[],
        brand_instructions="",
        sponsor_instructions=None,
        sourced_asset_ids=[],
        safety_notes=[],
        why_this_design="default",
        text_layers={"result_value": "1:02.34"},
        palette={"primary": "#0E2A47", "secondary": "#C9A227", "accent": "#C9A227"},
        format_priority=["feed_portrait"],
        hero_stat_options={"pb_delta": "−0.42s on PB", "placing": "2nd place"},
    )
    base.update(over)
    return CreativeBrief(**base)


def test_apply_design_spec_maps_all_fields_and_restamps_signature():
    names = list_archetypes()
    spec = normalise(_spec_json(names[3]), archetypes=names, token_roles=list(TOKEN_ROLES))
    brief = _bare_brief()
    before_sig = brief.variation_signature
    apply_design_spec(brief, spec)
    assert brief.layout_template == names[3]
    assert brief.primary_hook == "FLY LIKE THAT"
    assert brief.mood == "electric"
    assert brief.ai_directed is True
    assert brief.why_this_design.startswith("The PB drop")
    assert brief.text_layers["hero_stat"] == "−0.42s on PB"
    assert brief.colour_role_assignment == {
        "ground": "primary",
        "surface": "surface",
        "headline": "on_primary",
        "accent": "accent",
    }
    assert brief.variation_signature != before_sig
    assert brief.variation_signature.startswith(names[3] + "|")


def test_apply_design_spec_never_fabricates_a_hero_stat():
    names = list_archetypes()
    spec = normalise(
        _spec_json(names[0], hero_stat="relay_split"),
        archetypes=names,
        token_roles=list(TOKEN_ROLES),
    )
    brief = _bare_brief(hero_stat_options={})  # nothing measured
    apply_design_spec(brief, spec)
    assert "hero_stat" not in brief.text_layers  # absent fact stays absent


# ---------------------------------------------------------------------------
# Colour-role assignment — honoured only behind the APCA gate
# ---------------------------------------------------------------------------


def test_legible_role_assignment_is_honoured():
    from mediahub.graphic_renderer.render import resolved_role_vars_for_brief

    baseline = resolved_role_vars_for_brief(_bare_brief(), NAVY_GOLD)
    # Full brand inversion: gold ground + navy accent. On a navy/gold kit
    # every scored pair clears APCA, so the director's assignment must ship.
    brief = _bare_brief(colour_role_assignment={"ground": "secondary", "accent": "primary"})
    got = resolved_role_vars_for_brief(brief, NAVY_GOLD)
    assert got["--mh-primary"] == baseline["--mh-secondary"]
    assert got["--mh-accent"] == baseline["--mh-primary"]
    from mediahub.quality.compliance import check_roles

    assert check_roles(got).passes


def test_partial_assignment_that_breaks_a_pair_is_rejected_atomically():
    from mediahub.graphic_renderer.render import resolved_role_vars_for_brief

    baseline = resolved_role_vars_for_brief(_bare_brief(), NAVY_GOLD)
    # Ground→gold while the accent stays gold makes accent==ground (Lc 0):
    # the gate must reject the WHOLE assignment, not ship a half-legal card.
    brief = _bare_brief(colour_role_assignment={"ground": "secondary"})
    got = resolved_role_vars_for_brief(brief, NAVY_GOLD)
    assert got == baseline


def test_illegible_role_assignment_falls_back_to_brand_defaults():
    from mediahub.graphic_renderer.render import resolved_role_vars_for_brief

    baseline = resolved_role_vars_for_brief(_bare_brief(), NAVY_GOLD)
    # Painting the headline in the same colour as the ground can never read;
    # the gate must reject the whole assignment and keep the safe baseline.
    brief = _bare_brief(colour_role_assignment={"headline": "primary"})
    got = resolved_role_vars_for_brief(brief, NAVY_GOLD)
    assert got == baseline


# ---------------------------------------------------------------------------
# create_candidate_pool_for_item — floor path (no provider)
# ---------------------------------------------------------------------------


@pytest.fixture
def pool_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _fake_render_all_formats(brief, *, output_dir, formats=None, **kw):
    """Stand-in renderer: writes a tiny PNG per format, returns RenderResult-alikes."""
    from pathlib import Path
    from PIL import Image

    class _V:
        def __init__(self, vid, fmt, path):
            self.id = vid
            self.format_name = fmt
            self.width, self.height = 8, 10
            self.file_path = str(path)
            self.layout_template = brief.layout_template
            self.confidence_label = brief.confidence_label
            self.why_this_design = brief.why_this_design
            self.safety_notes = list(brief.safety_notes)
            self.sourced_asset_ids = list(brief.sourced_asset_ids)
            self.brief_id = brief.id

        def to_dict(self):
            return {"id": self.id, "format_name": self.format_name}

    class _R:
        def __init__(self, v):
            self.visual = v

    out = []
    # Seed the pixel from the archetype so perceptual_spread sees variety.
    shade = (hash(brief.layout_template) % 200, 40, 90)
    for fmt in formats or ["feed_portrait"]:
        p = Path(output_dir) / f"{brief.id}_{fmt}.png"
        Image.new("RGB", (8, 10), shade).save(p)
        out.append(_R(_V(f"v_{brief.id}_{fmt}", fmt, p)))
    return out


def test_pool_without_provider_returns_ranked_deterministic_shortlist(pool_env):
    from mediahub.content_pack_visual import integration

    with mock.patch.object(
        ai_director, "ai_design_specs", return_value=None
    ) as director, mock.patch(
        "mediahub.graphic_renderer.variants.render_all_formats",
        side_effect=_fake_render_all_formats,
    ):
        pool = integration.create_candidate_pool_for_item(
            dict(ITEM),
            NAVY_GOLD,
            profile_id="tier-b-club",
            run_id="run-tb-1",
            n=5,
        )
    assert director.called
    cands = pool["candidates"]
    assert len(cands) == 5
    # ≥4 structurally distinct candidates (verification bar) — floor gives 5.
    assert len({c["archetype"] for c in cands}) == 5
    assert pool["pool_metrics"]["archetype_diversity"] == 1.0
    for rank, c in enumerate(cands, start=1):
        assert c["rank"] == rank
        assert c["ai_directed"] is False  # honest floor, not fabricated AI
        comp = c["compliance"]
        assert 0.0 <= comp["score"] <= 1.0
        assert isinstance(comp["passes"], bool)
        assert comp["explain"]
        assert c["visuals"] and c["visuals"][0]["file_path"]
    # Ranked legibility-first: scores never increase down the list.
    scores = [c["compliance"]["score"] for c in cands]
    assert scores == sorted(scores, reverse=True)


def test_pool_with_mocked_director_marks_ai_candidates(pool_env):
    from mediahub.content_pack_visual import integration

    names = list_archetypes()
    specs = [
        normalise(_spec_json(names[0]), archetypes=names, token_roles=list(TOKEN_ROLES)),
        normalise(
            _spec_json(names[1], hero_stat="placing"),
            archetypes=names,
            token_roles=list(TOKEN_ROLES),
        ),
    ]
    with mock.patch.object(ai_director, "ai_design_specs", return_value=specs), mock.patch(
        "mediahub.graphic_renderer.variants.render_all_formats",
        side_effect=_fake_render_all_formats,
    ):
        pool = integration.create_candidate_pool_for_item(
            dict(ITEM),
            NAVY_GOLD,
            profile_id="tier-b-club",
            run_id="run-tb-2",
            n=4,
        )
    cands = pool["candidates"]
    assert len(cands) == 4
    # Two AI-directed + two deterministic gap-fillers, all distinct archetypes.
    assert sum(1 for c in cands if c["ai_directed"]) == 2
    assert len({c["archetype"] for c in cands}) == 4
    ai_archetypes = {c["archetype"] for c in cands if c["ai_directed"]}
    assert ai_archetypes == {names[0], names[1]}
    # The AI hook landed on its candidate's brief.
    ai_briefs = [c["brief"] for c in cands if c["ai_directed"]]
    assert any(b["primary_hook"] == "FLY LIKE THAT" for b in ai_briefs)


def test_pool_disabled_when_killswitch_off(pool_env, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "0")
    from mediahub.content_pack_visual import integration

    pool = integration.create_candidate_pool_for_item(
        dict(ITEM), NAVY_GOLD, profile_id="tier-b-club", run_id="run-tb-3", n=5
    )
    assert pool["candidates"] == []
    assert "gen_v2_disabled_or_no_archetypes" in pool["errors"]


# ---------------------------------------------------------------------------
# Route: additive shortlist; classic shape untouched without the param
# ---------------------------------------------------------------------------


@pytest.fixture
def web_app(tmp_path, monkeypatch):
    import importlib
    import uuid as _uuid

    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    run_id = "run-tb-" + _uuid.uuid4().hex[:8]
    run_payload = {
        "run_id": run_id,
        "profile_id": "",
        "meet": {"name": "Tier B Invitational"},
        "cards": [],
        "recognition_report": {
            "ranked_achievements": [
                {
                    "achievement": dict(ITEM["achievement"]),
                    "safe_to_post": {"level": "safe"},
                }
            ],
            "n_elite": 1,
            "n_strong": 0,
            "n_story": 0,
            "n_achievements": 1,
            "n_swims_analysed": 1,
        },
        "parse_warnings": [],
        "self_check": {},
        "detector_summary": {},
        "dispatch_log": {},
    }
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(run_payload))
    app = wm.create_app()
    app.config["TESTING"] = True
    return app, run_id


def test_route_returns_additive_shortlist_with_legacy_fields(web_app):
    app, run_id = web_app
    with mock.patch.object(ai_director, "ai_design_specs", return_value=None), mock.patch(
        "mediahub.graphic_renderer.variants.render_all_formats",
        side_effect=_fake_render_all_formats,
    ):
        with app.test_client() as client:
            resp = client.post(
                f"/api/runs/{run_id}/cards/swim-tb-1/create-graphic?candidates=4"
            )
    assert resp.status_code == 200, resp.get_data(as_text=True)[:400]
    body = resp.get_json()
    assert body["ok"] is True
    cands = body["candidates"]
    assert len(cands) == 4
    assert len({c["archetype"] for c in cands}) == 4
    assert all("compliance" in c and "score" in c["compliance"] for c in cands)
    assert body["pool_metrics"]["archetype_diversity"] == 1.0
    # Legacy fields mirror the top-ranked candidate — old callers unaffected.
    assert body["visuals"] == cands[0]["visuals"]
    assert body["brief"]["id"] == cands[0]["brief"]["id"]
    assert body["variation_signature"] == cands[0]["brief"]["variation_signature"]


def test_regenerate_variants_sync_yields_three_distinct_archetypes(web_app):
    """SEQ-3: the 3-variant worker now rides the design-spec pool.

    No provider → the deterministic archetype walk must still produce three
    mutually-distinct variants (distinct by construction, no re-roll guard).
    """
    app, run_id = web_app
    with mock.patch.object(ai_director, "ai_design_specs", return_value=None), mock.patch(
        "mediahub.graphic_renderer.variants.render_all_formats",
        side_effect=_fake_render_all_formats,
    ):
        with app.test_client() as client:
            resp = client.post(
                f"/api/runs/{run_id}/cards/swim-tb-1/regenerate-variants?sync=1"
            )
    assert resp.status_code == 200, resp.get_data(as_text=True)[:400]
    body = resp.get_json()
    variants = body.get("variants") or []
    assert len(variants) == 3
    archetypes = [
        (v.get("variation_signature") or "").split("|", 1)[0] for v in variants
    ]
    assert len(set(archetypes)) == 3
    assert all(a in list_archetypes() for a in archetypes)
    assert all(v.get("visual") for v in variants)


def test_route_without_param_keeps_classic_single_shape(web_app):
    app, run_id = web_app

    def _fake_single(item, brand_kit, **kw):
        return {
            "visuals": [{"id": "v1", "format_name": "feed_portrait"}],
            "brief": {"variation_signature": "sig", "primary_hook": "H", "ai_directed": False},
            "evaluation": {},
            "errors": [],
        }

    import mediahub.web.web as wm

    with mock.patch.object(wm, "_v8_create_visual_for_item", side_effect=_fake_single):
        with app.test_client() as client:
            resp = client.post(f"/api/runs/{run_id}/cards/swim-tb-1/create-graphic")
    assert resp.status_code == 200, resp.get_data(as_text=True)[:400]
    body = resp.get_json()
    assert body["ok"] is True
    assert "candidates" not in body  # additive key absent on the classic path
    assert "pool_metrics" not in body
    assert body["visuals"][0]["id"] == "v1"
