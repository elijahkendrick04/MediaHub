# V7.5 — Self-Learning Interpreter Spec

## Goal
A format-agnostic results-document interpreter. No file-type-specific code. No hardcoded swim ontology in the interpreter itself — it reads the ontology from `data/ontology/` JSON files (which the engine grows over time) and learns new patterns from real documents, persisting them to `data/patterns.jsonl`.

## Package layout to create

```
interpreter/
  __init__.py           — public API: interpret_document(bytes, hint=None) -> InterpretedMeet
  ingest.py             — bytes → IngestStream (text + tokens + visual layout markers)
  schema_induce.py      — IngestStream → ColumnSchema with confidence per column
  events_induce.py      — finds event headers (gender + distance + stroke + course + age band)
  rows.py               — extract rows using induced schema; per-row & per-field confidence
  patterns.py           — load + extend data/patterns.jsonl
  hypothesis.py         — when parsing partly fails, propose candidate patterns (regex/heuristic) and validate against past corpus before persisting
  ontology_loader.py    — read data/ontology/*.json (strokes, courses, levels, governing_bodies)
  schema_dataclasses.py — InterpretedMeet, InterpretedEvent, InterpretedSwim, ColumnSchema, etc.
```

## InterpretedMeet schema (minimum)
```python
@dataclass
class InterpretedSwim:
    swimmer_name: str
    yob: Optional[int]
    club: Optional[str]
    place: Optional[int]
    time: Optional[str]          # canonical "mm:ss.cc" or "ss.cc"
    reaction: Optional[str]
    confidence: float            # 0..1 per swim
    raw_row: str
    field_confidence: dict[str, float]

@dataclass
class InterpretedEvent:
    gender: Optional[str]        # "M"/"F"/"X"/None
    distance_m: Optional[int]
    stroke: Optional[str]        # canonical
    course: Optional[str]        # "LC"/"SC"/None
    age_band: Optional[str]
    swims: list[InterpretedSwim]
    confidence: float

@dataclass
class InterpretedMeet:
    meet_name: Optional[str]
    venue: Optional[str]
    dates: Optional[tuple[str, str]]
    course_default: Optional[str]
    governing_body_hint: Optional[str]
    events: list[InterpretedEvent]
    overall_confidence: float
    needs_review: list[dict]     # rows/events the interpreter flagged as ambiguous
    sources_used: list[str]      # paths/URLs of any auxiliary docs read
    patterns_used: list[str]     # ids of patterns from data/patterns.jsonl that fired
    new_patterns_proposed: list[dict]  # patterns hypothesised this run, awaiting confirmation
```

## Ingest stage

`ingest(bytes, content_type_hint=None) -> IngestStream`

- Sniff format: PDF (try pypdf first, then pdfminer fallback), HTML, plain text, ZIP (recurse), image (OCR via tesseract if available, else flag), hy3 (treat as line-based).
- Output:
  - `text: str` — the linear text
  - `lines: list[Line]` — each line with text, page_no, y_position, font_size_hint (when available)
  - `tables: list[TableCandidate]` — detected tabular regions (PDF: column-clustering; HTML: `<table>` parse)
  - `format_detected: str` — for logging

No swim-domain logic in this file.

## Schema induction (the heart of the learning)

`induce_schema(stream: IngestStream) -> list[ColumnSchema]`

Strategy:

1. **Header-word matching** — load `data/ontology/column_headers.json` (seeded with common variants like `Place`, `Pos`, `Pl`, `Name`, `Athlete`, `YoB`, `Year`, `DOB`, `Club`, `Team`, `Time`, `Result`, `RT`, `Reaction`). Extend at runtime when new variants appear.
2. **Regex families** — column type detected by regex family:
   - `time_family`: `\d{0,2}:?\d{2}\.\d{2}`, `\d+:\d{2}\.\d{2}`, etc.
   - `place_family`: `^\d{1,3}$` or `^=?\d{1,3}\b`
   - `yob_family`: 4-digit year 1940-current, or 2-digit
   - `name_family`: capitalised words
   - `reaction_family`: `0\.\d{2,3}`
3. **Position clustering** — for PDFs, infer columns from x-coordinates of text fragments.
4. **Voting** — combine all three signals; each column gets a type plus confidence.
5. Return list of `ColumnSchema(name, type, confidence, x_range)`.

If confidence on any column is below a threshold (configurable, default 0.6), add the column to `needs_review`. Don't fail — flag.

## Events induction

Events are typically delimited by lines like `Event 1 - Female 50m Freestyle`, or `Female 50m Freestyle Open`, or `LC Meters Female 50 Freestyle`, etc. Detect via:

- Regex families for distance + stroke + gender, loaded from `data/ontology/strokes.json` etc.
- Section breaks in the layout (font size jumps, blank lines, `Event \d+`).
- Hierarchical: a meet may have section headers (Day 1, Session 2) wrapping events.

Persist any *new* event-header phrasings observed in `data/patterns.jsonl` after validation.

## Hypothesis loop

When schema induction or event detection has confidence < 0.6 on a section:

1. `hypothesis.propose_patterns(stream_section, current_patterns)` — generate up to 5 candidate regex/heuristic patterns from the failing section (e.g., generalise observed numbers/words into a pattern).
2. For each candidate, **validate** it against past corpus stored in `data/patterns_validation_corpus/` (sections from earlier successful runs). Keep candidates that don't break past parses.
3. Persist surviving candidates to `data/patterns.jsonl` with `provisional: true`.
4. Mark the section as `needs_review` with the candidate IDs so a human can confirm later.

## Constraint
**No swim-vocabulary literals** in interpreter Python files except:
- The literal characters used to detect numeric/regex shapes (digits, punctuation)
- Names of dataclass fields

All swim words ("Freestyle", "Backstroke", "LC", "national", "Swim England", etc.) live in `data/ontology/*.json` files.

## Data files to seed
Create the following ontology seeds (small, extendable):

**`data/ontology/strokes.json`**:
```json
{
  "Freestyle": ["Freestyle", "FR", "Free", "FREE"],
  "Backstroke": ["Backstroke", "BK", "Back", "BACK"],
  "Breaststroke": ["Breaststroke", "BR", "Breast", "BREAST"],
  "Butterfly": ["Butterfly", "FLY", "Fly", "BUTTERFLY", "BFLY"],
  "Individual Medley": ["Individual Medley", "IM", "Medley", "I.M.", "Ind. Medley"]
}
```

**`data/ontology/courses.json`**:
```json
{
  "LC": ["LC", "LCM", "Long Course", "LONG COURSE", "Long Course Meters", "50m"],
  "SC": ["SC", "SCM", "Short Course", "SHORT COURSE", "25m"]
}
```

**`data/ontology/column_headers.json`**:
```json
{
  "place": ["Place", "Pl", "Pos", "Position", "Rank", "#"],
  "name": ["Name", "Athlete", "Swimmer", "Competitor"],
  "yob": ["YoB", "YOB", "Year", "Born", "DOB", "Date of Birth"],
  "club": ["Club", "Team", "School", "Affiliation"],
  "time": ["Time", "Result", "Final Time", "Swim Time", "Mark"],
  "reaction": ["RT", "Reaction", "React", "Start"]
}
```

**`data/ontology/governing_bodies.json`** — start empty `{}`; engine populates from context-engine research.

**`data/ontology/levels.json`** — start empty; engine seeds when it observes meets.

## Tests to write

`tests_v75/test_interpreter_smoke.py`:
- Synthetic mini-PDFs for 3 fake formats (column variants).
- Verify each is parsed with overall_confidence >= 0.7.
- Verify no swim-vocabulary literals in `interpreter/*.py` (use `grep` in the test).

## Anti-shortcut rule
Do NOT import or reuse `engine_v4/adapters/sportsystems_pdf.py` patterns. The interpreter must rediscover what works from data + induction, not be handed the answer.

## Deliverable
- All files under `interpreter/` and `data/ontology/` created
- `tests_v75/test_interpreter_smoke.py` passing
- `INTERPRETER_BUILD_REPORT.md` summarising what's built + any limitations
