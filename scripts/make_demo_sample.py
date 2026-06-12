#!/usr/bin/env python3
"""Generate the synthetic public-demo results PDF (PC.12, Children's Code).

The /try demo previously shipped a real meet's results PDF — real, named
under-18 swimmers — as its bundled sample. The Age Appropriate Design Code
pass (docs/compliance/CHILDRENS_CODE_PASS.md) replaced it with this
generator's output: the same Hy-Tek-style layout the interpreter parses,
but every swimmer, club and meet is fictional. Deterministic by design —
re-running produces the same swims so the demo cards stay stable.

Regenerate with:

    python scripts/make_demo_sample.py     # writes samples/demo-meet-results.pdf

Requires reportlab (a dev dependency only — the PDF artifact is committed).
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "samples" / "demo-meet-results.pdf"

MEET_TITLE = "Riverbend Autumn Sprint Gala 2025 (SYNTHETIC DEMO DATA)"
SESSION_LINE = "Results - Session 1 (DEMO000001)"
FOOTER = (
    "Synthetic sample generated for the MediaHub demo - every swimmer, club "
    "and result on this page is fictional."
)

# Fictional clubs only — no real club codes or names.
CLUBS = ["Riverbend SC", "Harbour City", "Greystone", "Foxglove Bay", "Mistral Aq"]

# (event_no, gender, event_name, age_line, rows)
# rows: (place, name, age, club_idx, final_time, wa_pts, splits)
EVENTS = [
    (
        101,
        "Female",
        "200m IM",
        "16 Yrs/Under Age Group - Full Results",
        [
            (1, "Tamsin Veldt", 15, 0, "2:24.61", 671, ("31.82", "1:10.04", "1:52.20")),
            (2, "Orla Quenby", 15, 1, "2:26.18", 650, ("31.40", "1:09.95", "1:53.41")),
            (3, "Maren Liddycoat", 14, 2, "2:30.92", 581, ("31.95", "1:12.01", "1:56.30")),
            (4, "Sive Arkwright", 15, 0, "2:33.07", 562, ("32.10", "1:12.85", "1:55.76")),
            (5, "Beatrix Fenwick", 16, 3, "2:33.85", 555, ("32.55", "1:11.20", "1:56.71")),
            (6, "Nuala Redfern", 13, 0, "2:34.11", 552, ("31.70", "1:12.30", "1:59.84")),
        ],
    ),
    (
        102,
        "Male",
        "100m Freestyle",
        "Open Age Group - Full Results",
        [
            (1, "Caspian Mellor", 17, 1, "52.34", 702, ("25.31",)),
            (2, "Dashiell Okonkwo-Hart", 16, 2, "53.07", 673, ("25.66",)),
            (3, "Idris Vanterpool", 18, 0, "53.78", 647, ("25.92",)),
            (4, "Lorcan Quistorff", 16, 4, "54.40", 625, ("26.20",)),
            (5, "Bertram Saltmarsh", 15, 3, "55.93", 575, ("26.85",)),
            (6, "Ottoline Grayweather", 17, 1, "56.21", 566, ("27.02",)),
        ],
    ),
    (
        103,
        "Female",
        "50m Butterfly",
        "14 Yrs/Under Age Group - Full Results",
        [
            (1, "Wren Tallowfield", 14, 2, "29.84", 612, ()),
            (2, "Isolde Marchbank", 13, 0, "30.41", 578, ()),
            (3, "Clemency Drey", 14, 4, "30.95", 548, ()),
            (4, "Hesper Lindqvist-Bell", 13, 1, "31.52", 519, ()),
            (5, "Rosalind Attewater", 14, 3, "32.08", 492, ()),
        ],
    ),
    (
        104,
        "Male",
        "200m Breaststroke",
        "Open Age Group - Full Results",
        [
            (1, "Fenton Ashgrove", 18, 3, "2:28.93", 645, ("33.81", "1:11.92", "1:50.34")),
            (2, "Soren Quickfall", 16, 0, "2:31.27", 615, ("34.20", "1:13.05", "1:52.10")),
            (3, "Albin Westerdale", 17, 2, "2:34.66", 575, ("34.95", "1:14.48", "1:54.87")),
            (4, "Percival Lunt", 15, 1, "2:37.90", 539, ("35.40", "1:15.92", "1:57.21")),
        ],
    ),
    (
        105,
        "Female",
        "100m Backstroke",
        "Open Age Group - Full Results",
        [
            (1, "Verity Holmwood", 17, 4, "1:03.42", 668, ("30.88",)),
            (2, "Saskia Renshaw-Pike", 16, 0, "1:04.17", 645, ("31.22",)),
            (3, "Eulalia Birchall", 15, 1, "1:05.30", 612, ("31.85",)),
            (4, "Marigold Stennett", 16, 2, "1:06.84", 570, ("32.40",)),
            (5, "Cordelia Vance", 14, 3, "1:08.02", 541, ("33.01",)),
        ],
    ),
    (
        106,
        "Male",
        "400m Freestyle",
        "16 Yrs/Under Age Group - Full Results",
        [
            (1, "Barnaby Eastcote", 16, 0, "4:12.55", 660, ("58.92", "2:03.40", "3:08.71")),
            (2, "Rafferty Coldstream", 15, 2, "4:15.83", 635, ("59.45", "2:05.10", "3:11.02")),
            (3, "Linus Wendelboe", 16, 1, "4:21.47", 594, ("1:00.31", "2:07.66", "3:15.40")),
            (4, "Hartley Dunmore", 14, 4, "4:28.12", 549, ("1:01.85", "2:11.32", "3:20.55")),
        ],
    ),
]


def build_pdf(out: Path = OUT) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    out.parent.mkdir(parents=True, exist_ok=True)
    # Uncompressed so the SYNTHETIC marker is grep-able in the artifact;
    # invariant so regeneration is byte-identical (no embedded timestamps).
    c = canvas.Canvas(str(out), pagesize=A4, pageCompression=0, invariant=1)
    width, height = A4
    margin = 40
    y = height - margin

    def line(text: str, font: str = "Helvetica", size: float = 9.0, gap: float = 12.0):
        nonlocal y
        if y < margin + 30:
            c.showPage()
            y = height - margin
        c.setFont(font, size)
        c.drawString(margin, y, text)
        y -= gap

    line(MEET_TITLE, "Helvetica-Bold", 12, 16)
    line(SESSION_LINE, "Helvetica", 10, 16)
    for ev_no, gender, ev_name, age_line, rows in EVENTS:
        line(f"EVENT {ev_no} {gender} {ev_name}", "Helvetica-Bold", 10, 13)
        line(age_line, "Helvetica-Bold", 9, 12)
        split_header = " ".join(("50", "100", "150")[: len(rows[0][6])])
        header = "Place Name AaD Club Time WA Pts"
        line((header + " " + split_header).strip(), "Helvetica-Oblique", 8.5, 11)
        for place, name, age, club_idx, t, pts, splits in rows:
            row = f"{place}. {name} {age} {CLUBS[club_idx]} {t} {pts}"
            if splits:
                row += " " + " ".join(splits)
            line(row, "Helvetica", 9, 11.5)
        y -= 6
    line("", gap=8)
    line(FOOTER, "Helvetica-Oblique", 8, 10)
    c.save()
    return out


if __name__ == "__main__":
    path = build_pdf()
    print(f"wrote {path} ({path.stat().st_size} bytes)")
