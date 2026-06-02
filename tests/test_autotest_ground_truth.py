"""Ground-truth regression oracle (LLM Council 2026-06-01).

The finder's live-prod sweep has no ground truth, so it can't tell a real defect
from correct behaviour. ``autotest/ground_truth.py`` fixes that: it runs the
canonical sample meet through the real pipeline with a club that matches it and
diffs the deterministic output against a committed golden baseline. A mismatch is
a falsifiable, reproducible regression finding.

The fast tests stub the pipeline and assert the invariant logic; the slow test
runs the real pipeline and asserts the committed baseline actually matches reality
(so the oracle neither false-fires nor sleeps through a real change).
"""
from __future__ import annotations

import json

import pytest

from autotest import baseline, ground_truth


class _FakeCard:
    def __init__(self, names):
        self.swimmer_names = names


class _FakeRun:
    def __init__(self, *, error=None, n_cards=177, n_ranked=177, parsed=1217,
                 ours=195, name="Amelia Osborne"):
        self.error = error
        self.cards = [_FakeCard([name]) for _ in range(n_cards)]
        self.recognition_report = {
            "ranked_achievements": [{} for _ in range(n_ranked)],
            "n_achievements": n_ranked,
        }
        self.parsed_swim_count = parsed
        self.our_swim_count = ours


@pytest.fixture
def stub(monkeypatch, tmp_path):
    """A controlled golden baseline + the oracle, independent of the committed file."""
    if not ground_truth.SAMPLE.exists():
        pytest.skip("sample meet missing")
    bp = tmp_path / "golden-baseline.json"
    bp.write_text(json.dumps({
        "cards": 177, "achievements": 177, "export_ok": True,
        "club_filter": "City of Manchester Aquatics", "parsed_swim_count": 1217,
        "known_swimmers": ["Amelia Osborne"],
    }), encoding="utf-8")
    monkeypatch.setattr(baseline, "BASELINE_PATH", bp)
    return monkeypatch


def _run_returns(monkeypatch, run):
    import mediahub.pipeline.pipeline_v4 as p
    monkeypatch.setattr(p, "run_pipeline_v4", lambda **k: run)


def _bugs():
    return [f for f in ground_truth.check() if getattr(f, "is_bug", True)]


def test_healthy_pipeline_yields_no_regression(stub):
    _run_returns(stub, _FakeRun())
    assert _bugs() == []


def test_parser_regression_fires(stub):
    _run_returns(stub, _FakeRun(parsed=1200))  # fixed PDF must parse to 1217
    assert any("Parser regression" in f.title for f in _bugs())


def test_zero_cards_fires_via_baseline_floor(stub):
    _run_returns(stub, _FakeRun(n_cards=0, n_ranked=0))  # the headline empty-pack bug
    assert _bugs(), "0 cards on the golden meet must be flagged"


def test_club_mismatch_fires(stub):
    _run_returns(stub, _FakeRun(ours=0))  # club known to be in the meet matched nothing
    assert any("Club-matching" in f.title for f in _bugs())


def test_bridge_regression_fires(stub):
    _run_returns(stub, _FakeRun(n_cards=177, n_ranked=150))  # cards != ranked
    assert any("bridge" in f.title.lower() for f in _bugs())


def test_detection_drift_fires_when_no_known_swimmer(stub):
    _run_returns(stub, _FakeRun(name="Nobody McUnknown"))
    assert any("Detection drift" in f.title for f in _bugs())


def test_pipeline_crash_is_a_regression(stub):
    import mediahub.pipeline.pipeline_v4 as p

    def _boom(**k):
        raise RuntimeError("kaboom")

    stub.setattr(p, "run_pipeline_v4", _boom)
    assert any("raised" in f.title.lower() for f in _bugs())


def test_run_error_is_a_regression(stub):
    _run_returns(stub, _FakeRun(error="parse failed"))
    assert any("failed to process" in f.title.lower() for f in _bugs())


def test_missing_sample_skips_without_a_false_regression(stub, monkeypatch, tmp_path):
    monkeypatch.setattr(ground_truth, "SAMPLE", tmp_path / "nope.pdf")
    out = ground_truth.check()
    assert out and out[0].is_bug is False and "skipped" in out[0].category


def test_committed_baseline_matches_reality():
    """The REAL pipeline on the committed baseline must yield zero regressions —
    proves the golden numbers are accurate (the oracle won't false-fire in CI) and
    that the full parse→detect→rank→cards path is healthy on the known input.
    (~17s: runs the real pipeline, like test_v5_v3_card_bridge.)"""
    if not ground_truth.SAMPLE.exists():
        pytest.skip("sample meet missing")
    bugs = [f for f in ground_truth.check() if getattr(f, "is_bug", True)]
    assert bugs == [], f"committed golden baseline drifted from reality: {[b.title for b in bugs]}"
