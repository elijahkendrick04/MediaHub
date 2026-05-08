# Known Issues

Live issues that we accept for now. Each has a workaround and is tracked in
`TECHNICAL_DEBT.md` or in the next planned version.

## Pipeline

- **Single-meet runs only.** Uploading a ZIP containing multiple meets'
  results runs them as one super-meet. Workaround: split the upload.
- **Background thread leaks on Werkzeug debug-server reload.** Run with
  Gunicorn in any non-trivial scenario.
- **Run-id is not signed** — anyone with a run id can read its cards. Mitigate
  by deploying behind authentication.

## Interpreter

- **PDFs scanned at low DPI silently parse to gibberish.** No OCR fallback yet.
  The interpreter logs a low-confidence warning at `phase = interpreting`; the
  user has to spot it.
- **HTML scraping is per-format** (Hy-Tek WebGen + SportSystems + Goodtime).
  Other formats fall through to the generic table extractor with reduced
  reliability.
- **HY3 split-time records** are parsed but not surfaced to detectors. Lap-by-lap
  achievements are therefore blind.

## PB verification

- **swimmingresults.org rate-limits** are real. The cache helps but a fresh
  meet with 100 swimmers will pause for ~5 min during the first upload.
- **Identity matches by name + DOB** — twins or siblings with very close DOBs
  occasionally cross-match. No UI override yet.
- **Short-course / long-course conversion** is exact-course only.

## Rendering

- **WeasyPrint fallback can't render WebFonts** the way Chromium does. Pages
  that depend on Google Fonts will subset fall back to Helvetica.
- **Playwright cold start is ~5 s** in the Docker image. The first card after
  a server restart is slow.
- **Story format (1080×1920)** sometimes truncates long captions. Layout is
  not yet caption-length-aware.

## Caption / voice

- **Voice fidelity decays for very short exemplar sets** (< 10 captions).
  Provide ≥ 25 for stable induction.
- **The deterministic fallback (no API key)** is intentionally generic. Users
  often expect more flair than the templates provide.

## Brand kit

- **Colour-contrast checks** are not enforced. A kit with white text on a
  light-yellow background will render badly.
- **Logo placement** is fixed top-left across all layouts; no per-card
  override.

## Deployment

- **No multi-tenant isolation.** Per-club directories share the filesystem.
- **No backups.** `data/` should be on a snapshot-capable volume.

## Accessibility

- **Generated images do not include alt-text** in the export ZIP. Captions are
  the only text track.
