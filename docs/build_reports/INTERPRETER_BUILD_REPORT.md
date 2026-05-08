# V7.5 Interpreter Build Report

## Summary

The V7.5 format-agnostic learning interpreter has been fully implemented under
`interpreter/` with all supporting data files in `data/ontology/` and
`data/patterns.jsonl`.

All 7 smoke tests in `tests_v75/test_interpreter_smoke.py` pass, including the
grep test that verifies zero swim-vocabulary literals in interpreter Python
source files.

---

## What Was Built

### Package Structure

```
interpreter/
  __init__.py           — public API: interpret_document(bytes, hint=None) → InterpretedMeet
  ingest.py             — bytes → IngestStream (pypdf primary, pdfminer.six fallback; HTML, text, ZIP, hy3)
  schema_induce.py      — IngestStream → list[ColumnSchema] with 3-signal voting
  events_induce.py      — finds event headers using ontology-driven regex + heuristics
  rows.py               — extracts InterpretedSwim rows using induced schema; per-field confidence
  patterns.py           — JSONL-backed PatternStore: load, match, extend, flush
  hypothesis.py         — propose candidate patterns from failing sections; validate vs corpus
  ontology_loader.py    — reads data/ontology/*.json; builds canonical maps and compiled regex
  schema_dataclasses.py — InterpretedMeet, InterpretedEvent, InterpretedSwim, ColumnSchema, etc.

data/
  ontology/
    strokes.json          — 5 stroke canonical forms + aliases (as spec)
    courses.json          — LC / SC aliases (as spec)
    column_headers.json   — place/name/yob/club/time/reaction variants (as spec)
    governing_bodies.json — empty seed; populated by context engine
    levels.json           — empty seed; populated by engine
    genders.json          — M / F / X aliases
  patterns.jsonl          — 7 seed patterns (non-provisional) + provisional patterns added at runtime
  patterns_validation_corpus/  — directory for successful parse sections

tests_v75/
  __init__.py
  test_interpreter_smoke.py   — 7 tests total
```

### Schema Induction — Three-Signal Voting

1. **Header-word matching** (weight 0.55): checks column header text against
   `data/ontology/column_headers.json` canonical map.
2. **Regex-family matching** (weight 0.35): six structural regex families
   (`time`, `place`, `yob`, `reaction`, `name`, `club`) applied to sample values.
3. **Position heuristic** (weight 0.10): leftmost columns tend to be
   place/name; rightmost tends to be time.

A novel improvement over a naive approach: the `_find_best_header_row()`
function scores each of the first 5 rows of a table candidate to identify
the true column-header row, rather than blindly taking row 0. This correctly
handles documents where event-header lines appear above the column-header row
in the same tokenised table (see Fixture C).

### Events Induction

Loads stroke, course, and gender ontologies at runtime, builds compiled regex
alternations, then scores each line on:
- Presence of a stroke term (50% weight)
- Presence of a distance number (30%)
- Presence of gender (10%)
- Presence of course hint (5%)
- Presence of `Event N` label (5%)

Lines scoring ≥ 0.55 are classified as event headers.

### Hypothesis Module

When confidence < 0.6 on any section, `hypothesis.propose_patterns()`:
1. Generates up to 5 candidate regex patterns by progressively generalising
   the failing text (literal → digits-generalised → words-generalised → combined
   → prefix-anchor).
2. Validates candidates against `data/patterns_validation_corpus/*.txt`
   (accepts all compilable candidates when corpus is empty).
3. Persists survivors to `data/patterns.jsonl` with `provisional: true`.
4. Returns the pattern dicts for inclusion in `needs_review`.

### OCR Graceful Degradation

When an image format is detected (`_sniff_format` returns `"image"`),
`ingest()` returns an empty `IngestStream` with `format_detected="image-needs-ocr"`.
`interpret_document()` then returns an `InterpretedMeet` with
`overall_confidence=0.0` and a `needs_review` entry containing `"ocr"`.
No exception is raised.

---

## Test Results

```
tests_v75/test_interpreter_smoke.py::test_fixture_a_plain_text              PASSED
tests_v75/test_interpreter_smoke.py::test_fixture_b_html                    PASSED
tests_v75/test_interpreter_smoke.py::test_fixture_c_plain_text_variant      PASSED
tests_v75/test_interpreter_smoke.py::test_grep_no_swim_vocabulary_in_interpreter  PASSED
tests_v75/test_interpreter_smoke.py::test_image_input_graceful_degradation  PASSED
tests_v75/test_interpreter_smoke.py::test_empty_input_does_not_raise        PASSED
tests_v75/test_interpreter_smoke.py::test_hy3_like_input                    PASSED

7 passed in 0.24s
```

### Confidence Scores Achieved

| Fixture | Format | overall_confidence | Events | Swims |
|---------|--------|--------------------|--------|-------|
| A — Space-aligned tabular | plain text | 0.8645 | 1 | 3 |
| B — HTML with `<table>` | HTML | 0.8536 | 1 | 2 |
| C — Varied column labels (Rank/Competitor/Born/Team/Mark) | plain text | 0.8348 | 1 | 4 |

All exceed the 0.7 threshold required by the spec.

### Grep Test

The test `test_grep_no_swim_vocabulary_in_interpreter` uses Python `re.search`
over every line of every `interpreter/*.py` file checking for 20+ forbidden
swim-vocabulary regex patterns. No violations were found. Manual verification:

```
$ grep -ni "freestyle\|backstroke\|breaststroke\|butterfly\|individual medley\
\|long course\|short course\|swim england\|fina" interpreter/*.py
(no output — CLEAN)
```

---

## Patterns Added to data/patterns.jsonl

### Seed patterns (provisional: false, 7 total)

| ID | Type | Description |
|----|------|-------------|
| `evt-001` | `event_header` | Standard event header: label + gender + distance + stroke |
| `evt-002` | `event_header` | Compact: distance + stroke + optional gender |
| `time-001` | `time_value` | `mm:ss.cc` format |
| `time-002` | `time_value` | `ss.cc` format (short events) |
| `place-001` | `place_value` | `=?NNN` format |
| `yob-001` | `yob_value` | 4-digit year 1940–2030 |
| `reaction-001` | `reaction_value` | `0.xx` or `0.xxx` reaction time |

### Auto-proposed patterns (provisional: true)

During test runs the hypothesis module generated provisional patterns from
low-confidence sections:

- Patterns of type `schema_place`, `schema_name`, `schema_yob`, `schema_club`,
  `schema_time`, `schema_unknown`, and `document_layout` were generated from
  Fixture C (which initially had low column confidence for the `place` column
  before the header-row detection fix).
- Patterns were also generated from the `hy3`-format test fixture (which has
  no conventional column structure).

These provisional patterns are marked `"provisional": true` and are included
in the `new_patterns_proposed` list of the returned `InterpretedMeet` for
human review and confirmation. They are **not** used for parsing until confirmed.

---

## Limitations

1. **PDF layout fidelity**: `pypdf` layout-mode extraction produces reasonable
   line text but does not recover precise x-coordinates for column-clustering.
   The position-based voting signal (10% weight) falls back to a crude
   fractional-position heuristic. Real PDF column clustering would require
   `pdfplumber` or direct PDF stream parsing.

2. **Multi-event table splitting**: When a plain-text document merges multiple
   events into a single continuous block without blank-line separators, all
   swim rows are currently distributed evenly across detected events (sequential
   round-robin). A production version would use page/line offsets from event
   header positions to correctly bound each event's rows.

3. **hy3 structured parsing**: The hy3 format has a rich record-type grammar
   (A1 = meet header, B1 = event, D0 = individual result). The current ingest
   stage treats hy3 as plain text. A purpose-built hy3 parser would greatly
   improve confidence on that format.

4. **Hypothesis pattern quality**: The auto-proposed patterns generated from
   failing sections are structural generalisations of specific document samples.
   They are useful as seeds for future pattern engineering but are intentionally
   not used automatically (they require human confirmation). The `_generalise()`
   function's regex candidates can produce overly broad patterns.

5. **Governing body / level ontologies**: `governing_bodies.json` and
   `levels.json` are empty seeds. The context engine is expected to populate
   them over time.

6. **OCR**: Image inputs cannot be processed. The system flags them gracefully
   but does not attempt Tesseract integration (not available in the current
   environment).

---

## Constraint Compliance

| Constraint | Status |
|-----------|--------|
| Zero swim vocabulary in `interpreter/*.py` | ✅ Verified by grep test |
| No import from `engine_v4/adapters/sportsystems_pdf.py` | ✅ Never referenced |
| `pypdf` primary PDF extractor, `pdfminer.six` fallback | ✅ Implemented in `ingest.py` |
| Produces `InterpretedMeet` for any input type | ✅ Including graceful image flag |
| Hypothesis loop when confidence < 0.6 | ✅ Implemented in `hypothesis.py` |
| Patterns persisted to `data/patterns.jsonl` with `provisional:true` | ✅ Verified |
| `tests_v75/test_interpreter_smoke.py` passes | ✅ 7/7 tests pass |

---

# V7.5 Interpreter Hardening (Round 2) — May 2026

## Summary of the Hardening Pass

The Round-1 interpreter passed 7/7 synthetic fixtures but the real-world
44-document corpus only reached **75% recovery** (33/44 docs yielding ≥1
swim) at mean confidence 0.523 with 24,763 total swims. The hardening pass
brought the corpus to:

| Metric                        | Before | After |
|-------------------------------|-------:|------:|
| Documents with ≥1 swim        |  33/44 | **43/44** |
| Recovery percentage           |  75.0% | **97.7%** |
| Mean confidence (successes)   |  0.523 | **0.75** |
| Total swims extracted         | 24,763 | **48,286** |
| Tests passing                 |   217  | **225** |

The single remaining failure is the Conwy autumn meet whose source PDF is a
*Session Report* (events programme + heat counts), not a results document —
no swimmer-time rows exist to extract.

## What Changed

### 1. pdfplumber-based PDF extractor (`interpreter/pdf_extractor.py`)

`pypdf`'s layout-mode extraction misaligned column data on multi-column PDFs.
The new extractor uses pdfplumber word-level coordinates and applies:

- **Coverage-histogram column band detection.** Each x-position is scored
  by how many distinct y-rows contain a word covering it. Sustained
  low-coverage corridors (≤5% of max coverage, width ≥12 pt) are column
  boundaries. Bands narrower than 80 pt or carrying <5 words are merged
  into neighbours. A min-row-count guard (`len(by_y) < 8` ⇒ single column)
  prevents over-segmenting on small or sparse pages.
- **Multi-line row merger** for the split-time row pattern. A "child" line
  whose tokens are *only* time-shaped values or pure numbers AND that
  follows a parent line containing alphabetic content is merged into the
  parent. This recovers Hytek-style results where the place+name lives on
  line N and split times on lines N+1..N+3.

### 2. Frameset + sibling-aggregation HTML handling (`interpreter/ingest.py`)

When the ingested HTML is structurally thin (`body_chars < 120`, contains a
`<frameset>` tag, or has no `<table>`), the interpreter follows:

1. Explicit `<frame src="...">` children inside the same parent directory.
2. Sibling HTML files matching the structural filename shape
   `^[A-Za-z]{1,4}\d{1,3}[A-Za-z]?\d*\.html?$` AND containing ≥4 time-shaped
   tokens. (No brand or domain matching — pure structure.)
3. Sibling **PDF** files in the same directory when both the original HTML
   body and any aggregated frames still produce no usable content
   (handles "landing-page HTML next to results PDFs" cases).

`source_path` is now an optional input to `interpret_document(..., source_path=)`;
bytes-only callers continue to work.

### 3. Structural row-regex extractor (`interpreter/rows.py`)

Schema-based extraction (Path A) remains the default but is augmented by a
pure structural row-regex extractor (Path B) that scans `stream.lines`
directly with three layered patterns:

- `place + name + age + club + time` (full row)
- `name + age + club + time` (no leading place)
- `place + name + club + time` (no age column)

Each match becomes an `InterpretedSwim` with per-field confidences and a
robust YOB/age disambiguator (4-digit year ⇒ YOB; 2-digit ⇒ split at 2030;
1-3 digit ⇒ age).

The **path with the most swims having a real time value wins** — this
matters because a fragile schema can otherwise produce thousands of "rows"
containing only a single name token (header words like "Session", "Female",
"AaD"). When Path B wins, swims are bucketed to events by *line index* (most
recent header at or before the swim's line) instead of even chunking,
producing per-event swim assignments that are spatially correct.

### 4. Anti-shortcut compliance

- All swim vocabulary continues to live in `data/ontology/*.json`. The grep
  test (`test_grep_no_swim_vocabulary_in_interpreter`) passes.
- No brand-name string appears in `interpreter/*.py` source or comments
  (verified by `tests_v75/test_no_hardcoded_sources.py`).
- No domain-specific URLs appear in live paths (verified by
  `tests_v75/test_no_hardcode_in_live_paths.py`).
- All detection is structural (frameset tag, time-shape density, column
  coverage histograms, row-regex patterns).

## New Tests

- `tests_v75/test_interpreter_corpus.py` — 5 synthetic fixtures: frameset+sibling
  HTML, multi-line PDF row, header-less PDF, thin-HTML+sibling-PDF, and a
  bytes-only-caller smoke test.
- `tests_v75/test_corpus_recovery.py` — acceptance gate: ≥90% recovery,
  mean confidence ≥0.65, total swims ≥30,000.

Total tests: **225** (217 baseline preserved, 8 new).

## Remaining Failure

| Document | Format | Status | Reason |
|----------|--------|--------|--------|
| Swim Conwy Autumn Meet 2025 | pdf | Session Report | The PDF is a heat schedule, not results — there are no swimmer-time rows present to extract. Theoretical maximum corpus recovery for the current INDEX is therefore 43/44 = 97.7%. |

## Constraint Compliance (Round 2)

| Constraint | Status |
|-----------|--------|
| Recovery ≥90% (≥40/44 docs)              | ✅ 43/44 (97.7%) |
| Mean confidence ≥0.65                    | ✅ 0.75 |
| Total swims ≥30,000                      | ✅ 48,286 |
| 217+ tests still pass, no regressions    | ✅ 225 pass |
| Zero swim vocabulary in interpreter      | ✅ Grep test green |
| Zero hardcoded source domains            | ✅ Test green |
| Zero brand-name special-casing           | ✅ Test green |
| Frameset + sibling aggregation           | ✅ HTML and PDF |
| Multi-line row grouping                  | ✅ Split-time merger in `pdf_extractor.py` |
| Header-less detection                    | ✅ Structural row-regex Path B |
