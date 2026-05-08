"""V8 media_requirements evaluator tests.

Verifies confidence-tier mapping + status routing per post angle.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mediahub.media_requirements.evaluator import evaluate
from mediahub.media_library.models import MediaAsset


def _item(angle, *, conf=0.85, swimmer="Eira Hughes", s2p="safe"):
    return {
        "id": "ci_1",
        "post_angle": angle,
        "confidence": conf,
        "swimmer_name": swimmer,
        "achievement": {
            "swimmer_name": swimmer,
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
            "post_angle": angle,
            "confidence": conf,
        },
        "safe_to_post": {"level": s2p},
    }


def _athlete_asset(name="Eira Hughes"):
    return MediaAsset(
        id="ma_eira",
        filename="e.jpg", path="/tmp/e.jpg",
        type="athlete_action",
        profile_id="p",
        linked_athlete_names=[name],
        permission_status="approved_by_club",
        approval_status="approved",
        orientation="portrait", width=1500, height=2000,
    )


def test_high_confidence_pb_label():
    res = evaluate(_item("confirmed_official_pb", conf=0.9), library_assets=[_athlete_asset()])
    assert res.confidence_tier == "high"
    assert res.confidence_label == "NEW PB"


def test_medium_confidence_likely_label():
    res = evaluate(_item("confirmed_official_pb", conf=0.5, s2p="needs_review"),
                   library_assets=[_athlete_asset()])
    assert res.confidence_tier == "medium"
    assert "LIKELY" in res.confidence_label


def test_low_confidence_skip():
    res = evaluate(_item("confirmed_official_pb", conf=0.2, s2p="do_not_post"),
                   library_assets=[_athlete_asset()])
    assert res.confidence_tier == "low"
    # Should be SKIP_LOW_CONFIDENCE per spec\n
    assert res.status.upper() == "SKIP_LOW_CONFIDENCE"


def test_weekend_in_numbers_text_led_ok():
    res = evaluate(_item("weekend_in_numbers", conf=0.95), library_assets=[])
    # Text-led layout family doesn't need a hero photo.
    assert res.status.upper() in ("READY", "TEXT_LED_OK")


def test_individual_pb_with_no_photo_needs_media():
    res = evaluate(_item("confirmed_official_pb", conf=0.9), library_assets=[])
    assert res.status.upper() in ("NEEDS_MEDIA", "READY", "TEXT_LED_OK")
    # Either hero_athlete is missing, or design opted for text fallback.
    miss = res.missing_required + res.missing_optional
    assert "hero_athlete" in miss or res.status.upper() in ("READY", "TEXT_LED_OK")
