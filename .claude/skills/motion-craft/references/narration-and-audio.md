# Narration and audio

Craft rules for the opt-in audio path. Adapted from HyperFrames' narration
guidance (Apache-2.0, `vendor/hyperframes-skills-main/`), constrained by
MediaHub's deterministic, fact-only audio model.

## The model (do not loosen it)

- Narration is **template-over-verified-labels** (`visual/narration.py`) —
  fixed sentence shapes filled with the same facts the video displays. No
  LLM in this path, ever; that's what keeps a spoken claim impossible to
  hallucinate.
- Voiceover is opt-in (`MEDIAHUB_VOICEOVER=1`); music is an
  operator-licensed bed (`MEDIAHUB_REEL_MUSIC_DIR`), picked
  deterministically, ducked under speech
  (`audio_mux.py`: bed 0.40 alone, 0.30 under voice, 0.6s fade-out).
- **Honest silence**: any synthesis/mux failure ships the video silent with
  the reason in the manifest. Never a placeholder track. Silent-path cache
  keys stay byte-identical.
- Most feed video plays muted — audio is reinforcement, never the only
  carrier of a fact.

## Pacing budgets

`narration.py::WORDS_PER_SECOND = 2.4` is the planning constant; the mux
hard-trims to video length regardless, so scripts must fit by design, not
by truncation:

- story card (6s) ≈ 14 words — one card line + club sign-off.
- reel: cover line + one line per card beat + outro, each card line ≈ 9–10
  words to land inside its 4s beat.
- Silence between sentences is a feature. A template that fills every
  second reads robotic; the script should feel *shorter* than the video.

## Writing template sentences (when editing `narration.py`)

The craft applies to the fixed templates themselves — improve the shapes,
keep them deterministic:

- Write like a person: contractions, varied sentence length, no brochure
  phrases. Read the rendered script aloud; if it sounds robotic, reshape
  the template, not the facts.
- Numbers are written as speech: that's `spoken_time()`'s job ("1:02.45" →
  "1 minute 2.45 seconds"). Any new numeric label needs the same
  treatment — TTS reads literally, so "50 Free" must be expanded by the
  template ("fifty metres freestyle"), never left for the voice to guess.
- The visual shows the exact figure; the voice may carry the *rounded
  natural phrasing* the template defines — but never a different claim.
- Sequence narration with the choreography: the time should be on screen
  when it's spoken; the club sign-off belongs over the outro.

## Music and SFX

- Track choice is a deterministic hash over the content key into the
  operator's licensed directory — never a per-render random pick, never a
  generated track.
- No per-beat SFX layer exists today. If one is ever added it follows the
  same model: operator-licensed assets, deterministic cue mapping from beat
  boundaries, folded into the audio plan part of the cache key, honest
  silent fallback. Beats must keep landing visually without it.
