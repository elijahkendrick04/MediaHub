"""adjustable-stagger — deterministic, mood-tuned entrance stagger.

The token-compiled entrance intents (drop_in / rise / pop) stagger the hero →
result → chrome layers by fixed frame delays. This exposes that stagger as a
mood-derived scale, folded into the story cache key only when it actually
differs from the default so every other card stays byte-identical.
"""

from __future__ import annotations

from mediahub.visual import motion


def _compile_ts() -> str:
    return (motion.REMOTION_DIR / "src" / "motion" / "compile.ts").read_text()


def test_entrance_stagger_scale_table():
    # The feature scopes to the entrance intents; every other intent is 1.0.
    assert motion._entrance_stagger_scale("calm", "fade_in") == 1.0
    # Calm / measured moods loosen the separation; high-energy tightens it;
    # a neutral or unknown mood is exactly 1.0 (→ prop omitted).
    assert motion._entrance_stagger_scale("calm focus", "drop_in") == 1.3
    assert motion._entrance_stagger_scale("electric_fierce", "rise") == 0.65
    assert motion._entrance_stagger_scale("", "pop") == 1.0
    assert motion._entrance_stagger_scale("workmanlike", "drop_in") == 1.0


def test_compile_ts_keeps_byte_identical_defaults_and_adds_resolver():
    src = _compile_ts()
    # The historic fixed delays survive verbatim as the default config.
    assert "DEFAULT_STAGGER: StaggerConfig = { hero: 3, secondary: 6, result: 9, chip: 14 }" in src
    assert "export function resolveStagger(scale: number): StaggerConfig" in src
    # entranceChannels keeps its exported signature (source-contract pin) and now
    # defaults its stagger to the fixed config.
    assert "export function entranceChannels(" in src
    assert "stagger: StaggerConfig = DEFAULT_STAGGER" in src
    # Still frame-pure — no RNG / wall-clock introduced by the refactor.
    for bad in ("Math.random(", "Date.now(", "new Date("):
        assert bad not in src


def test_staggerscale_folds_into_story_cache_key_only_when_present():
    base = {"motionIntent": "drop_in", "mood": "calm"}
    scaled = {**base, "staggerScale": 1.3}
    h_plain = motion._content_hash({"card": base}, kind="story")
    h_scaled = motion._content_hash({"card": scaled}, kind="story")
    assert h_plain == motion._content_hash({"card": base}, kind="story")
    assert h_plain != h_scaled
    # The prop carries the change, so no composition-revision bump is needed.
    assert motion.STORY_COMPOSITION_REVISION == "3"


def test_card_to_props_attaches_staggerscale_only_when_active():
    card = {
        "achievement": {
            "swimmer_name": "Ada Vale",
            "event_name": "100m Freestyle",
            "result_time": "59.80",
            "type": "PB",
        },
        "meet_name": "Test Open",
    }
    # calm + drop_in → the looser stagger is attached.
    calm = motion._card_to_props(card, brief={"mood": "calm", "motion_intent": "drop_in"})
    assert calm["staggerScale"] == 1.3
    # A neutral mood → omitted, so the prop dict (and cache key) is byte-identical.
    neutral = motion._card_to_props(card, brief={"mood": "workmanlike", "motion_intent": "drop_in"})
    assert "staggerScale" not in neutral
    # calm but a non-entrance intent → omitted (only drop_in/rise/pop consume it).
    non_entrance = motion._card_to_props(card, brief={"mood": "calm", "motion_intent": "fade_in"})
    assert "staggerScale" not in non_entrance
