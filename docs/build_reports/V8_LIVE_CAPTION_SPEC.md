# V8 — Live caption tone toggle (quick win)

## Goal
On every achievement card on the recognition page, show a tone toggle that lets the user pick:

- AI Generated (Claude, generated live, no DB caching)
- Each saved voice profile (data_led / hype / warm_club + any user-added voice)

When the user picks a tone, the caption regenerates **live** for that card. No pre-generated database of captions. No stale text.

## Architecture

### Backend
1. New endpoint `POST /api/runs/<run_id>/swim/<swim_id>/caption?tone=<voice_id|ai>` returns `{caption: str, tone: str, generated_at: iso}`
2. For voice tones: call `voice.learned.render.render_caption(achievement, profile, n_variants=1)` and return.
3. For tone=`ai`: call Computer's LLM bridge (Claude Sonnet) with a tight prompt:
   - System: "You are a sports social-media writer producing one caption for a swimming achievement. Keep it specific, human, club-appropriate, ~280 chars max, no generic filler, never invent facts."
   - User: structured achievement JSON.
4. Use `bash` LLM helper script if available, else direct anthropic API via `os.environ["ANTHROPIC_API_KEY"]`. Add a feature-flag fallback to voice render if neither works (graceful degradation).

### Frontend
On each achievement card, add a small tone toggle:

```
[ AI ▼ ] (button group: AI / Data-led / Hype / Warm-club)
```

Click → fetch → swap caption text in place + show small "regenerated live just now" timestamp.

Plus a "Regenerate" pill that re-runs the same tone (for AI it gets a fresh result).

## Constraints
- ZERO caching of AI captions at backend. Each click = fresh generation.
- Voice-rendered captions can stay client-side cached for the session (they're deterministic).
- Loading state ("Generating…") with spinner in the caption area while the AI request is in-flight.
- All copy buttons / approval flows continue to work — they just operate on whatever caption is currently displayed.

## Files to touch
- `swim_content_v4/web.py` — new `/api/runs/<run_id>/swim/<swim_id>/caption` route + tone-toggle HTML in card template + JS handler
- New module `swim_content_v4/ai_caption.py` — generate_ai_caption(achievement_dict, club_brand) → str
- New helper `media_ai/llm.py` (or reuse if exists) — Claude Sonnet wrapper using anthropic SDK or Computer LLM bridge

## Tests
- `tests_v75/test_live_caption_endpoint.py` — endpoint exists, returns JSON, voice tones produce different output, AI tone gracefully falls back to voice if no API key.

## Acceptance
- I open mediahub.pplx.app, upload Manchester PDF, click on a card, toggle to "AI" → caption regenerates live, different from voice version. Toggle again → fresh regeneration.
