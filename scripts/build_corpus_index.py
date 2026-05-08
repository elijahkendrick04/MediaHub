#!/usr/bin/env python3
"""Build samples/learning_corpus/INDEX.csv from per-meet meta.json files."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "samples" / "learning_corpus"

# Status overrides supplied by the corpus subagent
STATUS_OVERRIDES = {
    "level2/2025_10_uoa_autumn_web": "duplicate",
    "level2/2025_05_swim_conwy_whitsun": "skipped",
    "level4/2025_05_witney_district_tt": "skipped",
    "level4/2025_10_harpenden_bryan_thompson": "skipped",
    "level4/2026_02_harpenden_club_champs": "skipped",
    "level1/2026_05_se_region_lc_champs": "conditions_only",
    "level2/2025_05_broch_mayday_graded": "conditions_only",
    "level3/2025_06_swim_conwy_len_thomas": "conditions_only",
    "level3/2025_09_bromley_sprints": "conditions_only",
    "level3/2026_02_chalfont_otters_valentines": "conditions_only",
    "level4/2025_03_coalville_spring_tt_html": "partial",
    "level4/2025_12_city_of_hereford_cc": "partial",
}

def detect_format(meet_dir: Path) -> str:
    files = [p.name.lower() for p in meet_dir.iterdir() if p.is_file()]
    formats = []
    for f in files:
        if f.startswith("results.") or f.startswith("results_"):
            ext = f.rsplit(".", 1)[-1]
            formats.append(ext)
    if not formats:
        # any other file types
        for f in files:
            if f != "meta.json":
                ext = f.rsplit(".", 1)[-1] if "." in f else "?"
                formats.append(ext)
    return "+".join(sorted(set(formats))) or "none"

def find_results_path(meet_dir: Path) -> str:
    for p in sorted(meet_dir.iterdir()):
        if p.is_file() and p.name.lower().startswith("results."):
            return str(p.relative_to(ROOT))
    return ""

rows = []
for level_dir in sorted(CORPUS.iterdir()):
    if not level_dir.is_dir() or not level_dir.name.startswith("level"):
        continue
    level = level_dir.name.replace("level", "")
    for meet_dir in sorted(level_dir.iterdir()):
        if not meet_dir.is_dir():
            continue
        rel_key = f"{level_dir.name}/{meet_dir.name}"
        meta_path = meet_dir / "meta.json"
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
            except Exception:
                meta = {}
        # derive month
        slug = meet_dir.name
        month = "?"
        parts = slug.split("_")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            month = f"{parts[0]}-{parts[1]}"
        elif "dates" in meta and meta.get("dates"):
            d = str(meta["dates"]).strip()
            month = d[:7] if len(d) >= 7 else d

        status = STATUS_OVERRIDES.get(rel_key)
        fmt = detect_format(meet_dir)
        if not status:
            if fmt == "none":
                status = "empty"
            else:
                status = "captured"

        rows.append({
            "level": level,
            "month": month,
            "meet_name": meta.get("meet_name", slug),
            "host_club": meta.get("host_club", ""),
            "format": fmt,
            "file_path": find_results_path(meet_dir),
            "source_url": meta.get("results_url", meta.get("source_url", "")),
            "status": status,
        })

out = CORPUS / "INDEX.csv"
with out.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["level", "month", "meet_name", "host_club", "format", "file_path", "source_url", "status"])
    w.writeheader()
    w.writerows(rows)

print(f"Wrote {len(rows)} rows to {out}")
# Summary
from collections import Counter
status_counts = Counter(r["status"] for r in rows)
fmt_counts = Counter(r["format"] for r in rows)
print("Status:", dict(status_counts))
print("Formats:", dict(fmt_counts))
