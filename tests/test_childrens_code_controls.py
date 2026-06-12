"""Children's Code content controls (compliance/childrens-code).

Pins: name initialisation, age suppression, photo exclusion, pipeline-level
transformation, the LLM-boundary backstop, internal-fields preservation
(consent matching + erasure still work on transformed cards), and the
high-privacy defaults for new organisations.
"""

from __future__ import annotations

import json

import pytest


def _profile(**flags):
    from mediahub.web.club_profile import ClubProfile

    p = ClubProfile(profile_id="clubx", display_name="X")
    for k, v in flags.items():
        setattr(p, k, v)
    return p


# ------------------------------------------------------------- unit rules


def test_initialise_name():
    from mediahub.compliance.child_policy import initialise_name

    assert initialise_name("Eira Hughes") == "Eira H."
    assert initialise_name("Eira Mair Hughes") == "Eira H."
    assert initialise_name("Mononym") == "Mononym"
    assert initialise_name("") == ""


def test_surname_initialisation_keeps_internal_full_name():
    from mediahub.compliance.child_policy import apply_to_achievement

    ach = {
        "swimmer_name": "Eira Hughes",
        "age": 14,
        "headline": "Eira Hughes set a PB",
        "raw_facts": {"time": "57.10"},
    }
    out = apply_to_achievement(_profile(child_surname_initial=True), ach)
    assert out["swimmer_name"] == "Eira H."
    assert out["headline"] == "Eira H. set a PB"
    assert out["raw_facts"]["full_name"] == "Eira Hughes"  # internal — for gates/erasure


def test_age_suppression_keeps_internal_age():
    from mediahub.compliance.child_policy import apply_to_achievement

    ach = {"swimmer_name": "Eira Hughes", "age": 14, "age_group": "13-14", "raw_facts": {}}
    out = apply_to_achievement(_profile(child_suppress_age=True), ach)
    assert "age" not in out and "age_group" not in out
    assert out["raw_facts"]["age"] == 14  # safeguarding/consent gates still see it


def test_adults_and_unknown_age_untransformed():
    from mediahub.compliance.child_policy import apply_to_achievement

    profile = _profile(child_surname_initial=True, child_suppress_age=True)
    adult = {"swimmer_name": "Sam Adult", "age": 25}
    assert apply_to_achievement(profile, dict(adult))["swimmer_name"] == "Sam Adult"
    unknown = {"swimmer_name": "Mystery Swimmer"}
    assert apply_to_achievement(profile, dict(unknown))["swimmer_name"] == "Mystery Swimmer"


def test_policy_off_is_a_no_op():
    from mediahub.compliance.child_policy import apply_to_achievement

    ach = {"swimmer_name": "Eira Hughes", "age": 14}
    out = apply_to_achievement(_profile(), ach)
    assert out["swimmer_name"] == "Eira Hughes"
    assert out["age"] == 14


def test_photo_exclusion_treats_unknown_age_as_minor():
    from mediahub.compliance.child_policy import exclude_athlete_photos_for_item

    profile = _profile(child_exclude_photos=True)
    assert exclude_athlete_photos_for_item(profile, {"achievement": {"age": 14}}) is True
    assert exclude_athlete_photos_for_item(profile, {"achievement": {}}) is True  # fail-safe
    assert exclude_athlete_photos_for_item(profile, {"achievement": {"age": 30}}) is False
    assert exclude_athlete_photos_for_item(_profile(), {"achievement": {"age": 14}}) is False


# --------------------------------------------------- consent/erasure parity


def test_consent_gate_matches_transformed_card_via_full_name(tmp_path, monkeypatch):
    """An opted-out child must stay blocked AFTER the identity transform."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.compliance.child_policy import apply_to_achievement
    from mediahub.compliance.consent import ConsentRegistry
    from mediahub.compliance.gate import consent_block_reason_for_card
    from mediahub.web.club_profile import save_profile

    profile = _profile(child_surname_initial=True)
    save_profile(profile)
    ConsentRegistry("clubx").record(athlete_name="Eira Hughes", status="refused")

    ach = {"swimmer_name": "Eira Hughes", "age": 14, "raw_facts": {}}
    apply_to_achievement(profile, ach)
    assert ach["swimmer_name"] == "Eira H."
    reason = consent_block_reason_for_card("clubx", {"achievement": ach})
    assert reason is not None and "opted out" in reason


def test_erasure_reaches_transformed_cards(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    from mediahub.compliance.dsr import erase_athlete
    from mediahub.web.club_profile import save_profile

    save_profile(_profile())
    runs = tmp_path / "runs_v4"
    runs.mkdir(parents=True)
    run = {
        "run_id": "runT",
        "profile_id": "clubx",
        "cards": [],
        "recognition_report": {
            "ranked_achievements": [
                {
                    "achievement": {
                        "swim_id": "c1",
                        "swimmer_name": "Eira H.",
                        "raw_facts": {"full_name": "Eira Hughes", "age": 14},
                    }
                }
            ]
        },
    }
    (runs / "runT.json").write_text(json.dumps(run))
    erase_athlete("clubx", "Eira Hughes")
    after = json.loads((runs / "runT.json").read_text())
    assert "hughes" not in json.dumps(after).lower()


# -------------------------------------------------------------- pipeline


def test_apply_to_ranked_transforms_report():
    from mediahub.compliance.child_policy import apply_to_ranked

    ranked = [
        {"achievement": {"swimmer_name": "Eira Hughes", "age": 13, "raw_facts": {}}},
        {"achievement": {"swimmer_name": "Sam Adult", "age": 25, "raw_facts": {}}},
    ]
    apply_to_ranked(_profile(child_surname_initial=True, child_suppress_age=True), ranked)
    minor = ranked[0]["achievement"]
    adult = ranked[1]["achievement"]
    assert minor["swimmer_name"] == "Eira H." and "age" not in minor
    assert adult["swimmer_name"] == "Sam Adult" and adult["age"] == 25


def test_caption_boundary_backstop(monkeypatch):
    """generate_caption_for_tone applies the policy to the LLM payload."""
    captured = {}

    def fake_call_claude(*, system, user, max_tokens=400):
        captured["user"] = user
        return "Great swim!"

    import mediahub.web.ai_caption as ai_caption

    monkeypatch.setattr(ai_caption, "call_claude", fake_call_claude)
    profile = _profile(child_surname_initial=True, child_suppress_age=True)
    ach = {
        "swimmer_name": "Eira Hughes",
        "event": "100 Free",
        "time": "57.10",
        "age": 14,
        "type": "pb_confirmed",
        "raw_facts": {"time": "57.10"},
    }
    ai_caption.generate_caption_for_tone(ach, tone="warm-club", club_profile=profile)
    assert "Eira Hughes" not in captured["user"]
    assert "Eira H." in captured["user"]
    # original dict untouched (the run's stored facts are not mutated here)
    assert ach["swimmer_name"] == "Eira Hughes"


# ------------------------------------------------------------ evaluator


def test_evaluator_skips_athlete_photo_roles_when_excluded():
    from mediahub.media_requirements.evaluator import evaluate

    item = {
        "swim_id": "c1",
        "achievement": {"swimmer_name": "Eira H.", "age": 14, "confidence": 0.9},
        "post_angle": "confirmed_official_pb",  # hero_athlete is REQUIRED here
    }
    result = evaluate(item, [], exclude_athlete_photos=True)
    blob = json.dumps(result.to_dict() if hasattr(result, "to_dict") else result.__dict__)
    assert "hero_athlete" in blob  # surfaced as missing — never matched


# ------------------------------------------------------- defaults & UI


def test_new_org_setup_defaults_identity_controls_on(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    client = app.test_client()
    r = client.post(
        "/organisation",
        data={"profile_id": "fresh-club", "display_name": "Fresh Club", "action": "save"},
    )
    assert r.status_code in (200, 302)
    from mediahub.web.club_profile import load_profile

    profile = load_profile("fresh-club")
    assert profile is not None
    assert profile.child_surname_initial is True
    assert profile.child_suppress_age is True
    assert profile.child_exclude_photos is False  # photo control is opt-in


def test_child_policy_settings_route(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.club_profile import load_profile, save_profile
    from mediahub.web.web import create_app

    save_profile(_profile())
    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["active_profile_id"] = "clubx"
    r = client.post(
        "/organisation/consent/child-policy",
        data={"child_surname_initial": "1", "child_exclude_photos": "1"},
    )
    assert r.status_code == 302
    p = load_profile("clubx")
    assert p.child_surname_initial is True
    assert p.child_suppress_age is False
    assert p.child_exclude_photos is True
