"""Tests for results_fetch/live_watch.py — W.7 live meet mode engine core.

Every test runs against a throwaway SQLite db (tmp_path) with DATA_DIR
pointed at tmp_path too, so nothing touches the real data.db. The fetcher
returns LENEX (.lef) fixtures — interpret_document parses LENEX natively
and deterministically, so polls are fully reproducible.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mediahub.results_fetch import live_watch as lw


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))


@pytest.fixture
def db(tmp_path):
    return tmp_path / "live_watch_test.db"


URL = "https://results.exampleclub.org.uk/live/index.htm"
# Anchored to the real clock because create_watch's default expiry is
# real-now + 12h; the poll-interval arithmetic only uses offsets from this.
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _lenex(athletes) -> bytes:
    """A minimal LENEX .lef results document the interpreter parses natively.

    ``athletes``: list of (resultid, eventid, first, last, swimtime).
    Event 1 = Men's 100 Free LC, event 2 = Women's 50 Breast LC.
    """
    rankings = {"1": [], "2": []}
    results = []
    for rid, eid, first, last, swimtime in athletes:
        rankings[str(eid)].append(
            f'<RANKING place="{len(rankings[str(eid)]) + 1}" resultid="{rid}"/>'
        )
        results.append(
            f'<ATHLETE athleteid="a{rid}" firstname="{first}" lastname="{last}"'
            f' gender="M" birthdate="2008-01-01">'
            f'<RESULTS><RESULT resultid="{rid}" eventid="{eid}" swimtime="{swimtime}"/></RESULTS>'
            f"</ATHLETE>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<LENEX version="3.0">'
        '<CONSTRUCTOR name="t" registration="t" version="1.0"><CONTACT email="t@t.t"/></CONSTRUCTOR>'
        "<MEETS>"
        '<MEET name="Live Test Gala 2026" city="Swansea" nation="GBR" course="LCM">'
        "<SESSIONS>"
        '<SESSION number="1" date="2026-06-13">'
        "<EVENTS>"
        '<EVENT eventid="1" number="1" gender="M">'
        '<SWIMSTYLE distance="100" relaycount="1" stroke="FREE"/>'
        '<AGEGROUPS><AGEGROUP agegroupid="1" agemin="-1" agemax="-1">'
        f"<RANKINGS>{''.join(rankings['1'])}</RANKINGS>"
        "</AGEGROUP></AGEGROUPS>"
        "</EVENT>"
        '<EVENT eventid="2" number="2" gender="F">'
        '<SWIMSTYLE distance="50" relaycount="1" stroke="BREAST"/>'
        '<AGEGROUPS><AGEGROUP agegroupid="2" agemin="-1" agemax="-1">'
        f"<RANKINGS>{''.join(rankings['2'])}</RANKINGS>"
        "</AGEGROUP></AGEGROUPS>"
        "</EVENT>"
        "</EVENTS>"
        "</SESSION>"
        "</SESSIONS>"
        "<CLUBS>"
        '<CLUB name="Test SC" code="TEST" nation="GBR">'
        f"<ATHLETES>{''.join(results)}</ATHLETES>"
        "</CLUB>"
        "</CLUBS>"
        "</MEET>"
        "</MEETS>"
        "</LENEX>"
    ).encode("utf-8")


SESSION_1 = _lenex(
    [
        ("101", 1, "Calum", "Reid", "00:00:55.43"),
        ("201", 2, "Mhairi", "Watt", "00:00:41.07"),
    ]
)
# Same two swims plus exactly one new one.
SESSION_1_PLUS_ONE = _lenex(
    [
        ("101", 1, "Calum", "Reid", "00:00:55.43"),
        ("201", 2, "Mhairi", "Watt", "00:00:41.07"),
        ("102", 1, "Euan", "Park", "00:01:02.18"),
    ]
)


class RecordingRunner:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, watch, data, new_swim_keys):
        if self.fail:
            raise RuntimeError("pipeline blew up")
        self.calls.append((watch.id, bytes(data), list(new_swim_keys)))


class RecordingNotifier:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, watch, new_swim_keys):
        self.calls.append((watch.id, watch.status, list(new_swim_keys)))
        if self.fail:
            raise RuntimeError("ntfy down")


def _fetcher(payload):
    return lambda url: payload


# ---------------------------------------------------------------------------
# create / validate
# ---------------------------------------------------------------------------


class TestCreateWatch:
    def test_create_persists_with_defaults(self, db):
        w = lw.create_watch("org-a", URL, label="Swansea Gala", run_id="run1", db_path=db)
        got = lw.get_watch(w.id, db_path=db)
        assert got is not None
        assert got.profile_id == "org-a"
        assert got.url == URL
        assert got.interval_minutes == 5
        assert got.status == "active"
        assert got.label == "Swansea Gala"
        assert got.run_id == "run1"
        assert got.polls == 0 and got.new_swims_total == 0
        # Default expiry ~ now+12h, always set
        expiry = datetime.fromisoformat(got.expires_at)
        delta = expiry - datetime.now(timezone.utc)
        assert timedelta(hours=11) < delta < timedelta(hours=13)

    def test_interval_clamped_to_politeness_floor(self, db):
        w = lw.create_watch("org-a", URL, interval_minutes=1, db_path=db)
        assert w.interval_minutes == lw.MIN_INTERVAL_MINUTES

    def test_interval_clamped_to_max(self, db):
        # An absurd/malformed interval must clamp to the ceiling, never reach
        # the INSERT as an out-of-range int (SQLite INTEGER overflow).
        w = lw.create_watch("org-a", URL, interval_minutes=10**20, db_path=db)
        assert w.interval_minutes == lw.MAX_INTERVAL_MINUTES
        # And it round-trips through the DB without raising.
        assert lw.get_watch(w.id, db_path=db).interval_minutes == lw.MAX_INTERVAL_MINUTES

    def test_expiry_capped_at_48h(self, db):
        far = datetime.now(timezone.utc) + timedelta(days=30)
        w = lw.create_watch("org-a", URL, expires_at=far.isoformat(), db_path=db)
        expiry = datetime.fromisoformat(w.expires_at)
        assert expiry - datetime.now(timezone.utc) <= timedelta(hours=48, minutes=1)

    def test_past_expiry_rejected(self, db):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        with pytest.raises(ValueError, match="future"):
            lw.create_watch("org-a", URL, expires_at=past.isoformat(), db_path=db)

    def test_bad_scheme_rejected(self, db):
        for bad in ("ftp://results.club.org/x", "javascript:alert(1)", "results.club.org", ""):
            with pytest.raises(ValueError, match="http"):
                lw.create_watch("org-a", bad, db_path=db)

    def test_prohibited_hosts_rejected_with_clear_message(self, db):
        for bad in (
            "https://www.swimrankings.net/index.php?page=meetDetail&meetId=1",
            "https://swimrankings.net/x",
            "https://meetmobile.active.com/meets/123",
            "https://api.active.com/meetmobile/v1/meet/123",
            "https://www.meetmobile.com/whatever",
        ):
            with pytest.raises(ValueError, match="prohibited"):
                lw.create_watch("org-a", bad, db_path=db)

    def test_allowed_hosts_accepted(self, db):
        for good in (
            "https://results.swimming.org/meet/12345",
            "https://www.swanseaaquatics.uk/realtime/index.htm",
            "http://hostclub.example.com/live/evtindex.htm",
        ):
            assert lw.create_watch("org-a", good, db_path=db).status == "active"

    def test_requires_profile_id(self, db):
        with pytest.raises(ValueError, match="profile_id"):
            lw.create_watch("", URL, db_path=db)


# ---------------------------------------------------------------------------
# org isolation / list / stop
# ---------------------------------------------------------------------------


class TestOrgIsolation:
    def test_list_is_org_scoped(self, db):
        a = lw.create_watch("org-a", URL, db_path=db)
        lw.create_watch("org-b", URL, db_path=db)
        ids = [w.id for w in lw.list_watches("org-a", db_path=db)]
        assert ids == [a.id]

    def test_get_with_wrong_profile_returns_none(self, db):
        w = lw.create_watch("org-a", URL, db_path=db)
        assert lw.get_watch(w.id, profile_id="org-b", db_path=db) is None
        assert lw.get_watch(w.id, profile_id="org-a", db_path=db) is not None

    def test_stop_respects_profile(self, db):
        w = lw.create_watch("org-a", URL, db_path=db)
        assert lw.stop_watch("org-b", w.id, db_path=db) is False
        assert lw.get_watch(w.id, db_path=db).status == "active"
        assert lw.stop_watch("org-a", w.id, db_path=db) is True
        assert lw.get_watch(w.id, db_path=db).status == "stopped"
        # idempotent
        assert lw.stop_watch("org-a", w.id, db_path=db) is False

    def test_stopped_watch_does_not_poll(self, db):
        w = lw.create_watch("org-a", URL, db_path=db)
        lw.stop_watch("org-a", w.id, db_path=db)
        runner = RecordingRunner()
        res = lw.poll_watch(w.id, fetcher=_fetcher(SESSION_1), runner=runner, db_path=db)
        assert res.status == "stopped" and not res.changed
        assert runner.calls == []


# ---------------------------------------------------------------------------
# due_watches
# ---------------------------------------------------------------------------


class TestDueWatches:
    def test_new_watch_is_due_immediately(self, db):
        w = lw.create_watch("org-a", URL, db_path=db)
        assert [d.id for d in lw.due_watches(db_path=db)] == [w.id]

    def test_respects_interval(self, db):
        w = lw.create_watch("org-a", URL, interval_minutes=5, db_path=db)
        lw.poll_watch(
            w.id,
            fetcher=_fetcher(SESSION_1),
            runner=RecordingRunner(),
            notifier=RecordingNotifier(),
            now=NOW,
            db_path=db,
        )
        assert lw.due_watches(now=NOW + timedelta(minutes=3), db_path=db) == []
        due = lw.due_watches(now=NOW + timedelta(minutes=5), db_path=db)
        assert [d.id for d in due] == [w.id]

    def test_stopped_watch_never_due(self, db):
        w = lw.create_watch("org-a", URL, db_path=db)
        lw.stop_watch("org-a", w.id, db_path=db)
        assert lw.due_watches(db_path=db) == []

    def test_time_expired_watch_still_returned_for_final_poll(self, db):
        # The expiring poll is what flips status + sends "watch ended" —
        # the watch must surface as due once more so it can stop itself.
        w = lw.create_watch("org-a", URL, db_path=db)
        late = datetime.now(timezone.utc) + timedelta(hours=13)
        assert [d.id for d in lw.due_watches(now=late, db_path=db)] == [w.id]
        lw.poll_watch(w.id, notifier=RecordingNotifier(), now=late, db_path=db)
        assert lw.due_watches(now=late + timedelta(hours=1), db_path=db) == []


# ---------------------------------------------------------------------------
# poll_watch — the heart
# ---------------------------------------------------------------------------


class TestPollWatch:
    def _watch(self, db, **kw):
        return lw.create_watch("org-a", URL, run_id="run-7", **kw, db_path=db)

    def test_first_poll_all_swims_new(self, db):
        w = self._watch(db)
        runner, notifier = RecordingRunner(), RecordingNotifier()
        res = lw.poll_watch(
            w.id,
            fetcher=_fetcher(SESSION_1),
            runner=runner,
            notifier=notifier,
            now=NOW,
            db_path=db,
        )
        assert res.changed is True
        assert res.error == ""
        assert res.swim_count == 2
        assert len(res.new_swim_keys) == 2
        # Keys are name|gender,distance,stroke,course|time
        assert any(
            k.startswith("calum reid|M,100,") and k.endswith("|55.43") for k in res.new_swim_keys
        )
        assert any(
            k.startswith("mhairi watt|F,50,") and k.endswith("|41.07") for k in res.new_swim_keys
        )
        # Runner called exactly once, with the raw bytes and ALL new keys
        assert len(runner.calls) == 1
        _, data, keys = runner.calls[0]
        assert data == SESSION_1
        assert keys == res.new_swim_keys
        # Notifier saw the same keys
        assert notifier.calls == [(w.id, "active", res.new_swim_keys)]
        got = lw.get_watch(w.id, db_path=db)
        assert got.polls == 1
        assert got.last_swim_count == 2
        assert got.new_swims_total == 2
        assert got.last_digest != ""
        assert got.last_polled_at is not None

    def test_second_poll_same_content_no_runner_call(self, db):
        w = self._watch(db)
        runner, notifier = RecordingRunner(), RecordingNotifier()
        lw.poll_watch(
            w.id, fetcher=_fetcher(SESSION_1), runner=runner, notifier=notifier, now=NOW, db_path=db
        )
        res = lw.poll_watch(
            w.id,
            fetcher=_fetcher(SESSION_1),
            runner=runner,
            notifier=notifier,
            now=NOW + timedelta(minutes=5),
            db_path=db,
        )
        assert res.changed is False
        assert res.new_swim_keys == []
        assert len(runner.calls) == 1  # still just the first poll
        assert len(notifier.calls) == 1
        got = lw.get_watch(w.id, db_path=db)
        assert got.polls == 2
        assert got.new_swims_total == 2

    def test_incremental_poll_cards_exactly_the_one_new_swim(self, db):
        w = self._watch(db)
        runner = RecordingRunner()
        lw.poll_watch(
            w.id,
            fetcher=_fetcher(SESSION_1),
            runner=runner,
            notifier=RecordingNotifier(),
            now=NOW,
            db_path=db,
        )
        res = lw.poll_watch(
            w.id,
            fetcher=_fetcher(SESSION_1_PLUS_ONE),
            runner=runner,
            notifier=RecordingNotifier(),
            now=NOW + timedelta(minutes=5),
            db_path=db,
        )
        assert res.changed is True
        assert res.swim_count == 3
        assert len(res.new_swim_keys) == 1
        assert res.new_swim_keys[0].startswith("euan park|M,100,")
        assert runner.calls[-1][2] == res.new_swim_keys
        assert lw.get_watch(w.id, db_path=db).new_swims_total == 3

    def test_runner_failure_keeps_diff_for_retry(self, db):
        w = self._watch(db)
        failing = RecordingRunner(fail=True)
        notifier = RecordingNotifier()
        res = lw.poll_watch(
            w.id,
            fetcher=_fetcher(SESSION_1),
            runner=failing,
            notifier=notifier,
            now=NOW,
            db_path=db,
        )
        assert res.changed is False
        assert "runner failed" in res.error
        assert notifier.calls == []  # nothing committed → nothing announced
        got = lw.get_watch(w.id, db_path=db)
        assert got.status == "active"
        assert "runner failed" in got.last_error
        assert got.last_digest == "" and got.new_swims_total == 0
        # Next poll retries the SAME diff and succeeds
        runner = RecordingRunner()
        res2 = lw.poll_watch(
            w.id,
            fetcher=_fetcher(SESSION_1),
            runner=runner,
            notifier=notifier,
            now=NOW + timedelta(minutes=5),
            db_path=db,
        )
        assert res2.changed is True
        assert len(res2.new_swim_keys) == 2
        assert runner.calls[0][2] == res2.new_swim_keys
        assert lw.get_watch(w.id, db_path=db).last_error == ""

    def test_fetch_failure_is_transient(self, db):
        w = self._watch(db)
        runner = RecordingRunner()

        def dead(url):
            raise OSError("connection refused")

        res = lw.poll_watch(w.id, fetcher=dead, runner=runner, now=NOW, db_path=db)
        assert res.status == "active" and not res.changed
        assert "fetch failed" in res.error
        assert runner.calls == []
        got = lw.get_watch(w.id, db_path=db)
        assert got.status == "active" and "fetch failed" in got.last_error
        # None-returning fetcher is the same transient story
        res2 = lw.poll_watch(
            w.id, fetcher=_fetcher(None), runner=runner, now=NOW + timedelta(minutes=5), db_path=db
        )
        assert res2.status == "active" and "fetch failed" in res2.error
        # And the watch recovers fully once the site comes back
        res3 = lw.poll_watch(
            w.id,
            fetcher=_fetcher(SESSION_1),
            runner=runner,
            notifier=RecordingNotifier(),
            now=NOW + timedelta(minutes=10),
            db_path=db,
        )
        assert res3.changed is True and len(res3.new_swim_keys) == 2

    def test_parse_failure_never_emits_partial_rows(self, db):
        w = self._watch(db)
        runner = RecordingRunner()
        res = lw.poll_watch(
            w.id,
            fetcher=_fetcher(b"\x00\x01 not results at all"),
            runner=runner,
            now=NOW,
            db_path=db,
        )
        assert res.status == "active" and not res.changed
        assert "parse failed; will retry" in res.error
        assert runner.calls == []
        got = lw.get_watch(w.id, db_path=db)
        assert got.status == "active"
        assert "parse failed; will retry" in got.last_error

    def test_expiry_marks_expired_and_sends_final_notification(self, db):
        w = self._watch(db)
        runner, notifier = RecordingRunner(), RecordingNotifier()
        late = datetime.now(timezone.utc) + timedelta(hours=13)
        res = lw.poll_watch(
            w.id,
            fetcher=_fetcher(SESSION_1),
            runner=runner,
            notifier=notifier,
            now=late,
            db_path=db,
        )
        assert res.status == "expired" and not res.changed
        assert runner.calls == []  # no fetch, no runner past expiry
        assert notifier.calls == [(w.id, "expired", [])]  # "watch ended"
        assert lw.get_watch(w.id, db_path=db).status == "expired"
        # Already-expired watches are inert thereafter
        res2 = lw.poll_watch(
            w.id,
            fetcher=_fetcher(SESSION_1),
            runner=runner,
            notifier=notifier,
            now=late,
            db_path=db,
        )
        assert res2.status == "expired"
        assert len(notifier.calls) == 1

    def test_notifier_failure_never_fails_the_poll(self, db):
        w = self._watch(db)
        runner = RecordingRunner()
        res = lw.poll_watch(
            w.id,
            fetcher=_fetcher(SESSION_1),
            runner=runner,
            notifier=RecordingNotifier(fail=True),
            now=NOW,
            db_path=db,
        )
        assert res.changed is True
        assert res.error == ""
        assert lw.get_watch(w.id, db_path=db).new_swims_total == 2

    def test_missing_watch(self, db):
        res = lw.poll_watch("nope", fetcher=_fetcher(SESSION_1), db_path=db)
        assert res.status == "missing" and "not found" in res.error

    def test_last_error_omits_raw_exception_text(self, db):
        # last_error is displayed in the UI ("Last issue"); it must carry a
        # short stable phrase, never the raw internal exception string (which
        # can embed filesystem paths or other internal detail).
        w = self._watch(db)

        def dead(url):
            raise OSError("/etc/secret/path leaked here")

        res = lw.poll_watch(w.id, fetcher=dead, now=NOW, db_path=db)
        assert "fetch failed" in res.error and "secret" not in res.error.lower()
        assert "secret" not in (lw.get_watch(w.id, db_path=db).last_error or "").lower()

        # Runner blow-up: stable prefix kept, raw detail dropped.
        w2 = self._watch(db)

        def boom(watch, data, keys):
            raise RuntimeError("/var/secret/token boom")

        res2 = lw.poll_watch(
            w2.id,
            fetcher=_fetcher(SESSION_1),
            runner=boom,
            notifier=RecordingNotifier(),
            now=NOW,
            db_path=db,
        )
        assert "runner failed" in res2.error and "secret" not in res2.error.lower()
        assert "secret" not in (lw.get_watch(w2.id, db_path=db).last_error or "").lower()

        # Parse failure carries no appended internal detail either.
        w3 = self._watch(db)
        res3 = lw.poll_watch(w3.id, fetcher=_fetcher(b"\x00\x01 not results"), now=NOW, db_path=db)
        assert res3.error == "parse failed; will retry"


# ---------------------------------------------------------------------------
# scheduler task type
# ---------------------------------------------------------------------------


class TestSchedulerTask:
    def test_register_and_handler_polls_due_watches(self, db):
        import mediahub.scheduler as scheduler

        w = lw.create_watch("org-a", URL, run_id="run-9", db_path=db)
        runner, notifier = RecordingRunner(), RecordingNotifier()
        lw.register_live_watch_task(runner=runner, fetcher=_fetcher(SESSION_1), notifier=notifier)
        assert lw.TASK_TYPE in scheduler.registered_task_types()
        handler = scheduler._REGISTRY[lw.TASK_TYPE]
        handler({"db_path": str(db)})
        assert len(runner.calls) == 1
        assert runner.calls[0][0] == w.id
        assert lw.get_watch(w.id, db_path=db).polls == 1
        # Immediately re-running the handler is a no-op: nothing is due yet
        handler({"db_path": str(db)})
        assert len(runner.calls) == 1

    def test_one_watch_failure_does_not_stop_the_rest(self, db, monkeypatch):
        import mediahub.scheduler as scheduler

        lw.create_watch("org-a", URL, db_path=db)
        b = lw.create_watch("org-b", URL + "?x=2", db_path=db)
        polled = []
        real_poll = lw.poll_watch

        def flaky(watch_id, **kw):
            if not polled:
                polled.append(watch_id)
                raise RuntimeError("boom")
            polled.append(watch_id)
            return real_poll(watch_id, **kw)

        monkeypatch.setattr(lw, "poll_watch", flaky)
        lw.register_live_watch_task(
            runner=RecordingRunner(), fetcher=_fetcher(SESSION_1), notifier=RecordingNotifier()
        )
        scheduler._REGISTRY[lw.TASK_TYPE]({"db_path": str(db)})
        assert len(polled) == 2  # second watch still polled
        assert lw.get_watch(b.id, db_path=db).polls == 1


# ---------------------------------------------------------------------------
# dedupe-key derivation
# ---------------------------------------------------------------------------


class TestSwimKeys:
    def test_keys_are_deterministic_and_skip_timeless_swims(self):
        from mediahub.interpreter import interpret_document

        meet = interpret_document(SESSION_1_PLUS_ONE)
        keys = lw.swim_keys_for_meet(meet)
        assert keys == lw.swim_keys_for_meet(interpret_document(SESSION_1_PLUS_ONE))
        assert len(keys) == 3
        for k in keys:
            name, identity, time = k.split("|")
            assert name == name.casefold()
            assert identity.count(",") == 3  # gender,distance,stroke,course
            assert time

    def test_digest_is_order_independent(self):
        assert lw._digest({"b", "a"}) == lw._digest({"a", "b"})
        assert lw._digest({"a"}) != lw._digest({"a", "b"})
