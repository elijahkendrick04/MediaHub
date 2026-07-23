"""text-fx-richer — a closed enum of opt-in, frame-pure, seeded ENTRANCE text
animators that compose the per-glyph reveal machinery.

Two halves, mirroring the rest of the motion suite (no Node runner in the tree —
same discipline as ``test_per_glyph_text`` / ``test_motion_range_selectors``):

* Python shaping — the master switch + deterministic seed gate is
  fold-only-when-present, so with ``MEDIAHUB_TEXT_FX`` off every card keeps a
  byte-identical prop dict / cache key. The animator only ever attaches on the
  SAME glyph gate that yields per-glyph mode, so a per-glyph animator never lands
  on a word-mode card, and the preset is a stable function of ``variation_seed``.
* TSX / TS source contract — the closed enum, the frame-pure fx helpers (no
  Math.random / Date.now / new Date), the AnimChannels identity defaults, and the
  KineticLine byte-identity guards actually exist. The held/terminal state is
  identity (blur 0 / tracking 0 / no residual transform) within GLYPH_BUDGET_SEC,
  so still<->motion parity holds by construction.
"""

from __future__ import annotations

from pathlib import Path

from mediahub.visual import motion

ROOT = Path(__file__).resolve().parent.parent
REMOTION_SRC = ROOT / "src" / "mediahub" / "remotion" / "src"
STORY_TSX = (REMOTION_SRC / "compositions" / "StoryCard.tsx").read_text()
COMPILE_TS = (REMOTION_SRC / "motion" / "compile.ts").read_text()

_ENUM = ("", "blur_reveal", "track_in", "wiggle_settle", "word_rise_blur")
_ACTIVE = ("blur_reveal", "track_in", "wiggle_settle", "word_rise_blur")


def _card(name: str = "Kinetic Person", event: str = "100m Free LC") -> dict:
    return {"achievement": {"swimmer_name": name, "event_name": event}}


# ---------------------------------------------------------------------------
# Python — master switch + deterministic seed gate (fold-only-when-present)
# ---------------------------------------------------------------------------


def test_textanimator_off_by_default_no_prop(monkeypatch):
    """With MEDIAHUB_TEXT_FX unset, no card ever carries a textAnimator prop —
    for the eligible intents and every other intent — so the default prop dict /
    cache key is byte-identical."""
    monkeypatch.delenv("MEDIAHUB_TEXT_FX", raising=False)
    for intent in ("kinetic_type", "cascade", "count_up", "fade_in", "parallax", ""):
        for seed in (0, 1, 2, 3, 5, 7):
            props = motion._card_to_props(
                _card(), variation_seed=seed, brief={"motion_intent": intent}
            )
            assert "textAnimator" not in props, (intent, seed)


def test_textanimator_gate_fires_only_when_env_on_and_type_intent(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_TEXT_FX", "1")
    # Eligible intents on the odd (glyph) seed gate get a token…
    for intent in ("kinetic_type", "cascade"):
        props = motion._card_to_props(
            _card(), variation_seed=1, brief={"motion_intent": intent}
        )
        assert props.get("textAnimator") in _ACTIVE, intent
        # …and the animator only ever attaches where perGlyph is guaranteed true.
        assert props.get("textGranularity") == "glyph", intent
    # Even (word) seed: the glyph gate is off, so no animator (never a per-glyph
    # animator on a word-mode card).
    for intent in ("kinetic_type", "cascade"):
        props = motion._card_to_props(
            _card(), variation_seed=2, brief={"motion_intent": intent}
        )
        assert "textAnimator" not in props, intent
    # Non-type intents never get a token even on the odd seed with the env on.
    for intent in ("count_up", "fade_in", "parallax", ""):
        props = motion._card_to_props(
            _card(), variation_seed=1, brief={"motion_intent": intent}
        )
        assert "textAnimator" not in props, intent or "<default>"


def test_textanimator_selection_is_stable_and_independent_of_granularity_bucket(
    monkeypatch,
):
    monkeypatch.setenv("MEDIAHUB_TEXT_FX", "1")
    # Deterministic bucket (seed // 2) % 4 over the four presets, distinct from
    # the (seed % 2) granularity gate — so the two gates are independent.
    expected = {
        1: "blur_reveal",
        3: "track_in",
        5: "wiggle_settle",
        7: "word_rise_blur",
        9: "blur_reveal",
    }
    for seed, tok in expected.items():
        props = motion._card_to_props(
            _card(), variation_seed=seed, brief={"motion_intent": "kinetic_type"}
        )
        assert props.get("textAnimator") == tok, seed
    # Pure function of the seed: stable across repeated calls.
    a = motion._card_to_props(
        _card(), variation_seed=3, brief={"motion_intent": "kinetic_type"}
    )
    b = motion._card_to_props(
        _card(), variation_seed=3, brief={"motion_intent": "kinetic_type"}
    )
    assert a.get("textAnimator") == b.get("textAnimator") == "track_in"


def test_text_fx_enabled_honest_env_parse(monkeypatch):
    for v in ("1", "true", "TRUE", "Yes", "on"):
        monkeypatch.setenv("MEDIAHUB_TEXT_FX", v)
        assert motion._text_fx_enabled() is True, v
    for v in ("", "0", "false", "off", "nope"):
        monkeypatch.setenv("MEDIAHUB_TEXT_FX", v)
        assert motion._text_fx_enabled() is False, v
    monkeypatch.delenv("MEDIAHUB_TEXT_FX", raising=False)
    assert motion._text_fx_enabled() is False


# ---------------------------------------------------------------------------
# Python — cache-key identity (off) / distinctness (on)
# ---------------------------------------------------------------------------


def test_cache_key_identity_when_off_and_distinct_when_on(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_TEXT_FX", raising=False)
    off_props = motion._card_to_props(
        _card(), variation_seed=1, brief={"motion_intent": "kinetic_type"}
    )
    assert "textAnimator" not in off_props
    off_key = motion._content_hash({"card": off_props}, kind="story")

    # Turning the feature on for the same card forks the key (a text-fx render
    # can never serve from a non-fx cache entry, and vice-versa).
    monkeypatch.setenv("MEDIAHUB_TEXT_FX", "1")
    on_props = motion._card_to_props(
        _card(), variation_seed=1, brief={"motion_intent": "kinetic_type"}
    )
    assert on_props.get("textAnimator") == "blur_reveal"
    on_key = motion._content_hash({"card": on_props}, kind="story")
    assert on_key != off_key

    # Distinct tokens key distinct entries.
    keys = set()
    for seed in (1, 3, 5, 7):
        p = motion._card_to_props(
            _card(), variation_seed=seed, brief={"motion_intent": "kinetic_type"}
        )
        keys.add(motion._content_hash({"card": p}, kind="story"))
    assert len(keys) == 4


def test_manifest_records_text_animator(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_TEXT_FX", raising=False)
    plain = motion._card_manifest_axes(
        motion._card_to_props(_card(), variation_seed=1)
    )
    assert plain["text_animator"] == ""
    monkeypatch.setenv("MEDIAHUB_TEXT_FX", "1")
    fx = motion._card_to_props(
        _card(), variation_seed=1, brief={"motion_intent": "kinetic_type"}
    )
    assert motion._card_manifest_axes(fx)["text_animator"] == "blur_reveal"


def test_text_fx_in_effect_toggle_allowlist():
    # Suppressible as a decorative A/B axis (entrance-only, terminal == still).
    assert "text_fx" in motion.EFFECT_TOGGLE_ALLOWLIST
    assert list(motion.EFFECT_TOGGLE_ALLOWLIST) == sorted(motion.EFFECT_TOGGLE_ALLOWLIST)
    assert motion._validate_effect_toggles(["text_fx"]) == ["text_fx"]


# ---------------------------------------------------------------------------
# TS source contract — frame-pure fx maths in compile.ts
# ---------------------------------------------------------------------------


def test_compile_ts_exports_frame_pure_text_fx():
    assert "export function textFxGlyphAt(" in COMPILE_TS
    assert "export function textFxTrackingDeltaEm(" in COMPILE_TS
    assert "export function textFxUnitFor(" in COMPILE_TS
    # Frame-pure: no wall-clock / randomness entropy in the render path.
    assert "Math.random(" not in COMPILE_TS
    assert "Date.now(" not in COMPILE_TS
    assert "new Date(" not in COMPILE_TS
    assert "performance.now(" not in COMPILE_TS
    # Reuses the reveal's clamped budget maths, so every animator resolves to
    # identity by GLYPH_BUDGET_SEC (APCA hold + still parity by construction).
    assert "GLYPH_BUDGET_SEC" in COMPILE_TS
    assert "if (env <= 0) {" in COMPILE_TS
    assert "return TEXT_FX_IDENTITY;" in COMPILE_TS
    # track_in tracking delta closes to 0 at the budget (terminal == baked).
    assert "return MAX_TRACK_EM * (1 - p);" in COMPILE_TS


def test_cardschema_textanimator_is_closed_enum():
    # Exactly the five members, defaulting to "" (OFF). A closed enum + Python as
    # the sole trusted producer — no free operator string reaches the switch.
    assert (
        'z\n    .enum(["", "blur_reveal", "track_in", "wiggle_settle", "word_rise_blur"])\n'
        "    .default(\"\")" in STORY_TSX
    )


def test_animchannels_identity_fx_in_base_and_static():
    # The channel bundle carries the grouping unit + fx function + tracking delta.
    assert "fxUnit: \"\" | \"glyph\" | \"word\" | \"line\";" in STORY_TSX
    assert "glyphFx: (index: number, total: number) => TextFx;" in STORY_TSX
    assert "trackingDeltaEm: number;" in STORY_TSX
    # base + static both set the identity fx, so every existing intent is
    # byte-identical unless an animator is active.
    assert STORY_TSX.count("glyphFx: identityFx,") == 2
    assert STORY_TSX.count("fxUnit: \"\",") == 2
    assert "const identityFx = (): TextFx => ({ blur: 0, dx: 0, dy: 0, rotate: 0 });" in STORY_TSX


def test_withtextfx_reference_unchanged_when_off():
    # animProgram gains a trailing animator param and a withTextFx wrapper that
    # returns the SAME channel object when no animator is active (byte-identical).
    assert "animator: string = \"\"," in STORY_TSX
    assert "const withTextFx = (ch: AnimChannels): AnimChannels => {" in STORY_TSX
    assert "if (!animator) {\n      return ch;\n    }" in STORY_TSX
    # Suppressible as a review-only A/B axis. true-motion-blur hoisted the animator
    # expression into a captured `mbAnimator` (so the sampler can recompute the same
    # channels at sub-frames), but the off("text_fx") suppression is identical.
    assert 'const mbAnimator = off("text_fx") ? "" : card.textAnimator || "";' in STORY_TSX
    # …and it is the animator argument threaded into every animProgram call.
    assert "mbAnimator," in STORY_TSX


def test_kineticline_guards_identity_style():
    # The fx only enters the style object under a non-zero guard, so the OFF/held
    # DOM is key-for-key identical to the pre-fx render.
    assert "fx && fxActive(fx)" in STORY_TSX
    assert "wordFx && fxActive(wordFx)" in STORY_TSX
    # blur filter merged only when blur > 0.
    assert "...(fx.blur > 0 ? { filter: `blur(${fx.blur}px)` } : {})" in STORY_TSX
    # track_in em delta folded into BOTH branches' outer div, guarded (delta 0 =>
    # same style reference).
    assert STORY_TSX.count("withLineTracking(style, anim.trackingDeltaEm)") == 2
    assert "function withLineTracking(" in STORY_TSX
    assert "if (deltaEm === 0) {\n    return style;\n  }" in STORY_TSX
    # The pre-fx glyph reveal line is preserved verbatim (word-mode DOM intact).
    assert "const a = anim.glyphAt(base + ci, lineTotal);" in STORY_TSX
    # The six per-glyph call sites are untouched.
    assert STORY_TSX.count('perGlyph={ctx.card.textGranularity === "glyph"}') == 6
