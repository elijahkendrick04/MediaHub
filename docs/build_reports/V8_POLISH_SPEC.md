# V8 — Polish + Integration + Button Sweep

## Context
V8 build complete: 9 layouts render, Manchester smoke produces 6 PNGs, 191/191 unit tests pass. But several issues surfaced when I inspected the actual output:

## Issues found (must all be fixed)

### Critical bugs
1. **`weekend_numbers/feed_portrait.png` shows literal `{{HEADLINE_LINE1}}` and `{{HEADLINE_LINE2}}`** — the template interpolation is broken for that layout. Other layouts work, so it's specific to that template's variable names or the brief generator missing those fields.
2. **Smoke renders for Manchester PDF (`smoke_v8_output/item_*_feed_portrait.png`) are missing swimmer name and event text** — the headline/subhead area is blank, only the GOLD badge + brand chip render. The data is in the achievement object; the bridge from achievement → creative_brief → template fields is dropping name/event.

### Quality issues
3. **Layouts assume an athlete photo cutout in the empty half of the canvas** but the build seeded no photos. The result: half the canvas is empty background. Need either:
   - Sensible **text-led fallback** for the no-photo case that fills the canvas properly (oversized stat, secondary surname accent, etc.), OR
   - Auto-detect missing photo and switch to a **text-led variant of the same layout family**.
   - The system already has `text_led_recap.html` — apply the same text-density treatment as a fallback path on the OTHER layouts when no athlete asset is present.
4. **Athlete spotlight is too sparse** — needs more density. Add: career best, recent improvement chip, supporting stats grid.
5. **Backgrounds are too flat** — add subtle texture (water-ripple SVG pattern at low opacity, or geometric grid). Each layout file should reference a shared `_background.css` partial.

### Integration gaps
6. **Live caption toggle (V8 quick-win) is only on the OLD recognition page card template**. Verify it's also on the V7.4 multi-tone tab area. Most importantly: it must be on the cards that the user actually sees today.
7. **"Create graphic" button on cards** — does not yet exist on the recognition page. Add it. Click → expand inline panel showing the rendered graphic + tone toggle + format tabs + "add to pack" button.
8. **Media library page** — verify route exists, is linked from main nav, and the upload form is functional. Test by uploading a sample image and confirming description-parsing kicks in.
9. **Content pack page** — when visuals are generated for a run, the content pack page must show them. Verify by running Manchester PDF, generating ≥3 visuals, and viewing the content pack to confirm thumbnails appear.

## What to do

### Phase A — Bug fixes
1. Fix the weekend_numbers template variable substitution. Inspect `graphic_renderer/layouts/weekend_numbers.html` and `graphic_renderer/render.py` — likely missing variables in the brief or template uses different syntax than the renderer expects. Patch.
2. Trace the achievement → CreativeBrief → template binding for headline/athlete-name/event. Currently the smoke output proves these fields aren't reaching the template. Either:
   - Brief generator isn't populating them (check `creative_brief/generator.py`), or
   - Template uses different field names than brief produces.
   Fix by aligning field names and ensuring the brief always populates `athlete_name`, `event_label`, `result_time`, `achievement_label`, `meet_name` for every individual-style layout.
3. Re-run smoke. Inspect each PNG. Iterate until every PNG shows: athlete name, event, time, achievement label, brand footer, all populated correctly.

### Phase B — Photo-less fallback design
1. Add `_text_led_fill.css` partial that adds:
   - A second oversized accent character (the swimmer's first-initial as a watermark)
   - A horizontal stat strip with 3 mini stats (event, course, meet date)
   - A subtle background texture (water-ripple SVG at 5-8% opacity)
2. Each layout that previously left the photo region blank should fill it with this fallback fill when no `media_assets[primary_photo]` is present.
3. Re-render the same 6 smoke achievements; confirm no large empty areas remain.

### Phase C — Recognition page integration
1. On every achievement card, add a "Create graphic" button (right of the existing tone toggle if room, else below caption).
2. Click → POST `/api/runs/<run_id>/swim/<swim_id>/visual?layout=auto&format=feed_portrait` → returns JSON with `image_url, alt_text, brief.why_this_design`.
3. Render the image inline below the card. Add format tabs (Square / Portrait / Story). Add "Regenerate" + "Edit text" + "Add to pack" buttons.
4. The visual generation should be **lazy** — only fires on click, not on every recognition page render. Cached per (run_id, swim_id, layout, format).

### Phase D — Media library page
1. Verify `/media-library` route is live and reachable from main navigation. If not, add a nav link.
2. Verify upload form posts a file + free-text description to `POST /media-library`. Verify description gets parsed by Claude (or the heuristic fallback) into structured tags.
3. List view shows thumbnails with permission status badges. Filters work.
4. Add a simple test: upload a fake image, confirm asset appears in library, click on it, edit description, save, confirm changes persist.

### Phase E — Content pack visuals
1. After a recognition run, the user goes to `/pack/<run_id>` and should see visual thumbnails alongside captions.
2. Each visual: thumbnail, caption (editable in place), Approve button, Export PNG, Download all ZIP at top.
3. ZIP export must produce the folder structure the spec calls for: `feed/`, `stories/`, `reel-covers/`, `carousels/`, `captions/`, `approval-summary.json`.

### Phase F — Comprehensive button test (THE BIG ONE)
The user explicitly asked: "test all of the buttons across the entire website. If one is broken, fix it and don't stop fixing until every button is fully fixed."

Use Playwright via `js_repl`:

1. Open mediahub.pplx.app/port/5000 in a headless browser
2. Navigate every visible page: home, /upload, /review/<a-run>, /pack/<a-run>, /audit/<a-run>, /spotlight, /spotlight/<run>/<swimmer>, /weekend-preview, /sponsor-post, /profiles, /research, /privacy, /media-library
3. For EACH page:
   - Enumerate every clickable element (button, link, form submit, anchor)
   - Click each one (in a separate context so navigation doesn't kill the loop)
   - Assert: response status is 2xx OR 3xx (redirect to a 2xx). 4xx/5xx is a fail.
   - Assert: target page renders without `{` template variables in body text
   - Assert: target page does not return raw JSON `{"detail":"Not Found"}` or similar
4. For form submissions: where possible, submit with sensible test data; otherwise note and skip (don't count form submissions like "delete run" as failures if the form requires confirmation).
5. Build a `BUTTON_TEST_REPORT.md` listing every button tested + result (pass/fail/skipped-with-reason).
6. For every fail: investigate root cause, fix it, re-run that specific button until it passes. Iterate until ZERO failures remain.

### Phase G — PhD-level review
After Phases A-F: write `V8_PHD_REVIEW.md` evaluating the website as if you have a PhD in AI + coding, rating each axis 1-10:
- Vision alignment: how close is the live product to the user's stated vision in paste.txt?
- UX clarity: would a new user understand the workflow in 60 seconds?
- Visual quality: are the generated graphics genuinely professional sports media?
- Code quality: is it maintainable, modular, scalable?
- Accuracy: does it preserve facts (no fake claims, no fake people)?
- Performance: how long from upload to first generated visual?

For any axis < 8/10, propose and implement a fix in this same subagent run.

## Anti-shortcut rules
- Do NOT mock the button test. Every button must actually be clicked in a real browser. If a button can't be tested in a single click (form requires upload), document and continue.
- Do NOT declare a fix complete until you've re-rendered + visually inspected the result.
- Do NOT skip any layout in the bug-fix pass — all 9 layouts must produce correct, populated PNGs.
- Do NOT settle for "Canva-equivalent". Iterate until the visuals visibly outclass Canva.

## Deliverable
- All Phase A-G items addressed
- All tests passing (current 191 + new tests)
- mediahub.pplx.app redeployed and live
- BUTTON_TEST_REPORT.md proving every button works
- V8_POLISH_REPORT.md summarising what changed, sample PNG paths, deploy URL
- V8_PHD_REVIEW.md rating each axis with action items
