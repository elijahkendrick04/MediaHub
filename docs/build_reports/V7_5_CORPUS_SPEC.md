# V7.5 — Learning Corpus Collection Spec

## Objective
Build a real-world variety corpus of UK swim meet results documents to train a format-agnostic interpreter. **Do not** take results from swimmingresults.org's parsed view — we need the raw documents the publishing clubs themselves put out, in whatever format they happened to choose.

## Coverage requirements

- **Time range**: May 2025 to May 2026 (the last 12 months)
- **Per month**: 7–8 distinct licensed meets, spanning Level 1 → Level 4
- **Total target**: ~90 meets
- **Variety**: every meet's results doc must come from the publishing club's own website (or wherever that club's organisers actually published the file). NOT from swimmingresults.org's results view.

## Workflow per meet
1. From swimmingresults.org meets tab, identify a licensed meet for that month/level.
2. Find the publishing club / promoter (host club code on SR).
3. Visit the host club's own website, find the results page, locate the published results document.
4. Download the document (PDF / HTML page / image / hy3 / zip — whatever they used).
5. Save to `samples/learning_corpus/level<N>/<YYYY_MM>_<meet_slug>/` with:
   - The original document (`results.<ext>`)
   - `meta.json`: `{meet_name, host_club, host_url, results_url, level, course, dates, source_format, notes}`

## Format diversity bonus
Specifically seek out:
- Plain PDF results (multiple layout flavours)
- Image-based / scanned PDFs
- HTML results tables
- ZIP files of hy3
- Embedded PDFs in news posts
- Word doc / RTF if any club uses it

## Anti-laziness rules
- If a club's site doesn't link the results doc obviously, follow news/announcements/results-archive sub-pages.
- If you cannot find the doc on the host club's site, look on the licensee's site, the meet sponsor's site, or sportsystems.uk.com (since SPORTSYSTEMS hosts results for many UK meets directly). **Document the trail in `meta.json`**.
- Skip and pick a different meet only if the document genuinely isn't available anywhere outside swimmingresults.org.

## Output
- Filled `samples/learning_corpus/...` directory tree
- A top-level `samples/learning_corpus/INDEX.csv` with columns: level, month, meet_name, host_club, format, file_path, source_url, status

## Budget
- This is the most effort-intensive phase. Plan for ~1.5–2 hours of focused work. Use parallel browser tasks where possible.
- **Aim for 90 meets**; if you genuinely cannot find documents for some, document why in INDEX.csv and continue (target: at least 60 successful captures with good format diversity).
