# V7.5 — Learned Voices Spec

## Goal
Replace the V7.4 hardcoded `warm-club / hype / data-led` tones with **learned voice profiles**. Engine reads exemplar posts (from the user's own club account or any account they admire), induces a voice profile, the user names it. Dropdown is populated from saved voices on disk, not hardcoded labels.

## Package layout

```
voice/learned/
  induce.py            — exemplar posts → VoiceProfile (style features)
  store.py             — save/load named voices to data/voices/
  render.py            — given a swim achievement + chosen VoiceProfile, generate a caption
  feature_extract.py   — text → style features (sentence length, emoji density, capitalisation, lexicon, sign-off, hashtag frequency)
```

## VoiceProfile schema

```python
@dataclass
class VoiceProfile:
    voice_id: str               # slug, e.g. "swansea_warm"
    display_name: str           # "Warm club voice"
    description: str
    exemplars: list[str]        # raw post texts
    features: VoiceFeatures
    created_at: str
    updated_at: str

@dataclass
class VoiceFeatures:
    avg_sentence_len: float
    capitalisation_style: str   # "sentence" / "title" / "all_caps_emphasis"
    emoji_density: float        # per-100-chars
    emoji_palette: list[str]
    hashtag_density: float
    common_hashtags: list[str]
    starting_phrases: list[str]
    sign_offs: list[str]
    name_format: str            # "first_only" / "full" / "first_initial"
    time_format: str            # how times are written
    achievement_words: list[str]   # "stunning", "big", "GOES", etc. — extracted lexicon
    exclamation_density: float
    second_person_density: float
```

## Induce algorithm

1. Tokenise + analyse each exemplar.
2. Compute features above.
3. Save profile to `data/voices/<voice_id>.json`.

## Render algorithm

Given an achievement and a VoiceProfile, render N variants:
1. Pick a starter phrase from `features.starting_phrases` (or a templated fallback if empty).
2. Inject swim facts using `features.name_format` and `features.time_format`.
3. Apply capitalisation style.
4. Append hashtags and sign-off as per features.
5. Return text.

This is a heuristic-driven renderer (no AI required), but designed so an AI step could be slotted in later (V8 has image gen; voice gen is V8+ if needed).

## Seeded voices

Pre-create three default voices in `data/voices/seed/` so existing users have something out-of-the-box (and so the V7.4 multi-tone UI still works on day one):

- `seed/warm_club.json`
- `seed/hype.json`
- `seed/data_led.json`

These are starter samples — the user can fork, edit, rename, or delete.

## UI surfaces (specced; implementation comes after engine)

- "Voices" page: list voices, edit, add new.
- "Add voice" form: name + paste 3+ exemplar posts → engine induces features → save.
- Recognition page tone tabs populated from `voice/learned.store.list_voices()`, NOT hardcoded.

## Tests

`tests_v75/test_voice_induce.py`:
- Feed 3 sample posts with known characteristics, assert features come out correct (within tolerance).
- Save + load round trip.

`tests_v75/test_voice_no_hardcoded_tones.py`:
- Grep voice/learned for the literal strings `"warm-club"`, `"hype"`, `"data-led"` — assert ZERO matches in the inducer/renderer (allowed only in seed JSON file content, which is data not code).

## Deliverable
- voice/learned/ files
- data/voices/seed/{warm_club,hype,data_led}.json
- Tests passing
- VOICES_BUILD_REPORT.md summarising
