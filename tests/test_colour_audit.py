"""Tests for G1.18 — per-card colour-accessibility audit + colourblind sim.

``mediahub.quality.colour_audit`` layers an APCA+WCAG report and a
deuteranopia/protanopia/tritanopia simulation over the exact ``--mh-*`` roles a
card paints. These tests pin three things that matter:

  1. it stays byte-for-byte consistent with the ``quality.compliance`` ship gate
     (legibility verdict + score) — the audit can never disagree with what
     actually gates a card;
  2. the colourblind logic catches a *real* failure (a distinction that
     collapses under a deficiency) without false-flagging a deliberate tonal
     ground/surface step;
  3. it is deterministic, tolerant of partial input, and serialises cleanly.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest

from mediahub.quality import (
    ColourAudit,
    audit_brief,
    audit_roles,
    compliance,
    simulate_roles,
    swatches_svg,
)
from mediahub.quality.colour_audit import (
    CONTRAST_PAIRS,
    CVD_LABELS,
    CVD_TYPES,
    DE_THRESHOLD,
    apca_band,
    wcag_band,
)

# A legible navy + gold card (the canonical good case the compliance gate uses).
NAVY_GOLD = {
    "--mh-primary": "#0A2540",
    "--mh-secondary": "#F2C14E",
    "--mh-accent": "#F2C14E",
    "--mh-surface": "#05121F",
    "--mh-on-primary": "#FFFFFF",
    "--mh-on-surface": "#FFFFFF",
    "--mh-outline": "rgba(255,255,255,0.20)",  # non-hex, must pass through
}

# A dark-red card whose accent collapses to black — the illegible case.
BAD_RED = {
    "--mh-primary": "#A30D2D",
    "--mh-surface": "#5A0A18",
    "--mh-accent": "#000000",
    "--mh-on-primary": "#FFFFFF",
    "--mh-on-surface": "#FFFFFF",
}


# --------------------------------------------------------------------------- #
# Public API + structure
# --------------------------------------------------------------------------- #


class TestApiSurface:
    def test_exports_are_importable_from_package(self):
        import mediahub.quality as q

        for name in (
            "ColourAudit",
            "audit_brief",
            "audit_roles",
            "simulate_roles",
            "swatches_svg",
        ):
            assert name in q.__all__ and hasattr(q, name), name

    def test_cvd_types_are_the_three_dichromacies(self):
        assert set(CVD_TYPES) == {"deutan", "protan", "tritan"}
        assert set(CVD_LABELS) == set(CVD_TYPES)

    def test_contrast_pairs_cover_the_canonical_card_roles(self):
        names = {p.name for p in CONTRAST_PAIRS}
        assert names == {
            "name_on_ground",
            "text_on_surface",
            "accent_on_ground",
            "chip_text_on_accent",
        }


# --------------------------------------------------------------------------- #
# Band classifiers
# --------------------------------------------------------------------------- #


class TestBands:
    @pytest.mark.parametrize(
        "lc,band",
        [
            (95, "preferred"),
            (90, "preferred"),
            (80, "silver"),
            (75, "silver"),
            (65, "fluent"),
            (60, "fluent"),
            (50, "bronze"),
            (45, "bronze"),
            (35, "ui"),
            (30, "ui"),
            (10, "fail"),
            (0, "fail"),
        ],
    )
    def test_apca_band_boundaries(self, lc, band):
        assert apca_band(lc) == band

    def test_apca_band_uses_magnitude_not_sign(self):
        # Light-on-dark text is a negative Lc; the band must match its size.
        assert apca_band(-90) == apca_band(90) == "preferred"
        assert apca_band(-45) == "bronze"

    @pytest.mark.parametrize(
        "ratio,band",
        [
            (21.0, "AAA"),
            (7.0, "AAA"),
            (5.0, "AA"),
            (4.5, "AA"),
            (3.5, "AA (large)"),
            (3.0, "AA (large)"),
            (2.0, "fail"),
            (1.0, "fail"),
        ],
    )
    def test_wcag_band_boundaries(self, ratio, band):
        assert wcag_band(ratio) == band


# --------------------------------------------------------------------------- #
# simulate_roles — the colourblind preview palette
# --------------------------------------------------------------------------- #


class TestSimulateRoles:
    @pytest.mark.parametrize("cvd", CVD_TYPES)
    def test_passes_non_hex_tokens_through_unchanged(self, cvd):
        out = simulate_roles(NAVY_GOLD, cvd)
        assert out["--mh-outline"] == "rgba(255,255,255,0.20)"

    @pytest.mark.parametrize("cvd", CVD_TYPES)
    def test_every_hex_role_becomes_valid_hex(self, cvd):
        out = simulate_roles(NAVY_GOLD, cvd)
        for role, val in out.items():
            if role == "--mh-outline":
                continue
            assert val.startswith("#") and len(val) == 7

    def test_each_deficiency_yields_a_distinct_palette(self):
        d = simulate_roles(NAVY_GOLD, "deutan")
        p = simulate_roles(NAVY_GOLD, "protan")
        t = simulate_roles(NAVY_GOLD, "tritan")
        # The gold accent is perceived differently across the three.
        assert len({d["--mh-accent"], p["--mh-accent"], t["--mh-accent"]}) >= 2

    def test_is_deterministic(self):
        assert simulate_roles(NAVY_GOLD, "deutan") == simulate_roles(NAVY_GOLD, "deutan")


# --------------------------------------------------------------------------- #
# audit_roles — full-colour vision
# --------------------------------------------------------------------------- #


class TestAuditFullVision:
    def test_legible_card_passes_with_populated_pairs(self):
        a = audit_roles(NAVY_GOLD)
        assert a.passes
        assert 0.0 < a.score <= 1.0
        assert len(a.pairs) == 4
        for p in a.pairs:
            assert p.apca_band and p.wcag_band
            assert p.wcag2_ratio >= 1.0
            assert p.passes

    def test_illegible_card_fails_with_warnings(self):
        a = audit_roles(BAD_RED)
        assert not a.passes
        assert a.score < 1.0
        assert any("low contrast" in w for w in a.warnings)

    def test_apca_sign_encodes_polarity(self):
        # White ink on a dark ground is light-on-dark → negative Lc.
        pair = next(p for p in audit_roles(NAVY_GOLD).pairs if p.name == "name_on_ground")
        assert pair.apca_lc < 0

    def test_tolerates_empty_and_partial_role_sets(self):
        empty = audit_roles({})
        assert empty.passes and empty.score == 1.0 and empty.pairs == []
        # Only the ground/ink pair resolvable → exactly one scored pair.
        partial = audit_roles({"--mh-primary": "#0A2540", "--mh-on-primary": "#FFFFFF"})
        assert {p.name for p in partial.pairs} == {"name_on_ground"}


class TestComplianceEquivalence:
    """The audit's full-vision verdict must equal the ship gate's, always."""

    @pytest.mark.parametrize(
        "roles",
        [
            NAVY_GOLD,
            BAD_RED,
            {  # green + gold
                "--mh-primary": "#1B7A3D",
                "--mh-surface": "#0E3D1F",
                "--mh-accent": "#FFD24A",
                "--mh-on-primary": "#FFFFFF",
                "--mh-on-surface": "#FFFFFF",
            },
            {  # purple, accent collapses
                "--mh-primary": "#6A1B9A",
                "--mh-surface": "#3A0E54",
                "--mh-accent": "#000000",
                "--mh-on-primary": "#FFFFFF",
                "--mh-on-surface": "#FFFFFF",
            },
        ],
    )
    def test_passes_and_score_match_compliance_gate(self, roles):
        audit = audit_roles(roles)
        gate = compliance.check_roles(roles)
        assert audit.passes == gate.passes
        assert audit.score == gate.score


# --------------------------------------------------------------------------- #
# audit_roles — colourblind simulation
# --------------------------------------------------------------------------- #


class TestCVDSimulation:
    def test_one_preview_per_deficiency(self):
        a = audit_roles(NAVY_GOLD)
        assert [p.cvd for p in a.cvd] == list(CVD_TYPES)
        for prev in a.cvd:
            assert prev.label == CVD_LABELS[prev.cvd]
            assert prev.simulated_roles  # the preview palette is present
            assert prev.pairs  # text pairs re-scored

    def test_high_luminance_contrast_survives_all_deficiencies(self):
        # White on navy is a luminance contrast — CVD preserves luminance, so it
        # must stay legible for every viewer.
        a = audit_roles(NAVY_GOLD)
        assert a.cvd_safe
        assert a.accessible
        for prev in a.cvd:
            assert prev.legible

    def test_tonal_ground_surface_step_is_not_flagged_as_a_collision(self):
        # primary/surface are the same hue a lightness apart (a design step),
        # close in full colour — never a colour-blindness defect.
        a = audit_roles(NAVY_GOLD)
        for prev in a.cvd:
            for col in prev.collisions:
                if {col.role_a, col.role_b} == {"--mh-primary", "--mh-surface"}:
                    assert col.distinguishable

    def test_real_collapse_is_caught(self):
        # Red and green read as different colours in full vision but collapse
        # for a red-green deficiency — the audit must flag it.
        rg = {
            "--mh-primary": "#1B7A3D",  # green ground
            "--mh-secondary": "#C0392B",
            "--mh-accent": "#C0392B",  # red accent
            "--mh-surface": "#0E3D1F",
            "--mh-on-primary": "#FFFFFF",
            "--mh-on-surface": "#FFFFFF",
        }
        a = audit_roles(rg)
        assert not a.cvd_safe
        collapses = [
            col
            for prev in a.cvd
            for col in prev.collisions
            if {col.role_a, col.role_b} == {"--mh-accent", "--mh-primary"}
            and not col.distinguishable
        ]
        assert collapses, "red accent on green ground should collapse under a CVD"
        c = collapses[0]
        assert c.delta_e_normal >= DE_THRESHOLD  # distinct in full colour
        assert c.delta_e_2000 < DE_THRESHOLD  # merged under the deficiency

    def test_apca_shift_recorded_for_cvd_pairs(self):
        a = audit_roles(NAVY_GOLD)
        for prev in a.cvd:
            for cp in prev.pairs:
                assert isinstance(cp.apca_shift, float)

    def test_cvd_types_arg_narrows_the_report(self):
        a = audit_roles(NAVY_GOLD, cvd_types=("deutan",))
        assert [p.cvd for p in a.cvd] == ["deutan"]


# --------------------------------------------------------------------------- #
# audit_brief — resolves the exact ship colours then audits
# --------------------------------------------------------------------------- #


class TestAuditBrief:
    def test_matches_audit_of_resolved_roles(self):
        from mediahub.graphic_renderer.render import resolved_role_vars_for_brief

        brief = SimpleNamespace(
            palette={"primary": "#0A2540", "secondary": "#F2C14E", "accent": "#F2C14E"},
            text_layers={},
        )
        assert (
            audit_brief(brief).to_detail()
            == audit_roles(resolved_role_vars_for_brief(brief)).to_detail()
        )

    def test_medal_tier_accent_is_audited(self):
        # A 1st-place brief paints the gold medal accent; the audit scores it.
        gold = SimpleNamespace(
            palette={"primary": "#0A2540", "secondary": "#444444", "accent": None},
            text_layers={"place": "1"},
        )
        a = audit_brief(gold)
        assert a.roles["--mh-accent"].upper() != "#444444"  # tinted, not the dull secondary
        assert isinstance(a, ColourAudit)


# --------------------------------------------------------------------------- #
# Serialisation + explainability
# --------------------------------------------------------------------------- #


class TestSerialisation:
    def test_to_summary_shape(self):
        s = audit_roles(NAVY_GOLD).to_summary()
        assert s["passes"] is True
        assert s["cvd_safe"] is True
        assert s["accessible"] is True
        assert s["n_pairs"] == 4
        assert s["n_pair_failures"] == 0
        assert set(s["cvd"]) == set(CVD_TYPES)

    def test_to_detail_is_json_safe(self):
        import json

        detail = audit_roles(NAVY_GOLD).to_detail()
        # Must round-trip through JSON (all dataclasses already asdict-ed).
        assert json.loads(json.dumps(detail))["passes"] is True
        assert len(detail["pairs"]) == 4
        assert len(detail["cvd"]) == 3

    def test_explain_reflects_state(self):
        assert "accessible" in audit_roles(NAVY_GOLD).explain()
        assert "low contrast" in audit_roles(BAD_RED).explain()


# --------------------------------------------------------------------------- #
# swatches_svg — the visual preview artifact
# --------------------------------------------------------------------------- #


class TestSwatchesSvg:
    def test_is_well_formed_xml(self):
        svg = swatches_svg(NAVY_GOLD)
        root = ET.fromstring(svg)  # raises on malformed markup
        assert root.tag.endswith("svg")

    def test_contains_a_row_for_full_colour_and_each_deficiency(self):
        svg = swatches_svg(NAVY_GOLD)
        assert "Full colour" in svg
        for label in CVD_LABELS.values():
            # The label text is XML-escaped; the leading word survives intact.
            assert label.split(" ")[0] in svg

    def test_includes_simulated_hex_values(self):
        svg = swatches_svg(NAVY_GOLD)
        # The full-colour ground hex appears verbatim.
        assert "#0A2540" in svg
        # And a deutan-simulated accent (different from the brand gold).
        deut_accent = simulate_roles(NAVY_GOLD, "deutan")["--mh-accent"]
        assert deut_accent in svg

    def test_is_deterministic(self):
        assert swatches_svg(NAVY_GOLD) == swatches_svg(NAVY_GOLD)

    def test_handles_partial_palette_without_error(self):
        svg = swatches_svg({"--mh-primary": "#0A2540"})
        ET.fromstring(svg)


# --------------------------------------------------------------------------- #
# Determinism (whole audit)
# --------------------------------------------------------------------------- #


def test_audit_is_fully_deterministic():
    assert audit_roles(NAVY_GOLD).to_detail() == audit_roles(NAVY_GOLD).to_detail()
