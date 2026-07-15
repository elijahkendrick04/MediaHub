"""tests/test_swim_tiers_and_promotion.py — per-swim tiering + custom-highlight promotion.

Covers the "every swim ranked, standouts honest, any swim promotable" feature:

* ``recognition.swim_tiers`` — deterministic grouping/dedup of ranked
  achievements into distinct swims, standout counting, and the all-swims
  row model (standouts pinned first, close calls flagged, ordinary honest).
* The review surface — the "All swims — ranked" panel, the standout-swims
  headline stat, and the per-swim "Create highlight" affordance.
* ``POST /api/runs/<run_id>/swims/promote`` — synthesises a
  ``custom_highlight`` card append-only, applies gates, persists atomically,
  and the card flows through the normal queue → approve path.
* The detector assembly regression — the Phase W detectors must appear
  exactly once (the old double-append emitted duplicate achievements).
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.recognition import swim_tiers as st  # noqa: E402


# ---------------------------------------------------------------------------
# Unit: swim_tiers grouping / counting
# ---------------------------------------------------------------------------


def _ra(swim_id, atype, band, priority):
    return {
        "achievement": {"swim_id": swim_id, "type": atype},
        "quality_band": band,
        "priority": priority,
    }


class TestSwimGroupKey:
    def test_two_segment_prefix(self):
        assert st.swim_group_key("k1:100FRLC:F:pb") == "k1:100FRLC"

    def test_token_round_ids_share_the_group(self):
        assert st.swim_group_key("k1:100FRLC:barrier:7000") == "k1:100FRLC"
        assert st.swim_group_key("k1:100FRLC:qual:CTY") == "k1:100FRLC"

    def test_club_record_two_suffix_segments(self):
        assert st.swim_group_key("k1:100FRLC:F:clubrecord:11-12") == "k1:100FRLC"

    def test_relay_and_multi_pb_form_their_own_groups(self):
        assert st.swim_group_key("club:400FR:relay:gold") == "club:400FR"
        assert st.swim_group_key("k1:multi_pb") == "k1:multi_pb"

    def test_degenerate_ids(self):
        assert st.swim_group_key("") == ""
        assert st.swim_group_key("bare") == "bare"


class TestStandoutCounting:
    def test_one_swim_many_achievements_counts_once(self):
        """The inflation fix: a PB + magnitude + medal on ONE race is one
        standout swim, not three achievements in the headline."""
        rr = {
            "ranked_achievements": [
                _ra("k1:100FRLC:F:gold", "medal_gold", "elite", 0.9),
                _ra("k1:100FRLC:F:pb", "pb_confirmed", "nice", 0.4),
                _ra("k1:100FRLC:F:mag_big", "pb_magnitude_big", "strong", 0.65),
            ]
        }
        assert st.n_standout_for_report(rr) == 1

    def test_story_and_nice_are_not_standout(self):
        rr = {
            "ranked_achievements": [
                _ra("k1:100FRLC:F:pb", "pb_confirmed", "nice", 0.3),
                _ra("k2:50BKSC:F:rtf", "return_to_form", "story", 0.45),
            ]
        }
        assert st.n_standout_for_report(rr) == 0

    def test_custom_highlight_counts_as_standout(self):
        rr = {
            "ranked_achievements": [
                _ra("k1:100FRLC:F:custom", st.CUSTOM_HIGHLIGHT_TYPE, "story", 0.5),
            ]
        }
        assert st.n_standout_for_report(rr) == 1

    def test_relay_standout_counts(self):
        rr = {
            "ranked_achievements": [_ra("club:400FR:relay:gold", "relay_medal_gold", "strong", 0.7)]
        }
        assert st.n_standout_for_report(rr) == 1

    def test_tolerates_missing_and_malformed_reports(self):
        assert st.n_standout_for_report(None) == 0
        assert st.n_standout_for_report({}) == 0
        assert st.n_standout_from_run(None) == 0
        assert st.n_standout_from_run({}) == 0
        assert st.n_standout_from_run({"recognition_report": "corrupt"}) == 0
        # Non-dict entries are skipped, not fatal.
        assert st.n_standout_for_report({"ranked_achievements": ["junk", 42]}) == 0


class TestSwimRows:
    def _report(self):
        return {
            "ranked_achievements": [
                _ra("k1:100FRLC:F:gold", "medal_gold", "elite", 0.88),
                _ra("k1:100FRLC:F:pb", "pb_confirmed", "nice", 0.35),
                _ra("k2:50BKSC:F:pb", "pb_confirmed", "nice", 0.3),
            ],
            "swim_traces": [
                {
                    "swim_id": "k2:50BKSC:F",
                    "swimmer_name": "Ben",
                    "event": "50 Back",
                    "time_str": "31.20",
                    "achievement_count": 1,
                },
                {
                    "swim_id": "k1:100FRLC:F",
                    "swimmer_name": "Ava",
                    "event": "100 Free",
                    "time_str": "59.10",
                    "achievement_count": 2,
                },
                {
                    "swim_id": "k3:200IMLC:F",
                    "swimmer_name": "Cara",
                    "event": "200 IM",
                    "time_str": "2:41.00",
                    "achievement_count": 0,
                    "near_miss_category": "almost_pb",
                },
                {
                    "swim_id": "k4:100BRLC:F",
                    "swimmer_name": "Dan",
                    "event": "100 Breast",
                    "time_str": "1:25.00",
                    "achievement_count": 0,
                    "near_miss_category": "lower_priority",
                },
            ],
        }

    def test_rows_ordered_standout_first_then_score(self):
        rows = st.swim_rows_for_report(self._report())
        assert [r["tier"] for r in rows] == [
            st.TIER_STANDOUT,
            st.TIER_NOTABLE,
            st.TIER_CLOSE_CALL,
            st.TIER_ORDINARY,
        ]
        assert rows[0]["swimmer_name"] == "Ava"
        assert rows[0]["score"] == 0.88  # max across the swim's achievements
        assert rows[0]["achievement_count"] == 2

    def test_promotable_only_when_nothing_fired(self):
        rows = {r["swimmer_name"]: r for r in st.swim_rows_for_report(self._report())}
        assert not rows["Ava"]["promotable"]
        assert not rows["Ben"]["promotable"]
        assert rows["Cara"]["promotable"] and rows["Cara"]["close_call"]
        assert rows["Dan"]["promotable"] and not rows["Dan"]["close_call"]

    def test_deterministic_output(self):
        assert st.swim_rows_for_report(self._report()) == st.swim_rows_for_report(self._report())

    def test_empty_report_yields_no_rows(self):
        assert st.swim_rows_for_report(None) == []
        assert st.swim_rows_for_report({}) == []

    def test_prelim_and_final_attach_by_round(self):
        """Round-carrying achievement ids attach to the matching round's trace,
        not the prelim of the same event."""
        rr = {
            "ranked_achievements": [_ra("k1:100FRLC:F:gold", "medal_gold", "elite", 0.9)],
            "swim_traces": [
                {
                    "swim_id": "k1:100FRLC:P",
                    "swimmer_name": "Ava",
                    "event": "100 Free",
                    "time_str": "60.00",
                    "achievement_count": 0,
                    "near_miss_category": "lower_priority",
                },
                {
                    "swim_id": "k1:100FRLC:F",
                    "swimmer_name": "Ava",
                    "event": "100 Free",
                    "time_str": "59.10",
                    "achievement_count": 1,
                },
            ],
        }
        rows = {r["swim_id"]: r for r in st.swim_rows_for_report(rr)}
        assert rows["k1:100FRLC:F"]["tier"] == st.TIER_STANDOUT
        assert rows["k1:100FRLC:P"]["tier"] == st.TIER_ORDINARY
        # The prelim trace keeps engine_count 0 but shares the group, so it
        # must not be promotable (the swim already has a card).
        assert not rows["k1:100FRLC:P"]["promotable"]


# ---------------------------------------------------------------------------
# Regression: Phase W detectors appear exactly once
# ---------------------------------------------------------------------------


class TestDetectorAssembly:
    def test_production_detectors_unique(self):
        from mediahub.recognition_swim import production_detectors

        names = [type(d).__name__ for d in production_detectors()]
        assert len(names) == len(set(names)), f"duplicate detectors: {names}"

    def test_report_no_longer_double_appends(self):
        """report.py used to append MilestoneDetector/ClubRecordDetector on top
        of production_detectors() (which already contains them), so both ran
        twice per swim and emitted duplicate achievements. Tripwire on the
        exact re-append expression so the bug cannot quietly return."""
        src = (_ROOT / "legacy" / "swim_content_v5" / "report.py").read_text()
        assert "detectors + [MilestoneDetector(), ClubRecordDetector()]" not in src


# ---------------------------------------------------------------------------
# Web: review panel + promotion route
# ---------------------------------------------------------------------------


def _seed_run(tmp_path, wm, profile_id, run_payload):
    run_id = run_payload["run_id"]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(run_payload))
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs "
        "(id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, profile_id, run_payload["meet"]["name"], "test.hy3"),
    )
    conn.commit()
    conn.close()
    return run_id


@pytest.fixture
def review_env(client, web_module, tmp_path):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="org-test",
            display_name="Test Club",
            brand_voice_summary="Clear and energetic.",
        )
    )

    r = client.post("/api/organisation/active", data={"profile_id": "org-test"})
    assert r.status_code == 200, r.get_json()
    yield {"client": client, "wm": web_module, "tmp_path": tmp_path}


def _payload(profile_id="org-test"):
    run_id = "run-tiers-" + uuid.uuid4().hex[:8]
    return {
        "run_id": run_id,
        "profile_id": profile_id,
        "profile_display": "Test Club",
        "meet": {"name": "TIERS TEST MEET"},
        "our_swim_count": 4,
        "cards": [],
        "trust": {},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "rank": 1,
                    "achievement": {
                        "swim_id": "k1:100FRLC:F:gold",
                        "swimmer_name": "Ava Gold",
                        "event": "100m Freestyle (LC)",
                        "headline": "Gold in the 100 Free",
                        "type": "medal_gold",
                        "confidence_label": "high",
                    },
                    "quality_band": "elite",
                    "priority": 0.88,
                    "suggested_post_type": "main_feed",
                    "factors": [],
                },
                {
                    "rank": 2,
                    "achievement": {
                        "swim_id": "k1:100FRLC:F:pb",
                        "swimmer_name": "Ava Gold",
                        "event": "100m Freestyle (LC)",
                        "headline": "PB in the 100 Free",
                        "type": "pb_confirmed",
                        "confidence_label": "high",
                    },
                    "quality_band": "nice",
                    "priority": 0.35,
                    "suggested_post_type": "recap",
                    "factors": [],
                },
            ],
            "swim_traces": [
                {
                    "swim_id": "k1:100FRLC:F",
                    "swimmer_name": "Ava Gold",
                    "event": "100m Freestyle (LC)",
                    "time_str": "59.10",
                    "achievement_count": 2,
                    "detector_traces": [],
                    "summary": "2 achievement(s) detected",
                },
                {
                    "swim_id": "k3:200IMLC:F",
                    "swimmer_name": "Cara Close",
                    "event": "200m IM (LC)",
                    "time_str": "2:41.00",
                    "achievement_count": 0,
                    "detector_traces": [],
                    "summary": "almost a PB",
                    "near_miss_category": "almost_pb",
                },
                {
                    "swim_id": "k4:100BRLC:F",
                    "swimmer_name": "Dan Ordinary",
                    "event": "100m Breaststroke (LC)",
                    "time_str": "1:25.00",
                    "achievement_count": 0,
                    "detector_traces": [],
                    "summary": "no notable achievement detected by any detector",
                    "near_miss_category": "lower_priority",
                },
            ],
            "n_elite": 1,
            "n_strong": 0,
            "n_story": 0,
            "n_nice": 1,
            "n_achievements": 2,
            "n_swims_analysed": 4,
        },
        "parse_warnings": [],
        "self_check": {},
        "detector_summary": {},
        "dispatch_log": {},
    }


class TestReviewAllSwimsPanel:
    def test_panel_lists_every_swim_with_tiers(self, review_env):
        wm, tmp_path, client = review_env["wm"], review_env["tmp_path"], review_env["client"]
        run_id = _seed_run(tmp_path, wm, "org-test", _payload())
        body = client.get(f"/review/{run_id}").get_data(as_text=True)
        assert 'id="mh-all-swims"' in body
        # Every analysed swim appears, including the ones with no card.
        for name in ("Ava Gold", "Cara Close", "Dan Ordinary"):
            assert name in body
        # Standouts / close calls surfaced in the summary line.
        assert "1 standout" in body
        assert "close call" in body

    def test_headline_stat_is_standout_swims_not_raw_total(self, review_env):
        wm, tmp_path, client = review_env["wm"], review_env["tmp_path"], review_env["client"]
        run_id = _seed_run(tmp_path, wm, "org-test", _payload())
        body = client.get(f"/review/{run_id}").get_data(as_text=True)
        assert "Standout swims" in body
        assert "Total achievements" not in body
        # 2 raw achievements dedupe to 1 standout swim.
        seg = body.split("Standout swims", 1)[1][:200]
        assert 'data-mh-count="1"' in seg

    def test_promote_button_only_on_unflagged_swims(self, review_env):
        wm, tmp_path, client = review_env["wm"], review_env["tmp_path"], review_env["client"]
        run_id = _seed_run(tmp_path, wm, "org-test", _payload())
        body = client.get(f"/review/{run_id}").get_data(as_text=True)
        panel = body.split('id="mh-all-swims"', 1)[1]
        # Two promotable swims (Cara + Dan), none for Ava's carded swim —
        # one promotion form each.
        assert panel.count('class="mh-promote"') == 2
        assert 'value="k3:200IMLC:F"' in panel and 'value="k4:100BRLC:F"' in panel
        assert 'value="k1:100FRLC:F"' not in panel


class TestPromoteRoute:
    def test_promote_creates_custom_card_in_queue(self, review_env):
        wm, tmp_path, client = review_env["wm"], review_env["tmp_path"], review_env["client"]
        run_id = _seed_run(tmp_path, wm, "org-test", _payload())
        r = client.post(
            f"/api/runs/{run_id}/swims/promote",
            data={
                "swim_id": "k3:200IMLC:F",
                "headline": "Cara's comeback",
                "note": "First 200 IM since injury",
            },
        )
        assert r.status_code == 302
        assert "promoted=1" in r.headers["Location"]

        data = json.loads((tmp_path / "runs_v4" / f"{run_id}.json").read_text())
        rr = data["recognition_report"]
        new = rr["ranked_achievements"][-1]
        ach = new["achievement"]
        assert ach["type"] == "custom_highlight"
        assert ach["swim_id"] == "k3:200IMLC:F:custom"
        assert ach["headline"] == "Cara's comeback"
        assert ach["detector_name"] == "manual_promotion"
        assert new["safe_to_post"]["level"] == "needs_review"
        # Append-only: prior entries untouched, rank continues the list.
        assert rr["ranked_achievements"][0]["achievement"]["swim_id"] == "k1:100FRLC:F:gold"
        assert new["rank"] == 3
        assert rr["n_achievements"] == 3
        # The swim's trace now reads as promoted (and is no longer promotable).
        tr = [t for t in rr["swim_traces"] if t["swim_id"] == "k3:200IMLC:F"][0]
        assert tr["achievement_count"] == 1

    def test_default_headline_is_fact_only(self, review_env):
        wm, tmp_path, client = review_env["wm"], review_env["tmp_path"], review_env["client"]
        run_id = _seed_run(tmp_path, wm, "org-test", _payload())
        r = client.post(f"/api/runs/{run_id}/swims/promote", data={"swim_id": "k4:100BRLC:F"})
        assert r.status_code == 302
        data = json.loads((tmp_path / "runs_v4" / f"{run_id}.json").read_text())
        ach = data["recognition_report"]["ranked_achievements"][-1]["achievement"]
        assert ach["headline"] == "Dan Ordinary — 100m Breaststroke (LC) in 1:25.00"

    def test_promoted_swim_counts_as_standout(self, review_env):
        wm, tmp_path, client = review_env["wm"], review_env["tmp_path"], review_env["client"]
        run_id = _seed_run(tmp_path, wm, "org-test", _payload())
        client.post(f"/api/runs/{run_id}/swims/promote", data={"swim_id": "k3:200IMLC:F"})
        js = client.get(f"/api/runs/{run_id}/status").get_json()
        assert js["n_standout"] == 2  # Ava's gold + the promoted highlight

    def test_duplicate_promotion_refused(self, review_env):
        wm, tmp_path, client = review_env["wm"], review_env["tmp_path"], review_env["client"]
        run_id = _seed_run(tmp_path, wm, "org-test", _payload())
        assert (
            client.post(
                f"/api/runs/{run_id}/swims/promote", data={"swim_id": "k3:200IMLC:F"}
            ).status_code
            == 302
        )
        assert (
            client.post(
                f"/api/runs/{run_id}/swims/promote", data={"swim_id": "k3:200IMLC:F"}
            ).status_code
            == 409
        )

    def test_carded_swim_not_promotable(self, review_env):
        wm, tmp_path, client = review_env["wm"], review_env["tmp_path"], review_env["client"]
        run_id = _seed_run(tmp_path, wm, "org-test", _payload())
        r = client.post(f"/api/runs/{run_id}/swims/promote", data={"swim_id": "k1:100FRLC:F"})
        assert r.status_code == 409

    def test_unknown_swim_404(self, review_env):
        wm, tmp_path, client = review_env["wm"], review_env["tmp_path"], review_env["client"]
        run_id = _seed_run(tmp_path, wm, "org-test", _payload())
        assert (
            client.post(f"/api/runs/{run_id}/swims/promote", data={"swim_id": "nope:1"}).status_code
            == 404
        )

    def test_missing_swim_id_400(self, review_env):
        wm, tmp_path, client = review_env["wm"], review_env["tmp_path"], review_env["client"]
        run_id = _seed_run(tmp_path, wm, "org-test", _payload())
        assert client.post(f"/api/runs/{run_id}/swims/promote", data={}).status_code == 400

    def test_foreign_org_cannot_promote(self, review_env, tmp_path):
        wm, client = review_env["wm"], review_env["client"]
        run_id = _seed_run(tmp_path, wm, "org-other", _payload("org-other"))
        r = client.post(f"/api/runs/{run_id}/swims/promote", data={"swim_id": "k3:200IMLC:F"})
        assert r.status_code == 404  # anti-enumeration: reads as not-found

    def test_user_text_is_escaped_on_review(self, review_env):
        """A promoted headline/note is user input — it must render escaped."""
        wm, tmp_path, client = review_env["wm"], review_env["tmp_path"], review_env["client"]
        run_id = _seed_run(tmp_path, wm, "org-test", _payload())
        xss = "<script>alert(1)</script>"
        client.post(
            f"/api/runs/{run_id}/swims/promote",
            data={"swim_id": "k3:200IMLC:F", "headline": xss, "note": xss},
        )
        body = client.get(f"/review/{run_id}").get_data(as_text=True)
        assert "<script>alert(1)</script>" not in body
        assert "&lt;script&gt;" in body

    def test_promoted_card_flows_queue_to_approved_to_pack(self, review_env):
        wm, tmp_path, client = review_env["wm"], review_env["tmp_path"], review_env["client"]
        run_id = _seed_run(tmp_path, wm, "org-test", _payload())
        client.post(f"/api/runs/{run_id}/swims/promote", data={"swim_id": "k3:200IMLC:F"})
        r = client.post(
            f"/api/workflow/{run_id}/k3:200IMLC:F:custom",
            json={"action": "set_status", "status": "approved"},
        )
        assert r.status_code == 200, r.get_data(as_text=True)[:200]
        from mediahub.workflow.pack import build_content_pack

        cards = build_content_pack(run_id, "org-test", runs_dir=tmp_path / "runs_v4")
        ids = [(c.get("achievement") or {}).get("swim_id") for c in cards]
        assert "k3:200IMLC:F:custom" in ids

    def test_json_request_gets_json_response(self, review_env):
        wm, tmp_path, client = review_env["wm"], review_env["tmp_path"], review_env["client"]
        run_id = _seed_run(tmp_path, wm, "org-test", _payload())
        r = client.post(
            f"/api/runs/{run_id}/swims/promote",
            json={"swim_id": "k3:200IMLC:F"},
        )
        assert r.status_code == 200
        assert r.get_json() == {"ok": True, "card_id": "k3:200IMLC:F:custom"}


class TestStandoutBackfill:
    def test_warm_helper_backfills_old_rows_from_json(self, review_env):
        """Rows persisted before the n_standout column existed get the count
        recomputed from the run JSON when listed (and the column warmed)."""
        wm, tmp_path, client = review_env["wm"], review_env["tmp_path"], review_env["client"]
        run_id = _seed_run(tmp_path, wm, "org-test", _payload())
        # Seeded row has NULL n_standout — listing the Activity page recomputes.
        body = client.get("/activity").get_data(as_text=True)
        assert "Standout swims" in body
        conn = wm._db()
        v = conn.execute("SELECT n_standout FROM runs WHERE id = ?", (run_id,)).fetchone()[0]
        conn.close()
        assert v == 1
