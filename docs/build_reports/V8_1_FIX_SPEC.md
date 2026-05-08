# V8.1 Fix-Everything Spec

## Mandate
The user reported these issues. Fix every one fully. Do not ship V8.1 until all are resolved.

Workspace: `/home/user/workspace/swim-content/`. Live site: `https://mediahub.pplx.app` (site_id `e287696a-e61f-4108-bdb1-ee3bdd82d2af`). 284 unit tests currently pass.

---

## ISSUE 1 — ZIP / .hy3 results files completely fail to parse

**Symptom:** uploading any UK meet results ZIP (which contains a Hytek `.hy3` + `.cl2`) yields garbage. Real reproduction: `samples/learning_corpus/level2/2025_01_westhill_january/results.zip` produces 1 event, "swimmer name = 02Meet Results", confidence 0.23, distance/stroke None.

**Root cause:** `interpreter/ingest.py` ZIP path treats `.hy3` as free-form text. Hytek `.hy3` is a **fixed-width record format** with 2-char type codes: `A0` (system info), `A1` (meet info), `B1`/`B2` (team), `C1`/`C2` (athlete), `D0` (event entry), `E1`/`E2` (event), `F1` (relay), `H1`/`H2` (split), and `J0`-`J3` (event-level results) etc. The `.cl2` (SDIF) is also fixed-width with similar conventions.

**Fix required:**
1. Build a proper Hytek `.hy3` parser at `interpreter/hytek_parser.py`. It must:
   - Detect the `.hy3` shape from the leading record (`A0...` with version + program name)
   - Parse athletes (D0/D1/D2 records → name + DOB + club + sex)
   - Parse events (E1 → event header gender/distance/stroke/course)
   - Parse results (F-records → swimmer + place + time + reaction)
   - Build `InterpretedMeet` dataclass with full athlete + event + swim data
2. Add `.cl2` (SDIF) parser at `interpreter/sdif_parser.py` covering record types A1, B1, C1, D0, E0, F0 (entries/results).
3. In `interpreter/ingest.py` ZIP handler: when a ZIP contains `.hy3` or `.cl2`, route to those parsers, NOT the schema-induce path.
4. Verify with these real files (all in workspace):
   - `samples/learning_corpus/level2/2025_01_westhill_january/results.zip` (Westhill, Hytek)
   - `samples/learning_corpus/level2/2025_02_elgin_spring_meet/results.zip`
   - `samples/learning_corpus/level2/2025_03_garioch_pre_snags/results.zip`
   - `samples/learning_corpus/level2/2025_03_dyce_mini_meet/results.zip`
   - `samples/learning_corpus/level2/2025_02_silver_city_blues_masters/results.zip`
5. Each must produce ≥10 events, ≥50 swims, confidence ≥0.7 with proper swimmer names + clubs. Add tests at `tests_v75/test_hytek_parser.py`.
6. Also support common USA Hytek variants (.hy3 from US club meets follow the same format). Find one US sample online via the existing browser_task / web search if no sample exists locally.

References: Hytek Meet Manager file format is documented publicly; check the SwimAtlas / CFL parser projects on GitHub for ground truth on record structures.

---

## ISSUE 2 — Strip every Swansea hardcode site-wide

**Files known to contain hardcoded Swansea references in non-archive code paths:**

- `swim_content_v4/web.py`: lines 800 ("Try Swansea demo" button), 872 (seed_swansea_uni route), 2885 ("e.g. —Swansea Uni" placeholder), 4050 + 4103 + 4199 (`profile_id = ... or "swansea"` defaults)
- `swim_content_v4/club_profile.py`: SWANSEA-UNI default profile, demo seeding, comments. Lines 27-29, 160, 183, 190-254
- `templates/home_v2.html` and `templates/upload_v3.html`: hardcoded Swansea strings (these may be legacy unused templates — verify and delete if so)
- `data/voices/seed/warm_club.json`: 5 exemplar posts all use `#SwimSwansea`, "Cardiff Open", "Welsh Age Groups", Swansea-coloured names. Replace with **generic/neutral exemplars** that don't name any specific club. Use placeholders like `#YourClub` or rely on the renderer to substitute the user's hashtag.
- `run_with_demo.py`: pre-loads Swansea ZIP. Either delete this file or rename to `run_with_demo.py.disabled`.

**Action:**
1. Delete the "Try Swansea demo" button + route + seeding function. Replace home empty-state with a generic "Create your first club profile" CTA only.
2. Remove all `or "swansea"` defaults — make profile_id required where the route needs it, return a clear error otherwise.
3. Replace Swansea-specific hardcoded strings in placeholders with neutral text ("e.g. —YourClub").
4. Rewrite `data/voices/seed/warm_club.json` exemplars to use neutral text without specific club references; let voice features still be inducible from them.
5. Delete `templates/home_v2.html`, `templates/upload_v3.html`, `run_with_demo.py` if they are not imported anywhere live (`grep -r "home_v2.html" --include="*.py"` etc).
6. The `swansea-uni.json` profile file in `club_profiles/` can stay (it's user data — a real club exists) but no code path should auto-create it.
7. Verification: write a test `tests_v75/test_no_swansea_hardcodes.py` that greps every non-archive directory (`swim_content_v4/`, `interpreter/`, `context_engine/`, `pb_discovery/`, `voice/`, `media_ai/`, `media_library/`, `media_requirements/`, `venue_search/`, `inspiration/`, `creative_brief/`, `graphic_renderer/`, `content_pack_visual/`, `recognition/`, `recognition_swim/`, `engine_v4/`, `web_research/`, `content_pack/`, `brand/`, `workflow/`, `club_platform/`, `canonical/`, `history/`, `templates/`, `data/voices/seed/`) for case-insensitive `swansea` and asserts ZERO matches. Excludes: `swim_content/` (legacy), `swim_content_pb/` (legacy), `swim_content_v5/` (legacy), `legacy_scripts/`, `samples/learning_corpus/` (real meet data), `data/discovered/` (engine-discovered data may legitimately include Swansea as a real club name), `*.md`, `tests/`, `tests_v4/`, `tests_v75/`.

---

## ISSUE 3 — Live AI captions not actually working

**Root cause:** the deployed sandbox has no `pplx-tool` bridge AND no `ANTHROPIC_API_KEY`, so `media_ai/llm.py` always returns None and the caption endpoint falls back to a voice. When the user clicks the AI tab they get a voice caption labelled "AI generation unavailable". The user explicitly does NOT want this masquerade.

**Fix required:**
1. Add a `Settings → API keys` page (`/settings`) where the user can paste their Anthropic API key. Store at `data/secrets.json` with permissions 0600.
2. In `media_ai/llm.py`, if `ANTHROPIC_API_KEY` env is empty, also check `data/secrets.json` for `anthropic_api_key`. If present, set it on the anthropic SDK client per-call (don't write to env globally; pass `api_key=...` to `anthropic.Anthropic()`).
3. The caption endpoint must:
   - When AI is requested AND key exists: actually call Claude. Return `{caption, tone:"ai", live:true}`.
   - When AI is requested AND no key: return HTTP 200 with `{caption: "", tone:"ai", live:false, error:"no_key", message:"Add an Anthropic API key in Settings to enable live AI captions."}`. The frontend then shows a clear "Add your API key" prompt + link to /settings, NOT a fallback voice masquerading as AI.
4. The "AI" tab on each card displays a small status indicator: green "live" dot when key is present, amber "needs setup" when not. Click the amber → opens settings.

---

## ISSUE 4 — Regenerate produces an identical graphic

**Root cause:** `regenerateGraphic()` re-calls the same create-graphic endpoint with the same brief. The brief generator is deterministic for a given (achievement, brand, layout) input, so the second call returns the same layout and same brief.

**Fix required:**
1. Change regenerate semantics: a click should produce **3 visibly different design alternatives** in parallel, then the user picks one.
2. Variation must come from real differences:
   - Variant A: same layout family but inverted colour roles (primary → background, secondary → accent, etc.)
   - Variant B: a different layout family entirely (e.g. if current is `individual_hero`, try `medal_card` or `text_led_recap` or `story_card`)
   - Variant C: different image treatment (cutout vs. duotone-overlay vs. text-led-no-photo)
3. The brief generator gets a `variation_seed: int` parameter that influences layout selection, colour role mapping, image treatment, and headline phrasing. Same seed = same output; different seeds = visibly different.
4. Frontend: when "Regenerate" is clicked, fire 3 parallel POSTs with seeds `[1, 2, 3]`, show all 3 thumbnails side-by-side in the panel with a "Pick this one" button under each. The pick replaces the primary.
5. Add a test that asserts seed-1 and seed-2 outputs are NOT byte-identical PNGs.

---

## ISSUE 5 — Logo + colour upload on upload page

**Spec:**
On the `/upload` page, between "club to feature" and "submit", add:
- File input: "Club logo (optional, PNG/JPG/SVG)"
- Three colour pickers: primary / secondary / accent (HTML5 `<input type="color">`) with sensible defaults
- Checkbox: "Use logo colours as club colours" (default OFF)
- When the checkbox is ticked AND a logo is uploaded, the colour pickers are disabled and the system extracts dominant colours from the logo at submit time. Use `colorthief` or Pillow `Image.quantize` palette extraction (no external API needed).
- After upload, the chosen brand kit is persisted to `data/brand_kits/<run_id>.json` AND is used for ALL graphics generated for this run.

**Wiring:**
- Modify `_v8_brand_kit_for(profile_id)` to first check for a per-run brand kit at `data/brand_kits/<run_id>.json` and use that if present.
- Modify pipeline to pass `run_id` into the brand-kit lookup.
- Persist logo PNG/SVG bytes inside the run's directory: `runs_v4/<run_id>/brand/logo.{ext}`. The renderer's logo path resolves to that file.

**Verify:** Upload a Manchester ZIP/PDF with a custom logo + custom colours, click Create graphic on a card, the rendered PNG must show the uploaded logo (not the default monogram) and the chosen colours (not navy/gold defaults).

---

## ISSUE 6 — Club picker shows clubs from disk only, not from the file being uploaded

**Symptom:** user uploads results, types "Co Cardiff" → not in dropdown because Cardiff hasn't been seen by the engine before. The dropdown only lists clubs from `data/discovered/clubs/`.

**Fix required:**
1. Two-step upload flow:
   - Step 1: user uploads file. Light parse (just get the InterpretedMeet's club list) without running full pipeline. Display a "Clubs found in this file" dropdown populated from the file's own clubs.
   - Step 2: user picks club + colour + logo + tone. Submit. Full pipeline runs.
2. If single-step is preferred, parse the file before showing the form's club picker (i.e. file-input only on first POST; second GET shows clubs).
3. Implement as: POST `/upload` with a file → if no `club_filter` provided, redirect to `/upload/configure?run_id=<temp>` showing the parsed club list + brand kit form. POST `/upload/configure` runs the full pipeline.
4. Fuzzy match remains: if the user types a non-listed club name, fuzzy-match against the parsed clubs and accept the closest if score ≥0.7.

---

## ISSUE 7 — Upgrade graphic-generation software stack

**Goal:** improve visual quality wherever there's headroom. Research the current state-of-the-art, swap better tools where they exist.

**Suggested upgrades (research and apply if genuinely better):**
1. **Better cutouts:** add `Photoroom` API or `Replicate 851-labs/background-remover` as a higher-quality option. Default to local rembg (free) but if user supplies REPLICATE_API_TOKEN or PHOTOROOM_API_KEY in settings, use that instead.
2. **Premium fonts:** use Google Fonts `Anton`, `Bebas Neue`, `Space Grotesk`, `Inter`, `Druk Wide-style` open alternatives like `Bowlby One`. Embed via `@font-face` so they render in headless chromium. Verify loading completes before screenshot.
3. **Real image LLM creative direction:** use Claude's vision capability to look at the actual athlete photo and the brand assets, then write the brief as an LLM call rather than rule-based. Activate only when API key is set.
4. **Sharper renders:** use 2x device-pixel-ratio (DPR=2) when rendering then downsample. Sharper text + better gradients.
5. **Texture overlays:** add subtle noise / grain via SVG filters in the layout CSS to break the flat gradient look.

Each upgrade gets a feature flag and graceful fallback. Do not break the no-API-key path.

---

## ISSUES 8 — Five upgrades from prior review (already agreed)

8a. Real-photo cutouts drive the layouts visually (already partially in place; tighten so when a photo IS uploaded the empty half fills with the cutout, not the watermark fallback).

8b. AI captions: clear UI status — already covered in Issue 3.

8c. Inspiration exemplar uploader: drag-drop UI in profiles → Claude vision parses → style features stored in voice profile → applied at render time.

8d. Pack ZIP includes `/source-assets/` folder with all photos + logo used.

8e. Pack thumbnail strip shows ALL formats per visual (Square / Portrait / Story tabs) — currently shows only one.

---

## ISSUE 9 — User role-play

After fixing 1-7, role-play as a user from a random UK club whose meet appears in `samples/learning_corpus/`. Pick a meet at random, navigate to mediahub.pplx.app, upload the file, set logo+colours, pick a club, walk through to graphic creation, edit a caption, regenerate variants, export ZIP. Log every problem encountered to `USER_ROLEPLAY_LOG.md` even if minor (typos, slow load, confusing copy, missing affordance, broken state). Fix root causes for each.

---

## ISSUE 10 — Re-test every button across the site

Use Playwright via `js_repl`. Walk every page, click every button + link + form-submit, assert HTTP 200/300 and no template-var leaks. Generate `BUTTON_TEST_REPORT.md`. **Especially the content-creation buttons** (Create graphic, Regenerate, Add to pack, Export, Tone toggle, AI status indicator). Iterate until 100% pass.

---

## Deliverables
- All issues 1-10 fixed
- `V8_1_FIX_REPORT.md` summarising what was done + open items
- `USER_ROLEPLAY_LOG.md` with the role-play log
- `BUTTON_TEST_REPORT.md` with the button sweep results
- Site redeployed to mediahub.pplx.app with health 200
- All tests pass: `pytest -x -q --ignore=tests_v75/test_corpus_recovery.py --ignore=tests_v75/test_v8_smoke_manchester.py`

## Anti-shortcut commitments
- No partial fixes. Each issue fully resolved before moving on.
- No same-output regenerations (Issue 4 must produce visibly different variants every time).
- No Swansea hardcodes (Issue 2 grep test must pass).
- ZIP parser must work on the listed real samples; no synthetic-only tests.
