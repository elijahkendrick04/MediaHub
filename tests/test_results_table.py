"""tests/test_results_table.py — UI 1.12 results data table.

Two layers:

* **Pure helpers** (``mediahub.web.results_table``) — time/delta formatting, the
  registry-matching event key, the human event label, the deterministic
  PB/improvement *delta* classifier, row building from a meet + athlete history,
  and the server-side sort/filter. No app, no IO.
* **The route** (``GET /runs/<run_id>/results``) end-to-end — rendering, the
  entry point on the review page, server-side sort & filter via query params,
  the embedded sparkline payload (with real registry history), tenant
  isolation, the empty + not-found states, and XSS-safety of swimmer names.
"""

from __future__ import annotations

import json

import pytest

from mediahub.web import results_table as rt


# =========================================================================
# Pure helpers
# =========================================================================


class TestFormatting:
    def test_under_minute(self):
        assert rt.format_time_cs(234) == "2.34"

    def test_over_minute(self):
        assert rt.format_time_cs(6234) == "1:02.34"

    def test_exact_minute(self):
        assert rt.format_time_cs(6000) == "1:00.00"

    def test_zero_pads_fraction_and_seconds(self):
        assert rt.format_time_cs(6005) == "1:00.05"

    def test_none_and_negative(self):
        assert rt.format_time_cs(None) == ""
        assert rt.format_time_cs(-5) == ""

    def test_delta_two_dp_and_magnitude(self):
        assert rt.format_delta_cs(42) == "0.42"
        assert rt.format_delta_cs(130) == "1.30"
        assert rt.format_delta_cs(-42) == "0.42"
        assert rt.format_delta_cs(None) == ""


class TestEventKeyLabel:
    def test_key_matches_registry_format(self):
        # Must equal athletes.registry._swims_from_run_payload's
        # f"{dist}{stroke}{course}" so a row lines up with logged history.
        assert rt.event_key(100, "FR", "LC") == "100FRLC"
        assert rt.event_key(50, "fr", "lc") == "50FRLC"
        assert rt.event_key(200, "IM", "SC") == "200IMSC"

    def test_label_metres_and_yards(self):
        assert rt.event_label(100, "FR", "LC") == "100m Free (LC)"
        assert rt.event_label(50, "FR", "Y") == "50y Free (SCY)"

    def test_label_all_strokes(self):
        assert rt.event_label(100, "BK", "SC") == "100m Back (SC)"
        assert rt.event_label(100, "BR", "SC") == "100m Breast (SC)"
        assert rt.event_label(100, "FL", "SC") == "100m Fly (SC)"
        assert rt.event_label(200, "IM", "SC") == "200m IM (SC)"

    def test_label_unknown_stroke_titlecased(self):
        assert rt.event_label(100, "XX", "LC").startswith("100m Xx")


class TestClassifyDelta:
    def test_pb(self):
        b = rt.classify_delta(6200, 6234, 6250)
        assert b.kind == "pb"
        assert b.delta_cs == 34
        assert "PB" in b.label

    def test_matched(self):
        b = rt.classify_delta(6234, 6234, 6240)
        assert b.kind == "matched"
        assert b.delta_cs == 0

    def test_improvement_off_pb_but_faster_than_last(self):
        b = rt.classify_delta(6240, 6234, 6260)
        assert b.kind == "improvement"
        assert b.delta_cs == 20  # vs the last outing (6260)

    def test_slower_than_everything(self):
        b = rt.classify_delta(6240, 6234, 6235)
        assert b.kind == "slower"
        assert b.delta_cs == 6  # vs the lifetime best

    def test_first_when_no_history(self):
        b = rt.classify_delta(6200, None, None)
        assert b.kind == "first"
        assert b.delta_cs is None

    def test_none_when_no_clocked_time(self):
        b = rt.classify_delta(None, 6234, 6240)
        assert b.kind == "none"
        assert b.label == ""


def _meet():
    return {
        "name": "Spring Open",
        "start_date": "2026-03-01",
        "end_date": "2026-03-02",
        "course": "LC",
        "venue": "City Pool",
        "swimmers": {
            "sw1": {"first_name": "Alice", "last_name": "Lee", "gender": "F"},
            "sw2": {"first_name": "Bob", "last_name": "Ng", "gender": "M"},
        },
        "results": [
            {
                "swimmer_key": "sw1",
                "distance": 100,
                "stroke": "FR",
                "course": "LC",
                "gender": "F",
                "age_band": "13-14",
                "finals_time_cs": 6200,
                "place": 2,
                "status": "completed",
                "swim_date": "2026-03-01",
            },
            {
                "swimmer_key": "sw2",
                "distance": 100,
                "stroke": "FR",
                "course": "LC",
                "gender": "M",
                "age_band": "15-16",
                "finals_time_cs": 5800,
                "place": 1,
                "status": "completed",
                "swim_date": "2026-03-01",
            },
            {
                "swimmer_key": "sw1",
                "distance": 50,
                "stroke": "BK",
                "course": "LC",
                "gender": "F",
                "age_band": "13-14",
                "finals_time_cs": None,
                "dq": True,
                "status": "dq",
                "swim_date": "2026-03-01",
            },
        ],
    }


class TestBuildRows:
    def test_one_row_per_result_with_names(self):
        rows = rt.build_rows(_meet(), {}, "cur")
        assert len(rows) == 3
        assert rows[0].swimmer_name == "Alice Lee"
        assert rows[1].swimmer_name == "Bob Ng"
        assert rows[0].event_label == "100m Free (LC)"

    def test_dq_row_has_no_time_and_none_delta(self):
        dq = rt.build_rows(_meet(), {}, "cur")[2]
        assert dq.is_dq is True
        assert dq.time_cs is None
        assert dq.time_str == "—"
        assert dq.delta.kind == "none"

    def test_first_on_record_without_history(self):
        rows = rt.build_rows(_meet(), {}, "cur")
        assert rows[0].delta.kind == "first"
        assert rows[0].series_cs == [6200]  # just this swim
        assert rows[0].series_current_index == 0

    def test_pb_against_prior_history(self):
        history = {
            "sw1": [
                {"event": "100FRLC", "swim_date": "2025-12-01", "time_cs": 6300, "run_id": "old1"},
                {"event": "100FRLC", "swim_date": "2026-01-15", "time_cs": 6234, "run_id": "old2"},
                # an unrelated event in history must not bleed in
                {"event": "200IMLC", "swim_date": "2026-01-15", "time_cs": 14000, "run_id": "old2"},
            ]
        }
        row = rt.build_rows(_meet(), history, "cur")[0]
        assert row.delta.kind == "pb"
        assert row.delta.delta_cs == 34  # 6234 -> 6200
        # series = prior outings (date asc) + this swim
        assert row.series_cs == [6300, 6234, 6200]
        assert row.series_current_index == 2

    def test_current_run_excluded_from_prior(self):
        # History already carries this run's swim (registry synced) — it must
        # not be compared against itself, so it still reads as "first".
        history = {
            "sw1": [
                {"event": "100FRLC", "swim_date": "2026-03-01", "time_cs": 6200, "run_id": "cur"},
            ]
        }
        row = rt.build_rows(_meet(), history, "cur")[0]
        assert row.delta.kind == "first"


class TestSortFilter:
    def test_normalise_sort_clamps(self):
        assert rt.normalise_sort("bogus", "sideways") == (rt.DEFAULT_SORT, "asc")
        assert rt.normalise_sort("time", "desc") == ("time", "desc")

    def test_sort_by_time_puts_dq_last(self):
        rows = rt.build_rows(_meet(), {}, "cur")
        ordered = rt.sort_rows(rows, "time", "asc")
        assert [r.swimmer_name for r in ordered][:2] == ["Bob Ng", "Alice Lee"]
        assert ordered[-1].is_dq is True  # no clocked time sorts to the bottom

    def test_sort_by_name(self):
        rows = rt.build_rows(_meet(), {}, "cur")
        names = [r.swimmer_name for r in rt.sort_rows(rows, "name", "asc")]
        assert names == sorted(names)

    def test_sort_order_reverses(self):
        rows = rt.build_rows(_meet(), {}, "cur")
        asc = [r.swimmer_name for r in rt.sort_rows(rows, "name", "asc")]
        desc = [r.swimmer_name for r in rt.sort_rows(rows, "name", "desc")]
        assert asc == list(reversed(desc))

    def test_filter_by_event(self):
        rows = rt.build_rows(_meet(), {}, "cur")
        only = rt.filter_rows(rows, event="100FRLC")
        assert {r.swimmer_name for r in only} == {"Alice Lee", "Bob Ng"}
        assert all(r.event_key == "100FRLC" for r in only)

    def test_filter_by_query_case_insensitive(self):
        rows = rt.build_rows(_meet(), {}, "cur")
        only = rt.filter_rows(rows, query="ALICE")
        assert {r.swimmer_name for r in only} == {"Alice Lee"}

    def test_filter_pb_only(self):
        history = {
            "sw1": [
                {"event": "100FRLC", "swim_date": "2025-12-01", "time_cs": 6300, "run_id": "old"}
            ]
        }
        rows = rt.build_rows(_meet(), history, "cur")
        only = rt.filter_rows(rows, pb_only=True)
        assert [r.swimmer_name for r in only] == ["Alice Lee"]

    def test_event_options_sorted_distinct(self):
        rows = rt.build_rows(_meet(), {}, "cur")
        assert rt.event_options(rows) == [
            ("100FRLC", "100m Free (LC)"),
            ("50BKLC", "50m Back (LC)"),
        ]

    def test_sparkline_series_shape(self):
        history = {
            "sw1": [
                {"event": "100FRLC", "swim_date": "2025-12-01", "time_cs": 6300, "run_id": "old"}
            ]
        }
        row = rt.build_rows(_meet(), history, "cur")[0]
        s = rt.sparkline_series(row)
        assert s["t"] == [6300, 6200]
        assert s["cur"] == 1
        assert s["kind"] == "pb"
        assert len(s["d"]) == 2


# =========================================================================
# Route — GET /runs/<run_id>/results
# =========================================================================


@pytest.fixture
def wm(web_module):
    """The imported web module pinned at an isolated DATA_DIR.

    Delegates to the canonical ``web_module`` fixture (tests/conftest.py), which
    repoints the shared module's RUNS_DIR / DB_PATH — and the registry's
    env-derived data.db — at this test's tmp dir, so a run written here is the
    run the route reads and the history seeded here is the history it charts.
    No reload: class identity stays stable across tests.
    """
    return web_module


def _write_run(wm, run_id="r1", profile_id="org-x", meet=None):
    meet = meet if meet is not None else _meet()
    payload = {"run_id": run_id, "profile_id": profile_id, "meet": meet}
    (wm.RUNS_DIR / f"{run_id}.json").write_text(json.dumps(payload))
    return run_id


def _client(wm):
    app = wm.create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    return app.test_client()


class TestRoute:
    def test_renders_table_with_results(self, wm):
        _write_run(wm)
        r = _client(wm).get("/runs/r1/results")
        assert r.status_code == 200
        b = r.get_data(as_text=True)
        for needle in ("Spring Open", "Alice Lee", "Bob Ng", "100m Free (LC)", "1:02.00", "58.00"):
            assert needle in b, needle
        # the sortable column headers + the filter controls are server-rendered
        assert "Δ vs PB" in b
        assert "PBs &amp; improvements only" in b

    def test_usable_without_javascript(self, wm):
        # Every data row is server-rendered into the table body; the canvas is
        # only an enhancement. The facts live in the <tbody>, no JS required.
        _write_run(wm)
        b = _client(wm).get("/runs/r1/results").get_data(as_text=True)
        body = b.split("<tbody>")[1].split("</tbody>")[0]
        assert "Alice Lee" in body and "1:02.00" in body and "58.00" in body

    def test_server_side_sort_by_time(self, wm):
        _write_run(wm)
        b = _client(wm).get("/runs/r1/results?sort=time&order=asc").get_data(as_text=True)
        assert b.index("Bob Ng") < b.index("Alice Lee")  # 58.00 before 1:02.00

    def test_server_side_sort_toggle_link_present(self, wm):
        _write_run(wm)
        b = _client(wm).get("/runs/r1/results?sort=name&order=asc").get_data(as_text=True)
        # the active column offers the opposite order as its next click
        assert "sort=name&amp;order=desc" in b or "sort=name&order=desc" in b

    def test_invalid_sort_param_does_not_500(self, wm):
        _write_run(wm)
        r = _client(wm).get("/runs/r1/results?sort=DROP%20TABLE&order=NONSENSE")
        assert r.status_code == 200

    @pytest.mark.parametrize("key", list(rt.SORT_KEYS))
    def test_every_sort_key_renders(self, wm, key):
        _write_run(wm)
        c = _client(wm)
        for ordering in ("asc", "desc"):
            r = c.get(f"/runs/r1/results?sort={key}&order={ordering}")
            assert r.status_code == 200, (key, ordering)
            assert "Alice Lee" in r.get_data(as_text=True)

    def test_server_side_filter_by_name(self, wm):
        _write_run(wm)
        b = _client(wm).get("/runs/r1/results?q=alice").get_data(as_text=True)
        # restrict to the table body so chrome text can't create a false hit
        body = b.split("<tbody>")[1].split("</tbody>")[0]
        assert "Alice Lee" in body
        assert "Bob Ng" not in body

    def test_server_side_filter_by_event(self, wm):
        _write_run(wm)
        b = _client(wm).get("/runs/r1/results?event=50BKLC").get_data(as_text=True)
        body = b.split("<tbody>")[1].split("</tbody>")[0]
        assert "50m Back (LC)" in body
        assert "100m Free (LC)" not in body

    def test_sparkline_payload_with_registry_history(self, wm):
        from mediahub.athletes import record_run_swims

        # A prior outing of Alice's 100FRLC, slower than this meet's 6200 -> PB,
        # and two points so the <canvas> sparkline renders.
        record_run_swims(
            "org-x",
            "old1",
            [{"name": "Alice Lee", "event": "100FRLC", "time_cs": 6300, "swim_date": "2025-12-01"}],
        )
        _write_run(wm)
        b = _client(wm).get("/runs/r1/results").get_data(as_text=True)
        assert 'canvas class="mh-spark"' in b
        assert "6300" in b  # the historical time rode into the embedded JSON
        # Alice's row carries the PB (medal) badge
        assert "tag medal" in b
        # the meet's PB tally surfaces in the summary stat block
        assert "Personal bests" in b

    def test_embedded_sparkline_payload_drops_dates_and_escapes_script(self, wm):
        """The embedded <script> DATA must not carry swim_date strings (the JS
        never reads 'd') and must escape any '</script>' so a crafted date in an
        uploaded results file can't break out of the script block."""
        from mediahub.athletes import record_run_swims

        record_run_swims(
            "org-x",
            "old1",
            [
                {
                    "name": "Alice Lee",
                    "event": "100FRLC",
                    "time_cs": 6300,
                    "swim_date": "2025-12-01</script><script>alert(1)//",
                }
            ],
        )
        _write_run(wm)
        b = _client(wm).get("/runs/r1/results").get_data(as_text=True)
        # Isolate the embedded DATA <script> block.
        assert "var DATA =" in b
        script = b.split("var DATA =", 1)[1].split("</script>", 1)[0]
        # The date payload never rides into the page…
        assert '"d"' not in script
        assert "alert(1)" not in script
        # …and any closing-tag sequence is escaped, not raw.
        assert "</script>" not in script

    def test_pb_only_filter_via_route(self, wm):
        from mediahub.athletes import record_run_swims

        record_run_swims(
            "org-x",
            "old1",
            [{"name": "Alice Lee", "event": "100FRLC", "time_cs": 6300, "swim_date": "2025-12-01"}],
        )
        _write_run(wm)
        b = _client(wm).get("/runs/r1/results?pb=1").get_data(as_text=True)
        body = b.split("<tbody>")[1].split("</tbody>")[0]
        assert "Alice Lee" in body  # her PB stays
        assert "Bob Ng" not in body  # first-on-record (not a PB/improvement) drops

    def test_empty_results_state(self, wm):
        _write_run(wm, meet={"name": "Empty Meet", "swimmers": {}, "results": []})
        b = _client(wm).get("/runs/r1/results").get_data(as_text=True)
        assert "No parsed results" in b

    def test_run_not_found(self, wm):
        r = _client(wm).get("/runs/does-not-exist/results")
        assert r.status_code == 404

    def test_swimmer_name_is_escaped(self, wm):
        meet = _meet()
        meet["swimmers"]["sw1"] = {
            "first_name": "<script>alert(1)</script>",
            "last_name": "Lee",
            "gender": "F",
        }
        _write_run(wm, meet=meet)
        b = _client(wm).get("/runs/r1/results").get_data(as_text=True)
        assert "<script>alert(1)</script>" not in b
        assert "&lt;script&gt;" in b

    def test_entry_point_link_on_review_page(self, wm):
        _write_run(wm)
        b = _client(wm).get("/review/r1").get_data(as_text=True)
        assert "/runs/r1/results" in b
        assert "Browse all results" in b


class TestRouteTenantIsolation:
    """Focused owner-vs-foreigner check (the url_map sweep in
    test_run_route_isolation_invariant covers this route generically too)."""

    def _two_orgs(self, wm):
        from mediahub.web.club_profile import ClubProfile, save_profile

        save_profile(ClubProfile(profile_id="org-alpha", display_name="Org Alpha"))
        save_profile(ClubProfile(profile_id="org-beta", display_name="Org Beta"))
        meet = _meet()
        meet["name"] = "SECRET ALPHA MEET"
        (wm.RUNS_DIR / "ra.json").write_text(
            json.dumps({"run_id": "ra", "profile_id": "org-alpha", "meet": meet})
        )
        # Tenant isolation is enforced by _can_access_run on the run's owner,
        # not the org-setup gate — so leave the gate on its TESTING bypass and
        # just pin the active org via the session.
        app = wm.create_app()
        app.config["TESTING"] = True
        if not app.secret_key:
            app.secret_key = "test-secret"
        return app.test_client()

    def test_owner_sees_run(self, wm):
        c = self._two_orgs(wm)
        c.post("/api/organisation/active", data={"profile_id": "org-alpha"})
        b = c.get("/runs/ra/results").get_data(as_text=True)
        assert "SECRET ALPHA MEET" in b

    def test_foreign_org_blocked(self, wm):
        c = self._two_orgs(wm)
        c.post("/api/organisation/active", data={"profile_id": "org-beta"})
        r = c.get("/runs/ra/results", follow_redirects=True)
        assert "SECRET ALPHA MEET" not in r.get_data(as_text=True)
