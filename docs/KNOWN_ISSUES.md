# Known Issues

Live issues that we accept for now. Each has a workaround and is tracked in
`TECHNICAL_DEBT.md` or in the next planned version.

## Pipeline

- **Single-meet runs only.** Uploading a ZIP containing multiple meets'
  results runs them as one super-meet. Workaround: split the upload.
- **Background thread leaks on Werkzeug debug-server reload.** Run with
  Gunicorn in any non-trivial scenario.
- **Run-ids are not signed (defence-in-depth gap, not an open cross-tenant leak).**
  Cross-organisation access *is* enforced: every `<run_id>` route checks
  `_can_access_run`, regression-tested in `tests/test_cross_tenant_access.py` and
  locked as an invariant across all current/future run routes by
  `tests/test_run_route_isolation_invariant.py`. The residual: within a single org,
  run-ids are 48-bit random (`uuid4().hex[:12]`) rather than HMAC-signed, and
  owner-less *legacy* runs stay readable by design so historical data isn't orphaned.
  Signed tokens would add defence-in-depth against guessing; the cross-tenant hole
  itself is closed. *(Partially hardened by W.9, 2026-06-12: the magic-link
  review surface uses HMAC-signed, expiring, revocable run-scoped tokens —
  the signed-token pattern now exists in-tree for other routes to adopt.)*

## Interpreter

- **PDFs scanned at low DPI** — ✅ improved (W.10, 2026-06-12): an OCR
  fallback (Tesseract in the deployed image; engine optional elsewhere) now
  catches image-only PDFs and photos, with per-row uncertainty flags and
  confidence capped at 0.55. With no engine installed the honest
  "image-needs-ocr" review flag is raised instead of gibberish.
- **HTML scraping is per-format** (Hy-Tek WebGen + SportSystems + Goodtime).
  Other formats fall through to the generic table extractor with reduced
  reliability.
- **HY3 split-time records** are parsed but not surfaced to detectors. Lap-by-lap
  achievements are therefore blind.

## PB verification

- **swimmingresults.org rate-limits** are real. The cache helps but a fresh
  meet with 100 swimmers will pause for ~5 min during the first upload.
- **Identity matches by name + DOB** — twins or siblings with very close DOBs
  occasionally cross-match. ✅ Fix surface added (W.1, 2026-06-12): the
  Athletes page's "same swimmer?" merge persists the human's decision and is
  audited; cross-matches now have a durable correction path.
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
- **AI providers are required.** When no LLM key is configured, AI-driven
  surfaces (captioning, brand interpretation, creative direction) surface
  an "AI unavailable" error rather than fabricating heuristic output.
  Configure `GEMINI_API_KEY` (free tier) or `ANTHROPIC_API_KEY`.

## Brand kit

- **Colour-contrast checks** are not enforced. A kit with white text on a
  light-yellow background will render badly.
- **Logo placement** is fixed top-left across all layouts; no per-card
  override.

## Deployment

- **No multi-tenant isolation.** Per-club directories share the filesystem.
- **No backups.** `data/` should be on a snapshot-capable volume.

## Accessibility

- **Generated images do not include alt-text** — ✅ fixed (W.11, 2026-06-12):
  a result-grounded alt text is produced in the same provider call as the
  caption, is editable beside it in review, and rides the export ZIP, the
  public wall embeds/feeds and Buffer publish payloads.
