"""
swim_content_pb/ground_truth.py
PB-specific ground-truth harness.

Load a CSV of expected PB outcomes, find each entry in the run's PB
decisions, compare, and output precision/recall metrics.

CSV format (with header row):
  swimmer_name, event_label, result_time, expected_pb, expected_prev_pb,
  expected_barrier_crossed, notes

expected_pb: "yes" | "no" | "unknown"
expected_barrier_crossed: "yes" | "no" | "" (empty = not checked)
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class GroundTruthEntry:
    swimmer_name: str
    event_label: str           # "100 Freestyle LC"
    result_time: str
    expected_pb: str           # "yes" | "no" | "unknown"
    expected_prev_pb: Optional[str]
    expected_barrier_crossed: Optional[bool]
    notes: Optional[str]


@dataclass
class GroundTruthResult:
    entry: GroundTruthEntry
    matched_decision: Optional[dict]   # PBDecision serialised dict
    actual_status: Optional[str]       # actual PBDecision.status
    outcome: str  # "true_positive" | "false_positive" | "false_negative" | "correct_rejection" | "skipped" | "unknown_expected"
    mismatch_details: Optional[str]


@dataclass
class GroundTruthReport:
    run_id: str
    truth_csv_path: str
    total_entries: int
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    correct_rejections: int = 0
    skipped: int = 0
    ambiguous: int = 0
    precision: Optional[float] = None
    recall: Optional[float] = None
    f1: Optional[float] = None
    results: list = field(default_factory=list)   # list[GroundTruthResult]
    warnings: list = field(default_factory=list)


def _normalise_name(name: str) -> str:
    """Simple normalise for matching swimmer names in ground truth."""
    return name.strip().upper()


def _normalise_event(label: str) -> str:
    """Normalise event label: '100 Freestyle LC' → '100M FREESTYLE (LC)'."""
    label = label.strip().upper()
    # Attempt to normalise spacing
    label = label.replace("  ", " ")
    return label


def _parse_bool(s: Optional[str]) -> Optional[bool]:
    if not s:
        return None
    sl = s.strip().lower()
    if sl in ("yes", "true", "1", "y"):
        return True
    if sl in ("no", "false", "0", "n"):
        return False
    return None


def load_ground_truth_csv(csv_path: Path) -> tuple[list[GroundTruthEntry], list[str]]:
    """Load ground truth CSV. Returns (entries, warnings)."""
    entries: list[GroundTruthEntry] = []
    warnings: list[str] = []
    try:
        text = csv_path.read_text(encoding="utf-8-sig")
    except Exception as e:
        return [], [f"Could not read CSV: {e}"]

    reader = csv.DictReader(io.StringIO(text))
    required = {"swimmer_name", "event_label", "result_time", "expected_pb"}
    for i, row in enumerate(reader, start=2):
        missing = required - {k.strip().lower() for k in row.keys()}
        if missing:
            warnings.append(f"Row {i}: missing columns {missing}")
            continue
        # Normalise keys
        row = {k.strip().lower(): (v.strip() if v else "") for k, v in row.items()}
        entries.append(GroundTruthEntry(
            swimmer_name=row.get("swimmer_name", ""),
            event_label=row.get("event_label", ""),
            result_time=row.get("result_time", ""),
            expected_pb=row.get("expected_pb", "unknown").lower(),
            expected_prev_pb=row.get("expected_prev_pb") or None,
            expected_barrier_crossed=_parse_bool(row.get("expected_barrier_crossed")),
            notes=row.get("notes") or None,
        ))
    return entries, warnings


def run_ground_truth(
    *,
    run_id: str,
    truth_csv_path: Path,
    run_pb_audit_dict: Optional[dict] = None,
    decisions_by_swim_id: Optional[dict] = None,
) -> GroundTruthReport:
    """Load CSV, find each entry in the run's PB decisions, compare.

    run_pb_audit_dict: serialised RunPBAudit (from stored JSON)
    decisions_by_swim_id: optional pre-built lookup {swim_id: PBDecision}
    """
    entries, warnings = load_ground_truth_csv(truth_csv_path)
    report = GroundTruthReport(
        run_id=run_id,
        truth_csv_path=str(truth_csv_path),
        total_entries=len(entries),
        warnings=warnings,
    )

    if not entries:
        return report

    # Build a lookup from per_swimmer decisions
    # Key: (normalised_name, normalised_event) → list of decisions
    decision_lookup: dict[tuple, list[dict]] = {}

    if run_pb_audit_dict:
        for swimmer_audit in run_pb_audit_dict.get("per_swimmer", []):
            sname = _normalise_name(swimmer_audit.get("hy3_name", ""))
            sr_name = _normalise_name(swimmer_audit.get("sr_name") or "")
            for dec in swimmer_audit.get("pb_decisions", []):
                ev = _normalise_event(dec.get("event", ""))
                for key in [sname, sr_name]:
                    if key:
                        decision_lookup.setdefault((key, ev), []).append(dec)

    results: list[GroundTruthResult] = []
    for entry in entries:
        norm_name = _normalise_name(entry.swimmer_name)
        norm_event = _normalise_event(entry.event_label)

        matches = decision_lookup.get((norm_name, norm_event), [])

        if not matches:
            # Try partial name match
            for (k_name, k_event), decs in decision_lookup.items():
                if norm_name in k_name or k_name in norm_name:
                    if norm_event == k_event:
                        matches = decs
                        break

        if not matches:
            results.append(GroundTruthResult(
                entry=entry,
                matched_decision=None,
                actual_status=None,
                outcome="skipped",
                mismatch_details="No matching PBDecision found in run.",
            ))
            report.skipped += 1
            continue

        # Use the first match (should be unique per swimmer+event)
        dec = matches[0]
        actual_status = dec.get("status", "")

        # Evaluate
        expected_is_pb = entry.expected_pb == "yes"
        expected_not_pb = entry.expected_pb == "no"
        expected_unknown = entry.expected_pb == "unknown"

        actual_is_pb = actual_status in ("CONFIRMED_PB", "LIKELY_PB")

        if expected_unknown:
            outcome = "unknown_expected"
            report.ambiguous += 1
        elif expected_is_pb and actual_is_pb:
            outcome = "true_positive"
            report.true_positives += 1
        elif expected_is_pb and not actual_is_pb:
            outcome = "false_negative"
            report.false_negatives += 1
        elif expected_not_pb and actual_is_pb:
            outcome = "false_positive"
            report.false_positives += 1
        elif expected_not_pb and not actual_is_pb:
            outcome = "correct_rejection"
            report.correct_rejections += 1
        else:
            outcome = "ambiguous"
            report.ambiguous += 1

        mismatch = None
        if outcome in ("false_positive", "false_negative"):
            mismatch = (
                f"Expected pb={entry.expected_pb}, "
                f"actual status={actual_status}"
            )

        results.append(GroundTruthResult(
            entry=entry,
            matched_decision=dec,
            actual_status=actual_status,
            outcome=outcome,
            mismatch_details=mismatch,
        ))

    report.results = results

    # Precision / Recall / F1
    tp = report.true_positives
    fp = report.false_positives
    fn = report.false_negatives

    if tp + fp > 0:
        report.precision = round(tp / (tp + fp), 4)
    if tp + fn > 0:
        report.recall = round(tp / (tp + fn), 4)
    if report.precision and report.recall and (report.precision + report.recall) > 0:
        report.f1 = round(
            2 * report.precision * report.recall / (report.precision + report.recall), 4
        )

    return report
