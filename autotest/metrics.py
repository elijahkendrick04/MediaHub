#!/usr/bin/env python3
"""Judge-trust metrics (A5): measure the LLM council's precision/recall against a
human-labelled calibration set, so "is the council trustworthy?" becomes a NUMBER,
not a vibe. The human labels are ground truth; the council's keep/demote verdicts
(read from the ledger) are the noisy predictions being scored.

  precision = of the findings the council KEPT as real bugs, how many a human agrees
              are real  → high precision == low false-positive noise (the report's goal).
  recall    = of the findings a human says are real, how many the council KEPT
              → low recall == the council is demoting real bugs.

The measured precision is written to ``autotest/calibration/precision.json``, where
``report.py`` reads it to (a) print the BUGS.md "🔬 Judge trust" line and (b) scale
the A1 confirm gate (low precision → demand more confirmations before opening a bug).

Anti-"blind-trust" guard (the report's central warning): a precision is only
PUBLISHED to precision.json once enough labels are HUMAN-CURATED
(``AUTOTEST_CALIBRATION_MIN_CURATED``, default 20). An auto-seeded set trivially
agrees with the council, so until a human reviews it — especially adding cases where
they DISAGREE — the live system keeps its defaults (precision = null).

Calibration set: ``autotest/calibration/labels.jsonl`` (one JSON object per line):
  {"fingerprint": "...", "category": "...", "title": "...", "label": "real"|"noise"}
Curate by hand (see ``calibration/README.md``). ``python -m autotest.metrics --seed``
drafts a starter set from the current ledger for a human to review.

Sources (docs/autotest/AUTOTEST_BENCHMARK_AND_GAPS.md, A5): "Noisy but Valid"
(calibration set → TPR/FPR; arXiv:2601.20913), ChainPoll / 2-of-3 panel voting
(arXiv:2310.18344), and the cautionary "A Coin Flip for Safety" (arXiv:2603.06594) /
"confabulation consensus" (arXiv:2602.09341).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autotest import report

CALIBRATION_DIR = Path(__file__).resolve().parent / "calibration"
LABELS_PATH = CALIBRATION_DIR / "labels.jsonl"
PRECISION_PATH = CALIBRATION_DIR / "precision.json"
METRICS_MD_PATH = report.REPORTS_DIR / "METRICS.md"

_VALID = {"real", "noise"}


def _min_curated() -> int:
    return report._env_int("AUTOTEST_CALIBRATION_MIN_CURATED", 20)


def load_labels(path: Path | None = None) -> list[dict]:
    """Read labels.jsonl (one JSON object per line). Tolerates blanks / comments
    (``#``) and malformed lines (skipped) so a half-edited file never crashes CI."""
    path = path or LABELS_PATH
    out: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("label") in _VALID and obj.get("fingerprint"):
            out.append(obj)
    return out


def _is_curated(item: dict) -> bool:
    """A human-reviewed label (not the auto-seed draft). The auto-seeder stamps
    ``source`` with 'auto-seed'; a human removes/replaces it when they confirm."""
    return "auto-seed" not in str(item.get("source", "")).lower()


def council_prediction(fingerprint: str, ledger: dict[str, Any]) -> str | None:
    """The council's verdict for a fingerprint, derived from the ledger: ``real`` if
    it was kept as a bug, ``noise`` if it was demoted (``council:noise``) or skipped.
    None when the fingerprint isn't in the ledger (no prediction to score)."""
    entry = ledger.get("bugs", {}).get(fingerprint)
    if entry is not None:
        return "noise" if "council:noise" in str(entry.get("category", "")) else "real"
    if fingerprint in ledger.get("skipped", {}):
        return "noise"
    return None


def compute(labels: list[dict], ledger: dict[str, Any]) -> dict[str, Any]:
    """Confusion-matrix precision/recall of the council vs the human labels. Only
    labels with a council prediction are scored. precision/recall are None when the
    denominator is zero (no positive predictions / no real labels)."""
    tp = fp = fn = tn = 0
    scored = 0
    for item in labels:
        truth = item.get("label")
        if truth not in _VALID:
            continue
        pred = council_prediction(str(item.get("fingerprint", "")), ledger)
        if pred is None:
            continue
        scored += 1
        if pred == "real" and truth == "real":
            tp += 1
        elif pred == "real" and truth == "noise":
            fp += 1
        elif pred == "noise" and truth == "real":
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    return {
        "precision": precision,
        "recall": recall,
        "n_labelled": len(labels),
        "n_curated": sum(1 for x in labels if _is_curated(x)),
        "n_scored": scored,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


def write_precision(metrics: dict[str, Any], *, min_curated: int | None = None) -> dict[str, Any]:
    """Publish the council's measured precision/recall to precision.json — but only
    a real number once enough labels are HUMAN-curated (anti-blind-trust). Otherwise
    publishes null so the live system (report.py) keeps its defaults. Returns the
    published payload."""
    min_curated = _min_curated() if min_curated is None else min_curated
    publish = metrics["n_curated"] >= min_curated and metrics["precision"] is not None
    payload = {
        "precision": metrics["precision"] if publish else None,
        "recall": metrics["recall"] if publish else None,
        "n_labelled": metrics["n_labelled"],
        "n_curated": metrics["n_curated"],
        "n_scored": metrics["n_scored"],
        "computed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "note": ("" if publish else
                 f"not published: only {metrics['n_curated']}/{min_curated} labels are "
                 "human-curated — using defaults (precision=null) to avoid blind trust"),
    }
    CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
    PRECISION_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def seed_from_ledger(ledger: dict[str, Any]) -> list[dict]:
    """Draft a starter calibration set from the ledger's CLEAR cases (council-demoted
    / blind-spot → noise; verified-fixed → real-or-noise from its note). Open findings
    are left UNLABELLED — a human decides those. Every draft is stamped
    ``source='auto-seed (review me)'`` so it doesn't count as curated until reviewed."""
    drafts: list[dict] = []

    def _add(fp: str, e: dict, label: str, note: str) -> None:
        drafts.append({"fingerprint": fp, "category": e.get("category", ""),
                       "title": (e.get("title", "") or "")[:120], "label": label,
                       "source": "auto-seed (review me)", "note": note})

    for fp, e in ledger.get("bugs", {}).items():
        cat = str(e.get("category", ""))
        if not report.is_subjective(cat):
            continue  # the council only judges subjective findings
        if "council:noise" in cat:
            _add(fp, e, "noise", "council demoted")
        elif cat.startswith("council:blind_spot"):
            _add(fp, e, "noise", "council blind-spot theory (meta — no reproducible route)")
        elif e.get("status") == "verified-fixed":
            note = str((e.get("verified_fixed") or {}).get("note", "")).lower()
            _add(fp, e, "noise" if "false" in note else "real", f"verified-fixed: {note[:80]}")
        # open / pending / fixing left unlabelled on purpose.
    for fp, e in ledger.get("skipped", {}).items():
        if "council:noise" in str(e.get("category", "")):
            _add(fp, e, "noise", "council demoted (skipped bucket)")
    return drafts


def _summary_line(m: dict[str, Any]) -> str:
    if m["precision"] is None:
        return (f"🔬 Judge trust: insufficient data — {m['n_scored']} scored of "
                f"{m['n_labelled']} labelled ({m['n_curated']} human-curated). "
                "Curate autotest/calibration/labels.jsonl to activate.")
    r = f"{m['recall']:.2f}" if m["recall"] is not None else "n/a"
    return (f"🔬 Judge trust: council precision {m['precision']:.2f} · recall {r} "
            f"(tp={m['tp']} fp={m['fp']} fn={m['fn']} tn={m['tn']}; "
            f"{m['n_curated']} human-curated of {m['n_labelled']} labelled)")


def _write_metrics_md(m: dict[str, Any], published: dict[str, Any]) -> None:
    lines = [
        "# Autotest trust metrics (A5)", "",
        "> Regenerated by `python -m autotest.metrics`. The council's precision/recall "
        "vs the human-labelled calibration set (`autotest/calibration/labels.jsonl`).", "",
        f"- {_summary_line(m)}",
        f"- **Published to precision.json:** "
        + ("yes" if published.get("precision") is not None else f"no — {published.get('note', '')}"),
        f"- **Computed:** `{published.get('computed_at', '?')}`", "",
        "See `docs/autotest/AUTOTEST_BENCHMARK_AND_GAPS.md` (A5) for the methodology and sources.",
        "",
    ]
    METRICS_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_MD_PATH.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ledger = report.load_ledger()

    if "--seed" in argv:
        drafts = seed_from_ledger(ledger)
        existing = {x.get("fingerprint") for x in load_labels()}
        new = [d for d in drafts if d["fingerprint"] not in existing]
        CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
        with open(LABELS_PATH, "a", encoding="utf-8") as fh:
            for d in new:
                fh.write(json.dumps(d) + "\n")
        print(f"seeded {len(new)} draft label(s) into {LABELS_PATH} "
              f"({len(drafts) - len(new)} already present). Review them by hand.")
        return 0

    labels = load_labels()
    m = compute(labels, ledger)
    published = write_precision(m)
    _write_metrics_md(m, published)
    line = _summary_line(m)
    print(line)
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        try:
            with open(step, "a", encoding="utf-8") as fh:
                fh.write(f"### {line}\n\n")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
