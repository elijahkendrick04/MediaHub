"""video — MediaHub's footage path: the video suite (roadmap 1.6).

Where ``visual`` renders *data-driven* video (reels/story cards from card data),
``video`` is the **footage path**: a club uploads or records real clips and
MediaHub turns them into branded, captioned, reframed cuts with the same
approval-before-export flow.

The pieces, smallest to largest:

* :mod:`.probe`       — measure a clip (duration, shape, audio) via ``ffmpeg -i``.
* :mod:`.edl`         — the Edit Decision List (+ colour grade + audio plan) and
  its deterministic FFmpeg compiler.
* :mod:`.moments`     — deterministic highlight detection (+ optional AI labelling).
* :mod:`.silence`     — deterministic dead-air detection + jump-cut planning.
* :mod:`.reframe`     — saliency-tracked aspect reframe (16:9 ↔ 9:16 ↔ 1:1).
* :mod:`.enhance`     — deterministic enhancement passes (stabilise, looks, upscale).
* :mod:`.captions`    — the editable styled caption layer over the ASR seam.
* :mod:`.caption_render` — burn captions (static or animated/karaoke word-sweep).
* :mod:`.audio_post`  — soundtrack pass: clean voice + ducked music + loudness.
* :mod:`.render`      — render an EDL to MP4, cache-keyed, server-side, honest.
* :mod:`.clip_maker`  — Clip-Maker-for-sport: footage → branded cut (one clip).
* :mod:`.director`    — AI judgement: order/look/mood/hook for a reel (honest default).
* :mod:`.reel_builder`— assemble a branded reel from many clips (the centrepiece).
* :mod:`.matting`     — video background removal, behind a provider slot (flagged).
* :mod:`.avatars`     — opt-in, disclosed AI avatars, behind a provider slot (flagged).
* :mod:`.broll`       — opt-in, disclosed generative b-roll, behind a provider slot (flagged).
* :mod:`.dub`         — opt-in, disclosed lip-sync / dubbing, behind a provider slot (flagged).
* :mod:`.object_removal` — opt-in, disclosed object removal / inpainting (flagged).
* :mod:`.eye_contact` — opt-in eye-contact (gaze) correction — a pixel edit (flagged).
* :mod:`.ingest`      — bring footage into the media library (consent-aware).
* :mod:`.projects`    — per-profile persistence for saved timelines + approval state.

The standing rules hold throughout: detection/ranking/compilation, the colour
grade, the silence cuts and the soundtrack DSP are all **deterministic**; the
judgement surfaces (moment labelling, the reel director's order/look/mood/hook)
are AI and honest-erroring with a deterministic default; rendering is
**server-side** and cached; a **human approves before export**; and synthetic
people are opt-in and disclosed.
"""

from .edl import EDL, Clip, EDLError, TextOverlay, Transition, compile_filtergraph, validate
from .probe import ClipProbe, ProbeUnavailable, probe_clip

__all__ = [
    "EDL",
    "Clip",
    "Transition",
    "TextOverlay",
    "EDLError",
    "compile_filtergraph",
    "validate",
    "ClipProbe",
    "ProbeUnavailable",
    "probe_clip",
]
