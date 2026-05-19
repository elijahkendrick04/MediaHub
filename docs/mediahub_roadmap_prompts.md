# MediaHub Roadmap — Paired Implementation & Verification Prompts

**Source document:** `docs/competitor_dissertation_2026.md`
**Branch model:** every step on its own feature branch from `dev`; never merge to `main` without approval
**Cadence:** each step is a 1-3 day Claude Code session; verification prompt is run before merging

---

## How to use this document

1. Copy the **Implementation Prompt** for the next step and paste it into a fresh Claude Code session.
2. When Claude reports the step is done, **start a new Claude Code session** (so context isn't biased by the implementation work) and paste the matching **Verification Prompt**.
3. If verification fails, paste the failing output back into the implementation session and ask Claude to fix the regressions.
4. Only move to the next step when the verification session reports a clean pass.
5. After every step: commit, push, and update `CLAUDE.md` if the workflow has changed.

Standing constraints (apply to every step):

- Use `DATA_DIR` env var; never hardcode `Path("data/...")` relative paths.
- Use `url_for()` for all internal links; never hardcode URL paths.
- Do not remove existing routes or break existing test files.
- Run `python -m pytest tests/ -q` before claiming a step is done — must remain at 253+ passed.
- Apply `frontend-design` skill for any UI changes; keep the dark-first palette (`--bg`, `--accent`, `--ink`, `--panel`).
- Never expose `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, or any secret in user-visible text.
- Human approval must remain required before any external publishing — no autopost without confirmation.

---

# Phase 1 — Parity (Steps 1-7, target months 0-3)

## Step 1: Brand DNA Capture from Website

### Context
MediaHub's `ClubProfile` currently captures colours, logo, tone slider, exemplar captions. Competitors like Holo (tryholo.ai) ingest a club website URL and produce a structured brand profile in ten minutes. This step closes the most visible onboarding gap with the horizontal leaders.

### Implementation Prompt

```
Build a Brand DNA capture flow for MediaHub.

GOAL: a user supplies a single website URL on /organisation; MediaHub
crawls the page, extracts visual identity and voice signals, and
populates the ClubProfile with a structured brand profile in under 90
seconds.

FILES TO MODIFY:
- src/mediahub/web/club_profile.py: extend ClubProfile with fields
  brand_voice_summary: str, brand_keywords: list[str],
  brand_palette_extracted: dict, brand_logo_url: str,
  brand_typography_hint: str, brand_phrases_to_avoid: list[str],
  brand_phrases_to_use: list[str], brand_source_url: str,
  brand_captured_at: str, brand_capture_status: str
  (all optional, backward-compatible defaults; from_dict already
  filters unknown keys so old JSONs still load)
- NEW src/mediahub/brand/dna_capture.py with:
    capture_brand_dna(website_url: str) -> dict
  This uses requests + a lightweight HTML parser to fetch the page,
  extracts <title>, <meta description>, <h1>/<h2>, og:image, theme-color
  meta, primary CSS variables / inline-style colours, the largest <img>
  that looks like a logo, then sends a structured prompt to the LLM
  (mediahub.media_ai.llm.generate_json) asking for: voice_summary
  (50 words), 8-12 keywords, 3-5 phrases the brand uses, 3-5 phrases to
  avoid, primary/secondary/accent palette in hex, typography hint
  (serif/sans/display).
- src/mediahub/web/web.py: extend the /organisation route to accept a
  "Capture from website" form action that calls capture_brand_dna,
  merges the result into the loaded ClubProfile, and shows a preview
  panel the user can accept or edit before save.
- src/mediahub/data/runs cache: store the raw HTML + extracted JSON
  under DATA_DIR / "brand_dna_cache" / "<domain>.json" keyed by
  domain, so re-capturing is fast and replayable without re-fetching.

ACCEPTANCE CRITERIA:
- /organisation has a new section "Capture from website" with a URL
  input and a "Analyse" button.
- Clicking Analyse shows a loading state and within ~30s renders a
  preview with the extracted palette swatches, the voice summary, the
  detected logo, and the phrase lists.
- Accept-and-save writes everything to the existing club profile JSON.
- Old club_profiles/*.json files still load without error (backward
  compatibility).
- No new top-level dependency beyond what is already in pyproject.toml
  (use requests + html.parser or beautifulsoup4 if already present).
- Graceful failure: if the URL is unreachable or the LLM is
  unavailable, show a clear error and keep the form usable.

DON'T BREAK:
- /organisation GET must still render with no URL provided.
- Existing ClubProfile JSONs in club_profiles/ must still load.
- /settings page must still work (Gemini and Anthropic key fields).

TESTS:
- Add tests/test_brand_dna_capture.py covering: HTML colour extraction,
  graceful failure on unreachable URL, honest error surface when the
  LLM provider is unavailable (no silent heuristic substitution), and a
  smoke test that /organisation accepts and persists captured fields.
- Full pytest run must still be 253+ passed.

Reference: dissertation §4.1 (Holo), §6 Workstream 1.1.
```

### Verification Prompt

```
Verify Step 1 (Brand DNA Capture) is fully working with no regressions.

CHECK THESE THINGS:

1. Backend tests:
   - Run python -m pytest tests/ -q. Report total passed/skipped.
     Must be 253+ passed, no new failures.
   - Run python -m pytest tests/test_brand_dna_capture.py -v. List
     each test name and outcome.

2. Module imports:
   - python -c "from mediahub.brand.dna_capture import capture_brand_dna; print('ok')"
   - python -c "from mediahub.web.club_profile import ClubProfile; p=ClubProfile(profile_id='x'); print(p.brand_voice_summary, p.brand_keywords)"

3. ClubProfile backward compatibility:
   - List the *.json files in club_profiles/ and load each one with
     ClubProfile.from_dict. None should raise.
   - Confirm at least one old profile loads with the new fields
     defaulting (empty list / empty string).

4. Route smoke test:
   - Boot the app: python -m mediahub.web.web (in background; kill
     after the test).
   - GET /organisation must return 200.
   - POST /organisation with action=capture and a real public URL
     (try https://www.britishswimming.org or similar) must return
     a page containing extracted palette swatches and a voice summary
     within 60 seconds. Report status, response time, and a 200-char
     excerpt of the preview HTML.
   - POST /organisation with a garbage URL must return 200 with an
     error banner (not 500).

5. Regression checks on prior features:
   - /, /add-input, /upload, /settings, /free-text all must return
     200. Report status codes.
   - /api/runs/<existing_run_id>/swim/<existing_swim_id>/caption?tone=ai
     still returns a valid caption response.

6. UI quality:
   - Open /organisation in a headless browser (use browser-use or
     playwright). Take a screenshot.
   - Confirm the new section uses the existing dark palette (--bg,
     --accent, --ink). Flag any blue-300 Tailwind-ish leakage.

7. Storage hygiene:
   - Confirm DATA_DIR / "brand_dna_cache" / *.json was written
     (not Path("data/...") relative).
   - Confirm no API key appears in the cached HTML or extracted JSON.

OUTPUT FORMAT:
Return a single report with sections 1-7, each with a clear
✅ PASS / ❌ FAIL marker. End with a short summary: "Step 1 is /
is not ready to merge".
```

---

## Step 2: Voice Imitation from Past Social Posts

### Context
Brand DNA captured the *visual* identity. This step captures the *linguistic* identity by ingesting recent social posts and producing a voice profile that the caption generator consults on every call. Lately.ai and Jasper both ship this; MediaHub's current tone slider does not.

### Implementation Prompt

```
Extend Brand DNA with a voice-imitation layer that learns from past
social posts.

GOAL: a user pastes 5-20 recent Instagram/Facebook/X captions; MediaHub
produces a structured voice profile that the live caption generator
consults so the output sounds like the club's own past posts.

FILES TO MODIFY:
- src/mediahub/web/club_profile.py: add voice_examples (list[str]),
  voice_profile (dict) with keys: sentence_length_avg, sentence_length_p90,
  emoji_rate_per_caption, hashtag_count_avg, characteristic_openers
  (list[str]), characteristic_closers (list[str]),
  forbidden_phrases (list[str]), preferred_swimmer_address
  (first_name|last_name|surname_only|nickname).
- NEW src/mediahub/brand/voice_imitation.py:
    analyse_examples(examples: list[str]) -> dict
  Computes the numeric stats deterministically (sentence length, emoji
  count, hashtag count) and asks the LLM (via generate_json) for the
  characteristic patterns (openers, closers, phrases to avoid).
- src/mediahub/web/web.py /organisation: add a "Voice examples" section
  with a textarea (one caption per line) and an "Analyse voice" button.
- src/mediahub/web/ai_caption.py: extend
  generate_caption_for_tone() to accept the loaded ClubProfile and
  inject voice_profile fields into the system prompt — characteristic
  openers, sentence-length target, hashtag count, swimmer address
  preference, phrases to avoid. Keep this behind a feature check so
  profiles without voice_profile still work.
- src/mediahub/web/web.py api_live_caption: pass the loaded
  ClubProfile to generate_caption_for_tone.

ACCEPTANCE CRITERIA:
- Pasting 10 example captions produces a non-empty voice_profile dict
  saved to the club profile JSON.
- Subsequent live caption calls visibly reflect the voice (open the
  same achievement with two different voice_profiles set and confirm
  the outputs differ in opener style, hashtag count, swimmer address).
- The system still works for profiles without voice examples (current
  behaviour preserved).
- No PII (real swimmer names from the examples) leaks into the saved
  voice profile — strip names with a simple regex pass before saving.

DON'T BREAK:
- All four tone tabs (AI, Warm, Hype, Precise) must still generate
  captions live, each call unique (nonce path preserved).
- /api/runs/<id>/swim/<id>/caption?tone=warm-club still returns a
  caption.
- tests/test_live_caption_endpoint.py — all 30 must still pass.

TESTS:
- Add tests/test_voice_imitation.py with deterministic-mode tests
  (no LLM): verify sentence-length stats, emoji/hashtag counting, and
  that PII redaction strips obvious names.
- Run full pytest, confirm 253+ passed.

Reference: dissertation §4.5 (Lately), §4.6 (Jasper), §6 Workstream 2.4.
```

### Verification Prompt

```
Verify Step 2 (Voice Imitation) end-to-end.

1. Tests:
   - python -m pytest tests/test_voice_imitation.py
     tests/test_live_caption_endpoint.py -v. Report each test result.
   - Full python -m pytest tests/ -q. Must be 253+ passed.

2. Voice-influenced generation:
   - Create two test club profiles in tmp:
     A: voice_examples = 10 captions that are short, no emoji,
        all-caps openers, no hashtags
     B: voice_examples = 10 captions that are long, heavy emoji,
        3 hashtags each, "Massive shoutout to..." openers
   - Run generate_caption_for_tone() with the same achievement dict
     and tone='ai' for each profile. Print both outputs.
   - Confirm the outputs visibly differ in style. Specifically:
     A should be shorter and emoji-free, B should be longer and have
     emoji. Report PASS/FAIL with the diff.

3. Live endpoint smoke:
   - Boot the app. POST a caption request for each of the 4 tones
     against an existing run. Confirm 200 + non-empty caption + live=True.

4. Backward compatibility:
   - Load 3 existing club_profiles/*.json. None should raise. Confirm
     each profile.voice_profile defaults to empty dict.

5. /organisation form:
   - Open /organisation in browser, paste 5 example captions, click
     "Analyse voice". Screenshot the resulting preview.
   - Confirm sentence-length / emoji / hashtag stats are non-zero
     in the preview.
   - Confirm Save persists the voice_profile field (load the JSON
     after save and grep for the field).

6. Privacy / PII:
   - Paste examples that contain a fake name "Sarah Johnson". Confirm
     the saved voice_profile does NOT contain that string.

7. Regression sweep:
   - Step 1 features still work: /organisation capture-from-URL still
     produces a brand DNA preview.
   - /add-input, /upload, /settings still 200.

OUTPUT: single report, sections 1-7, ✅/❌ each, summary line.
```

---

## Step 3: Visible Intelligence UI — "Why This Card?"

### Context
MediaHub's strongest moat is the editorial reasoning behind every generated card (PB detection, ranking, source-grounding). Today that reasoning is invisible to the user. This step surfaces it in the content pack and converts an invisible asset into a marketing-grade product surface.

### Implementation Prompt

```
Add a "Why this card?" explainer surface to every generated card.

GOAL: in the content pack and review page, every card exposes a
plain-English explanation of why MediaHub surfaced it, with the
specific factors (PB, county qualifier, place, confidence) and the
source-of-truth citation (which line of the result file produced
this fact).

FILES TO MODIFY:
- src/mediahub/recognition/: locate the ranked-achievement scoring
  module. Each ranked achievement already has a "factors" list with
  name/value/reason. Add a one-line plain_summary (str) to every
  factor in the ranker before returning.
- NEW src/mediahub/recognition/explainer.py:
    explain_achievement(achievement: dict, factors: list[dict]) -> dict
  Returns {"headline": str (15-25 words), "bullets": list[str] (3-5
  short bullets), "source_lines": list[dict] with file_offset,
  raw_text, and a human label}.
- src/mediahub/web/web.py review page: for each ach_row, render the
  explanation under a collapsible "Why this card?" disclosure. Use the
  existing card layout — do NOT introduce a new template engine.
  Include a "Copy reasoning" button so users can paste the explanation
  into a sponsor report.
- src/mediahub/web/web.py api_create_graphic and api_live_caption:
  optionally append the explanation as a data block on every
  generated card response so the JSON consumers also have it.

ACCEPTANCE CRITERIA:
- Every card in the content pack has a "Why this card?" toggle.
- Expanding it shows the headline + bullets + 1-3 cited source lines.
- The source lines are quoted verbatim from the original results file
  (no AI rewording — these are evidence quotes).
- The explanation must NEVER contain text that isn't supported by the
  factor data or the source file. If an explanation cannot be grounded,
  show "Generated for: ranked top-N by overall score" only.

DON'T BREAK:
- The existing scoring pipeline output shape must remain a superset
  of the old shape — new fields are additive.
- Existing tests for the ranker / explainer / recognition must still pass.

TESTS:
- Add tests/test_explainer.py covering: a PB swim produces a
  PB-mention bullet, a non-PB swim does not falsely claim a PB,
  source lines are returned with non-empty raw_text.
- Full pytest must stay at 253+.

Reference: dissertation §5 Dimension 2, §6 Workstream 2.1.
```

### Verification Prompt

```
Verify Step 3 (Visible Intelligence) is correct and grounded.

1. Tests: full pytest + tests/test_explainer.py -v.

2. Grounding correctness — the critical check:
   - Pick one existing run with at least 10 ranked achievements.
   - For each card, fetch the "Why this card?" data via the API.
   - For each bullet, search the original results file for evidence
     supporting the claim. Report any bullet that is NOT supported
     verbatim or by clear factor data. ZERO unsupported bullets is
     the pass threshold.

3. PB claim integrity:
   - Find at least 3 cards where pb=False. Confirm none of those
     explanations contain the substring "PB", "personal best", or
     "first time".
   - Find at least 3 cards where pb=True. Confirm at least one
     bullet mentions PB.

4. UI:
   - Open the review page for the run in a browser. Screenshot the
     content pack with one card's "Why this card?" expanded.
   - Confirm the disclosure uses the existing dark palette and that
     the source-line quotes are visually distinct (monospace font or
     italic).

5. Copy-button:
   - Click "Copy reasoning" on one card. Paste the clipboard contents
     and confirm it matches the on-screen text.

6. Regression sweep:
   - All four caption tones still generate (sample 2 cards).
   - Brand DNA capture from Step 1 still works.
   - Voice analysis from Step 2 still works.
   - /add-input, /settings, /upload all 200.

OUTPUT: single report with sections 1-6.
```

---

## Step 4: Output Expansion — Animated Graphics and Short-form Video

### Context
The horizontal leaders (Holo, Blaze, Predis) ship animated and video output natively. MediaHub today produces static cards. This step adds two new output types using Remotion (already in the installed skills) so a meet produces motion-graphic story cards and a 15-second reel of the top three moments.

### Implementation Prompt

```
Add motion-graphic and short-form video output types.

GOAL: every card in the content pack has an optional "Generate motion
version" button that produces an MP4 (story-format 1080x1920, 6 sec)
and "Generate reel from this meet" produces a 15-second multi-card
reel.

FILES TO MODIFY:
- NEW src/mediahub/remotion/ directory with:
  - package.json (Node project, Remotion 4.x)
  - src/Root.tsx, src/compositions/StoryCard.tsx,
    src/compositions/MeetReel.tsx
  - render.js: a CLI entry-point that takes a JSON props file and
    output path, renders the composition, exits 0 on success.
- NEW src/mediahub/visual/motion.py:
    render_story_card(card_payload: dict, brand_kit: dict, out_path: Path) -> Path
    render_meet_reel(top_cards: list[dict], brand_kit: dict, out_path: Path) -> Path
  Both call out to the Node CLI via subprocess; cache outputs by content
  hash in DATA_DIR / "motion_cache" / <hash>.mp4.
- src/mediahub/web/web.py: new routes
  /api/runs/<run_id>/card/<card_id>/motion (POST)
  /api/runs/<run_id>/reel (POST)
  Both render lazily (return existing cached file if present) and serve
  the MP4 with correct mime type.
- src/mediahub/web/web.py review page: add "Generate motion" buttons
  next to "Create graphic" on each card and a "Generate reel" button at
  the top of the content pack.

ACCEPTANCE CRITERIA:
- Click "Generate motion" → MP4 produced in <30s on a card that's been
  rendered before (cache hit) and <90s cold.
- Click "Generate reel" → MP4 produced from the top-3 cards with brand
  colours, palette, and a smooth transition between cards.
- Both outputs use the same brand_kit as the static cards (palette,
  logo, typography hint).
- Variation seed from src/mediahub/creative_brief/generator.py is
  honoured so re-renders of the same card produce the same motion.
- Node + Remotion install is documented in CLAUDE.md.

DON'T BREAK:
- Static graphic generation (api_create_graphic) still works.
- The existing Playwright headless Chromium path for static images
  still works.
- pytest stays at 253+ (Remotion tests are integration-only and may
  be skipped if Node is not installed — use pytest.skipif).

TESTS:
- tests/test_motion.py: skipif "node not installed"; otherwise verify
  a 1-second test render produces a valid MP4.

Reference: dissertation §4.1 (Holo's video output), §4.2 (Blaze's
limit on video), §6 Workstream 1.2.
```

### Verification Prompt

```
Verify Step 4 (Motion + Reel output) end-to-end.

1. Node + Remotion install:
   - which node; node --version. Report.
   - cd src/mediahub/remotion && npm ls remotion. Confirm Remotion 4.x
     installed.

2. Pytest: full run + tests/test_motion.py -v. If Node missing, the
   skipif must be active. Report.

3. Smoke render — static card to motion:
   - Pick one existing run with at least 3 cards.
   - POST /api/runs/<id>/card/<id>/motion. Time the call. Confirm
     200 + Content-Type: video/mp4 + file size > 100 KB.
   - Re-call. Confirm cache hit (response time < 1s).
   - Open the MP4 (ffprobe or VLC) and confirm:
     - Resolution 1080x1920 (story format)
     - Duration 5-7 seconds
     - Audio stream optional (it's fine if silent)

4. Meet reel:
   - POST /api/runs/<id>/reel. Confirm 200 + MP4.
   - Duration 14-16 seconds, contains at least 3 distinct card
     visuals (sample 3 frames at t=3, t=8, t=13 and confirm they differ).

5. Brand fidelity:
   - Pick a frame from the reel and visually confirm the palette
     matches the club's brand_kit (primary colour visible in the
     background, logo somewhere on screen).

6. UI:
   - On the review page, screenshot the card with the "Generate
     motion" button. Click it, screenshot the result (preview should
     embed a <video> tag).

7. Regression:
   - Static graphics still render via api_create_graphic.
   - Caption tone tabs all still generate live.
   - /organisation, /settings, /upload all 200.

OUTPUT: single report.
```

---

## Step 5: Output Expansion — Turn-Into and Newsletter Format

### Context
Blaze's Turn-Into converts one piece of content into 60+ derivatives. For MediaHub the equivalent is: one meet produces a recap post, a swimmer-spotlight series, a data thread, a parent-newsletter section, a sponsor thank-you, a coach quote, and a next-meet preview — automatically, in one workflow.

### Implementation Prompt

```
Implement sport-native Turn-Into: one meet produces 7 derivative
content artefacts.

GOAL: on the review page, a "Turn meet into content pack" button
generates seven derivative pieces from a single meet:
  1. Meet recap post (single feed-format card + caption)
  2. Swimmer spotlight series (one card per top-3 swimmer)
  3. Data-led thread (3-5 numbered posts for X/LinkedIn)
  4. Parent newsletter section (HTML + plain-text, ~200 words)
  5. Sponsor thank-you post (mentions sponsor_name from ClubProfile)
  6. Coach quote post (one card + caption, coach quote synthesised from
     the meet narrative — flagged "draft, needs coach approval")
  7. Next-meet preview (if next meet info present in profile, a
     teaser; otherwise skip with a clear note)

FILES TO MODIFY:
- NEW src/mediahub/turn_into/__init__.py
- NEW src/mediahub/turn_into/pipeline.py:
    turn_meet_into_pack(run_data: dict, profile: ClubProfile) -> dict
  Returns {artefacts: [{type, title, captions, cards, html?}], ...}.
- NEW src/mediahub/turn_into/templates.py: the seven artefact builders.
  Each builder must use the existing brand_kit + voice_profile +
  generate_caption_for_tone primitives — DO NOT introduce a parallel
  generation pipeline.
- src/mediahub/web/web.py:
  - new POST /api/runs/<run_id>/turn-into route
  - on the review page: "Turn meet into content pack" button at the
    top of the content pack section
  - new GET /runs/<run_id>/pack/<pack_id> renders the generated pack
- Storage: DATA_DIR / "turn_into_packs" / <run_id> / <pack_id>.json.
  Old packs preserved; the user can re-generate.

ACCEPTANCE CRITERIA:
- Clicking Turn-Into produces all 7 artefacts (or 6 if next-meet
  data is absent) within 60s.
- Each artefact uses the loaded club voice_profile so the language
  matches the brand.
- Sponsor thank-you appears only if sponsor_name is set in ClubProfile
  (else skipped with a note).
- The coach-quote post is clearly labelled "DRAFT — review with coach
  before publishing".
- Each artefact has a per-platform variant where applicable (the X
  thread is 3-5 posts of ≤280 chars; the LinkedIn variant is one
  longer post; the Instagram caption is ≤2,200 chars).
- The user can edit each caption inline and save.

DON'T BREAK:
- Existing single-card generation still works.
- Visible-intelligence "Why this card?" still works on the recap.
- /upload, /organisation, /settings all still 200.

TESTS:
- tests/test_turn_into.py: deterministic-mode test (no LLM) that
  asserts pipeline structure (7 artefacts max, sponsor skip works,
  next-meet skip works).
- Full pytest at 253+.

Reference: dissertation §4.2 (Blaze's Turn-Into), §6 Workstream 2.3.
```

### Verification Prompt

```
Verify Step 5 (Turn-Into) end-to-end.

1. Tests: full pytest + tests/test_turn_into.py -v.

2. Smoke run with full data:
   - Use an existing run with sponsor_name set.
   - POST /api/runs/<id>/turn-into. Confirm 200, returns 7 artefacts.
   - Confirm each artefact has non-empty captions/content.
   - Confirm the coach-quote post is labelled DRAFT.

3. Smoke run with sponsor absent:
   - Remove sponsor_name from the profile temporarily.
   - Re-run Turn-Into. Confirm 6 artefacts (no sponsor thank-you) and
     a clear skip message in the response.

4. Per-platform variants:
   - Confirm the X thread has 3-5 posts, each ≤280 chars.
   - Confirm the Instagram caption is ≤2,200 chars and present.
   - Confirm the LinkedIn post exists and is longer than the X variant.

5. Brand fidelity:
   - Confirm the captions reflect the loaded voice_profile (compare
     with and without a voice_profile set — outputs must differ).

6. Inline editing:
   - On the rendered pack page, edit one caption and click Save.
   - Reload the page. Confirm the edit persists.

7. Storage:
   - ls DATA_DIR/turn_into_packs/<run_id>/. Confirm a pack JSON was
     written. Old packs (if any) still present.

8. Regression sweep:
   - All four caption tones still work.
   - Motion/reel generation still works.
   - Brand DNA capture, voice imitation, visible intelligence all
     still work.

OUTPUT: single report.
```

---

## Step 6: Publishing Layer (Buffer Integration)

### Context
MediaHub today produces downloadable assets; competitors close the loop with native scheduling and publish APIs. To close the gap fast we integrate via Buffer/Hootsuite first (faster, weaker moat) and build native publishing in Phase 2 (Step 12).

### Implementation Prompt

```
Add a publishing layer via Buffer's API.

GOAL: from a content pack or Turn-Into pack, the user can click
"Schedule" on any card to queue it in their connected Buffer account
across one or more channels. Human approval is required before
anything is scheduled — no autopost.

FILES TO MODIFY:
- src/mediahub/web/secrets_store.py: add get/set for buffer_access_token.
- NEW src/mediahub/publishing/buffer.py:
    list_channels(token: str) -> list[dict]
    schedule_post(token: str, channel_id: str, text: str,
                  media_urls: list[str] | None,
                  scheduled_at: datetime | None) -> dict
  Use Buffer's API v1 (https://api.bufferapp.com); document the
  endpoints used in a docstring.
- src/mediahub/web/web.py:
  - /settings: add a "Connect Buffer" section with an access-token
    input (manual paste for now; full OAuth deferred to Step 12).
  - new GET /api/buffer/channels — returns the user's channels.
  - new POST /api/runs/<run_id>/card/<card_id>/schedule
    Body: {channel_ids: [..], scheduled_at: iso, caption: str,
           media_url: str | null}.
  - On the content pack / pack page: a "Schedule…" button on each
    card opens a modal with channel checkboxes, an editable caption,
    and a date/time picker. The Send button POSTs to the new route.
- workflow state: extend WorkflowStore so a card has a
  schedule_status (queued|scheduled|published|failed) and a
  buffer_update_id for back-reference.

ACCEPTANCE CRITERIA:
- /settings has a Buffer section; pasting a token, saving, and
  reloading shows "Connected" + the user's channel count.
- "Schedule" modal lists the user's channels.
- Submitting the modal returns 200 from Buffer and updates the
  card's schedule_status to "scheduled".
- A failure from Buffer is shown clearly without losing the user's
  edited caption.
- Without a connected token, the Schedule button shows "Connect
  Buffer in Settings" instead of opening the modal.

DON'T BREAK:
- All earlier features (Brand DNA, voice, visible intelligence,
  Turn-Into, motion) still work.
- /settings still works for Gemini and Anthropic keys.
- pytest at 253+.

TESTS:
- tests/test_publishing_buffer.py: mock Buffer's HTTP API, test
  list_channels and schedule_post with both success and failure paths.
  Test that a missing token raises a clear error.

Reference: dissertation §5 Dimension 5, §6 Workstream 1.3.
```

### Verification Prompt

```
Verify Step 6 (Buffer publishing) end-to-end.

1. Tests: full pytest + tests/test_publishing_buffer.py -v.

2. Settings flow:
   - Open /settings. Confirm the Buffer section is visible.
   - Without a token, the Schedule button on any card must show
     a "Connect Buffer in Settings" hint instead of opening a modal.

3. Mocked happy path (no real Buffer account needed):
   - Set BUFFER_API_BASE_URL env to a mock server hosted in a staging
     deploy (or use the test stub in-process).
   - Save a fake token via /settings POST.
   - GET /api/buffer/channels returns mocked channels.
   - POST /api/runs/<id>/card/<id>/schedule returns 200, and the
     card's schedule_status in WorkflowStore is now "scheduled".

4. Failure path:
   - Configure the mock to return 401.
   - POST schedule. Confirm the UI surfaces a clear error ("Buffer
     rejected the request — re-check your token") and the original
     caption text is preserved in the modal.

5. No autopost:
   - Confirm there is NO code path that sends to Buffer without an
     explicit POST from the user. Grep for buffer.schedule_post — every
     call site must be reachable only via the schedule route.

6. Audit log:
   - Confirm every schedule attempt writes a row to the workflow
     state with timestamp, card_id, channel_ids, success/failure,
     and (if available) the Buffer update_id.

7. Regression sweep:
   - All caption tones still work.
   - Turn-Into still produces 6-7 artefacts.
   - Motion still renders.
   - Brand DNA capture still works.

OUTPUT: single report.
```

---

## Step 7: Commercial Layer — Stripe, Tiers, Self-Serve Signup

### Context
MediaHub has no commercial layer today. The dissertation prescribes shipping public pricing, self-serve signup, and a free tier alongside Phase 1's product improvements so commercial pressure surfaces during iteration.

### Implementation Prompt

```
Add a commercial layer: signup, Stripe billing, three tiers.

GOAL: a new user can land on /, click "Get started", create an account
with email + password, choose a plan (Free / Club £30/mo / Federation
£250/mo), pay via Stripe Checkout, and start using MediaHub on the
hosted service.

FILES TO MODIFY:
- NEW src/mediahub/web/auth.py: minimal email+password auth (use
  passlib bcrypt; sessions via Flask's session cookie with a
  signed secret).
- NEW src/mediahub/web/billing.py: Stripe Checkout session creation,
  webhook handler for subscription events.
- src/mediahub/web/web.py:
  - new GET/POST /signup, /login, /logout
  - new GET /pricing (3-tier table)
  - new GET /billing (current plan, manage subscription via Stripe
    Customer Portal)
  - new POST /webhooks/stripe (verify signature, update subscription
    status)
  - guard premium features (multi-club, enterprise tools — to be
    added in Phase 3) behind a plan check; existing features remain
    open on Free.
- DB: extend the existing DATA_DIR storage with a users.jsonl ledger
  (email, hashed_password, plan, stripe_customer_id, created_at).
  Do not introduce SQLAlchemy.
- environment: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET,
  STRIPE_PRICE_CLUB, STRIPE_PRICE_FEDERATION.
- Free tier limits: 3 runs/month, single brand profile, no Buffer
  scheduling. Soft limit (a banner) — never lock the user out
  permanently on free.

ACCEPTANCE CRITERIA:
- /signup creates a user, hashes the password, logs them in.
- /pricing shows the three tiers with feature lists.
- "Upgrade" buttons start a Stripe Checkout flow (use Stripe test
  mode keys for dev).
- A successful Stripe Checkout webhook updates the user's plan.
- /billing lets the user manage their subscription via Stripe Customer
  Portal.
- Self-hosted deployments (no STRIPE_SECRET_KEY env) continue to
  work — auth is optional, billing routes return 503 with a clear
  "billing is not configured for this deployment" message.

DON'T BREAK:
- Any existing route that was open is still open if no STRIPE_*
  env vars are configured.
- pytest at 253+.
- The Stop hook git push flow continues to work.

TESTS:
- tests/test_auth.py: signup, login, logout, password hashing.
- tests/test_billing.py (mocked Stripe): webhook verification,
  subscription update flow.

Reference: dissertation §5 Dimension 6, §6 Workstream 1.4.
```

### Verification Prompt

```
Verify Step 7 (Commercial layer) end-to-end.

1. Tests: full pytest + tests/test_auth.py + tests/test_billing.py -v.

2. Self-hosted-without-billing path:
   - With STRIPE_SECRET_KEY unset, boot the app.
   - GET /, /add-input, /upload, /organisation, /settings — all 200.
   - GET /pricing and /billing — 200 (show "billing not configured").
   - All caption / motion / Turn-Into routes work as before.

3. Signup / login flow:
   - POST /signup with a fresh email + 12-char password. Confirm
     redirect to /add-input + a session cookie.
   - Log out. Log back in. Confirm session restored.
   - Submit a wrong password. Confirm a clear error, not a 500.
   - Confirm passwords in users.jsonl are bcrypt hashes (not plain).

4. Stripe-mode (test keys):
   - Set STRIPE_SECRET_KEY, STRIPE_PRICE_CLUB, STRIPE_PRICE_FEDERATION
     to Stripe test values.
   - Hit /pricing. Click "Upgrade to Club".
   - Confirm a Stripe Checkout session URL is returned and the test
     mode page renders (open in browser, fill 4242 4242 4242 4242).
   - Complete checkout. Confirm the webhook handler updates the
     user's plan in users.jsonl to "club".

5. Free tier soft limit:
   - On a Free account, create 3 runs. Create a 4th. Confirm a banner
     appears (NOT a hard lock).

6. Buffer scheduling guarded:
   - On Free, the Schedule button must show "Upgrade to schedule
     posts" instead of opening the modal.

7. Security checks:
   - Try to access /billing without a session. Confirm redirect to
     /login.
   - Inspect the session cookie — must be HttpOnly + Secure (when
     served via HTTPS) and signed.
   - Grep the codebase for STRIPE_SECRET_KEY — must only appear in
     billing.py and never logged.

8. Regression sweep: all features from Steps 1-6 still work.

OUTPUT: single report.
```

---

# Phase 2 — Distinction (Steps 8-12, target months 3-9)

## Step 8: Sport Expansion — Athletics (Track and Field)

### Context
MediaHub today is swimming-only. Athletics is the natural second sport — overlapping audience (school athletic programmes, multi-sport clubs), similar result-file structure (event, time/distance, place), but a different event vocabulary and a different PB taxonomy.

### Implementation Prompt

```
Add athletics (track and field) as MediaHub's second sport.

GOAL: a user can upload an athletics result file (CSV or Hytek-format
.txt) on /upload, MediaHub recognises athletes, computes PBs, ranks
achievements, and produces a content pack with athletics-appropriate
language.

FILES TO MODIFY:
- NEW src/mediahub/sports/: refactor the sport-specific bits of the
  existing pipeline out of swimming-implicit code paths. Each sport
  should have:
    sports/<sport>/events.py — canonical event vocabulary
    sports/<sport>/parser.py — result-file parsers
    sports/<sport>/pb_logic.py — PB and record detection
    sports/<sport>/templates.py — celebratory phrase patterns
- src/mediahub/sports/__init__.py: register a SPORTS dict and a
  pick_sport(file_bytes, hint) -> SportModule selector.
- src/mediahub/sports/swimming/: move existing swimming code here
  (preserve all behaviour and tests).
- src/mediahub/sports/athletics/: new athletics implementation.
  Event vocabulary: 100m, 200m, 400m, 800m, 1500m, 3000m, 5000m,
  10000m, hurdles (60m/100m/110m/400m), steeplechase, all field
  events (LJ, TJ, HJ, PV, SP, DT, HT, JT), relays. Distinguish
  TRACK (time-based) from FIELD (distance/height-based) for PB
  comparison logic.
- src/mediahub/web/web.py /upload: detect sport from filename and
  content; allow user to override via a sport dropdown.
- ClubProfile: add primary_sport field; default to "swimming" for
  backward compatibility.

ACCEPTANCE CRITERIA:
- Uploading an athletics result file produces an athletics-specific
  content pack with phrases like "smashed a PB" appropriate to track
  ("ran a personal best") and field ("threw a personal best").
- A field PB is correctly detected (higher = better) vs track PB
  (lower = better).
- All swimming tests still pass — no regression.
- Adding a third sport in future is a matter of creating a new
  sports/<sport>/ subpackage, no refactoring of the platform code.

DON'T BREAK:
- Every existing swimming test (interpreter, recognition, corpus,
  visual, caption) still passes.
- pytest at 253+ (new athletics tests added).
- All Phase 1 features (Brand DNA, voice, visible intelligence,
  Turn-Into, motion, Buffer publishing) work for athletics output.

TESTS:
- tests/test_athletics_parser.py: parse a sample athletics CSV,
  verify event detection.
- tests/test_athletics_pb_logic.py: field PB (higher = better) and
  track PB (lower = better) are correctly classified.
- tests/test_sports_registry.py: pick_sport routes correctly.

Reference: dissertation §4.9 (FanWord's 19 sports), §6 Workstream 2.2.
```

### Verification Prompt

```
Verify Step 8 (Athletics support) end-to-end with no swimming regression.

1. Tests:
   - python -m pytest tests/ -q. Must be 253+ plus the new athletics
     tests (target 260+).
   - python -m pytest tests/test_athletics_*.py
     tests/test_sports_registry.py -v.

2. Swimming regression:
   - Upload an existing swimming sample file. Confirm the content pack
     is identical in structure to pre-Step-8 behaviour.
   - All four caption tones generate; visible intelligence shows PB
     reasoning; Turn-Into produces 6-7 artefacts; motion renders.
   - tests/test_interpreter_smoke.py, tests/test_pb_discovery.py,
     tests/test_corpus_recovery.py — all pass.

3. Athletics happy path:
   - Upload a sample athletics CSV. Confirm sport detection routes
     to athletics.
   - Confirm event names include 100m, 800m, LJ, TJ, etc.
   - Confirm PB logic: a long jump of 6.45m beats a previous 6.30m
     (higher = better); a 100m time of 11.40 beats 11.50 (lower = better).
   - Confirm captions use athletics-appropriate language ("ran a
     PB in the 800m" not "swam a PB").

4. Sport switching:
   - Manually override sport from swimming → athletics on the /upload
     page. Confirm the override takes effect.

5. Module structure:
   - ls src/mediahub/sports/ — confirms swimming/ and athletics/
     subpackages.
   - python -c "from mediahub.sports import SPORTS, pick_sport;
     print(list(SPORTS.keys()))"
     — confirms both sports registered.

6. Regression sweep on Phase 1:
   - All 7 Phase 1 steps' features still work (sample one feature
     from each).

OUTPUT: single report.
```

---

## Step 9: Athlete-Facing Micro-Surfaces

### Context
Greenfly routes content from a league to athletes for personal sharing. For MediaHub the parallel is letting a swimmer/athlete receive their own personal share-ready cards via a private link, which they post to their own channels. This expands distribution beyond the club account.

### Implementation Prompt

```
Add athlete-facing micro-surfaces for personal sharing.

GOAL: each swimmer/athlete in a run can be given a personal,
unlisted link to a page that shows their cards for that meet plus
their season-to-date highlights, with a "Share to Instagram" / "Save
to camera roll" affordance per card. No login required for the
swimmer.

FILES TO MODIFY:
- src/mediahub/athlete_pages/: new module.
- Token: per-athlete unlisted token = HMAC(server_secret, run_id +
  athlete_id), 24 chars base32. Stored in run JSON.
- src/mediahub/web/web.py:
  - new GET /a/<token> — renders the athlete page. No auth required.
  - new GET /a/<token>/card/<card_id>/share — returns the card as a
    direct-download image for the athlete to save and post.
  - new POST /api/runs/<run_id>/athlete-tokens — admin route on the
    review page: generate or revoke tokens for athletes in the run.
- Review page: "Send to athlete" button on each card; clicking copies
  the personal share link (or opens a QR code modal for in-person
  hand-off).
- Privacy: the athlete page MUST NOT show any other swimmer's data,
  the original results file, or any club admin surface.

ACCEPTANCE CRITERIA:
- An athlete with a token can see only their own cards.
- The link is unguessable (HMAC + secret rotation).
- An admin can revoke a token; revoked tokens render a "this link has
  been revoked" page.
- Share affordances work on mobile: tapping "Save to camera roll" on
  iOS Safari triggers a long-press save flow; on Android, a direct
  download.
- Page renders correctly on screens 320px wide (smallest common mobile).

DON'T BREAK:
- All earlier features still work.
- Privacy: no PII leakage from athlete page to the rest of the
  system. Specifically: an athlete cannot enumerate other tokens.

TESTS:
- tests/test_athlete_pages.py: token generation determinism, HMAC
  verification, revoked-token handling, isolation between athletes.

Reference: dissertation §4.10 (Greenfly), §6 Workstream 2.5.
```

### Verification Prompt

```
Verify Step 9 (Athlete pages) end-to-end.

1. Tests: full pytest + tests/test_athlete_pages.py -v.

2. Happy path:
   - On an existing run, generate a token for athlete A and athlete B.
   - GET /a/<token_A> — confirm 200, shows only A's cards.
   - GET /a/<token_B> — confirm 200, shows only B's cards.
   - Try GET /a/<token_A> with one character changed — confirm 404,
     NOT a leak of the original page.

3. Isolation:
   - On A's page, the response body must NOT contain B's swimmer_name.
   - The page must NOT contain the path to the results file.

4. Revocation:
   - Revoke A's token. Re-fetch /a/<token_A> — confirm a clear
     "revoked" page, status 410 or 200 with a message.

5. Mobile rendering:
   - Open /a/<token_A> in a 360x800 viewport. Screenshot.
   - Confirm cards fit, text is readable, the share buttons are
     thumb-sized (≥44px).

6. Share affordance:
   - GET /a/<token>/card/<card_id>/share — must return an image with
     Content-Disposition: attachment.

7. Regression sweep: all Phase 1 + Step 8 features still work.

OUTPUT: single report.
```

---

## Step 10: Sponsor-Aware Generation

### Context
Sponsors are a primary revenue driver for clubs and the buyer's biggest stakeholder. A sponsor-aware product variant of every output type — caption with sponsor mention, graphic with sponsor logo, newsletter section with sponsor block — turns MediaHub into a sponsorship-value-realisation tool.

### Implementation Prompt

```
Make every output type sponsor-aware.

GOAL: when ClubProfile has sponsor_name + sponsor_guidelines set,
every generated caption, graphic, motion, reel, and Turn-Into
artefact has an opt-in sponsor variant. The sponsor variant must
respect the guidelines (e.g. "always include #BrandNameSwim";
"never combine our logo with a competitor's").

FILES TO MODIFY:
- ClubProfile: extend with sponsor_logo_path,
  sponsor_brand_colour (hex), sponsor_required_hashtags (list),
  sponsor_forbidden_phrases (list), sponsor_activation_rate
  (e.g. "every 3rd post"), sponsor_position_preference
  (top|bottom|watermark).
- src/mediahub/sponsor/: new module:
    apply_sponsor_to_caption(caption: str, profile: ClubProfile,
                              activation: bool) -> str
    apply_sponsor_to_graphic(graphic_brief: dict,
                              profile: ClubProfile) -> dict
- Generators (caption, graphic, motion, Turn-Into) call the sponsor
  apply functions when activation=True. Activation is determined by
  the sponsor_activation_rate or explicit user toggle per card.
- review page: a "Sponsor mode" toggle on each card; the entire
  content pack also has a global toggle.
- Compliance: a "Sponsor compliance check" panel lists each generated
  artefact and confirms it satisfies all guidelines or flags
  violations.

ACCEPTANCE CRITERIA:
- With sponsor configured, the sponsor toggle on a card produces a
  sponsor variant that:
  - Includes any required hashtags.
  - Avoids any forbidden phrases.
  - Displays the sponsor logo in the configured position.
  - Uses the sponsor brand colour as a tasteful accent (without
    overriding the club's primary palette).
- The compliance panel surfaces any violation clearly.
- Without a sponsor configured, the toggle is hidden, not greyed out.

DON'T BREAK:
- All earlier features still work.
- pytest at 260+ (athletics tests added in Step 8).

TESTS:
- tests/test_sponsor_pipeline.py: required-hashtag enforcement,
  forbidden-phrase blocking, logo positioning.

Reference: dissertation §6 Workstream 2.5 (sponsor variants in
output expansion).
```

### Verification Prompt

```
Verify Step 10 (Sponsor mode) end-to-end.

1. Tests: full pytest + tests/test_sponsor_pipeline.py -v.

2. Configuration round-trip:
   - Set sponsor_name + sponsor_required_hashtags ["#TestSponsor"]
     + sponsor_forbidden_phrases ["beat the competition"].
   - Save, reload /organisation. Confirm the fields persist.

3. Sponsor caption check:
   - Toggle "Sponsor mode" on one card.
   - Confirm the caption now contains "#TestSponsor".
   - Force the LLM (or heuristic) to produce text containing "beat the
     competition" via a test fixture, run the apply function, and
     confirm the phrase is removed or rewritten.

4. Sponsor graphic check:
   - Toggle sponsor mode, regenerate the graphic.
   - Open the image; confirm the sponsor logo appears in the
     configured position.
   - Confirm the sponsor colour appears as an accent (not as
     the primary background).

5. Compliance panel:
   - Configure a deliberate violation (a required hashtag NOT present
     in the caption). Confirm the compliance panel flags it visibly.

6. Sponsor absent:
   - Clear sponsor_name. Confirm the sponsor toggle is hidden, not
     present in the DOM.

7. Regression sweep: all Phase 1 and Steps 8-9 features still work.

OUTPUT: single report.
```

---

## Step 11: Multi-Sport Architecture Cleanup + Football/Rugby

### Context
With athletics shipped in Step 8 the sports/ package exists. Adding football and rugby validates that the architecture genuinely scales and unlocks the largest UK market segment (school and university football/rugby).

### Implementation Prompt

```
Add football and rugby as sports 3 and 4; clean up the sports/
architecture as needed.

GOAL: a user can upload a football match report (CSV / structured
text / one-pager PDF) and get a content pack appropriate to football
(goal scorers, clean sheets, man-of-the-match, league position,
fixture preview). Same for rugby (tries, conversions, line-out
stats, set-piece dominance, man-of-the-match).

FILES TO MODIFY:
- src/mediahub/sports/football/: events.py (match events: goals,
  assists, yellow/red cards, subs), parser.py (parse common
  match-report formats including OPTA-style CSV if available),
  achievement_logic.py (goal-of-the-match, hat-trick detection,
  clean-sheet recognition), templates.py.
- src/mediahub/sports/rugby/: similar structure for rugby union
  (tries, conversions, penalties, man-of-the-match, line-out wins).
- Generalise the existing pb_logic.py — for team sports it's
  achievement_logic.py with different primitives. Refactor the
  swimming/athletics modules to use a common interface
  (sports/<sport>/achievement_logic.py) where appropriate.
- /upload: detect sport from file content + filename.
- /organisation: add a "Sports" multi-select so a club can declare
  it covers multiple sports.

ACCEPTANCE CRITERIA:
- A hat-trick is correctly detected and surfaced as the headline
  achievement in football.
- A clean sheet is correctly attributed to the goalkeeper.
- Rugby man-of-the-match selection prefers tries > conversions >
  metres made if not explicitly named in the input.
- A clean league position (1st in the table) is detected as a
  high-priority achievement.
- All previous sports tests (swimming + athletics) still pass.

DON'T BREAK:
- pytest at the new baseline (target 280+).
- Phase 1 features remain functional on football/rugby output.

TESTS:
- tests/test_football_*.py and tests/test_rugby_*.py covering parsing,
  achievement detection, and caption generation.

Reference: dissertation §4.9 (FanWord's 19 sports), §6 Workstream 2.2.
```

### Verification Prompt

```
Verify Step 11 (Football + Rugby) end-to-end.

1. Tests: full pytest. Target 280+ passed.
   - python -m pytest tests/test_football_*.py tests/test_rugby_*.py -v.

2. Hat-trick detection:
   - Upload a football match where player X scored 3 goals.
   - Confirm the top-ranked card mentions a hat-trick.
   - Confirm the visible-intelligence reasoning includes goal count.

3. Clean sheet attribution:
   - Upload a 2-0 win match. Confirm the goalkeeper's card mentions
     "clean sheet".

4. Rugby try detection:
   - Upload a rugby match with 4 tries by player Y. Confirm Y is the
     headline and the caption uses rugby-appropriate language.

5. Multi-sport club:
   - Set a club's sports to ["swimming","football"]. Upload swimming.
     Confirm swimming pipeline. Upload football. Confirm football
     pipeline.

6. Cross-sport caption consistency:
   - Same voice_profile applied to a football caption and a swimming
     caption — the stylistic signature (sentence length, hashtag
     count) should match across both.

7. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

## Step 12: Native Publishing APIs (Replace Buffer Dependency)

### Context
Step 6 shipped Buffer integration to close the publishing gap fast. This step builds direct integrations to Instagram Graph API, Facebook Pages, X (v2), LinkedIn Marketing, and TikTok Business so MediaHub no longer depends on Buffer for the core publishing path.

### Implementation Prompt

```
Replace Buffer dependency with native publishing APIs.

GOAL: a user can connect Instagram Business, Facebook Pages, X,
LinkedIn (Company Page), and TikTok Business directly. Scheduling
no longer requires a Buffer account.

FILES TO MODIFY:
- src/mediahub/publishing/instagram.py: Graph API; OAuth via
  Facebook Login. Single-image + reels upload + caption.
- src/mediahub/publishing/facebook.py: Pages API; OAuth via
  Facebook Login.
- src/mediahub/publishing/x_twitter.py: v2 API; OAuth 2.0 with PKCE.
- src/mediahub/publishing/linkedin.py: Marketing Developer Platform;
  OAuth 2.0.
- src/mediahub/publishing/tiktok.py: TikTok Business API; OAuth 2.0.
- src/mediahub/publishing/scheduler.py: a unified Scheduler interface
  (queue, schedule_at, dispatch_now) so the UI calls one API
  regardless of platform.
- A background worker (lightweight — Flask-APScheduler or a simple
  cron-style polling thread) that dispatches scheduled posts at
  their scheduled_at time.
- /settings: native "Connect Instagram", "Connect Facebook" etc.
  buttons (in addition to the existing Buffer field, which remains
  as a fallback).

ACCEPTANCE CRITERIA:
- A user can complete the OAuth flow for each platform and the
  resulting access tokens are stored encrypted (Fernet) in
  DATA_DIR / "secrets" / <user_id>.json.
- Scheduling a post via the UI dispatches to the right platform at
  the right time.
- Token refresh is handled before each dispatch.
- Buffer remains available as a fallback channel; users can choose
  per-card whether to dispatch direct or via Buffer.

DON'T BREAK:
- pytest at the new baseline (target 290+ with publishing tests).
- All earlier features still work.

TESTS:
- tests/test_native_publishing.py: mocked OAuth + dispatch, token
  refresh, dispatcher worker.

Reference: dissertation §5 Dimension 5 risks (publishing-API
landscape closing), §6 Workstream 3.x.
```

### Verification Prompt

```
Verify Step 12 (Native publishing) end-to-end.

1. Tests: full pytest + tests/test_native_publishing.py -v.

2. OAuth flows (mocked):
   - For each of the 5 platforms, simulate the OAuth callback with a
     fixed test token. Confirm the token is stored encrypted (not
     plaintext) in the per-user secrets file.

3. Dispatch (mocked):
   - Schedule a post with scheduled_at = now + 30s.
   - Wait 45s. Confirm the post was dispatched via the mocked API.
   - Confirm the workflow state shows schedule_status=published.

4. Token refresh:
   - Set an expired-token scenario. Confirm the dispatcher refreshes
     the token before dispatching, or surfaces a clear "re-connect"
     error if refresh fails.

5. Buffer fallback:
   - Confirm Buffer is still selectable per-card and the Buffer
     dispatch path still works.

6. Security:
   - grep the codebase for any access_token logging — must be zero.
   - Confirm the encrypted secrets file mode is 0600.

7. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

# Phase 3 — Leadership (Steps 13-17, target months 9-18)

## Step 13: Integration Moat — Hy-Tek, TeamUnify, ClubBuzz Importers

### Context
The single most defensible distribution moat against horizontal entrants is direct integration with the software clubs already use. Hy-Tek MeetManager (results), TeamUnify (club management), ClubBuzz (UK clubs), SwimManager — each integration is one to three engineering weeks and creates a switching cost.

### Implementation Prompt

```
Build first-class importers for the most-used club software.

GOAL: a user with a TeamUnify or ClubBuzz account can connect MediaHub
once, and every new meet result automatically flows into MediaHub
without a manual upload.

FILES TO MODIFY:
- src/mediahub/integrations/teamunify.py: OAuth or API key auth,
  poll for new meet results, ingest as a new run, run the full
  pipeline.
- src/mediahub/integrations/clubbuzz.py: same pattern.
- src/mediahub/integrations/hytek_meetmanager.py: file-format
  importer for the .hy3 format with deeper coverage than the existing
  parser (handle all common event codes, age groups, time conversions).
- src/mediahub/integrations/splash_meet_manager.py: file-format
  importer for Splash's export format.
- /settings: new "Integrations" section with one-click connect
  buttons.
- A background polling worker for the API-based integrations.

ACCEPTANCE CRITERIA:
- A connected TeamUnify account auto-ingests new meets within 1 hour
  of them appearing in TeamUnify.
- Hytek and Splash file imports produce identical content packs to
  manual uploads.
- A revoked integration cleanly stops polling and surfaces in the UI.

DON'T BREAK:
- Manual file upload still works.
- pytest at the new baseline (target 300+).

TESTS:
- tests/test_integrations_*.py: mocked API responses, end-to-end
  ingestion.

Reference: dissertation §4.4 (Ocoya integration moat), §6 Workstream 3.1.
```

### Verification Prompt

```
Verify Step 13 (Integrations) end-to-end.

1. Tests: full pytest + tests/test_integrations_*.py -v.

2. TeamUnify mocked happy path:
   - Connect with a test API key.
   - Push a fake new-meet event via the mock server.
   - Confirm a new run appears in MediaHub within the polling interval.
   - Confirm the run produces a valid content pack.

3. Hytek parity:
   - Take an existing .hy3 file that worked with the manual uploader.
   - Run it through the new importer. Confirm the resulting content
     pack is identical (same number of achievements, same ranking).

4. Splash importer:
   - Process a sample Splash file. Confirm event detection + PB
     attribution.

5. Disconnection:
   - Revoke the test API key. Confirm polling stops within 1 polling
     cycle and the /settings page shows "Disconnected".

6. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

## Step 14: Enterprise Tier — Multi-Club Orchestration

### Context
The financial backbone of the strategy. Governing bodies, leagues, federations, and large university athletic departments need multi-club orchestration: branded league templates, federation-wide engagement analytics, sponsorship reporting across clubs.

### Implementation Prompt

```
Ship the enterprise tier: multi-club orchestration.

GOAL: a Federation user (Stripe enterprise plan from Step 7) can
manage up to 50 clubs from one account, push league-branded templates
to all clubs, view aggregated engagement analytics, and produce
sponsorship reports.

FILES TO MODIFY:
- Data model: introduce Organisation (governing body / league) →
  Club → Run hierarchy. Backward-compatible: a club without an
  organisation is treated as a standalone (today's default).
- src/mediahub/enterprise/: new module:
    OrganisationProfile dataclass
    league_templates.py — manage and distribute templates
    aggregated_analytics.py — engagement metrics across child clubs
    sponsorship_report.py — sponsor-exposure metrics with citations
- new pages:
  /federation — dashboard
  /federation/clubs — manage child clubs
  /federation/templates — push templates
  /federation/analytics — aggregated metrics
  /federation/sponsorship — sponsor reports
- billing: Stripe plan "federation" unlocks these pages.

ACCEPTANCE CRITERIA:
- A federation user can add a child club and the child club's owner
  receives an invite link to accept the relationship.
- Pushing a template to all child clubs makes the template available
  in each club's Turn-Into picker.
- Aggregated analytics correctly sum engagement across all child
  clubs and never double-count.
- A sponsorship report can be exported as a branded PDF.

DON'T BREAK:
- Standalone clubs (no parent organisation) work exactly as before.
- pytest at the new baseline (target 310+).

TESTS:
- tests/test_enterprise_*.py covering hierarchy, template push,
  analytics aggregation, sponsorship report generation.

Reference: dissertation §6 Workstream 3.2, §4.8 (Nota at small-club
scale).
```

### Verification Prompt

```
Verify Step 14 (Enterprise tier) end-to-end.

1. Tests: full pytest + tests/test_enterprise_*.py -v.

2. Hierarchy:
   - Create a federation account and three child clubs.
   - Confirm the federation dashboard shows all three.
   - Sign in as one child club — confirm it can see only its own runs.

3. Template push:
   - Federation pushes a "Meet Recap League Template".
   - Each child club's Turn-Into picker now includes it.

4. Analytics:
   - Federation analytics page sums engagement across the three clubs.
   - Manually verify the sum equals the per-club totals.

5. Sponsorship report:
   - Generate a sponsorship PDF for the federation's headline sponsor.
   - Confirm the PDF includes per-club sponsor activations with
     citations (which post, which date, which platform).

6. Plan guard:
   - On a non-federation plan, the federation pages return a clear
     upgrade prompt, not a 404.

7. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

## Step 15: Conversational / Agentic Caption Editing

### Context
Lately's Kately and Holo's chat-editor demonstrate the next interaction primitive: a conversational layer over the existing content pack. "Make this caption more energetic", "Add a thank-you to the parents", "Generate a TikTok script from this meet" — the user issues natural-language instructions and the agent operates over the existing assets.

### Implementation Prompt

```
Add a conversational editing surface to the content pack.

GOAL: every card on the review page has a chat panel where the user
can issue natural-language edit commands ("shorter", "more energetic",
"in Spanish", "add a sponsor mention", "generate a TikTok variant").
The agent uses the existing tools (generate_caption_for_tone,
sponsor.apply, motion.render_story_card) rather than free-form
generation.

FILES TO MODIFY:
- src/mediahub/agent/__init__.py
- src/mediahub/agent/tools.py: register the tools the agent can call
  (regenerate_caption, change_tone, translate_caption, add_sponsor,
  generate_motion, generate_reel_variant).
- src/mediahub/agent/runner.py: a small tool-use loop using the
  existing LLM (Gemini or Anthropic) with structured tool calling.
- /review page: a chat panel toggle next to each card.
- Every agent action writes an audit entry (who, when, what tool,
  what arguments, what result) to DATA_DIR/agent_audit/<run_id>.jsonl.

ACCEPTANCE CRITERIA:
- "Make this shorter" produces a caption ≤80% of the original length.
- "Make this in Spanish" produces Spanish output.
- "Add a sponsor mention" calls the sponsor.apply tool and produces
  a sponsor variant.
- The agent NEVER publishes — every change is staged and requires
  the user's Save click.

DON'T BREAK:
- pytest at the new baseline (target 320+).
- All earlier features still work.

TESTS:
- tests/test_agent_*.py: tool invocation, no-publish guarantee,
  audit log integrity.

Reference: dissertation §4.5 (Kately), §4.1 (Holo chat editor),
§6 Workstream 3.3.
```

### Verification Prompt

```
Verify Step 15 (Agentic editing) end-to-end.

1. Tests: full pytest + tests/test_agent_*.py -v.

2. Edit commands:
   - "shorter" → length reduction confirmed.
   - "more energetic" → tone shift confirmed (compare against baseline).
   - "in Spanish" → output is Spanish (langdetect).
   - "add a sponsor mention" → sponsor hashtag present.

3. No-publish guarantee:
   - Issue 10 agent commands. Confirm NONE of them dispatched a
     publish action. The audit log should show zero publishing tool
     calls.

4. Audit:
   - For each agent action, confirm DATA_DIR/agent_audit/<run_id>.jsonl
     has a corresponding entry with full arguments and result.

5. Tool safety:
   - Try to inject "delete this run" via the chat input. Confirm the
     agent does not call any destructive tool (no such tool exists in
     the registry).

6. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

## Step 16: Template Marketplace

### Context
Community templates raise switching cost. Once a club has invested in templates that exist only on MediaHub — branded recap layouts, voice profiles, season-narrative arcs — leaving the platform costs them their accumulated content infrastructure.

### Implementation Prompt

```
Ship a community template marketplace.

GOAL: clubs and federations can publish templates (visual layouts,
voice profiles, Turn-Into recipes, sponsor activation patterns) for
other clubs to fork. Templates are versioned and reviewable.

FILES TO MODIFY:
- src/mediahub/marketplace/: new module.
- Template types: visual_layout (graphic + motion templates),
  voice_profile_template (anonymised voice patterns),
  turn_into_recipe (which 7 artefacts a Turn-Into produces and how),
  sponsor_activation (predefined sponsor variants for common partners).
- /marketplace page: browse, preview, fork.
- /marketplace/submit: submit a template (with review queue).
- /marketplace/admin: review/approve/reject submissions (federation
  + MediaHub admin role).

ACCEPTANCE CRITERIA:
- A submitted template enters a review queue.
- Forking a template clones it into the user's own club profile —
  edits to the fork do not affect the source.
- Templates are versioned; the user can upgrade their fork to a newer
  source version.
- Marketplace search by sport, audience size, language.

DON'T BREAK:
- pytest stays green.
- All earlier features still work.

TESTS:
- tests/test_marketplace_*.py covering submission, fork, version
  upgrade, isolation between fork and source.

Reference: dissertation §6 Workstream 3.4.
```

### Verification Prompt

```
Verify Step 16 (Template marketplace) end-to-end.

1. Tests: full pytest + tests/test_marketplace_*.py -v.

2. Submit + approve:
   - As a club user, submit a visual_layout template.
   - As an admin, approve it.
   - The template now shows in /marketplace.

3. Fork:
   - As another club, fork the template. Confirm the fork lives in
     the new club's profile.
   - Edit the fork. Confirm the source is unchanged.

4. Version upgrade:
   - As the source owner, publish version 2.
   - The fork shows an "upgrade available" badge. Confirm the upgrade
     applies cleanly.

5. Search:
   - Search by sport=athletics. Confirm only athletics templates
     appear.

6. Privacy:
   - Confirm voice_profile_template templates are anonymised (no
     PII / no club name leaked) before they enter the public
     marketplace.

7. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

## Step 17: Sponsor-Side Analytics Product

### Context
The final defensible primitive: a sponsor-facing product that proves to the sponsor the value of their brand exposure across a club's content. Nota and FanWord do not do this at small-club scale; this is a category MediaHub can own.

### Implementation Prompt

```
Build a sponsor-side product surface.

GOAL: a sponsor (the brand paying the club) can log in and see a
dashboard of all the times their brand appeared in content produced
by clubs they sponsor, with engagement metrics and an estimated
brand-exposure value.

FILES TO MODIFY:
- New user role: sponsor. Sponsor accounts are linked to specific
  club profiles via an invitation flow.
- src/mediahub/sponsor_dashboard/: new module.
- /sponsor — sponsor dashboard.
- /sponsor/exposure — list of every post where this sponsor's brand
  appeared, with date, platform, engagement, and a thumbnail of
  the asset.
- /sponsor/value — estimated brand-exposure value (impressions ×
  CPM-equivalent based on the platform).
- /sponsor/export — branded PDF report.

ACCEPTANCE CRITERIA:
- A sponsor can only see content produced by clubs they sponsor.
- Engagement metrics are pulled from the publishing layer's
  post-success records (Step 12).
- The brand-exposure value calculation is documented and auditable
  (open the value calculation in a tooltip).
- The PDF export is reproducible and includes citations to every
  source post.

DON'T BREAK:
- pytest stays green.
- All earlier features still work.

TESTS:
- tests/test_sponsor_dashboard_*.py: scoping (sponsor sees only their
  clubs), metric calculation determinism, PDF export shape.

Reference: dissertation §6 Workstream 3.5.
```

### Verification Prompt

```
Verify Step 17 (Sponsor-side product) end-to-end.

1. Tests: full pytest + tests/test_sponsor_dashboard_*.py -v.

2. Scoping:
   - Sponsor A is linked to Club 1 and Club 2 (not Club 3).
   - Sponsor A's exposure page shows posts from Club 1 and 2 only.
   - Confirm Club 3's posts do NOT appear in any sponsor query.

3. Metric calculation:
   - For a post with known engagement, manually compute the value
     using the documented formula. Confirm the dashboard matches.

4. PDF export:
   - Export a sponsor report. Confirm it opens, contains citations,
     and is reproducible (re-export, byte-equality of the content
     section).

5. Sponsor cannot leak admin:
   - As a sponsor, attempt to access /federation, /admin,
     /api/runs/<id>/turn-into. All must return 403.

6. Regression sweep: all earlier features still work.

OUTPUT: single report.
```

---

# Final Audit — After Step 17 (or any time after Step 7)

### Context
At any milestone the full product should be audited end-to-end. This audit is the prompt to run after a major release.

### Audit Prompt

```
Conduct a full MediaHub product audit.

OBJECTIVE: confirm that every feature shipped to date — every step
in the roadmap that has been completed — still works end-to-end with
no regressions, and that the product as a whole holds up against the
quality bar set by the competitors documented in
docs/competitor_dissertation_2026.md.

PHASE A — Automated tests:
1. python -m pytest tests/ -q. Report pass/skip/fail counts.
2. python -c "from mediahub.web.web import create_app; create_app()".
3. Boot the app: python -m mediahub.web.web (background).
4. Confirm 0 ERROR-level log lines on a clean boot.

PHASE B — Route sweep:
For each of these routes, confirm a 200 (or correct 30x/40x):
- GET /, /add-input, /upload, /organisation, /settings, /privacy
- GET /pricing, /signup, /login (if Step 7 shipped)
- GET /free-text, /weekend-preview, /sponsor-post, /session-update
- GET /spotlight (if implemented)
- GET /federation, /federation/clubs (if Step 14 shipped)
- GET /marketplace (if Step 16 shipped)
- GET /sponsor (if Step 17 shipped)

PHASE C — Critical user journeys, for each completed step:
- Brand DNA capture: paste a URL, confirm preview, save. Should work.
- Voice imitation: paste 5 examples, save, confirm voice_profile.
- Visible intelligence: open any run, confirm "Why this card?" works.
- Motion: render a story card; render a reel.
- Turn-Into: produce 6-7 artefacts from a meet.
- Buffer or native publishing: schedule a mocked post.
- Commercial: signup, login, upgrade (Stripe test mode).
- Athletics: upload athletics sample, confirm pipeline.
- Athlete page: generate a token, fetch /a/<token>.
- Sponsor mode: toggle on a card, confirm variant.
- Football/Rugby: upload sample, confirm hat-trick / clean sheet.
- Native publishing OAuth: complete one platform's mock flow.
- Integrations: TeamUnify mocked auto-ingest.
- Enterprise: multi-club orchestration.
- Agent: 5 edit commands all hit tools correctly.
- Marketplace: submit + approve + fork.
- Sponsor dashboard: scope correctness + PDF export.

PHASE D — Cross-cutting quality:
- Visual polish: open / and the review page in a browser; screenshot.
  Compare against tryholo.ai's homepage. List any obvious gaps.
- Performance: time a fresh upload-to-content-pack run end-to-end.
  Target < 90s for a 200-swim meet.
- Security: grep the codebase for hardcoded API keys, exposed
  secrets in logs, Path("data/...") relative paths. Report any.
- Test isolation: confirm tests do not write to the real
  data/secrets.json or club_profiles/*.json.
- Accessibility: run a quick a11y scan on the review page. Report
  contrast and keyboard-nav issues.

PHASE E — Strategic position:
For each of the 10 competitors in the dissertation, evaluate where
MediaHub now stands on a 5-point Leading / Competitive / Adequate /
Underdeveloped / Absent scale across the 6 dimensions:
1. Input modality
2. Intelligence layer
3. Output surface
4. Brand context capture
5. Distribution
6. Commercial model

Cross-reference with §5 of the dissertation. Has MediaHub moved up
the matrix on the dimensions Phase 1 targeted? Are there new gaps
that have opened?

OUTPUT FORMAT:
Return a structured audit report:
- Phase A: automated tests results
- Phase B: route table with status codes
- Phase C: per-step pass/fail table
- Phase D: a quality scorecard (1-5) per cross-cutting area
- Phase E: an updated competitive matrix
- Top 5 regression risks (ordered by severity)
- Top 5 next-step recommendations
- A single "release readiness" verdict: Ship / Hold / Block.
```

---

## Notes on running this roadmap

**Branching.** Every step is a feature branch off `dev`; never merge to `main` without approval. Use names like `step-01-brand-dna-capture`, `step-06-buffer-publishing`. The verification prompt is run before opening the merge request.

**Sequencing.** Steps 1-7 (Phase 1) should be done strictly in order — each builds on the previous. Steps 8-12 (Phase 2) can be partially parallelised once Step 8 (sports architecture) is in. Steps 13-17 (Phase 3) are highest value when done in the order shown but Step 14 (enterprise tier) is the highest financial priority; consider promoting it earlier if revenue is the limiting factor.

**Test budget.** Maintain ≥ 253 passed at every step. Each step adds 5-15 tests, so by Step 17 expect 350+ passing.

**When verification fails.** Paste the failing report back into the implementation session of the same step. Do not move forward until a clean verification report is produced.

**When you stop following the prompts.** Each step is designed to be readable on its own. If during implementation Claude needs context that the prompt didn't provide, the prompt is at fault — improve the prompt and re-run rather than letting Claude guess.

**Source of truth.** This document and `docs/competitor_dissertation_2026.md` are paired references. The dissertation is the strategic argument; this document is the execution plan. Edits to one should be reflected in the other.

---

*End of roadmap.*
