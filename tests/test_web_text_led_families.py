"""Guard: web.py's no-photo gates use the generator's text-led family set.

PR 257 made ``creative_brief.generator._TEXT_LED_FAMILIES`` the single source
of truth, but web.py's two no-photo gates carried their own hardcoded copies —
a new text-led family added to the constant was silently excluded from the
gates. This pins the de-duplication (grep-guard style, like
tests/test_craft_skills.py): no hardcoded copy may creep back in.
"""

from __future__ import annotations

from pathlib import Path

WEB_PY = Path(__file__).resolve().parents[1] / "src" / "mediahub" / "web" / "web.py"


def test_no_photo_gates_import_the_generator_constant():
    src = WEB_PY.read_text(encoding="utf-8")
    # Both gates import the canonical set instead of hardcoding the families.
    assert src.count("from mediahub.creative_brief.generator import _TEXT_LED_FAMILIES") >= 2
    assert src.count("sorted(_TEXT_LED_FAMILIES)") >= 2


def test_no_hardcoded_text_led_family_list_left():
    src = WEB_PY.read_text(encoding="utf-8")
    assert '["text_led_recap", "weekend_numbers", "stat_line"]' not in src


def test_generator_constant_still_covers_the_known_families():
    from mediahub.creative_brief.generator import _TEXT_LED_FAMILIES

    assert {"text_led_recap", "weekend_numbers", "stat_line"} <= set(_TEXT_LED_FAMILIES)
