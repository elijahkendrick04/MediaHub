"""Tests for the G1.19 grayscale / mono accessibility render hook.

Covers the whole contract of ``graphic_renderer/sprint_hooks/mono_mode.py``:

* it is auto-discovered by the sprint-hook registry at its declared ``ORDER``;
* it is a strict **opt-in** — every non-mono brief renders byte-identically, so
  the colour pipeline is untouched (the seam's headline guarantee);
* each opt-in channel fires (``render_mode`` / ``background_style`` token, a mono
  phrase in ``mood`` / ``style_pack``, and the operator ``MEDIAHUB_MONO_MODE`` env);
* the **role remap** is deterministic, neutral-grey (so a global grayscale pass
  leaves it invariant), polarity-aware, and — the headline accessibility claim —
  clears the engine's own APCA legibility gate (``quality.compliance.check_roles``)
  on every scored pair for a spread of real palettes, *including* low-contrast
  pairs that naive desaturation would collapse into mud;
* the global ``filter: grayscale(1)`` is injected once (idempotent), folds the
  optional ``MEDIAHUB_MONO_CONTRAST`` trim, and ``var(--mh-*)`` usages / non-colour
  tokens (photo-pos, autofit sizes) are never touched;
* the hook never raises, and it flows through the real ``render_brief`` path
  (Playwright stubbed) exactly like every other render-time transform.
"""

from __future__ import annotations

import re

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import generate as gen_brief
from mediahub.graphic_renderer.sprint_hooks import (
    RenderHookCtx,
    _discover,
    apply_render_hooks,
)
from mediahub.graphic_renderer.sprint_hooks import mono_mode as MM
from mediahub.media_requirements.evaluator import EvaluationResult
from mediahub.quality.compliance import LC_LARGE, check_roles, is_legible

# A representative painted card head: the v2 ``:root{}`` role block the renderer
# injects, plus a body that *uses* the tokens (declarations vs ``var()`` usages).
_ROOT_BLOCK = (
    ":root{--mh-primary:#0A2540;--mh-secondary:#06182B;--mh-accent:#FFD700;"
    "--mh-surface:#05121F;--mh-on-primary:#FFFFFF;--mh-on-surface:#FFFFFF;"
    "--mh-outline:rgba(255,255,255,0.20);--mh-fit-surname-px:96px;"
    "--mh-photo-pos:center 28%;}"
)
_SAMPLE_HTML = (
    "<!DOCTYPE html><html lang=en><head><meta charset=utf-8>"
    f"<style>{_ROOT_BLOCK}</style></head><body>"
    '<div class="bn" style="background:var(--mh-primary);color:var(--mh-on-primary)">'
    '<span style="color:var(--mh-accent)">9:41.2</span>'
    '<em style="background:var(--mh-accent);color:var(--mh-primary)">PB</em>'
    "</div></body></html>"
)

_COLOUR_ROLES = (
    "--mh-primary",
    "--mh-secondary",
    "--mh-accent",
    "--mh-surface",
    "--mh-on-primary",
    "--mh-on-surface",
    "--mh-outline",
)


def _ctx(brief) -> RenderHookCtx:
    return RenderHookCtx(
        brief=brief,
        width=1080,
        height=1350,
        family="big_number_dominant",
        format_name="story",
        is_v2=True,
    )


class _Brief:
    """Minimal stand-in for a CreativeBrief — only the fields the hook reads."""

    def __init__(self, **kw):
        self.render_mode = kw.get("render_mode", "")
        self.background_style = kw.get("background_style", "water")
        self.mood = kw.get("mood", "")
        self.style_pack = kw.get("style_pack", "")


def _root_of(html: str) -> str:
    m = re.search(r":root\{[^}]*\}", html)
    assert m, "no :root block in html"
    return m.group(0)


def _roles_from(html: str) -> dict:
    """Parse the painted ``--mh-*`` hex roles back out of the html :root block."""
    root = _root_of(html)
    roles = {}
    for name in _COLOUR_ROLES:
        m = re.search(rf"(?<![\w-]){re.escape(name)}\s*:\s*([^;}}]+)", root)
        if m:
            roles[name] = m.group(1).strip()
    return roles


# ---------------------------------------------------------------------------
# Registry / contract
# ---------------------------------------------------------------------------


def test_hook_is_discovered_at_declared_order():
    found = [(order, name) for order, name, _ in _discover()]
    assert (MM.ORDER, "mono_mode") in found
    assert MM.ORDER == 90  # runs late, after colour-emitting hooks
    assert callable(MM.apply)


def test_apply_is_pure_string_to_string():
    out = MM.apply(_SAMPLE_HTML, _ctx(_Brief(render_mode="mono")))
    assert isinstance(out, str)


# ---------------------------------------------------------------------------
# Opt-out: the byte-identical guarantee
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "brief",
    [
        _Brief(),
        _Brief(background_style="water"),
        _Brief(background_style="gradient_mesh"),
        _Brief(mood="hype electric"),
        _Brief(style_pack="aurora_grain"),
        None,
    ],
)
def test_opt_out_is_byte_identical(brief):
    assert MM.apply(_SAMPLE_HTML, _ctx(brief)) == _SAMPLE_HTML


def test_registry_noop_when_not_requested(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_MONO_MODE", raising=False)
    # The whole registry over the sample is a no-op for a non-mono brief, even
    # with the module installed — proves the seam stays byte-identical.
    assert apply_render_hooks(_SAMPLE_HTML, _ctx(_Brief())) == _SAMPLE_HTML


def test_word_boundary_avoids_false_positive_mood(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_MONO_MODE", raising=False)
    # "monumental" contains "mono" only as a substring — must NOT trigger.
    assert not MM.mono_requested(_Brief(mood="a monumental swim"))
    assert MM.apply(_SAMPLE_HTML, _ctx(_Brief(mood="a monumental swim"))) == _SAMPLE_HTML


@pytest.mark.parametrize(
    "phrase",
    ["monochrome editorial", "clean black and white look", "b/w press", "grey scale"],
)
def test_free_text_phrase_positives(monkeypatch, phrase):
    monkeypatch.delenv("MEDIAHUB_MONO_MODE", raising=False)
    assert MM.mono_requested(_Brief(mood=phrase))


@pytest.mark.parametrize(
    "phrase", ["a monumental swim", "below average", "fresh brew", "chromatic harmony"]
)
def test_free_text_phrase_negatives(monkeypatch, phrase):
    monkeypatch.delenv("MEDIAHUB_MONO_MODE", raising=False)
    assert not MM.mono_requested(_Brief(mood=phrase))


def test_underscored_style_pack_id_triggers(monkeypatch):
    # style-pack ids are underscore-delimited; "mono_press" must still match.
    monkeypatch.delenv("MEDIAHUB_MONO_MODE", raising=False)
    assert MM.mono_requested(_Brief(style_pack="mono_press"))
    assert not MM.mono_requested(_Brief(style_pack="aurora_grain"))


# ---------------------------------------------------------------------------
# Opt-in: every channel
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "brief",
    [
        _Brief(render_mode="mono"),
        _Brief(render_mode="Monochrome"),
        _Brief(render_mode="grayscale"),
        _Brief(render_mode="greyscale"),
        _Brief(render_mode="b&w"),
        _Brief(render_mode="black and white"),
        _Brief(background_style="mono"),
        _Brief(mood="monochrome editorial"),
        _Brief(mood="clean black and white look"),
        _Brief(style_pack="mono_press"),
    ],
)
def test_opt_in_channels_trigger(monkeypatch, brief):
    monkeypatch.delenv("MEDIAHUB_MONO_MODE", raising=False)
    assert MM.mono_requested(brief)
    out = MM.apply(_SAMPLE_HTML, _ctx(brief))
    assert out != _SAMPLE_HTML
    assert "filter:grayscale(1)" in out


def test_env_flag_triggers_globally(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_MONO_MODE", "1")
    # Even a plainly non-mono brief renders mono when the operator flag is on.
    assert MM.mono_requested(_Brief(background_style="water"))
    out = MM.apply(_SAMPLE_HTML, _ctx(_Brief(background_style="water")))
    assert "filter:grayscale(1)" in out
    for falsy in ("0", "false", "off", ""):
        monkeypatch.setenv("MEDIAHUB_MONO_MODE", falsy)
        assert not MM.mono_requested(_Brief())


def test_dict_brief_supported():
    # The opt-in reader tolerates a dict-shaped brief, not only a dataclass.
    assert MM.mono_requested({"render_mode": "mono"})
    assert not MM.mono_requested({"background_style": "water"})


# ---------------------------------------------------------------------------
# Role remap — the accessibility core
# ---------------------------------------------------------------------------

_PALETTES = {
    "navy_gold_dark": ("#0A2540", "#05121F"),
    "crimson_dark": ("#B11226", "#7A0C1A"),
    "light_ground": ("#F4F4F4", "#DADADA"),
    "low_contrast_pair": ("#556070", "#454F5C"),  # collapses under naive grayscale
    "mid_grey": ("#808080", "#606060"),
    "teal_dark": ("#0E5BFF", "#101820"),
}


@pytest.mark.parametrize("name", list(_PALETTES))
def test_mono_ramp_clears_apca_gate(name):
    ground, surface = _PALETTES[name]
    roles = MM.mono_role_vars(ground, surface)
    report = check_roles(roles)
    assert report.passes, f"{name}: APCA failures {report.failures}"
    assert min(report.pairs.values()) >= LC_LARGE
    # both directions of the accent/ground relationship read (text AND chip)
    assert is_legible(roles["--mh-accent"], roles["--mh-primary"])
    assert is_legible(roles["--mh-primary"], roles["--mh-accent"])


@pytest.mark.parametrize("name", list(_PALETTES))
def test_mono_ramp_is_neutral_grey(name):
    # Every hex role must be a true neutral (R==G==B), so the page-level
    # grayscale(1) pass leaves the remapped tokens exactly invariant.
    roles = MM.mono_role_vars(*_PALETTES[name])
    for key, val in roles.items():
        if val.startswith("#"):
            r, g, b = MM._hex_to_rgb(val)
            assert r == g == b, f"{name} {key}={val} is not neutral grey"


def test_polarity_dark_vs_light_ground():
    dark = MM.mono_role_vars("#0A2540", "#05121F")
    light = MM.mono_role_vars("#F4F4F4", "#E2E2E2")
    # dark ground -> light ink + white accent; light ground -> dark ink + black accent
    assert dark["--mh-accent"] == "#FFFFFF" and dark["--mh-on-primary"] == "#F4F4F4"
    assert light["--mh-accent"] == "#000000" and light["--mh-on-primary"] == "#161616"


def test_surface_stays_distinct_from_ground():
    roles = MM.mono_role_vars("#0A2540", "#05121F")
    assert roles["--mh-primary"] != roles["--mh-surface"]
    # original surface is darker than ground, so the mono surface stays darker too
    assert MM._relative_luminance(roles["--mh-surface"]) < MM._relative_luminance(
        roles["--mh-primary"]
    )


# ---------------------------------------------------------------------------
# HTML transform details
# ---------------------------------------------------------------------------


def test_remaps_declarations_not_var_usages():
    out = MM.apply(_SAMPLE_HTML, _ctx(_Brief(render_mode="mono")))
    # the painted role declarations are now mono...
    roles = _roles_from(out)
    assert roles["--mh-accent"] == "#FFFFFF"
    assert roles["--mh-primary"] in ("#1A1A1A", "#0B0B0B")
    assert roles["--mh-outline"] == "rgba(255,255,255,0.30)"
    # ...but the original brand hexes are gone and var() usages are intact
    assert "#FFD700" not in out and "#0A2540" not in out
    assert out.count("var(--mh-accent)") == _SAMPLE_HTML.count("var(--mh-accent)")
    assert out.count("var(--mh-primary)") == _SAMPLE_HTML.count("var(--mh-primary)")


def test_non_colour_tokens_untouched():
    out = MM.apply(_SAMPLE_HTML, _ctx(_Brief(render_mode="mono")))
    assert "--mh-fit-surname-px:96px" in out
    assert "--mh-photo-pos:center 28%" in out


def test_global_desaturation_injected_once_and_idempotent():
    once = MM.apply(_SAMPLE_HTML, _ctx(_Brief(render_mode="mono")))
    assert once.count('id="mh-mono-mode"') == 1
    assert "filter:grayscale(1)" in once
    assert "</head>" in once and once.index("mh-mono-mode") < once.index("</head>")
    # re-running must not double-inject and must not change the result
    twice = MM.apply(once, _ctx(_Brief(render_mode="mono")))
    assert twice.count('id="mh-mono-mode"') == 1
    assert twice == once


def test_contrast_env_folds_into_filter(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_MONO_CONTRAST", "1.2")
    out = MM.apply(_SAMPLE_HTML, _ctx(_Brief(render_mode="mono")))
    assert "filter:grayscale(1) contrast(1.2)" in out
    # out-of-range / junk values clamp or fall back to the plain grayscale(1)
    monkeypatch.setenv("MEDIAHUB_MONO_CONTRAST", "not-a-number")
    out2 = MM.apply(_SAMPLE_HTML, _ctx(_Brief(render_mode="mono")))
    assert "filter:grayscale(1)" in out2 and "contrast(" not in out2


def test_determinism():
    a = MM.apply(_SAMPLE_HTML, _ctx(_Brief(render_mode="mono")))
    b = MM.apply(_SAMPLE_HTML, _ctx(_Brief(render_mode="mono")))
    assert a == b


def test_v1_card_without_role_tokens_still_desaturates():
    # A v1 .canvas card has no --mh-* tokens; the role remap is a no-op but the
    # global grayscale pass still makes it B/W.
    v1 = "<html><head><style>.canvas{background:#0A2540}</style></head><body>x</body></html>"
    out = MM.apply(v1, _ctx(_Brief(render_mode="mono")))
    assert "filter:grayscale(1)" in out
    assert ":root{--mh-mono:1;}" in out


def test_hook_never_raises_on_garbage():
    for junk in ("", "<html></html>", "no tags at all", "{:root malformed"):
        assert isinstance(MM.apply(junk, _ctx(_Brief(render_mode="mono"))), str)
    # a brief that explodes on attribute access is swallowed, not propagated
    class Boom:
        def __getattr__(self, _):
            raise RuntimeError("boom")

    assert MM.apply(_SAMPLE_HTML, _ctx(Boom())) == _SAMPLE_HTML


# ---------------------------------------------------------------------------
# End-to-end through the real render_brief path (Playwright stubbed)
# ---------------------------------------------------------------------------


def _brand():
    return BrandKit(
        profile_id="t",
        display_name="Test Swim Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="TSC",
    )


def _ev():
    return EvaluationResult(
        content_item_id="ci-1",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout="individual_hero",
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier="high",
        confidence_label="NEW PB",
        explain="ok",
    )


def _brief(**over):
    item = {
        "id": "ci-1",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
        },
    }
    b = gen_brief(
        item,
        _ev(),
        _brand(),
        profile_id="t",
        meet_name="Manchester Open",
        venue_name="Manchester Aquatics Centre",
        variation_seed=0,
    )
    b.layout_template = "big_number_dominant"  # force a v2 archetype
    for k, v in over.items():
        setattr(b, k, v)
    return b


def _render_capture(monkeypatch, tmp_path, brief):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    import mediahub.graphic_renderer.render as R

    captured = {}

    def _fake_png(html, output_path, size):
        captured["html"] = html
        from pathlib import Path

        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    R.render_brief(brief, output_dir=tmp_path, size=(1080, 1350))
    return captured["html"]


def test_end_to_end_mono_brief_renders_grayscale(monkeypatch, tmp_path):
    monkeypatch.delenv("MEDIAHUB_MONO_MODE", raising=False)
    html = _render_capture(monkeypatch, tmp_path, _brief(background_style="mono"))
    assert "filter:grayscale(1)" in html
    assert 'id="mh-mono-mode"' in html
    roles = _roles_from(html)
    # the brand blue (#0E5BFF) is gone; the painted roles are mono + legible
    assert "#0E5BFF" not in html
    report = check_roles(roles)
    assert report.passes, report.failures
    assert "{{" not in html  # template fully assembled


def test_end_to_end_normal_brief_unaffected(monkeypatch, tmp_path):
    monkeypatch.delenv("MEDIAHUB_MONO_MODE", raising=False)
    html = _render_capture(monkeypatch, tmp_path, _brief())  # default water bg
    # mono never fired: no injected style, and the brand colour survives intact
    assert "mh-mono-mode" not in html
    assert "--mh-primary:#0E5BFF" in html
