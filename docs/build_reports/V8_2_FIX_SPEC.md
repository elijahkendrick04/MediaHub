# V8.2 — Six-issue fix pass (under 2000 credits)

Workspace: `/home/user/workspace/swim-content/`. Live: `https://mediahub.pplx.app` (site_id `e287696a-e61f-4108-bdb1-ee3bdd82d2af`). 346 unit tests currently pass — keep them green.

## Issue 1 — ZIP file club names smushed together
The `.hy3` parser is using wrong column widths for `C1` team records, producing strings like `"Aberdeen ASC                  Aberdeen"` (full name + 4-letter SHORT name concatenated).

Root cause: `interpreter/hytek_parser.py::_parse_c1` uses `_safe_str(line, 7, 45)`. The actual layout for Hytek MM5 8.0+ is `team_name = cols 7..37 (30 chars)`, then short_name cols 37..45.

**Fix:** Change `_parse_c1` to slice `team_name = _safe_str(line, 7, 30)` and add `team_short = _safe_str(line, 37, 8)`. Also `.strip()` all extracted strings already (the helper does this). Verify by testing: `python3 -c "import zipfile; from interpreter.hytek_parser import parse_hy3; z = zipfile.ZipFile('samples/learning_corpus/level2/2025_03_garioch_pre_snags/results.zip'); hy3 = next(n for n in z.namelist() if n.endswith('.hy3')); print(set([s.club for e in parse_hy3(z.read(hy3)).events for s in e.swims if s.club]))"` — every club name should be clean (no trailing block of spaces + duplicate name suffix).

Also audit other parsers in `interpreter/hytek_parser.py` (`_parse_d1`, `_parse_e1`, `_parse_f1` etc) for similar issues. Specifically check that swimmer names are clean (no trailing chars). If you find swimmer name issues, fix them too — the user reports captions show wrong/extra names, which is downstream of this.

After fixing, run interpreter on all 5 ZIP samples in `samples/learning_corpus/level2/` and verify ZERO names contain a duplicate suffix or extra-name pattern.

## Issue 2 — Caption quality: wrong / extra names
After fixing Issue 1, verify if captions improve. If still wrong:

Look at `voice/learned/render.py` and `swim_content_v4/ai_caption.py`. Check what `swimmer_name` field is being passed to the renderer. Trace back through `swim_content_v4/interpreter_bridge.py` and `swim_content_v4/pipeline_v4.py`.

Common bug pattern: caption renderer reads `swimmer.name` but ALSO appends `swimmer.club` or `swimmer.related_swimmer` thinking it's the swimmer's display name. Or the achievement object has both `swimmer_name` and `athlete_name` and only one is correct.

Confirm fix by uploading a real ZIP and checking the captions on the recognition page show clean names like "Emma Assady" not "Emma Assady NANX" or "Emma Assady · Bob Smith".

## Issue 3 — Move club picker fully onto configure page
The `/upload` form currently shows a "Club to feature" text input alongside the file upload. Remove it. The upload page should show ONLY:

- File input
- Submit button

Optionally: a small note "You'll choose your club + branding on the next step after we read your file."

The configure page (`/upload/configure`) already exists and lists clubs from the file. After this change, EVERY upload goes through configure — the single-step path is removed.

Files to edit: `swim_content_v4/web.py` upload form HTML (around line 1035-1050). Remove the `club_filter`, profile dropdown, and brand-kit fields from the upload page. Keep the file input + a note.

After parse completes, configure page is shown as today. Update tests if any rely on single-step upload (`tests_v75/test_v8_two_step_upload.py` may have a single-step assertion to remove).

## Issue 4 — Configure page dropdown must show ONLY clubs from this file
The configure page club dropdown is populated from `meta["clubs"]` (parsed from file) — that's correct. But verify: the page must NOT also show clubs from `data/discovered/clubs/` or saved profiles. If it does, remove that code path.

Verify by uploading Garioch ZIP → configure page should list only the ~30 clubs that attended Garioch (Aberdeen ASC, Buckie, Elgin, etc.), nothing else.

## Issue 5 — Remove "Club profiles" tool entirely
Delete:
- `/profiles` route (and any sub-routes like `/profiles/<id>/edit`)
- The "Club profiles" link in the main nav
- `swim_content_v4/club_profile.py` if not imported by anything else still needed (check first; may need to keep BrandKit-related helpers)
- `data/club_profiles/coma.json` and `swansea-uni.json` files
- Any `seed_default_profiles()` call
- The `profile_id` form field on /upload (already removed by Issue 3)

But KEEP:
- `data/brand_kits/<run_id>.json` (per-run brand kits) 
- `_v8_brand_kit_for(profile_id, run_id=None)` — refactor it to ONLY look up by `run_id` now, since per-club profiles are gone

Branding becomes a required step on the configure page (no longer optional). The configure page form must enforce: logo OR colour pickers must be filled in (not both blank). Show an inline error if neither is provided.

## Issue 6 — Photo library on configure page + auto-include in graphics
Currently the configure page accepts a logo file. Add a multi-file photos input alongside it:

```html
<label>Photos (optional, multi-select) — athlete portraits, action shots, venue images</label>
<input type="file" name="club_photos" multiple accept="image/*" />
```

On configure-submit, save each uploaded photo bytes to `runs_v4/<run_id>/media/` with a metadata sidecar (filename, type guess, uploaded_at). Also persist to the V8 media library via `media_library.store.save_asset(...)` so the selector can pick them.

In `creative_brief/generator.py` and `content_pack_visual/integration.py`, the selector that picks the `primary_photo` must prefer user-uploaded photos for the run. Currently the selector queries by `profile_id` — change that to also query by the run's media folder OR by per-run override.

The logo MUST always render on every graphic regardless of layout family. If a layout doesn't currently include the logo, add a small logo chip in the corner (footer area).

## Final verification (CRITICAL — do this yourself, do not skip)
After implementing 1-6:

1. Run `pytest -x -q --ignore=tests_v75/test_corpus_recovery.py --ignore=tests_v75/test_v8_smoke_manchester.py`. Must pass (current 346).
2. Redeploy via `publish_website` with `site_id="e287696a-e61f-4108-bdb1-ee3bdd82d2af"`.
3. Health-check: curl `https://mediahub.pplx.app/port/5000/health` returns 200.
4. Pick a corpus meet you haven't role-played yet (NOT Manchester, NOT Elgin Mini Pineapple, NOT Westhill January). Try `samples/learning_corpus/level2/2025_03_garioch_pre_snags/results.zip` (Garioch).
5. Pick a club from that meet you haven't used yet (NOT Buckie, NOT COMA, NOT Swansea). Try `Bridge of Don ASC` or `Cults Otters` or `Inverness Amateur Swimming Club`.
6. Use Playwright via js_repl to: upload ZIP → configure → pick that club → upload a synthetic logo (use `/tmp/logo_test.png` — create one with PIL if needed) → upload 1 synthetic photo → submit → wait for recognition → click Create graphic on first card → verify the rendered PNG shows the uploaded logo + uses extracted colours + clean swimmer name (no extra surnames or short codes).
7. Save the rendered PNG to `/tmp/v82_verification.png` and confirm visually it's clean.

## Deliverables
- All 6 issues fixed
- Tests passing
- Site redeployed and healthy
- Verification PNG at `/tmp/v82_verification.png`
- Single-page report at `/home/user/workspace/swim-content/V8_2_FIX_REPORT.md`

## Anti-shortcut
- Do NOT just edit text in templates without verifying live output.
- Do NOT skip the live verification step. The PNG must show clean names + applied logo + applied colours.
- If tests break, fix root causes, do not delete tests.
- Be efficient: one focused pass, no exploratory subagents inside this one.
