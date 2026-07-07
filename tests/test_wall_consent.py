"""PC.12 — per-athlete consent (W.2) enforced on the public wall.

A blocked athlete (do_not_feature, or no consent on file under an active
regime) must be unreachable through every public wall exit: wall text,
JSON/RSS feeds, and the card PNG route. An ``initials_only`` athlete is
initialled even when the blanket toggle is off; consent can only tighten
the wall, never loosen it.
"""

from __future__ import annotations

import importlib
import json

import pytest


def _seed_run(runs_dir, run_id, profile_id):
    runs_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "profile_id": profile_id,
        "meet_name": "Spring Gala 2026",
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
                },
                {
                    "achievement": {
                        "swim_id": "swim-2",
                        "swimmer_name": "Bob Jones",
                        "event": "50m Backstroke",
                        "time": "31.42",
                    }
                },
            ]
        },
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(data))
    for cid, brief in (("swim-1", "brief-a"), ("swim-2", "brief-b")):
        vdir = runs_dir / run_id / "visuals" / brief
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "visual.json").write_text(json.dumps({"content_item_id": cid, "id": brief}))
        (vdir / "feed_portrait.png").write_bytes(b"\x89PNG fake")

    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    ws = WorkflowStore(runs_dir)
    ws.set_status(run_id, "swim-1", CardStatus.APPROVED)
    ws.set_status(run_id, "swim-2", CardStatus.APPROVED)


@pytest.fixture
def consent_wall(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="org-a",
            display_name="Org A SC",
            public_wall_enabled=True,
            public_wall_token="token-org-a-secret",
        )
    )
    _seed_run(tmp_path / "runs_v4", "run-a-1", "org-a")

    app = wm.create_app()
    app.config["TESTING"] = True
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        ("run-a-1", "org-a", "Spring Gala 2026", "gala.hy3"),
    )
    conn.commit()
    conn.close()
    return {"app": app, "tmp": tmp_path}


def _set_consent(profile_id: str, name: str, level: str):
    from mediahub.athletes.registry import get_or_create
    from mediahub.safeguarding.consent import set_consent

    rec = get_or_create(profile_id, name, source="manual")
    set_consent(profile_id, rec.athlete_id, level, actor="test")
    return rec


def test_no_regime_keeps_legacy_behaviour(consent_wall):
    from mediahub.web.club_profile import load_profile
    from mediahub.web.public_wall import wall_cards

    cards = wall_cards(load_profile("org-a"))
    assert {c["card_id"] for c in cards} == {"swim-1", "swim-2"}


def test_do_not_feature_athlete_dropped_everywhere(consent_wall):
    from mediahub.web.club_profile import load_profile
    from mediahub.web.public_wall import wall_cards, wall_image_path

    _set_consent("org-a", "Alice Smith", "do_not_feature")
    _set_consent("org-a", "Bob Jones", "full")

    hidden: list = []
    cards = wall_cards(load_profile("org-a"), consent_hidden=hidden)
    assert {c["card_id"] for c in cards} == {"swim-2"}
    assert len(hidden) == 1
    assert hidden[0]["athlete"] == "Alice Smith"
    assert hidden[0]["level"] == "do_not_feature"

    # The PNG route resolver refuses the blocked athlete's card outright.
    assert wall_image_path(load_profile("org-a"), "run-a-1", "swim-1") is None
    assert wall_image_path(load_profile("org-a"), "run-a-1", "swim-2") is not None

    c = consent_wall["app"].test_client()
    assert c.get("/wall/token-org-a-secret/card/run-a-1/swim-1.png").status_code == 404
    html = c.get("/wall/token-org-a-secret").get_data(as_text=True)
    assert "A.S." not in html  # not even initials
    feed = c.get("/wall/token-org-a-secret/feed.json").get_json()
    assert all("swim-1" not in item["image"] for item in feed["items"])
    rss = c.get("/wall/token-org-a-secret/feed.rss").get_data(as_text=True)
    assert "swim-1" not in rss


def test_unknown_athlete_blocked_under_active_regime(consent_wall):
    from mediahub.web.club_profile import load_profile
    from mediahub.web.public_wall import wall_cards

    # Only Bob has a record — the regime is active, so Alice (no consent on
    # file) collapses to most-restrictive and is held off the wall.
    _set_consent("org-a", "Bob Jones", "full")

    hidden: list = []
    cards = wall_cards(load_profile("org-a"), consent_hidden=hidden)
    assert {c["card_id"] for c in cards} == {"swim-2"}
    assert hidden and hidden[0]["athlete"] == "Alice Smith"
    assert "no consent on file" in hidden[0]["reason"]


def test_initials_only_level_binds_even_with_toggle_off(consent_wall):
    from mediahub.web.club_profile import load_profile, save_profile
    from mediahub.web.public_wall import wall_cards

    prof = load_profile("org-a")
    prof.public_wall_initials_only = False
    save_profile(prof)

    _set_consent("org-a", "Alice Smith", "initials_only")
    _set_consent("org-a", "Bob Jones", "full")

    cards = {c["card_id"]: c for c in wall_cards(load_profile("org-a"))}
    assert "Alice" not in cards["swim-1"]["title"]
    assert "A.S." in cards["swim-1"]["title"]
    # Bob consented to full naming and the blanket toggle is off.
    assert "Bob Jones" in cards["swim-2"]["title"]


def test_full_consent_cannot_loosen_blanket_toggle(consent_wall):
    from mediahub.web.club_profile import load_profile
    from mediahub.web.public_wall import wall_cards

    _set_consent("org-a", "Alice Smith", "full")
    _set_consent("org-a", "Bob Jones", "full")

    # Toggle stays on (default) → initials regardless of full consent.
    cards = {c["card_id"]: c for c in wall_cards(load_profile("org-a"))}
    assert "Alice" not in cards["swim-1"]["title"]
    assert "A.S." in cards["swim-1"]["title"]


def test_compliance_ledger_optout_blocks_the_wall_too(consent_wall):
    """The wall honours BOTH consent systems: an athlete who opted out (or
    is Art-18 restricted) in the compliance ledger is unreachable even with
    no W.2 record — the same unified check as the publish gate."""
    from mediahub.compliance.consent import ConsentRegistry
    from mediahub.web.club_profile import load_profile
    from mediahub.web.public_wall import wall_cards, wall_image_path

    ConsentRegistry("org-a").record(
        athlete_name="Alice Smith", status="revoked", recorded_by="test"
    )

    hidden: list = []
    cards = wall_cards(load_profile("org-a"), consent_hidden=hidden)
    assert {c["card_id"] for c in cards} == {"swim-2"}
    assert hidden and "opted out" in hidden[0]["reason"]
    assert wall_image_path(load_profile("org-a"), "run-a-1", "swim-1") is None

    c = consent_wall["app"].test_client()
    assert c.get("/wall/token-org-a-secret/card/run-a-1/swim-1.png").status_code == 404


def test_consent_lookup_failure_fails_closed(consent_wall, monkeypatch):
    """A broken consent registry drops every card (fail closed) while the
    public page itself still renders 200 — consent may only ever tighten
    this children's-data surface, never widen it."""
    import mediahub.compliance.gate as gate
    from mediahub.web.club_profile import load_profile
    from mediahub.web.public_wall import wall_cards, wall_image_path

    def _boom(*a, **k):
        raise RuntimeError("registry corrupt")

    monkeypatch.setattr(gate, "consent_block_reason", _boom)

    hidden: list = []
    cards = wall_cards(load_profile("org-a"), consent_hidden=hidden)
    assert cards == []  # every card excluded, none leaked
    assert len(hidden) == 2
    assert all("consent lookup failed" in h["reason"] for h in hidden)
    assert wall_image_path(load_profile("org-a"), "run-a-1", "swim-1") is None

    c = consent_wall["app"].test_client()
    assert c.get("/wall/token-org-a-secret/card/run-a-1/swim-1.png").status_code == 404
    r = c.get("/wall/token-org-a-secret")
    assert r.status_code == 200  # page renders; the cards are simply absent
    html = r.get_data(as_text=True)
    assert "Alice" not in html and "A.S." not in html


def test_settings_page_explains_consent_hidden_cards(consent_wall):
    _set_consent("org-a", "Alice Smith", "do_not_feature")
    _set_consent("org-a", "Bob Jones", "full")

    c = consent_wall["app"].test_client()
    assert c.post("/api/organisation/active", data={"profile_id": "org-a"}).status_code == 200
    html = c.get("/public-wall").get_data(as_text=True)
    assert "Held off the wall by consent" in html
    assert "Alice Smith" in html  # members-only page may name the athlete
    assert "Do not feature" in html
