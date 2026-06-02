"""A5 (Tier A): judge-trust metrics — the council's precision/recall vs a
human-labelled calibration set, with the anti-blind-trust publish gate.

Asserts on ground truth (the confusion-matrix maths, the publish gate, the seeder),
never on a live council.
"""
from __future__ import annotations

import json

import pytest

from autotest import metrics


def _ledger(bugs=None, skipped=None):
    return {"schema": 2, "bugs": bugs or {}, "skipped": skipped or {}}


# --- council_prediction ------------------------------------------------------
def test_prediction_real_when_kept_as_bug():
    led = _ledger(bugs={"f1": {"category": "semantic:functional"}})
    assert metrics.council_prediction("f1", led) == "real"


def test_prediction_noise_when_council_demoted():
    led = _ledger(bugs={"f2": {"category": "semantic:user_brain (council:noise)"}})
    assert metrics.council_prediction("f2", led) == "noise"


def test_prediction_noise_when_skipped():
    led = _ledger(skipped={"f3": {"category": "semantic:functional (council:noise)"}})
    assert metrics.council_prediction("f3", led) == "noise"


def test_prediction_none_when_absent():
    assert metrics.council_prediction("nope", _ledger()) is None


# --- compute (confusion matrix) ---------------------------------------------
def test_compute_precision_and_recall():
    # council kept f1 (real✓), f2 (noise✗ → FP); demoted f3 (real → FN), f4 (noise → TN)
    led = _ledger(
        bugs={"f1": {"category": "semantic:functional"},
              "f2": {"category": "semantic:user_brain"}},
        skipped={"f3": {"category": "semantic:functional (council:noise)"},
                 "f4": {"category": "vision:review (council:noise)"}})
    labels = [
        {"fingerprint": "f1", "label": "real"},
        {"fingerprint": "f2", "label": "noise"},
        {"fingerprint": "f3", "label": "real"},
        {"fingerprint": "f4", "label": "noise"},
    ]
    m = metrics.compute(labels, led)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 1, 1, 1)
    assert m["precision"] == 0.5 and m["recall"] == 0.5
    assert m["n_scored"] == 4


def test_compute_precision_none_without_positive_predictions():
    led = _ledger(skipped={"f1": {"category": "semantic:x (council:noise)"}})
    m = metrics.compute([{"fingerprint": "f1", "label": "noise"}], led)
    assert m["precision"] is None     # no TP/FP → undefined, not a crash


def test_compute_skips_unpredicted_labels():
    m = metrics.compute([{"fingerprint": "ghost", "label": "real"}], _ledger())
    assert m["n_scored"] == 0 and m["precision"] is None


# --- load_labels tolerance ---------------------------------------------------
def test_load_labels_tolerates_blanks_comments_and_garbage(tmp_path, monkeypatch):
    p = tmp_path / "labels.jsonl"
    p.write_text('\n# a comment\n{"fingerprint":"a","label":"real"}\nnot json\n'
                 '{"fingerprint":"b","label":"bogus"}\n{"fingerprint":"c","label":"noise"}\n')
    monkeypatch.setattr(metrics, "LABELS_PATH", p)
    labels = metrics.load_labels()
    fps = {x["fingerprint"] for x in labels}
    assert fps == {"a", "c"}          # blank/comment/garbage/invalid-label all dropped


# --- the publish gate (anti-blind-trust) ------------------------------------
def test_precision_not_published_below_min_curated(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics, "PRECISION_PATH", tmp_path / "precision.json")
    monkeypatch.setattr(metrics, "CALIBRATION_DIR", tmp_path)
    m = {"precision": 1.0, "recall": 1.0, "n_labelled": 5, "n_curated": 3,
         "n_scored": 5, "tp": 5, "fp": 0, "fn": 0, "tn": 0}
    published = metrics.write_precision(m, min_curated=20)
    assert published["precision"] is None and "not published" in published["note"]


def test_precision_published_when_curated_enough(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics, "PRECISION_PATH", tmp_path / "precision.json")
    monkeypatch.setattr(metrics, "CALIBRATION_DIR", tmp_path)
    m = {"precision": 0.83, "recall": 0.9, "n_labelled": 40, "n_curated": 25,
         "n_scored": 40, "tp": 30, "fp": 6, "fn": 4, "tn": 0}
    published = metrics.write_precision(m, min_curated=20)
    assert published["precision"] == 0.83 and published["recall"] == 0.9
    on_disk = json.loads((tmp_path / "precision.json").read_text())
    assert on_disk["precision"] == 0.83


def test_is_curated_distinguishes_autoseed_from_human():
    assert metrics._is_curated({"label": "real"}) is True                      # no marker → human
    assert metrics._is_curated({"label": "real", "source": "human"}) is True
    assert metrics._is_curated({"label": "real", "source": "auto-seed (review me)"}) is False


# --- seeder ------------------------------------------------------------------
def test_seed_classifies_clear_cases():
    led = _ledger(bugs={
        "bs": {"category": "council:blind_spot", "title": "theory"},
        "vf_false": {"category": "semantic:functional", "status": "verified-fixed",
                     "verified_fixed": {"note": "false-positive: legit empty state"}},
        "vf_real": {"category": "semantic:user_brain", "status": "verified-fixed",
                    "verified_fixed": {"note": "the real ux gap"}},
        "open_sub": {"category": "semantic:functional", "status": "open"},  # left unlabelled
        "det": {"category": "http_5xx", "status": "open"},                  # not subjective
    })
    drafts = {d["fingerprint"]: d for d in metrics.seed_from_ledger(led)}
    assert drafts["bs"]["label"] == "noise"
    assert drafts["vf_false"]["label"] == "noise"
    assert drafts["vf_real"]["label"] == "real"
    assert "open_sub" not in drafts and "det" not in drafts   # not auto-labelled
    assert all("auto-seed" in d["source"] for d in drafts.values())
