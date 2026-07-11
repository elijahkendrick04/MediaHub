"""Colour-literal inventory for Stage A of the Adaptive Theming Engine.

Walks one or more source files looking for hex / rgb / rgba / hsl / oklch
literals and classifies each occurrence by the surrounding context so the
migration in Stage A2 can target only the genuine f-string hardcodes.

Emits:
- CSV at the path passed via --out (default data/stage_a_color_inventory.csv)
- Stdout summary table

Run from repo root:
    python scripts/inventory_colors.py
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path


# The ``(?<!&)`` lookbehind excludes HTML numeric character references such as
# ``&#127912;`` (the 🎨 emoji): those are entities, not CSS colours, but their
# digits (``#127912``) otherwise match ``hex6`` and inflate the hardcode count.
COLOUR_PATTERNS = [
    ("hex8", re.compile(r"(?<!&)#[0-9a-fA-F]{8}\b")),
    ("hex6", re.compile(r"(?<!&)#[0-9a-fA-F]{6}\b")),
    ("hex4", re.compile(r"(?<!&)#[0-9a-fA-F]{4}\b(?![0-9a-fA-F])")),
    ("hex3", re.compile(r"(?<!&)#[0-9a-fA-F]{3}\b(?![0-9a-fA-F])")),
    ("rgba", re.compile(r"rgba\([^)]+\)")),
    ("rgb",  re.compile(r"rgb\([^)]+\)")),
    ("hsla", re.compile(r"hsla\([^)]+\)")),
    ("hsl",  re.compile(r"hsl\([^)]+\)")),
    ("oklch", re.compile(r"oklch\([^)]+\)")),
    ("oklab", re.compile(r"oklab\([^)]+\)")),
]


def _classify(line: str, match_start: int, file_text: str, abs_offset: int) -> str:
    """Tag a literal with where it sits in the file."""
    # Pull surrounding 200-char window from the file for better classification.
    win_lo = max(0, abs_offset - 200)
    win_hi = min(len(file_text), abs_offset + 200)
    window = file_text[win_lo:win_hi]
    line_lower = line.lower()

    # f-string emitting HTML style="..." — the migration target.
    if 'style="' in line or "style='" in line or 'style=\\"' in line:
        if line.lstrip().startswith(("f'", 'f"', "f'''", 'f"""')) or (
            line.lstrip().startswith(("'", '"')) and ("style=" in line and (
                "f'" in line[:line.find("style=")] or 'f"' in line[:line.find("style=")]
            ))
        ):
            return "inline_fstring"
        # Plain "style=" in HTML literal (no f-prefix, but still inline HTML).
        return "inline_html_style"

    # Token definition lines like "  --foo: #fff;" inside :root.
    if re.match(r"\s*--[a-zA-Z0-9_-]+\s*:", line):
        return "token_definition"

    # Shadow alpha — rgba inside box-shadow / text-shadow values.
    if "box-shadow" in line_lower or "text-shadow" in line_lower:
        return "shadow_alpha"

    # Gradient stops.
    if "gradient(" in line_lower:
        return "gradient_stop"

    # ::selection blocks.
    if "::selection" in window or "::-moz-selection" in window:
        return "selection_color"

    # Inside the @property at-rule (initial-value: #...;)
    if "initial-value" in line_lower:
        return "property_initial_value"

    # Wider window check for f-string hardcodes.
    if "f'" in window[:200] or 'f"' in window[:200]:
        if 'style=' in window:
            return "inline_fstring"

    return "unclassified"


def scan_file(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    line_starts = [0]
    for ln in lines:
        line_starts.append(line_starts[-1] + len(ln))

    rows: list[dict] = []
    for tag, pat in COLOUR_PATTERNS:
        for m in pat.finditer(text):
            abs_offset = m.start()
            # Find the line number.
            lineno = 1
            for i, lo in enumerate(line_starts):
                if lo > abs_offset:
                    lineno = i
                    break
            else:
                lineno = len(lines)
            line = lines[lineno - 1] if lineno - 1 < len(lines) else ""
            classification = _classify(line, m.start() - line_starts[lineno - 1], text, abs_offset)
            rows.append({
                "file": str(path),
                "line": lineno,
                "kind": tag,
                "literal": m.group(0),
                "classification": classification,
                "context": line.rstrip("\n")[:120],
            })
    return rows


def summarise(rows: list[dict]) -> dict:
    by_class = Counter(r["classification"] for r in rows)
    by_kind = Counter(r["kind"] for r in rows)
    unique_literals = len({r["literal"] for r in rows})
    return {
        "total": len(rows),
        "unique_literals": unique_literals,
        "by_classification": dict(by_class),
        "by_kind": dict(by_kind),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", nargs="*", default=["src/mediahub/web/web.py"],
                    help="Files to scan (relative to repo root)")
    ap.add_argument("--out", default="data/stage_a_color_inventory.csv")
    ap.add_argument("--migration-targets-only", action="store_true",
                    help="If set, the exit code reflects whether any inline_fstring "
                         "or inline_html_style hex hardcodes remain (non-zero = fail).")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    rows: list[dict] = []
    for target in args.targets:
        path = (repo_root / target).resolve()
        if not path.exists():
            print(f"warning: {path} not found, skipping", file=sys.stderr)
            continue
        rows.extend(scan_file(path))

    out_path = (repo_root / args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "line", "kind", "literal",
                                               "classification", "context"])
        writer.writeheader()
        writer.writerows(rows)

    summary = summarise(rows)
    print(f"\n=== Colour-literal inventory ===")
    print(f"Total occurrences: {summary['total']}")
    print(f"Unique literals:   {summary['unique_literals']}")
    print(f"\nBy classification:")
    for k, v in sorted(summary["by_classification"].items(), key=lambda kv: -kv[1]):
        print(f"  {k:<28} {v:>5}")
    print(f"\nBy kind:")
    for k, v in sorted(summary["by_kind"].items(), key=lambda kv: -kv[1]):
        print(f"  {k:<10} {v:>5}")
    print(f"\nCSV written to: {out_path.relative_to(repo_root)}\n")

    if args.migration_targets_only:
        # Hex hardcodes specifically. rgba alphas with --lane primary use stay as
        # explicit-opacity fallbacks for Stage A; Stage E introduces color-mix.
        hex_kinds = {"hex3", "hex4", "hex6", "hex8"}
        remaining = [
            r for r in rows
            if r["kind"] in hex_kinds
            and r["classification"] in ("inline_fstring", "inline_html_style")
        ]
        if remaining:
            print(f"FAIL: {len(remaining)} hex hardcodes still in inline templates:")
            for r in remaining[:20]:
                print(f"  {r['file']}:{r['line']}  {r['literal']}  -- {r['context'][:80]}")
            return 1
        print("OK — zero hex hardcodes in inline templates")

    return 0


if __name__ == "__main__":
    sys.exit(main())
