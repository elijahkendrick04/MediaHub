# V7.5 — Hardcode Audit

Goal: nothing about the swimming domain (sources, formats, club codes, meet levels, governing bodies, event ontology, tones) lives in code as a fixed assumption. Code provides only mechanisms (ingest, search, parse-attempt, score, learn). All knowledge is data the engine writes itself or derives at runtime.

## 1. Hardcoded data sources (54 references across the codebase)

`swimmingresults.org` is referenced as a literal string in:

- `swim_content/crossref.py` — `SWIM_ENGLAND_BASE = "https://www.swimmingresults.org"`
- `swim_content/enrichment_swimmingresults.py` — `SR_BASE = "https://www.swimmingresults.org"`
- `swim_content/evidence.py`, `evidence_aggregate.py`, `self_check.py` — source name strings
- `swim_content_v4/canonical.py`, `trust.py` — example URLs and trust signals
- `swim_content_v4/web.py` (lines 883, 886, 894, 1934, 2572, 2610, 2613) — visible UI copy
- `swim_content_v5/achievements/{pb,barrier,standout_history,return_to_form}.py` — `source_name="swimmingresults.org"`
- `swim_content_v5/history.py` — comment + key normalisation tied to SR
- `swim_content_pb/{schema,parser,history,matcher}.py` — entire package assumes SR
- `recognition_swim/achievements/official_pb.py` — "matches swimmingresults.org PB"
- `club_platform/content_types.py` — UI string

**Action**: replace every literal occurrence. The engine must discover sources live for each query, score them by parse success, and persist what it learned in `data/discovered_sources.jsonl`. The current SR fetcher becomes a generic profile-page fetcher the engine *may* select — never assumed.

## 2. Hardcoded format adapters

- `engine_v4/adapters/sportsystems_pdf.py` — SPORTSYSTEMS-specific regex + `STROKE_MAP`
- `swim_content_v4/adapters/hy3.py` — Hy-Tek `.hy3` adapter
- `swim_content_v4/adapters/dispatcher.py` — file-format switch
- `swim_content/parsers.py`, `parsers_hy3.py`, `parsers_pb_pdf.py` — older format-specific parsers

**Action**: delete or freeze. New `interpreter/` package replaces them with format-agnostic stages: ingest → schema-induce → parse → score → learn. Surviving regex/heuristics that prove useful get demoted to entries in `data/patterns.jsonl` (data, not code).

## 3. Hardcoded swim ontology

- `swim_content/events.py` — `STROKES = {…}` constants
- `swim_content_v5/report.py:_STROKE_MAP`, `swim_content/detector_v3.py:_STROKE_MAP`, `swim_content_pb/parser.py:_STROKE_MAP`, `engine_v4/adapters/sportsystems_pdf.py:STROKE_MAP` — duplicated stroke abbreviation maps
- `swim_content_v5/ranker.py:_MEET_LEVEL_SCORE` — fixed `{international, national, university, regional, county, open}` levels with hardcoded weights
- `swim_content/quals_registry.py:32` — fixed level ladder
- `swim_content_v5/achievements/medal_final.py:63` — hardcoded `"national" / "university"` strings as decision points
- `recognition_swim/achievements/*` — 16 detectors with hardcoded thresholds

**Action**: the event ontology and meet-level taxonomy live in `data/ontology/` JSON files the engine seeds from learning passes and then refines from each new file/source it encounters. Detector thresholds become parameters the engine can tune from observed distributions, not constants.

## 4. Hardcoded governing bodies

- `swim_content/crossref.py`, `parsers_hy3.py` — references to Swim England specifically
- `swim_content/parsers_pb_pdf.py` — `'FINA'`, `'SPORTSYSTEMS'` as filter literals
- `swim_content/detector.py:214` — `type="FINAL_QUALIFICATION"` strings
- `swim_content_v5/achievements/medal_final.py` — assumes Swim England-style finals

**Action**: governing-body identity becomes a **discovered fact** the context engine writes per file, not a code constant.

## 5. Hardcoded tones

- `swim_content/captions_v3.py` — `clean / team / hype` baked literals with hardcoded transformations (`name.upper()`, etc.)
- `swim_content_v4/web.py` — V7.4 multi-tone picker hardcodes `warm-club / hype / data-led` as the only three tones
- `voice/multi_tone_renderer.py` (new V7.4) — same three constants

**Action**: tones become **learned voice profiles**. Engine reads exemplar posts (the user's club account or any account they admire), induces a voice profile, the user names and saves it. Dropdown is populated from saved voices on disk, not hardcoded labels. The three V7.4 defaults move to `data/voices/seed/` as starter samples the user can keep, edit, or delete.

## 6. Hardcoded UI copy referencing swim domain

- `swim_content_v4/web.py:2572` — "swimmingresults.org public meet pages (HTML adapter)"
- `swim_content_v4/web.py:883–894` — upload-form copy mentioning SR by name
- `swim_content_v4/web.py:2613` — privacy page mentions SR
- `club_platform/content_types.py:89` — "Optional: a pre-meet PB snapshot will be fetched from swimmingresults.org"

**Action**: rewrite all user-facing copy to describe the *capability* (look up PB / verify times) without naming the source. Per-run UI surfaces show the actual sources that were used (already supported by the research panel), discovered live.

## 7. Implicit assumptions to test

- Time format `mm:ss.cc` regex
- Place-of-finish always integer
- Date formats — UK `dd/mm/yyyy` assumed
- Course codes `LC` / `SC` exclusively
- Age groups expressed as `XX/Under` or `XX/Over`

**Action**: each becomes a regex-family the schema inducer tries, with confidence scoring; new variants observed in real corpora get added to `data/patterns.jsonl` automatically.

---

## Replacement architecture (V7.5)

```
context_engine/         — researches identity/level/governing-body/source-candidates LIVE per input
  research.py           (uses web_research.search; caches to data/discovered/)
  ontology.py           (loads + extends data/ontology/* — strokes, distances, courses, levels)
  trust.py              (per-domain ledger from data/discovered_sources.jsonl)
  identity.py           (meet identity, swimmer identity — discovered, not hardcoded)

interpreter/            — format-agnostic ingest + parse + score + learn
  ingest.py             (PDF/HTML/image/hy3/zip → text + token + visual stream)
  schema_induce.py      (column meanings via header words, regex families, position clustering)
  events_induce.py      (event-header detection from anywhere in stream)
  rows.py               (row extraction with confidence per field)
  patterns.py           (loads + extends data/patterns.jsonl — the learning store)
  hypothesis.py         (when a pattern fails, generate candidates, test on past corpus, persist winners)

pb_discovery/           — finds the right PB source per swimmer per query, live
  discover.py           (web search + candidate ranking + cache)
  fetch_profile.py      (generic profile-page fetcher; succeeds against any layout via interpreter)
  trust_ledger.py       (records parse success per domain, no hardcoded preference)

voice/learned/          — voice profiles learned from exemplars
  induce.py             (read posts, derive style features → VoiceProfile)
  store.py              (save/load named voices)

data/
  discovered/           — engine-grown facts (per meet, per swimmer, per source)
  discovered_sources.jsonl
  ontology/
    strokes.json
    levels.json
    governing_bodies.json
  patterns.jsonl        — learned regex / layout patterns
  voices/               — saved voice profiles
```

Old `swim_content_pb/`, `swim_content_v5/achievements/*` references to SR, `engine_v4/adapters/`, captions_v3.py — all migrated to either delete or read-from-data. The shim packages (`swim_content/`, `swim_content_v5/`, `app_v3.py`) are dead-end legacy and will be deleted to remove the audit surface.
