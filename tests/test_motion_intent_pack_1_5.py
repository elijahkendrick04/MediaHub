"""1.5 — the motion-vocabulary intent pack.

Roadmap 1.5 widens the director's motion vocabulary with three new languages —
``rise``, ``pop``, ``drop_in`` — each on the same sprint-intents seam as the R1.1
pack, but with a twist that *is* the 1.5 contract: the programme is **compiled
from the tokenised vocabulary** (``src/mediahub/motion/vocabulary.py`` →
``remotion/src/motion/compile.ts``), so the movement is identical to the CSS the
browser plays. These tests lock that contract end-to-end (mirroring
``test_motion_intent_pack_r1_1.py``).

No Node needed: pure-Python shaping + TS source contracts.
"""
from __future__ import annotations

import re

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief import ai_director
from mediahub.creative_brief import design_spec as ds
from mediahub.creative_brief.generator import generate
from mediahub.graphic_renderer import archetypes
from mediahub.visual import motion

PACK_1_5 = ("rise", "pop", "drop_in")

_INTENTS_DIR = motion.REMOTION_DIR / "src" / "compositions" / "sprint" / "intents"
_STORYCARD = motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx"
_COMPILE_TS = motion.REMOTION_DIR / "src" / "motion" / "compile.ts"


# -- vocabulary membership ---------------------------------------------------


@pytest.mark.parametrize("intent", PACK_1_5)
def test_intent_is_in_the_closed_vocabulary(intent):
    assert intent in ds.MOTION_INTENTS


@pytest.mark.parametrize("intent", PACK_1_5)
def test_normalise_round_trips(intent):
    spec = ds.normalise(
        {"motion_intent": intent, "archetype": "big_number_dominant"},
        archetypes=["big_number_dominant", "minimal_type_poster"],
        token_roles=["primary", "secondary"],
    )
    assert spec.motion_intent == intent


def test_pack_is_additive_to_the_existing_vocabulary():
    for existing in (
        "fade_in", "slide_up", "scale_in", "count_up", "static",  # built-ins
        "bounce_in", "flip_reveal", "swirl", "reveal_from_sides", "cascade",  # R1.1
    ):
        assert existing in ds.MOTION_INTENTS


# -- registry-file contract --------------------------------------------------


@pytest.mark.parametrize("intent", PACK_1_5)
def test_intent_has_its_own_registry_file(intent):
    assert (_INTENTS_DIR / f"{intent}.ts").is_file()


@pytest.mark.parametrize("intent", PACK_1_5)
def test_file_default_exports_name_and_program(intent):
    src = (_INTENTS_DIR / f"{intent}.ts").read_text()
    assert re.search(r"export default\s*\{", src)
    assert f'name: "{intent}"' in src
    assert "program" in src
    assert "IntentProgram" in src and '"../registry"' in src


@pytest.mark.parametrize("intent", PACK_1_5)
def test_file_is_vocabulary_compiled(intent):
    """The 1.5 distinction: the programme is compiled from the shared motion
    vocabulary, not hand-rolled — it routes through ``compile.ts``."""
    src = (_INTENTS_DIR / f"{intent}.ts").read_text()
    assert "entranceChannels" in src
    assert "motion/compile" in src


@pytest.mark.parametrize("intent", PACK_1_5)
def test_file_is_deterministic(intent):
    src = (_INTENTS_DIR / f"{intent}.ts").read_text()
    for banned in ("Math.random", "Date.now", "new Date", "performance.now"):
        assert banned not in src
    assert "frame" in src


def test_compile_ts_helper_exists_and_is_frame_pure():
    src = _COMPILE_TS.read_text()
    assert "export function entranceChannels" in src
    assert "export function sampleChannel" in src
    for banned in ("Math.random", "Date.now"):
        assert banned not in src


# -- isolation: sprint-only, no StoryCard edit -------------------------------


@pytest.mark.parametrize("intent", PACK_1_5)
def test_not_inlined_in_storycard(intent):
    assert f'"{intent}"' not in _STORYCARD.read_text()


# -- end-to-end reachability -------------------------------------------------


def _brand() -> BrandKit:
    return BrandKit(
        profile_id="m15", display_name="1.5 SC", primary_colour="#0E2A47",
        secondary_colour="#C9A227", short_name="MSC",
    )


def _card() -> dict:
    return {
        "id": "swim-15-1", "swim_id": "swim-15-1",
        "achievement": {
            "swim_id": "swim-15-1", "swimmer_name": "Swimmer One",
            "event_name": "100m Freestyle", "result_time": "1:01.00",
        },
        "meet_name": "1.5 Invitational",
    }


@pytest.mark.parametrize("intent", PACK_1_5)
def test_intent_flows_brief_to_props(intent):
    brief = generate(
        {"id": "swim-15-1", "post_angle": "confirmed_official_pb",
         "achievement": _card()["achievement"]},
        None, _brand(), profile_id="m15",
    )
    d = brief.to_dict()
    d["motion_intent"] = intent
    props = motion._card_to_props(_card(), variation_seed=3, brief=d)
    assert props["motionIntent"] == intent


@pytest.mark.parametrize("intent", PACK_1_5)
def test_director_prompt_offers_the_intent(intent):
    prompt = ai_director._design_spec_system_prompt(
        archetypes.list_archetypes(), list(archetypes.TOKEN_ROLES)
    )
    assert intent in prompt


def test_parity_corpus_executes_the_pack():
    """The motion-parity drift guard must see an execution path for each new
    intent (its sprint file appears in the scanned corpus)."""
    comp = motion.REMOTION_DIR / "src" / "compositions"
    corpus = (comp / "StoryCard.tsx").read_text()
    for p in (comp / "sprint").rglob("*.ts"):
        corpus += p.read_text()
    for intent in PACK_1_5:
        assert f'"{intent}"' in corpus
