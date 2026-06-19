"""mediahub.audio — the audio engine (roadmap 1.8).

A first-party, licence-clean audio subsystem for the reel/video engines and the
voice layer:

* :mod:`~mediahub.audio.library` — the music + SFX catalogue (bundled CC0 pool +
  operator directories), with licence/mood/energy/platform metadata.
* :mod:`~mediahub.audio.select` — AI selection of the track that fits a reel's
  emotional arc (``media_ai``, honest-error), over a deterministic floor.
* :mod:`~mediahub.audio.ops` — deterministic FFmpeg edits (trim/fade/gain/speed/
  extract/concat/mix/convert).
* :mod:`~mediahub.audio.clean` — deterministic denoise + EBU R128 loudness
  levelling ("Enhance Voice" / "Balance All").
* :mod:`~mediahub.audio.voice` — voice catalogue + SSML-ish params + the per-org
  pronunciation lexicon, layered over the shipped ``visual/voiceover`` seam.
* :mod:`~mediahub.audio.rights` — the licence ledger + upload fingerprinting.

Standing rules honoured here: deterministic maths stay deterministic (ops/clean/
the content-hash pick); the one judgement surface (which track suits the reel)
goes through ``media_ai`` and honest-errors; nothing fabricates a track or a
licence; every bundled asset is genuinely first-party and CC0.
"""

from mediahub.audio.library import (
    KINDS,
    PLATFORMS,
    AudioLibrary,
    AudioTrack,
    Licence,
    assets_dir,
    load_library,
)
from mediahub.audio.select import (
    AudioSelectionUnavailable,
    Selection,
    describe_arc,
    select_or_default,
    select_track,
)
from mediahub.audio.voice import (
    VOICE_CATALOGUE,
    OrgLexicon,
    Voice,
    VoiceParams,
    default_voice,
    get_voice,
    list_voices,
)

__all__ = [
    # library
    "AudioLibrary",
    "AudioTrack",
    "Licence",
    "PLATFORMS",
    "KINDS",
    "assets_dir",
    "load_library",
    # select
    "AudioSelectionUnavailable",
    "Selection",
    "describe_arc",
    "select_track",
    "select_or_default",
    # voice
    "Voice",
    "VOICE_CATALOGUE",
    "VoiceParams",
    "OrgLexicon",
    "list_voices",
    "get_voice",
    "default_voice",
]
