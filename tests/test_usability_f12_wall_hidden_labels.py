"""F-12 — hidden wall cards must be listed by name, not raw internal keys.

The "Hidden cards" table rendered each excluded card as its internal
"run_id::card_id" compound in a <code> tag, while the "Cards on the wall" table
showed friendly titles and meet names — so "Show again" was a guessing game.
public_wall.card_labels now resolves the keys to titles + meet names.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    runs = tmp_path / "runs_v4"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "run-a-1.json").write_text(
        json.dumps(
            {
                "profile_id": "org-a",
                "meet": {"name": "Spring Gala 2026"},
                "recognition_report": {
                    "ranked_achievements": [
                        {
                            "achievement": {
                                "swim_id": "swim-1",
                                "swimmer_name": "Alice Smith",
                                "event": "100m Freestyle",
                                "time": "59.10",
                            }
                        }
                    ]
                },
            }
        )
    )
    from mediahub.web.club_profile import ClubProfile

    return {"tmp": tmp_path, "profile": ClubProfile(profile_id="org-a", display_name="Org A")}


def test_card_labels_resolves_key_to_title_and_meet(world):
    from mediahub.web import public_wall as pw

    key = pw.card_key("run-a-1", "swim-1")
    labels = pw.card_labels(world["profile"], [key])
    assert key in labels
    # Initials-only is the default, so the name is initialled; event + meet present.
    assert "100m Freestyle" in labels[key]["title"]
    assert labels[key]["meet_name"] == "Spring Gala 2026"


def test_card_labels_tenant_scoped_and_missing_run_absent(world):
    from mediahub.web import public_wall as pw

    # A key for a run owned by another org is never resolved.
    other = type(world["profile"])(profile_id="org-b", display_name="Org B")
    assert pw.card_labels(other, [pw.card_key("run-a-1", "swim-1")]) == {}
    # A key whose run is gone is simply absent (caller falls back to the key).
    assert pw.card_labels(world["profile"], ["nope::x"]) == {}
