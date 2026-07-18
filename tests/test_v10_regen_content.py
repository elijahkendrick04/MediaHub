"""V10 regenerate + graphic-content fixes — pin the new contracts.

Covers the five user-facing defects fixed together:
  1. Variant distinctness: the batch AI director call dedupes
     same-direction responses; random fallbacks avoid prior signatures.
  2. Stub graphics no longer render "<SPONSOR> RECAP": each stub flow
     sets its own second headline line, and the renderer honours an
     explicitly-empty line 2 instead of defaulting to "RECAP".
  3. The text-led stat strip shows real caller-supplied stats (or real
     fields) and never fabricates filler ("3 VOICES" / "WEEK WINDOW").
  4. Bullets/captions are display-cleaned: emoji stripped, word-boundary
     truncation with an ellipsis instead of mid-word [:80] chops.
  5. The achievement ribbon always fits the canvas (shrink-then-truncate)
     and the medal_card layout drops the redundant "★ GOLD" pill.
"""
from __future__ import annotations

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.ai_director import _parse_strict_json_array
from mediahub.creative_brief.generator import VariationProfile, generate
from mediahub.graphic_renderer.render import (
    _ellipsize,
    _fill_medal_card,
    _fill_text_led_recap,
    _fit_ribbon_label,
)
from mediahub.web.web import _display_clean, _soft_trim, _stub_card_to_graphic_item


def _brand():
    return BrandKit(
        profile_id="v10test",
        display_name="V10 Test SC",
        primary_colour="#0A2540",
        secondary_colour="#101820",
        accent_colour="#D4FF3A",
    )


def _brief_with_layers(layers: dict):
    """Run generate() with caller-supplied graphic_text → brief."""
    item = {
        "id": "stub",
        "post_angle": "recap_mention",
        "achievement": {"post_angle": "recap_mention"},
        "meet_name": layers.get("kicker", ""),
        "graphic_text": layers,
    }
    profile = VariationProfile(
        layout_family="text_led_recap",
        palette_role_index=0,
        background_style="clean",
        accent_style="minimal",
        typography_pair="anton-inter",
        composition="center",
        photo_treatment="no-photo",
        decoration_strength=0.4,
    )
    return generate(
        item,
        None,
        _brand(),
        variation_profile=profile,
        allowed_families=["text_led_recap"],
    )


# ---------------------------------------------------------------------------
# 1. ai_director batch parsing + dedup
# ---------------------------------------------------------------------------


def test_parse_strict_json_array_peels_fences_and_prose():
    raw = 'Sure! ```json\n[{"layout_family": "medal_card"}, {"layout_family": "story_card"}]\n```'
    arr = _parse_strict_json_array(raw)
    assert arr is not None and len(arr) == 2
    assert arr[0]["layout_family"] == "medal_card"


def test_parse_strict_json_array_rejects_non_arrays():
    assert _parse_strict_json_array('{"layout_family": "medal_card"}') is None
    assert _parse_strict_json_array("") is None


# ---------------------------------------------------------------------------
# 2 + 3. stub graphic content: per-type line 2, real stats, no RECAP default
# ---------------------------------------------------------------------------


def test_sponsor_stub_does_not_become_a_recap():
    item = _stub_card_to_graphic_item(
        "sponsor_post",
        {"caption": "Thank you to Acme Sports for their support."},
        {"sponsor_name": "Acme Sports", "meet_name": "County Championships"},
    )
    gt = item["graphic_text"]
    joined = (gt["headline_line1"] + " " + gt["headline_line2"]).upper()
    assert "RECAP" not in joined
    assert gt["headline_line2"] == "THANK YOU"
    assert gt["stats"]["sponsor"] == "Acme Sports"
    assert gt["stats"]["event"] == "County Championships"


def test_each_stub_type_sets_its_own_line2():
    cases = {
        "weekend_preview": "PREVIEW",
        "session_update": "UPDATE",
    }
    for stub_type, expected in cases.items():
        item = _stub_card_to_graphic_item(stub_type, {"caption": "See you Saturday."}, {})
        assert item["graphic_text"]["headline_line2"] == expected, stub_type


def test_generate_honours_explicit_empty_line2():
    brief = _brief_with_layers(
        {
            "headline_line1": "ACME SPORTS",
            "headline_line2": "",
            "bullets": ["A line"],
            "primary_hook": "SPONSOR",
            "stats": {"sponsor": "Acme Sports"},
        }
    )
    assert brief.text_layers["headline_line1"] == "ACME SPORTS"
    assert brief.text_layers["headline_line2"] == ""
    assert brief.text_layers["stat_sponsor"] == "Acme Sports"
    repl = _fill_text_led_recap(brief, 1080, 1350, {})
    assert repl["HEADLINE_LINE2"] == ""
    assert "RECAP" not in repl["HEADLINE_LINE1"]


def test_text_led_recap_keeps_legacy_default_when_no_headline():
    brief = _brief_with_layers({"bullets": ["A line"]})
    brief.text_layers.pop("headline_line1", None)
    brief.text_layers.pop("headline_line2", None)
    repl = _fill_text_led_recap(brief, 1080, 1350, {})
    assert repl["HEADLINE_LINE1"] == "WEEKEND"
    assert repl["HEADLINE_LINE2"] == "RECAP"


def test_stat_strip_never_fabricates_filler():
    brief = _brief_with_layers(
        {"headline_line1": "HELLO", "headline_line2": "", "bullets": ["x"]}
    )
    # No stats, no result/event/meet → strip must be omitted, not faked.
    for k in list(brief.text_layers):
        if k.startswith("stat_") or k in ("result_value", "event_name", "meet_name"):
            brief.text_layers[k] = ""
    brief.text_layers["club_full"] = ""
    brief.text_layers["club_short"] = ""
    repl = _fill_text_led_recap(brief, 1080, 1350, {})
    assert "VOICES" not in repl["RECAP_STATS_BLOCK"]
    assert "WINDOW" not in repl["RECAP_STATS_BLOCK"]
    assert "HIGHLIGHTS" not in repl["RECAP_STATS_BLOCK"]


def test_no_bullets_does_not_invent_results():
    brief = _brief_with_layers({"headline_line1": "HELLO", "headline_line2": ""})
    brief.text_layers.pop("bullets", None)
    brief.text_layers["athlete_full_name"] = ""
    repl = _fill_text_led_recap(brief, 1080, 1350, {})
    assert "Multiple medals" not in repl["BULLETS_HTML"]
    assert "Personal bests across the squad" not in repl["BULLETS_HTML"]


# ---------------------------------------------------------------------------
# 4. display cleaning
# ---------------------------------------------------------------------------


def test_display_clean_strips_emoji():
    assert _display_clean("Huge win! \U0001F389 So proud ✨") == "Huge win! So proud"


def test_soft_trim_breaks_at_word_boundary():
    text = "Huge congratulations to Sam Jones for smashing the club record in the 200 Free today"
    out = _soft_trim(text, 80)
    assert len(out) <= 81
    assert out.endswith("…")
    assert not out[:-1].endswith(" ")
    # No mid-word chop: the fragment before the ellipsis is a whole word.
    assert out[:-1].rsplit(" ", 1)[-1] in text.split()


def test_stub_bullets_are_clean_display_copy():
    item = _stub_card_to_graphic_item(
        "free_text",
        {
            "caption": (
                "What a night! \U0001F525 Sam Jones absolutely smashed the two hundred "
                "metre freestyle club record with an incredible swim that nobody "
                "in the building will forget for a very long time."
            )
        },
        {},
    )
    for b in item["graphic_text"]["bullets"]:
        assert "\U0001F525" not in b
        assert len(b) <= 81


# ---------------------------------------------------------------------------
# 5. ribbon fit + medal badge dedup
# ---------------------------------------------------------------------------


def test_fit_ribbon_label_shrinks_then_truncates():
    label, px = _fit_ribbon_label("BREASTSTROKE DOMINANCE FOREVER MORE", 44, 1080)
    base_budget = 1080 * 0.55 - 56
    assert px <= 44
    assert len(label) * 0.52 * px <= base_budget + 1
    short, spx = _fit_ribbon_label("PB ALERT", 44, 1080)
    assert short == "PB ALERT" and spx == 44


def test_ellipsize_word_boundary():
    assert _ellipsize("County Championships June", 18).endswith("…")
    assert "Championshi" not in _ellipsize("County Championships June", 18)


def test_medal_card_drops_redundant_gold_pill():
    brief = _brief_with_layers(
        {"headline_line1": "X", "headline_line2": "", "primary_hook": "GOLDEN SWIM"}
    )
    brief.text_layers["place"] = "1"
    brief.text_layers["achievement_label"] = "GOLDEN BREASTSTROKE"
    repl = _fill_medal_card(brief, 1080, 1350, {"MEDAL_BADGE_BLOCK": "<div>★ GOLD</div>"})
    assert repl["MEDAL_BADGE_BLOCK"] == ""
    assert repl["MEDAL_TEXT"] == "GOLD"


# ---------------------------------------------------------------------------
# 6. variant job store survives multi-worker gunicorn (disk-backed)
# ---------------------------------------------------------------------------


def test_variant_job_store_roundtrips_via_disk(tmp_path, monkeypatch):
    """Jobs persist as files so a poll landing on ANOTHER gunicorn worker
    (docker-entrypoint.sh runs --workers 2) still finds the job. The in-memory dict
    this replaces 404'd half the polls with job_not_found."""
    from mediahub.web import web as web_mod

    monkeypatch.setattr(web_mod, "RUNS_DIR", tmp_path)
    job_id = "a" * 32
    job = {
        "id": job_id,
        "status": "running",
        "variants": [],
        "total": 3,
        "done": 0,
        "error": "",
        "created_at": 0.0,
        "owner_pid": "",
    }
    web_mod._variant_job_save(job)
    loaded = web_mod._variant_job_load(job_id)
    assert loaded is not None
    assert loaded["status"] == "running"
    assert loaded["updated_at"] > 0
    # Malformed / unknown ids stay not-found (and never touch the fs).
    assert web_mod._variant_job_load("nope") is None
    assert web_mod._variant_job_load("b" * 32) is None
    # GC removes expired files.
    monkeypatch.setattr(web_mod, "_VARIANT_JOB_TTL_S", -1.0)
    web_mod._variant_jobs_gc()
    assert web_mod._variant_job_load(job_id) is None
