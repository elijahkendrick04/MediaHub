#!/usr/bin/env python3
"""Run the V7.5 interpreter against every captured corpus document, report recovery.

Output: samples/learning_corpus/EVAL_REPORT.csv with per-document metrics, and a
summary printed to stdout.
"""
import csv
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mediahub.interpreter import interpret_document

CORPUS = ROOT / "samples" / "learning_corpus"
INDEX = CORPUS / "INDEX.csv"
OUT = CORPUS / "EVAL_REPORT.csv"

rows_in = []
with INDEX.open() as f:
    rows_in = list(csv.DictReader(f))

results = []
for row in rows_in:
    if row["status"] != "captured":
        continue
    fp = row["file_path"]
    if not fp:
        continue
    file_path = ROOT / fp
    if not file_path.exists():
        results.append({**row, "events": 0, "swims": 0, "confidence": 0.0, "error": "missing_file", "elapsed_s": 0.0})
        continue
    try:
        bytes_data = file_path.read_bytes()
        t0 = time.time()
        # Pick hint from extension
        ext = file_path.suffix.lower().lstrip(".")
        hint = None  # let interpreter sniff
        interpreted = interpret_document(
            bytes_data, hint=hint, source_path=file_path
        )
        elapsed = time.time() - t0
        n_events = len(interpreted.events)
        n_swims = sum(len(e.swims) for e in interpreted.events)
        results.append({
            **row,
            "events": n_events,
            "swims": n_swims,
            "confidence": round(interpreted.overall_confidence, 3),
            "error": "",
            "elapsed_s": round(elapsed, 2),
        })
        print(f"OK   {row['meet_name'][:50]:50s} fmt={row['format']:10s} events={n_events:3d} swims={n_swims:5d} conf={interpreted.overall_confidence:.2f} t={elapsed:.1f}s")
    except Exception as e:
        results.append({**row, "events": 0, "swims": 0, "confidence": 0.0, "error": f"{type(e).__name__}: {e}", "elapsed_s": 0.0})
        print(f"FAIL {row['meet_name'][:50]:50s} fmt={row['format']:10s} err={type(e).__name__}: {str(e)[:80]}")

# Write report
fieldnames = ["level", "month", "meet_name", "host_club", "format", "file_path", "source_url", "status", "events", "swims", "confidence", "elapsed_s", "error"]
with OUT.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(results)

# Summary
total = len(results)
ok = sum(1 for r in results if r["error"] == "" and r["swims"] > 0)
total_swims = sum(r["swims"] for r in results)
total_events = sum(r["events"] for r in results)
mean_conf = sum(r["confidence"] for r in results if r["confidence"] > 0) / max(1, sum(1 for r in results if r["confidence"] > 0))

print("\n=== SUMMARY ===")
print(f"Documents tried:    {total}")
print(f"Yielded ≥1 swim:    {ok} ({100*ok//max(1,total)}%)")
print(f"Total events:       {total_events}")
print(f"Total swims:        {total_swims}")
print(f"Mean confidence:    {mean_conf:.2f}")

# Group by format
from collections import defaultdict
by_fmt = defaultdict(lambda: {"n": 0, "ok": 0, "swims": 0})
for r in results:
    f = r["format"]
    by_fmt[f]["n"] += 1
    if r["error"] == "" and r["swims"] > 0:
        by_fmt[f]["ok"] += 1
    by_fmt[f]["swims"] += r["swims"]

print("\nPer-format recovery:")
for f, s in sorted(by_fmt.items()):
    pct = 100 * s["ok"] // max(1, s["n"])
    print(f"  {f:12s} {s['ok']:2d}/{s['n']:2d} ({pct:3d}%)  {s['swims']:5d} swims")

print(f"\nReport: {OUT}")
