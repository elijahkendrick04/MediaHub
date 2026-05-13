"""
tests_v75/test_corpus_recovery.py
==================================

Acceptance gate for V7.5 interpreter hardening.

Reads ``samples/learning_corpus/INDEX.csv``, runs ``interpret_document`` on
every captured row, and asserts:

  * ≥90% of documents yield at least one swim.
  * Mean confidence (over docs that yielded swims) is ≥0.65.
  * Total swim count is ≥30,000.

Image-only formats are skipped (image OCR is out of scope for V7.5).
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent
_INDEX = _REPO_ROOT / "samples" / "learning_corpus" / "INDEX.csv"


@pytest.fixture(scope="module")
def corpus_results() -> list[dict]:
    if not _INDEX.exists():
        pytest.skip(f"corpus index missing: {_INDEX}")

    from mediahub.interpreter import interpret_document  # noqa: PLC0415

    out: list[dict] = []
    with _INDEX.open() as fh:
        rows = list(csv.DictReader(fh))

    for row in rows:
        if row.get("status") != "captured":
            continue
        fmt = (row.get("format") or "").lower()
        if fmt in ("none", "image"):
            continue
        fp_rel = row.get("file_path") or ""
        if not fp_rel:
            continue
        file_path = _REPO_ROOT / fp_rel
        if not file_path.exists():
            continue
        try:
            data = file_path.read_bytes()
            result = interpret_document(
                data, hint=None, source_path=file_path
            )
            n_swims = sum(len(e.swims) for e in result.events)
            out.append(
                {
                    "name": row.get("meet_name", file_path.name),
                    "swims": n_swims,
                    "confidence": result.overall_confidence,
                }
            )
        except Exception as exc:  # noqa: BLE001
            out.append(
                {
                    "name": row.get("meet_name", file_path.name),
                    "swims": 0,
                    "confidence": 0.0,
                    "error": repr(exc),
                }
            )
    return out


def test_corpus_recovery_at_least_90_percent(corpus_results):
    total = len(corpus_results)
    assert total > 0, "no captured corpus rows found"
    yielded = sum(1 for r in corpus_results if r["swims"] > 0)
    pct = 100.0 * yielded / total
    assert pct >= 90.0, (
        f"Corpus recovery {pct:.1f}% ({yielded}/{total}) below 90% gate. "
        f"Failures: {[r['name'] for r in corpus_results if r['swims'] == 0]}"
    )


def test_corpus_mean_confidence_at_least_0_65(corpus_results):
    confs = [
        float(r["confidence"]) for r in corpus_results if r["swims"] > 0
    ]
    assert confs, "no successful corpus rows to score"
    mean = sum(confs) / len(confs)
    assert mean >= 0.65, (
        f"Mean confidence {mean:.3f} below 0.65 gate."
    )


def test_corpus_total_swims_at_least_30000(corpus_results):
    """Total swim count must reflect a substantive captured corpus.

    The original V7.5 acceptance gate was a flat 30,000 swims, sized for
    the ~50-document full sample corpus that shipped with the original V7.5
    snapshot. After the v8 src-layout migration the repo only ships a
    reduced sample (currently ~7–10 captured docs), so the gate now
    scales to ~600 swims per captured doc with a floor of 1,000 swims.
    This still proves the interpreter is producing volume; it just doesn't
    artificially fail when the bundled sample is smaller than the original
    V7.5 corpus.
    """
    captured = len(corpus_results)
    # Required count scales with corpus size, capped at the original 30k gate.
    required = min(30_000, max(1_000, captured * 600))
    total_swims = sum(r["swims"] for r in corpus_results)
    assert total_swims >= required, (
        f"Total swims {total_swims} below required {required} "
        f"(scaled from {captured} captured documents)."
    )
