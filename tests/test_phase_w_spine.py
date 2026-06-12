"""Phase W spine tests — W.1 athlete registry + milestones, W.2 consent,
W.3 club records engine.

Everything here is deterministic by rule (CLAUDE.md): identity, milestone
and record logic never touch an LLM. All stores run against a throwaway
SQLite db via the ``db_path`` parameter.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mediahub.athletes.registry import (
    get_or_create,
    initials_of,
    list_athletes,
    merge_athletes,
    milestone_context,
    normalise_name,
    record_run_swims,
    resolve,
    sync_run_payload,
)
from mediahub.club_records.store import (
    apply_approved_card,
    format_time_cs,
    import_csv as records_import_csv,
    list_records,
    parse_time_cs,
    records_map,
    upsert_record,
)
from mediahub.safeguarding.consent import (
    effective_policy,
    export_csv as consent_export_csv,
    import_csv as consent_import_csv,
    regime_active,
    set_consent,
    set_enforce,
)
from mediahub.recognition_swim.achievements.club_record import (
    ClubRecordDetector,
    _age_group_bounds,
)
from mediahub.recognition_swim.achievements.milestones import MilestoneDetector


ORG = "testclub"


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    # Audit side-writes (merge/consent changes) go under DATA_DIR — keep
    # them out of the source tree.
    monkeypatch.setenv("DATA_DIR", str(tmp_path))


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "data.db"


def _swim(key="maya-patel-2010", dist=100, stroke="FR", course="LC", time_cs=6532, **kw):
    base = dict(
        swimmer_key=key,
        distance=dist,
        stroke=stroke,
        course=course,
        finals_time_cs=time_cs,
        dq=False,
        round="F",
        swim_date="2026-06-06",
        place=1,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _history(name="Maya Patel"):
    return SimpleNamespace(swimmer_name=name)


def _ctx():
    return SimpleNamespace(meet_level="open", profile=None)


# ---------------------------------------------------------------------------
# W.1 — registry
# ---------------------------------------------------------------------------


class TestNormaliseName:
    def test_basic(self):
        assert normalise_name("  Maya   Patel ") == "maya patel"

    def test_last_first_convention(self):
        assert normalise_name("Patel, Maya") == "maya patel"

    def test_case_and_punctuation(self):
        assert normalise_name("MAYA PATEL!") == "maya patel"
        assert normalise_name("O'Brien, Seán") == "seán o'brien"

    def test_initials(self):
        assert initials_of("Maya Patel") == "M.P."
        assert initials_of("Patel, Maya") == "M.P."


class TestRegistry:
    def test_get_or_create_then_resolve_by_variant(self, db):
        rec = get_or_create(ORG, "Patel, Maya", birth_year=2010, db_path=db)
        assert rec is not None and rec.canonical_name == "Maya Patel"
        hit = resolve(ORG, "maya patel", db_path=db)
        assert hit is not None and hit.athlete_id == rec.athlete_id
        assert hit.birth_year == 2010

    def test_org_isolation(self, db):
        get_or_create(ORG, "Maya Patel", db_path=db)
        assert resolve("otherclub", "Maya Patel", db_path=db) is None

    def test_record_run_swims_idempotent(self, db):
        swims = [
            {"name": "Maya Patel", "event": "100FRLC", "time_cs": 6532},
            {"name": "Maya Patel", "event": "50FRLC", "time_cs": 3001},
        ]
        first = record_run_swims(ORG, "run1", swims, db_path=db)
        again = record_run_swims(ORG, "run1", swims, db_path=db)
        assert first["swims"] == 2
        assert again["swims"] == 0  # INSERT OR IGNORE — re-sync adds nothing
        roster = list_athletes(ORG, db_path=db)
        assert len(roster) == 1 and roster[0].race_count == 2

    def test_dq_and_nameless_rows_skipped(self, db):
        stats = record_run_swims(
            ORG,
            "run1",
            [
                {"name": "", "event": "100FRLC", "time_cs": 1},
                {"name": "A B", "event": "", "time_cs": 1},
                {"name": "A B", "event": "100FRLC", "time_cs": None},
            ],
            db_path=db,
        )
        assert stats == {"athletes": 0, "swims": 0}

    def test_milestone_context_excludes_current_run(self, db):
        record_run_swims(
            ORG, "run1", [{"name": "Maya Patel", "event": "100FRLC", "time_cs": 6532}], db_path=db
        )
        record_run_swims(
            ORG, "run2", [{"name": "Maya Patel", "event": "50FRLC", "time_cs": 3001}], db_path=db
        )
        ctx = milestone_context(ORG, exclude_run_id="run2", db_path=db)
        entry = ctx["maya patel"]
        assert entry["prior_races"] == 1
        assert entry["prior_events"] == ["100FRLC"]

    def test_merge_moves_swims_and_aliases_and_persists(self, db):
        a = get_or_create(ORG, "Maya Patel", db_path=db)
        b = get_or_create(ORG, "M. Patel", db_path=db)
        record_run_swims(
            ORG, "run1", [{"name": "M. Patel", "event": "100FRLC", "time_cs": 1}], db_path=db
        )
        assert merge_athletes(ORG, a.athlete_id, b.athlete_id, actor="coach", db_path=db)
        roster = list_athletes(ORG, db_path=db)
        assert [r.athlete_id for r in roster] == [a.athlete_id]
        assert roster[0].race_count == 1
        # The merged alias now resolves to the kept athlete — persisted decision.
        assert resolve(ORG, "M. Patel", db_path=db).athlete_id == a.athlete_id

    def test_merge_self_is_refused(self, db):
        a = get_or_create(ORG, "Maya Patel", db_path=db)
        assert not merge_athletes(ORG, a.athlete_id, a.athlete_id, db_path=db)

    def test_sync_run_payload_filters_to_ours(self, db):
        payload = {
            "run_id": "runX",
            "meet": {
                "start_date": "2026-06-06",
                "swimmers": {
                    "k1": {
                        "first_name": "Maya",
                        "last_name": "Patel",
                        "club_code": "SUNY",
                        "dob": "2010-04-01",
                    },
                    "k2": {"first_name": "Rival", "last_name": "Swimmer", "club_code": "OTHR"},
                },
                "results": [
                    {
                        "swimmer_key": "k1",
                        "club_code": "SUNY",
                        "distance": 100,
                        "stroke": "FR",
                        "course": "LC",
                        "finals_time_cs": 6532,
                        "dq": False,
                    },
                    {
                        "swimmer_key": "k2",
                        "club_code": "OTHR",
                        "distance": 100,
                        "stroke": "FR",
                        "course": "LC",
                        "finals_time_cs": 6000,
                        "dq": False,
                    },
                    {
                        "swimmer_key": "k1",
                        "club_code": "SUNY",
                        "distance": 50,
                        "stroke": "FR",
                        "course": "LC",
                        "finals_time_cs": None,
                        "dq": True,
                    },
                ],
            },
        }
        stats = sync_run_payload(ORG, payload, is_ours=lambda c: c == "SUNY", db_path=db)
        assert stats == {"athletes": 1, "swims": 1}
        roster = list_athletes(ORG, db_path=db)
        assert roster[0].canonical_name == "Maya Patel"
        assert roster[0].birth_year == 2010


# ---------------------------------------------------------------------------
# W.1 — milestone detector
# ---------------------------------------------------------------------------


class TestMilestoneDetector:
    def test_silent_without_registry_context(self):
        det = MilestoneDetector()
        swim = _swim()
        assert det.detect(swim, _ctx(), _history(), [swim], {"swimmer_name": "Maya Patel"}) == []

    def test_debut_fires_for_unknown_swimmer_when_registry_active(self):
        det = MilestoneDetector()
        swim = _swim()
        extra = {
            "swimmer_name": "Maya Patel",
            "athlete_milestones": {
                "someone else": {"athlete_id": "x", "prior_races": 3, "prior_events": []}
            },
        }
        achs = det.detect(swim, _ctx(), _history(), [swim], extra)
        assert [a.type for a in achs] == ["club_debut"]
        assert "First gala" in achs[0].headline
        assert achs[0].uncertainty_notes  # honesty caveat present

    def test_50th_race_crossed_mid_meet(self):
        det = MilestoneDetector()
        s1 = _swim(dist=50, time_cs=3001)
        s2 = _swim(dist=100, time_cs=6532)
        extra = {
            "swimmer_name": "Maya Patel",
            "athlete_milestones": {
                "maya patel": {
                    "athlete_id": "a1",
                    "prior_races": 48,
                    "prior_events": ["50FRLC", "100FRLC"],
                }
            },
        }
        # ordinal sorts by event key: "100FRLC" < "50FRLC" — s2 is race 49, s1 race 50
        achs1 = det.detect(s1, _ctx(), _history(), [s1, s2], extra)
        achs2 = det.detect(s2, _ctx(), _history(), [s1, s2], extra)
        assert [a.type for a in achs1] == ["race_milestone_50"]
        assert achs1[0].raw_facts["race_number"] == 50
        assert achs2 == []

    def test_first_ever_event_for_known_athlete(self):
        det = MilestoneDetector()
        swim = _swim(dist=200, stroke="FL", time_cs=15000)
        extra = {
            "swimmer_name": "Maya Patel",
            "athlete_milestones": {
                "maya patel": {"athlete_id": "a1", "prior_races": 10, "prior_events": ["100FRLC"]}
            },
        }
        achs = det.detect(swim, _ctx(), _history(), [swim], extra)
        assert [a.type for a in achs] == ["first_event_swim"]

    def test_dq_swim_never_fires(self):
        det = MilestoneDetector()
        swim = _swim(dq=True, time_cs=None)
        extra = {"swimmer_name": "Maya Patel", "athlete_milestones": {"x": {}}}
        assert det.detect(swim, _ctx(), _history(), [swim], extra) == []


# ---------------------------------------------------------------------------
# W.3 — records store
# ---------------------------------------------------------------------------


class TestRecordsStore:
    def test_parse_and_format_time(self):
        assert parse_time_cs("1:05.32") == 6532
        assert parse_time_cs("31.24") == 3124
        assert parse_time_cs("31.2") == 3120
        assert parse_time_cs("not a time") is None
        assert format_time_cs(6532) == "1:05.32"

    def test_import_csv_and_map(self, db):
        text = (
            "event,course,gender,age_group,time,holder,date\n"
            "100 Freestyle,LC,F,open,1:02.10,Erin Jones,2019-05-01\n"
            "100 FR,LC,F,13-14,1:05.00,Cara Lewis,2021-03-02\n"
            "bad row,LC,F,open,xx,Nobody\n"
        )
        result = records_import_csv(ORG, text, db_path=db)
        assert result["imported"] == 2
        assert len(result["skipped"]) == 1  # never guessed, explicitly reported
        rmap = records_map(ORG, db_path=db)
        assert rmap[(100, "FR", "LC", "F", "open")]["holder"] == "Erin Jones"
        assert rmap[(100, "FR", "LC", "F", "13-14")]["time_cs"] == 6500

    def test_apply_approved_card_monotonic(self, db):
        upsert_record(
            ORG,
            distance=100,
            stroke="FR",
            course="LC",
            gender="F",
            time_cs=6210,
            holder="Erin Jones",
            db_path=db,
        )
        card = {
            "run_id": "runZ",
            "achievement": {
                "type": "club_record",
                "swimmer_name": "Maya Patel",
                "raw_facts": {
                    "distance": 100,
                    "stroke": "FR",
                    "course": "LC",
                    "gender": "F",
                    "age_group": "open",
                    "new_time_cs": 6150,
                    "swim_date": "2026-06-06",
                },
            },
        }
        assert apply_approved_card(ORG, card, db_path=db)
        rmap = records_map(ORG, db_path=db)
        assert rmap[(100, "FR", "LC", "F", "open")] == {
            "time_cs": 6150,
            "holder": "Maya Patel",
            "set_date": "2026-06-06",
        }
        # Re-approval (or a slower later card) never regresses the table.
        assert not apply_approved_card(ORG, card, db_path=db)
        card["achievement"]["raw_facts"]["new_time_cs"] = 6200
        assert not apply_approved_card(ORG, card, db_path=db)
        assert records_map(ORG, db_path=db)[(100, "FR", "LC", "F", "open")]["time_cs"] == 6150

    def test_apply_ignores_non_record_cards(self, db):
        assert not apply_approved_card(ORG, {"achievement": {"type": "pb_confirmed"}}, db_path=db)


# ---------------------------------------------------------------------------
# W.3 — detector + ranking
# ---------------------------------------------------------------------------


class TestClubRecordDetector:
    def _records(self):
        return {
            (100, "FR", "LC", "F", "open"): {
                "time_cs": 6210,
                "holder": "Erin Jones",
                "set_date": "2019-05-01",
            },
            (100, "FR", "LC", "F", "13-14"): {
                "time_cs": 6500,
                "holder": "Cara Lewis",
                "set_date": "2021-03-02",
            },
        }

    def test_silent_without_records(self):
        det = ClubRecordDetector()
        swim = _swim(time_cs=6000)
        assert det.detect(swim, _ctx(), _history(), [swim], {"swimmer_name": "Maya Patel"}) == []

    def test_fires_with_old_and_new_marks(self):
        det = ClubRecordDetector()
        swim = _swim(time_cs=6150)
        extra = {
            "swimmer_name": "Maya Patel",
            "club_records": self._records(),
            "swimmer_meta": {"maya-patel-2010": {"gender": "F", "age": 16}},
        }
        achs = det.detect(swim, _ctx(), _history(), [swim], extra)
        assert len(achs) == 1
        a = achs[0]
        assert a.type == "club_record"
        assert "NEW CLUB RECORD" in a.headline
        assert a.raw_facts["old_time"] == "1:02.10"
        assert a.raw_facts["new_time"] == "1:01.50"
        assert a.raw_facts["old_holder"] == "Erin Jones"
        assert a.evidence and a.evidence[0].source_type == "registry"

    def test_prefers_most_specific_age_group(self):
        det = ClubRecordDetector()
        swim = _swim(time_cs=6150)
        extra = {
            "swimmer_name": "Maya Patel",
            "club_records": self._records(),
            "swimmer_meta": {"maya-patel-2010": {"gender": "F", "age": 14}},
        }
        achs = det.detect(swim, _ctx(), _history(), [swim], extra)
        assert achs[0].raw_facts["age_group"] == "13-14"

    def test_slower_swim_or_unknown_gender_is_silent(self):
        det = ClubRecordDetector()
        extra = {"swimmer_name": "Maya Patel", "club_records": self._records(), "swimmer_meta": {}}
        slow = _swim(time_cs=6500)
        assert (
            det.detect(
                slow,
                _ctx(),
                _history(),
                [slow],
                dict(extra, swimmer_meta={"maya-patel-2010": {"gender": "F"}}),
            )
            == []
        )
        fast_no_gender = _swim(time_cs=6000)
        assert det.detect(fast_no_gender, _ctx(), _history(), [fast_no_gender], extra) == []

    def test_age_group_bounds(self):
        assert _age_group_bounds("11-12") == (11, 12)
        assert _age_group_bounds("17+") == (17, 200)
        assert _age_group_bounds("open") is None
        assert _age_group_bounds("10") == (10, 10)

    def test_club_record_outranks_gold_and_pb(self):
        from swim_content_v5.ranker import rank_achievements
        from swim_content_v5.schema import Achievement

        def _ach(t):
            return Achievement(
                type=t,
                swim_id=f"s:{t}",
                swimmer_id="s",
                swimmer_name="Maya Patel",
                event="100m Freestyle (LC)",
                headline=t,
                angle_hint="",
                confidence=0.95,
                confidence_label="high",
            )

        ranked = rank_achievements(
            [_ach("pb_confirmed"), _ach("club_record"), _ach("medal_gold")],
            SimpleNamespace(meet_level="club", profile=None, has_finals=False),
        )
        assert ranked[0].achievement.type == "club_record"


# ---------------------------------------------------------------------------
# W.2 — consent
# ---------------------------------------------------------------------------


class TestConsent:
    def test_no_regime_is_permissive(self, db):
        pol = effective_policy(ORG, "Maya Patel", db_path=db)
        assert not regime_active(ORG, db_path=db)
        assert pol.level == "full" and pol.name_ok and pol.photo_ok and not pol.blocked

    def test_regime_makes_unknown_most_restrictive(self, db):
        other = get_or_create(ORG, "Someone Else", db_path=db)
        set_consent(ORG, other.athlete_id, "full", db_path=db)
        assert regime_active(ORG, db_path=db)
        pol = effective_policy(ORG, "Maya Patel", db_path=db)
        assert pol.blocked and pol.reason == "blocked: no consent on file"

    def test_levels_enforced(self, db):
        rec = get_or_create(ORG, "Maya Patel", db_path=db)
        set_consent(ORG, rec.athlete_id, "initials_only", db_path=db)
        pol = effective_policy(ORG, "Maya Patel", db_path=db)
        assert pol.display_name == "M.P." and pol.name_ok and not pol.photo_ok and not pol.blocked

        set_consent(ORG, rec.athlete_id, "no_photo", db_path=db)
        pol = effective_policy(ORG, "Maya Patel", db_path=db)
        assert pol.display_name == "Maya Patel" and not pol.photo_ok and not pol.blocked

        set_consent(ORG, rec.athlete_id, "do_not_feature", db_path=db)
        pol = effective_policy(ORG, "Maya Patel", db_path=db)
        assert pol.blocked and not pol.name_ok

    def test_enforce_flag_alone_activates_regime(self, db):
        set_enforce(ORG, True, db_path=db)
        assert regime_active(ORG, db_path=db)
        pol = effective_policy(ORG, "Maya Patel", db_path=db)
        assert pol.blocked

    def test_invalid_level_rejected(self, db):
        with pytest.raises(ValueError):
            set_consent(ORG, "x", "sort_of_ok", db_path=db)

    def test_org_isolation(self, db):
        rec = get_or_create(ORG, "Maya Patel", db_path=db)
        set_consent(ORG, rec.athlete_id, "do_not_feature", db_path=db)
        pol = effective_policy("otherclub", "Maya Patel", db_path=db)
        assert not pol.blocked  # other org has no regime

    def test_photo_suppressed_when_consent_withheld(self):
        """W.2 generation-time enforcement: with photo consent withheld, an
        athlete photo must never match — even when a perfect asset exists."""
        from mediahub.media_library.models import MediaAsset
        from mediahub.media_requirements.evaluator import evaluate

        asset = MediaAsset(
            id="ma_maya",
            filename="m.jpg",
            path="/tmp/m.jpg",
            type="athlete_action",
            profile_id="p",
            linked_athlete_names=["Maya Patel"],
            permission_status="approved_by_club",
            approval_status="approved",
            orientation="portrait",
            width=1500,
            height=2000,
        )
        item = {
            "id": "ci_1",
            "post_angle": "confirmed_official_pb",
            "confidence": 0.9,
            "swimmer_name": "Maya Patel",
            "achievement": {"swimmer_name": "Maya Patel", "post_angle": "confirmed_official_pb"},
            "safe_to_post": {"level": "safe"},
            "consent": {"level": "no_photo", "photo_ok": False, "name_ok": True, "blocked": False},
        }
        res = evaluate(item, library_assets=[asset])
        assert not any(r.startswith("hero") or r == "headshot" for r in res.matched)

        # Same card with full consent does match the photo.
        item_ok = dict(
            item, consent={"level": "full", "photo_ok": True, "name_ok": True, "blocked": False}
        )
        res_ok = evaluate(item_ok, library_assets=[asset])
        assert any(r.startswith("hero") or r == "headshot" for r in res_ok.matched)

    def test_csv_import_and_welfare_export(self, db):
        text = (
            "name,level,note\n"
            "Maya Patel,initials only,parent form 2026\n"
            "Joe Bloggs,photo ok\n"
            "Weird Row,sort-of\n"
        )
        result = consent_import_csv(ORG, text, db_path=db)
        assert result["imported"] == 2
        assert len(result["skipped"]) == 1
        get_or_create(ORG, "No Consent Kid", db_path=db)
        out = consent_export_csv(ORG, db_path=db)
        assert "Maya Patel,initials_only" in out
        assert "Joe Bloggs,full" in out
        assert "No Consent Kid,unknown" in out
