"""Comprehensive pinning tests for the G1.1 graphic-generator sprint families.

G1.1 adds **eight** new v2 archetype families — each shipping a still layout
(`layouts/v2/<name>.html`), authoring notes (`<name>.notes.md`), and a matching
motion scene (`remotion/.../sprint/scenes/<name>.tsx`) for still↔motion parity.

These tests guard the whole surface for the eight, in one place:

  * registry: all eight are auto-scanned into the Tier-A library;
  * still convention: `{{BASE_CSS}}`, role tokens only (no hex), allow-listed
    placeholders, the `{{ACCENT_DECORATION}}` style-pack slot, and an
    optional-highlight collapse so an empty slot never dangles;
  * overflow safety: the hero/result text is scaled to its box *and* allowed to
    wrap, and the layout assembles cleanly at BOTH 1080×1350 and 1080×1920;
  * notes → director catalog: a substantive `director_note` and a distinct
    `archetype_summary` are extracted for each;
  * motion parity: each ships a `sprint/scenes/<name>.tsx` that registers
    `{ archetype: "<name>", Scene }`, so its motion render matches its still
    (the parity test counts it as covered);
  * gallery (UI 1.10): each is categorised, in the display order, titled, and
    given a bespoke, theme-driven, distinct schematic.

The eight are also structurally distinct from one another (unique root class
prefixes) — G1.1's whole point is lifting archetype variety, not recolouring.
"""

from __future__ import annotations

import re

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import generate as gen_brief
from mediahub.graphic_renderer import archetypes
from mediahub.media_requirements.evaluator import EvaluationResult
from mediahub.quality import variant_metrics as VM
from mediahub.visual import motion
from mediahub.web import template_gallery as G

# The eight families G1.1 adds, with the root CSS class prefix each still uses.
G1_1_FAMILIES: dict[str, str] = {
    "timeline_progression": "tl",
    "radial_competition_ring": "rr",
    "vertical_stat_tower": "vt",
    "three_card_editorial_grid": "tg",
    "staggered_diagonal_offset": "so",
    "full_height_portrait_split": "ps",
    "ribbon_banner": "rb",
    "contact_sheet": "cs",
}
NAMES = sorted(G1_1_FAMILIES)

_ALLOWED_PLACEHOLDERS = {
    "ATHLETE_FULL_NAME",
    "ATHLETE_FIRST_NAME",
    "ATHLETE_SURNAME_DISPLAY",
    "EVENT_NAME",
    "RESULT_VALUE",
    "ACHIEVEMENT_LABEL",
    "MEET_NAME",
    "CLUB_FULL",
    "HERO_STAT",
    "LOGO_BLOCK",
    "ATHLETE_IMG_BLOCK",
    "ACCENT_DECORATION",
    "SPONSOR_BLOCK",
    "WIDTH",
    "HEIGHT",
    "BASE_CSS",
}

_SCENES_DIR = motion.REMOTION_DIR / "src" / "compositions" / "sprint" / "scenes"


def _html(name: str) -> str:
    return (archetypes.V2_DIR / f"{name}.html").read_text(encoding="utf-8")


def _scene_src(name: str) -> str:
    return (_SCENES_DIR / f"{name}.tsx").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


def test_all_eight_families_registered():
    lib = archetypes.list_archetypes()
    missing = [n for n in NAMES if n not in lib]
    assert not missing, f"G1.1 families not auto-scanned into the library: {missing}"


def test_library_grew_by_the_eight_families():
    # The eight lift the library well past the pre-sprint floor of 20 (their own
    # eight + the originals; sibling sprint items add more concurrently). A
    # floor guard catches a family silently dropping out of the scan without
    # being brittle to the rest of the G1/R1 sprint landing alongside.
    lib = archetypes.list_archetypes()
    assert len(lib) >= 28
    assert len(lib) == len(set(lib))  # no duplicate archetype ids
    assert set(NAMES) <= set(lib)  # all eight present


# --------------------------------------------------------------------------- #
# Still-layout convention (PAR-7)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", NAMES)
def test_still_follows_slot_convention(name):
    raw = _html(name)
    assert "{{BASE_CSS}}" in raw
    assert re.search(r"#[0-9a-fA-F]{3,6}\b", raw) is None, f"{name}: hex colour literal"
    assert "var(--mh-" in raw
    for ph in set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", raw)):
        assert ph in _ALLOWED_PLACEHOLDERS, f"{name}: unknown placeholder {ph}"


@pytest.mark.parametrize("name", NAMES)
def test_still_carries_style_pack_slot(name):
    # Every v2 archetype must expose the {{ACCENT_DECORATION}} style-pack slot.
    assert "{{ACCENT_DECORATION}}" in _html(name), f"{name}: missing style-pack slot"


@pytest.mark.parametrize("name", NAMES)
def test_still_consumes_autofit_vars_and_wraps(name):
    raw = _html(name)
    # Hero/result text is scaled to its box via the injected autofit vars …
    assert "var(--mh-fit-surname-px" in raw, f"{name}: surname not fitted"
    assert "var(--mh-fit-result-px" in raw, f"{name}: result not fitted"
    # … and allowed to wrap so a long/space-less token can never clip.
    assert raw.count("overflow-wrap: anywhere") >= 2, f"{name}: hero text can clip"


@pytest.mark.parametrize("name", NAMES)
def test_still_collapses_an_empty_optional_slot(name):
    # Each family hides an optional slot when its value is empty — via :empty or
    # a :has(... :empty) collapse — so an unfilled slot never dangles a label.
    raw = _html(name)
    assert ":empty" in raw, f"{name}: no optional-slot collapse"


# --------------------------------------------------------------------------- #
# Notes → director catalog + gallery summary
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", NAMES)
def test_notes_feed_a_substantive_director_note(name):
    notes = archetypes.V2_DIR / f"{name}.notes.md"
    assert notes.exists(), f"{name}: missing .notes.md"
    assert len(notes.read_text(encoding="utf-8").strip()) > 200
    note = archetypes.director_note(name)
    assert len(note) >= 60, f"{name}: director note too thin"
    assert "**" not in note and "`" not in note, f"{name}: markdown leaked into prompt line"


@pytest.mark.parametrize("name", NAMES)
def test_summary_is_present_and_distinct_from_when(name):
    s = archetypes.archetype_summary(name)
    assert s, f"{name}: empty summary"
    assert s != archetypes.director_note(name)
    assert "*" not in s and "`" not in s and "#" not in s


# --------------------------------------------------------------------------- #
# Motion scene parity (sprint registry)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", NAMES)
def test_motion_scene_file_registers_the_archetype(name):
    path = _SCENES_DIR / f"{name}.tsx"
    assert path.exists(), f"{name}: no sprint/scenes/{name}.tsx for motion parity"
    src = _scene_src(name)
    # The drop-in contract: default-export { archetype: "<name>", Scene }.
    assert f'archetype: "{name}"' in src, f"{name}: scene does not register its archetype id"
    assert "Scene" in src and "export default" in src


def test_every_g1_1_archetype_has_a_motion_scene_mapping():
    # The same contract test_motion_v2_parity enforces library-wide, asserted
    # explicitly for the eight: each id appears in the motion source corpus.
    comp = motion.REMOTION_DIR / "src" / "compositions"
    corpus = [(comp / "StoryCard.tsx").read_text()]
    sprint = comp / "sprint"
    corpus.extend(p.read_text() for p in sorted(sprint.rglob("*")) if p.suffix in {".ts", ".tsx"})
    blob = "\n".join(corpus)
    for name in NAMES:
        assert f'"{name}"' in blob, f"{name}: no motion scene mapping"


# --------------------------------------------------------------------------- #
# Gallery (UI 1.10) registration
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", NAMES)
def test_gallery_registers_each_family(name):
    known = {cid for cid, _, _ in G.CATEGORIES}
    assert name in G.CATEGORY_BY_ARCHETYPE, f"{name}: no category mapping"
    assert G.CATEGORY_BY_ARCHETYPE[name] in known
    assert name in G._DISPLAY_ORDER, f"{name}: missing from display order"
    assert G.humanize(name) and G.humanize(name) != name  # a friendly title


@pytest.mark.parametrize("name", NAMES)
def test_gallery_schematic_is_bespoke_and_theme_driven(name):
    assert name in G._SVG and G._SVG[name] != G._GENERIC_SVG, f"{name}: not a bespoke schematic"
    inner = G._SVG[name]
    assert not re.search(r"#[0-9a-fA-F]{3,6}", inner), f"{name}: hardcoded hex in schematic"
    assert "fill=" not in inner and "style=" not in inner, f"{name}: inline paint in schematic"


def test_gallery_schematics_distinct_across_the_eight():
    svgs = {n: G._SVG[n] for n in NAMES}
    assert len(set(svgs.values())) == len(svgs), "two G1.1 families share a schematic"


# --------------------------------------------------------------------------- #
# Structural distinctness — the point of G1.1
# --------------------------------------------------------------------------- #


def test_each_family_uses_a_distinct_root_class():
    prefixes = list(G1_1_FAMILIES.values())
    assert len(set(prefixes)) == len(prefixes), "two families reuse a root class prefix"
    for name, prefix in G1_1_FAMILIES.items():
        assert f'class="{prefix}"' in _html(name), f"{name}: root class .{prefix} not used"


def test_eight_families_lift_pack_diversity():
    pack = [archetypes.pick_archetype(s) for s in range(12)]
    assert VM.archetype_diversity(pack) >= 0.9


# --------------------------------------------------------------------------- #
# Full HTML assembly through the real render path (Playwright stubbed) — at
# BOTH feed-portrait and story sizes, so the overflow wiring is exercised.
# --------------------------------------------------------------------------- #


def _brand():
    return BrandKit(
        profile_id="g11",
        display_name="Test Swim Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="TSC",
    )


def _eval():
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


def _brief_for(name: str, *, swimmer="Eira Hughes", result="2:08.41"):
    item = {
        "id": "ci-1",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": swimmer,
            "event_name": "200m Freestyle",
            "result_time": result,
            "raw_facts": {"drop_seconds": 2.4},
        },
    }
    b = gen_brief(
        item,
        _eval(),
        _brand(),
        profile_id="g11",
        meet_name="Manchester Open",
        venue_name="Manchester Aquatics Centre",
        variation_seed=0,
    )
    b.layout_template = name
    return b


def _assemble(monkeypatch, tmp_path, brief, size):
    import mediahub.graphic_renderer.render as R

    captured: dict = {}

    def _fake_png(html, output_path, size):  # noqa: ARG001 - signature match
        captured["html"] = html
        from pathlib import Path

        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    R.render_brief(brief, output_dir=tmp_path, size=size)
    return captured["html"]


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("size", [(1080, 1350), (1080, 1920)])
def test_assembles_clean_html_at_both_sizes(monkeypatch, tmp_path, name, size):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    html = _assemble(monkeypatch, tmp_path, _brief_for(name), size)
    # no raw placeholders survive
    assert "{{" not in html and "}}" not in html
    # the brand role tokens + autofit vars were injected
    assert ":root{" in html
    for token in (
        "--mh-primary:",
        "--mh-accent:",
        "--mh-surface:",
        "--mh-fit-surname-px:",
        "--mh-fit-result-px:",
        "--mh-photo-pos:",
    ):
        assert token in html, f"{name} @ {size}: missing {token}"
    # real content made it in
    assert "Manchester Open" in html


@pytest.mark.parametrize("name", NAMES)
def test_long_surname_autofits_down_not_overflow(monkeypatch, tmp_path, name):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")

    def _surname_px(html: str) -> int:
        m = re.search(r"--mh-fit-surname-px:(\d+)px", html)
        assert m, "surname autofit var not found"
        return int(m.group(1))

    short = _assemble(monkeypatch, tmp_path, _brief_for(name, swimmer="Mo Li"), (1080, 1350))
    long = _assemble(
        monkeypatch,
        tmp_path,
        _brief_for(name, swimmer="Aleksandra Vandersloot-Chamberlain"),
        (1080, 1350),
    )
    assert _surname_px(long) < _surname_px(short), f"{name}: long surname did not autofit down"
