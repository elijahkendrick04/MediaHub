"""
test_pdf_extraction_accuracy.py — ground-truth accuracy gate for PDF reading.

Locks in the rewrite that took swim-result PDF reading from F1 0.53 to 0.99 on
a real championship PDF (scored against its parallel Hy-Tek .hy3 export) and to
exact reads across the synthetic layout corpus. Unlike test_corpus_recovery
(which only checks that *some* swims come out), this asserts the swims are
*correct* — the right competitor, time, place and event.

The harness lives in scripts/eval_pdf_accuracy.py so it is runnable by hand
(``python scripts/eval_pdf_accuracy.py``) and reused here as the gate.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

pytest.importorskip("pdfplumber", reason="pdfplumber required for PDF accuracy gate")
pytest.importorskip("reportlab", reason="reportlab required to render the synthetic corpus")

import eval_pdf_accuracy as E  # noqa: E402


@pytest.fixture(scope="module")
def metrics() -> dict:
    return E.compute_metrics()


# ---------------------------------------------------------------------------
# Real anchor — a genuine championship PDF vs its machine-readable .hy3.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (E.ANCHOR_DIR / "results.pdf").exists()
    or not (E.ANCHOR_DIR / "results_hy3.zip").exists(),
    reason="real anchor pair (PDF + .hy3) not present in this checkout",
)
class TestRealAnchor:
    def test_row_f1_at_least_0_95(self, metrics):
        f1 = metrics["anchor_f1"]
        assert f1 >= 0.95, f"anchor row F1 {f1:.4f} regressed below 0.95 (pre-rewrite was 0.53)"

    def test_recall_at_least_0_95(self, metrics):
        r = metrics["anchor_recall"]
        assert r >= 0.95, f"anchor recall {r:.4f} below 0.95 — results are being dropped"

    def test_place_accuracy_at_least_0_95(self, metrics):
        p = metrics["anchor_place_acc"]
        assert p >= 0.95, f"anchor place accuracy {p:.4f} below 0.95 on matched rows"

    def test_event_accuracy_at_least_0_95(self, metrics):
        e = metrics["anchor_event_acc"]
        assert e >= 0.95, f"anchor event accuracy {e:.4f} below 0.95 — swims paired to wrong events"


# ---------------------------------------------------------------------------
# Synthetic corpus — exact ground truth across real-world layout families.
# ---------------------------------------------------------------------------


class TestSyntheticCorpus:
    def test_row_f1_at_least_0_97(self, metrics):
        f1 = metrics["synthetic_f1"]
        assert f1 >= 0.97, f"synthetic row F1 {f1:.4f} below 0.97"

    def test_full_row_accuracy_at_least_0_95(self, metrics):
        """name + time + place + club + event ALL exact — the strict measure."""
        acc = metrics["synthetic_full_row_acc"]
        assert acc >= 0.95, f"synthetic full-row accuracy {acc:.4f} below the 0.95 target"

    def test_every_layout_individually_at_least_0_90(self, metrics):
        weak = {s.name: round(s.f1, 3) for s in metrics["synthetic"] if s.f1 < 0.90}
        assert not weak, f"these layouts regressed below 0.90 F1: {weak}"
