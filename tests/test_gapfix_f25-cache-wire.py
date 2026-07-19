"""Regression test for F25 wiring: the meet-freshness gate in
``WarmCache.get`` must actually be consulted by the production entry point
``discover_swimmer_pbs``.

The gate (cache.py) rejects a warm baseline captured more than
``MEET_FRESHNESS_GRACE`` before the meet being processed — otherwise a swim is
compared against a stale baseline that never saw an intervening competition's
PBs and a slower-than-true-PB swim is announced as a "new PB". That gate was
dead code because the only production caller never passed ``meet_date``. This
test drives the end-to-end path and asserts the stale warm entry is NOT served
when a meet date past the grace window is supplied.
"""

import json
import time

import pytest


@pytest.fixture()
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Belt-and-braces: keep discovery fully offline and deterministic.
    monkeypatch.setenv("MEDIAHUB_PB_DISCOVERY_PARALLEL", "0")
    return tmp_path


def _stub_out_network(monkeypatch):
    """Make discovery's live-research path a no-op so a warm-cache MISS resolves
    to an empty, non-cache-hit result instead of touching the network."""
    import mediahub.pb_discovery.discover as disc

    class _NoHits:
        def __init__(self, *a, **k):
            pass

        def search(self, *a, **k):
            return []

    monkeypatch.setattr(disc, "ResearchClient", _NoHits)


def _seed_warm_entry(swimmer_key: str, *, saved_at_ts: float) -> None:
    """Write a warm-cache baseline with a controlled capture timestamp."""
    from mediahub.pb_discovery.cache import WarmCache

    wc = WarmCache()
    payload = {
        "swimmer_query": "Test Swimmer (Test SC)",
        "pbs": [{"event": "100 Free", "time": "55.00", "course": "LC"}],
        "sources": [],
        "confidence": 0.9,
        "cache_hit": False,
    }
    p = wc._base / f"{swimmer_key}.json"
    p.write_text(
        json.dumps(
            {"_saved_at": "seed", "_saved_at_ts": saved_at_ts, "payload": payload}
        ),
        encoding="utf-8",
    )


def test_stale_warm_baseline_not_served_when_meet_postdates_it(
    isolated_data_dir, monkeypatch
):
    from mediahub.pb_discovery import discover_swimmer_pbs
    from mediahub.pb_discovery.cache import WarmCache, make_swimmer_key

    _stub_out_network(monkeypatch)

    name, club = "Test Swimmer", "Test SC"
    swimmer_key = make_swimmer_key(name, club)

    # Baseline captured well before the meet (grace + 2 days earlier), and the
    # meet happens "now" — beyond MEET_FRESHNESS_GRACE.
    now = time.time()
    saved_at = now - (WarmCache.MEET_FRESHNESS_GRACE + 2 * 24 * 3600)
    _seed_warm_entry(swimmer_key, saved_at_ts=saved_at)

    # Meet date is AFTER the grace window relative to the baseline.
    result = discover_swimmer_pbs(
        name=name,
        club=club,
        run_id="run-stale",
        meet_date=now,
    )

    # The stale warm entry must NOT be served: the wired-in meet-freshness gate
    # rejects it, so discovery re-researches (which, with network stubbed, is an
    # empty non-cache-hit result). If meet_date were ignored, cache_hit is True
    # and the stale PB list ships.
    assert result.cache_hit is False


def test_fresh_warm_baseline_still_served_within_grace(isolated_data_dir, monkeypatch):
    from mediahub.pb_discovery import discover_swimmer_pbs
    from mediahub.pb_discovery.cache import WarmCache, make_swimmer_key

    _stub_out_network(monkeypatch)

    name, club = "Fresh Swimmer", "Test SC"
    swimmer_key = make_swimmer_key(name, club)

    # Baseline captured just inside the grace window before the meet.
    now = time.time()
    saved_at = now - (WarmCache.MEET_FRESHNESS_GRACE // 2)
    _seed_warm_entry(swimmer_key, saved_at_ts=saved_at)

    result = discover_swimmer_pbs(
        name=name,
        club=club,
        run_id="run-fresh",
        meet_date=now,
    )

    # Within grace: the warm baseline is still trustworthy and IS served.
    assert result.cache_hit is True


def test_no_meet_date_preserves_legacy_warm_serving(isolated_data_dir, monkeypatch):
    """Back-compat: with no meet_date supplied, the meet gate is disabled and an
    otherwise-fresh (TTL-valid) warm entry is served exactly as before."""
    from mediahub.pb_discovery import discover_swimmer_pbs
    from mediahub.pb_discovery.cache import make_swimmer_key

    _stub_out_network(monkeypatch)

    name, club = "Legacy Swimmer", "Test SC"
    swimmer_key = make_swimmer_key(name, club)

    # A TTL-valid baseline (captured an hour ago). With no meet_date the meet
    # gate is disabled, so it is served exactly as before this fix.
    saved_at = time.time() - 3600
    _seed_warm_entry(swimmer_key, saved_at_ts=saved_at)

    result = discover_swimmer_pbs(name=name, club=club, run_id="run-legacy")

    assert result.cache_hit is True
