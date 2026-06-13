"""Craft skills — structural guards (2026-06-12).

`motion-craft` and `graphic-craft` are MediaHub's own adaptation of HeyGen's
HyperFrames skills (Apache-2.0, vendored at vendor/hyperframes-skills-main/),
rewritten for the Remotion + Playwright stack. These tests guard the three
things that would silently rot:

1. the skills stay structurally valid (frontmatter name == folder, every
   referenced reference file exists), so agents keep loading them;
2. no Google-Fonts CDN reference creeps into any skill file — skills feed
   agents that write renderer code, so a CDN link here would propagate to
   the surfaces `test_self_hosted_fonts.py` guards;
3. the vendored upstream keeps its Apache LICENSE alongside the copied
   files (the licence condition for carrying the adaptation at all).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = _ROOT / ".claude" / "skills"
CRAFT_SKILLS = ("motion-craft", "graphic-craft")
VENDORED = _ROOT / "vendor" / "hyperframes-skills-main"


@pytest.mark.parametrize("skill", CRAFT_SKILLS)
class TestCraftSkillStructure:
    def test_skill_md_exists(self, skill):
        assert (SKILLS_DIR / skill / "SKILL.md").is_file()

    def test_frontmatter_name_matches_folder(self, skill):
        text = (SKILLS_DIR / skill / "SKILL.md").read_text()
        match = re.search(r"^name:\s*(\S+)\s*$", text, re.MULTILINE)
        assert match, f"{skill}/SKILL.md has no frontmatter name"
        assert match.group(1) == skill

    def test_referenced_reference_files_exist(self, skill):
        skill_dir = SKILLS_DIR / skill
        text = (skill_dir / "SKILL.md").read_text()
        referenced = set(re.findall(r"references/[\w-]+\.md", text))
        assert referenced, f"{skill}/SKILL.md references no reference files"
        for rel in sorted(referenced):
            assert (skill_dir / rel).is_file(), f"{skill}: {rel} referenced but missing"

    def test_no_font_cdn_references(self, skill):
        for path in sorted((SKILLS_DIR / skill).rglob("*.md")):
            text = path.read_text()
            for banned in ("fonts.googleapis.com", "fonts.gstatic.com", "@fontsource"):
                assert banned not in text, f"{path.name} references {banned}"


class TestVendoredHyperframes:
    def test_upstream_license_retained(self):
        license_text = (VENDORED / "LICENSE").read_text()
        assert "Apache License" in license_text

    def test_vendored_core_skill_present(self):
        assert (VENDORED / "hyperframes" / "SKILL.md").is_file()
