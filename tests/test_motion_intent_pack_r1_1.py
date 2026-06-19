"""R1.1 — Reel generator sprint: the motion-intent program pack.

Roadmap R1.1 adds five new motion languages — ``bounce_in``, ``flip_reveal``,
``swirl``, ``reveal_from_sides``, ``cascade`` — each as its OWN auto-discovered
file under ``remotion/.../sprint/intents/<name>.ts`` (the sprint seam), with the
token added to ``creative_brief/design_spec.MOTION_INTENTS`` and NO edit to
``StoryCard.tsx``'s ``animProgram`` switch.

These tests lock the whole contract that makes the pack actually work
end-to-end:

  * each token is a member of the closed ``MOTION_INTENTS`` vocabulary and
    ``normalise`` round-trips it (so a director that emits it survives);
  * each token has exactly one registry file that DEFAULT-exports
    ``{ name: "<token>", program }`` with the name matching the filename, so
    ``registry.byName`` / ``EXTRA_INTENTS`` pick it up at build time;
  * the new languages are sprint-only — they do NOT appear in StoryCard.tsx
    (the isolation contract the roadmap requires), so they resolve through the
    ``animProgram`` default branch (``EXTRA_INTENTS[intent]``);
  * each programme is deterministic (no ``Math.random`` / clock) and a pure
    function of the frame — the motion-craft hard bound;
  * the intent flows design-spec → brief → Remotion props; and
  * the AI director can actually reach the new languages (its prompt lists
    them — that path is prompt-driven, not schema-constrained).

No Node needed: pure-Python shaping + TSX source contracts, like
``test_motion_v2_parity.py``.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief import ai_director
from mediahub.creative_brief import design_spec as ds
from mediahub.creative_brief.generator import generate
from mediahub.graphic_renderer import archetypes
from mediahub.visual import motion

# The pack this test file owns. Roadmap R1.1 specifies "5+ new intents".
R1_1_INTENTS = (
    "bounce_in",
    "flip_reveal",
    "swirl",
    "reveal_from_sides",
    "cascade",
)

_INTENTS_DIR = (
    motion.REMOTION_DIR / "src" / "compositions" / "sprint" / "intents"
)
_STORYCARD = motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx"


# ---------------------------------------------------------------------------
# Vocabulary membership + normalisation
# ---------------------------------------------------------------------------


def test_pack_is_at_least_five_intents():
    # Roadmap R1.1: "5+ new intents". Guard against the pack silently shrinking.
    assert len(R1_1_INTENTS) >= 5
    assert len(set(R1_1_INTENTS)) == len(R1_1_INTENTS)  # no dupes


@pytest.mark.parametrize("intent", R1_1_INTENTS)
def test_intent_is_in_the_closed_vocabulary(intent):
    assert intent in ds.MOTION_INTENTS


@pytest.mark.parametrize("intent", R1_1_INTENTS)
def test_normalise_round_trips_the_new_intent(intent):
    """A director that emits one of these survives normalisation unchanged —
    it does not collapse to the safe default."""
    spec = ds.normalise(
        {"motion_intent": intent, "archetype": "big_number_dominant"},
        archetypes=["big_number_dominant", "minimal_type_poster"],
        token_roles=["primary", "secondary"],
    )
    assert spec.motion_intent == intent


def test_new_intents_do_not_displace_the_originals():
    """Adding the pack must be purely additive — the nine built-ins stay."""
    for built_in in (
        "fade_in", "snap_in_then_settle", "slide_up", "scale_in", "crossfade",
        "kinetic_type", "parallax", "count_up", "static",
    ):
        assert built_in in ds.MOTION_INTENTS


# ---------------------------------------------------------------------------
# Registry-file contract (one auto-discovered file per intent)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("intent", R1_1_INTENTS)
def test_intent_has_its_own_registry_file(intent):
    assert (_INTENTS_DIR / f"{intent}.ts").is_file(), (
        f"R1.1 intent {intent!r} must live in its own sprint/intents/{intent}.ts"
    )


@pytest.mark.parametrize("intent", R1_1_INTENTS)
def test_registry_file_default_exports_name_and_program(intent):
    """``registry.byName`` reads ``m.name`` + ``m.program`` off the default
    export. The file must register the EXACT token (so EXTRA_INTENTS keys it
    correctly) and a program."""
    src = (_INTENTS_DIR / f"{intent}.ts").read_text()
    assert re.search(r"export default\s*\{", src), "must default-export the module"
    assert f'name: "{intent}"' in src, f"must register name {intent!r}"
    assert "program" in src, "must export a `program`"
    # It is an IntentProgram, typed from the shared registry contract.
    assert "IntentProgram" in src and '"../registry"' in src


@pytest.mark.parametrize("intent", R1_1_INTENTS)
def test_registry_file_is_deterministic(intent):
    """The motion-craft hard bound: a pure function of the frame. No RNG, no
    wall-clock — same props must render byte-identically."""
    src = (_INTENTS_DIR / f"{intent}.ts").read_text()
    for banned in ("Math.random", "Date.now", "new Date", "performance.now"):
        assert banned not in src, f"{intent}: non-deterministic call {banned!r}"
    # A programme that ignores the frame entirely is a static slide, not motion.
    assert "frame" in src


def test_intents_dir_has_no_orphan_registrations():
    """Every registered intent module in the folder is a real vocabulary member
    whose filename matches its token — catches a stray/dupe file that would
    register a phantom intent the vocabulary doesn't know about. The folder grows
    over time (1.5 added the motion-vocabulary pack on the same seam), so the
    guarantee is a *superset*: all R1.1 intents present, and nothing phantom."""
    registered = {}
    for path in _INTENTS_DIR.glob("*.ts"):
        m = re.search(r'name:\s*"([^"]+)"', path.read_text())
        if m:
            registered[path.stem] = m.group(1)
    # filename stem == registered name == a known vocabulary member.
    for stem, name in registered.items():
        assert stem == name, f"{stem}.ts registers mismatched name {name!r}"
        assert name in ds.MOTION_INTENTS, f"{name!r} not in MOTION_INTENTS"
    assert set(registered.values()) >= set(R1_1_INTENTS)


# ---------------------------------------------------------------------------
# Isolation contract — sprint-only, no StoryCard.tsx edit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("intent", R1_1_INTENTS)
def test_new_intent_is_not_inlined_in_storycard(intent):
    """R1.1 is 🟢 ISOLATED: the pack adds NEW files only. The new tokens must
    resolve through animProgram's default branch (EXTRA_INTENTS), so they must
    NOT appear as inline switch cases in StoryCard.tsx."""
    storycard = _STORYCARD.read_text()
    assert f'"{intent}"' not in storycard, (
        f"{intent!r} leaked into StoryCard.tsx — R1.1 must stay a sprint file"
    )


def test_storycard_default_branch_consults_the_registry():
    """The seam that makes the pack executable without a switch edit: the
    default branch hands unknown intents to EXTRA_INTENTS."""
    storycard = _STORYCARD.read_text()
    assert "EXTRA_INTENTS[intent]" in storycard


# ---------------------------------------------------------------------------
# End-to-end reachability: design-spec → brief → props, and the director prompt
# ---------------------------------------------------------------------------


def _brand() -> BrandKit:
    return BrandKit(
        profile_id="r11",
        display_name="R1.1 SC",
        primary_colour="#0E2A47",
        secondary_colour="#C9A227",
        short_name="RSC",
    )


def _card() -> dict:
    return {
        "id": "swim-r11-1",
        "swim_id": "swim-r11-1",
        "achievement": {
            "swim_id": "swim-r11-1",
            "swimmer_name": "Swimmer One",
            "event_name": "100m Freestyle",
            "result_time": "1:01.00",
        },
        "meet_name": "R1.1 Invitational",
    }


@pytest.mark.parametrize("intent", R1_1_INTENTS)
def test_intent_flows_brief_to_props(intent):
    """A brief carrying the new intent forwards it verbatim into the Remotion
    props as ``motionIntent`` (which then feeds the cache key, so a new value
    self-bumps the hash)."""
    brief = generate(
        {"id": "swim-r11-1", "post_angle": "confirmed_official_pb",
         "achievement": _card()["achievement"]},
        None,
        _brand(),
        profile_id="r11",
    )
    d = brief.to_dict()
    d["motion_intent"] = intent
    props = motion._card_to_props(_card(), variation_seed=3, brief=d)
    assert props["motionIntent"] == intent


@pytest.mark.parametrize("intent", R1_1_INTENTS)
def test_director_prompt_offers_the_new_intent(intent):
    """The director's chooser path (``ai_director.ask``) is prompt-driven, not
    schema-constrained — so a token only gets emitted if the prompt lists it.
    Without this, the intent would be a dead enum value the director never
    picks."""
    prompt = ai_director._design_spec_system_prompt(
        archetypes.list_archetypes(), list(archetypes.TOKEN_ROLES)
    )
    assert intent in prompt
