"""Stage J3 — docs/THEMING.md reference-doc contract.

The doc is the canonical reference for the Adaptive Theming
Engine. These tests pin the structural invariants:
  - documented section headers exist
  - every tier-2 role token in theme-base.css is documented
  - the seven seed variables are all named
  - the four content surfaces and their scheme mappings appear
  - the J1 feature flag is documented
  - at least 6 academic citations appear
  - word count is substantial (≥ 1,500)
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def doc_text() -> str:
    path = Path(__file__).resolve().parents[1] / "docs" / "THEMING.md"
    assert path.is_file(), f"missing {path}"
    return path.read_text(encoding="utf-8")


class TestStructure:
    def test_file_exists(self, doc_text):
        assert len(doc_text) > 1000

    @pytest.mark.parametrize("heading", [
        "# MediaHub Theming Reference",
        "## 1. What is the Adaptive Theming Engine?",
        "## 2. Architecture at a glance",
        "## 3. The role-token vocabulary",
        "## 4. The seven seed variables",
        "## 5. The cascade order",
        "## 6. The four consumer surfaces",
        "## 7. Override patterns",
        "## 8. Feature flags",
        "## 12. Academic citations",
    ])
    def test_section_heading_present(self, doc_text, heading):
        assert heading in doc_text, f"missing heading: {heading!r}"

    def test_word_count_substantial(self, doc_text):
        words = len(doc_text.split())
        assert words >= 1500, (
            f"THEMING.md is only {words} words; aim for ≥ 1,500"
        )


class TestRoleTokenCoverage:
    """Every tier-2 role token that ships in theme-base.css must
    appear in the doc's role-token table."""

    @pytest.fixture(scope="class")
    def declared_roles(self):
        from mediahub.web.theme_tokens import THEME_BASE_CSS
        # Find every --mh-* declaration that's a tier-2 role (i.e. NOT
        # a primitive --mh-prim-* nor a seed --mh-*-seed).
        names: set[str] = set()
        for m in re.finditer(r"(--mh-[a-z][a-z0-9-]*)\s*:", THEME_BASE_CSS):
            name = m.group(1)
            if name.startswith("--mh-prim-"):
                continue
            if name.endswith("-seed"):
                continue
            names.add(name)
        return names

    def test_every_role_documented(self, doc_text, declared_roles):
        missing = [n for n in sorted(declared_roles) if n not in doc_text]
        assert not missing, (
            f"role tokens declared but not documented: {missing}\n"
            f"add them to section 3 of docs/THEMING.md"
        )


class TestSeedVariables:
    """The seven seed variables documented in section 4."""

    @pytest.mark.parametrize("seed", [
        "--mh-brand-seed",
        "--mh-tertiary-seed",
        "--mh-neutral-seed",
        "--mh-error-seed",
        "--mh-success-seed",
        "--mh-warning-seed",
        "--mh-info-seed",
    ])
    def test_seed_named_in_doc(self, doc_text, seed):
        assert seed in doc_text, f"missing seed variable: {seed}"


class TestConsumerSurfaces:
    """The four content surfaces (web/motion/email/static) and
    their scheme mappings appear in section 6."""

    def test_all_four_surfaces(self, doc_text):
        # Pull section 6 specifically (between ## 6 and ## 7).
        section_6 = re.search(
            r"## 6\. .*?(?=\n## 7\. )", doc_text, re.DOTALL,
        )
        assert section_6, "section 6 missing"
        block = section_6.group(0)
        for surface in ("Web", "Motion", "Email", "Static"):
            assert surface in block, (
                f"surface {surface!r} not documented in section 6"
            )

    def test_scheme_mappings(self, doc_text):
        # Documented convention: motion uses dark, email + static use light
        block = doc_text
        assert "dark" in block.lower()
        assert "light" in block.lower()


class TestFeatureFlagDocumented:
    def test_adaptive_theme_flag_named(self, doc_text):
        assert "MEDIAHUB_ADAPTIVE_THEME" in doc_text, (
            "Stage J1 feature flag not documented in section 8"
        )

    def test_flag_default_documented(self, doc_text):
        # The doc must mention the default-enabled behaviour
        # plus the off-list.
        section_8 = re.search(
            r"## 8\. .*?(?=\n## 9\. )", doc_text, re.DOTALL,
        )
        assert section_8
        block = section_8.group(0)
        assert "default" in block.lower() or "enabled" in block.lower()
        # The off-list members should appear
        assert any(v in block.lower() for v in ("0", "false", "off"))


class TestAcademicCitations:
    """Section 12 must reference the algorithm-grounding papers
    by name. At least 6 citations are required (the engine's
    six biggest pillars)."""

    @pytest.fixture(scope="class")
    def citations_block(self, doc_text):
        m = re.search(
            r"## 12\. Academic citations.*?(?=\n## 13\.)",
            doc_text, re.DOTALL,
        )
        assert m, "section 12 (citations) missing"
        return m.group(0)

    @pytest.mark.parametrize("needle,reason", [
        ("Ottosson",              "OKLCH paper"),
        ("Sharma",                "CIEDE2000 paper"),
        ("Somers",                "APCA reference"),
        ("Material 3",            "Material 3 / HCT"),
        ("Machado",               "CVD simulation paper"),
        ("Cohen-Or",              "harmonic templates paper"),
    ])
    def test_citation_present(self, citations_block, needle, reason):
        assert needle in citations_block, (
            f"missing citation for {reason}: {needle!r}"
        )

    def test_minimum_six_citations(self, citations_block):
        # Crude count: each bullet starts with "- **"
        bullets = re.findall(r"^\s*-\s+\*\*", citations_block, re.MULTILINE)
        assert len(bullets) >= 6, (
            f"only {len(bullets)} citation bullets, need ≥ 6"
        )


class TestStageIndexPresent:
    """The doc closes with an index of the per-stage plans."""

    def test_stage_index_section(self, doc_text):
        assert "## 13. Phase 1.6 stage index" in doc_text or \
               "Stage index" in doc_text, (
            "stage index missing — readers can't drill into per-stage plans"
        )

    @pytest.mark.parametrize("plan", [
        "stage_a_token_foundation_plan.md",
        "stage_b_colour_science_plan.md",
        "stage_c_css_architecture_plan.md",
        "stage_e_looks_right_cascade_plan.md",
        "stage_f_logo_intelligence_plan.md",
        "stage_g_single_source_of_truth_plan.md",
        "stage_h_explainability_plan.md",
        "stage_i_test_coverage_plan.md",
        "stage_j_cutover_polish_plan.md",
    ])
    def test_each_plan_referenced(self, doc_text, plan):
        assert plan in doc_text, f"stage plan not referenced: {plan}"
