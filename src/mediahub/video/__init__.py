"""video — MediaHub's footage path: the video suite (roadmap 1.6).

Where ``visual`` renders *data-driven* video (reels/story cards from card data),
``video`` is the **footage path**: a club uploads or records real clips and
MediaHub turns them into branded, captioned, reframed cuts with the same
approval-before-export flow.

The pieces, smallest to largest:

* :mod:`.probe`       — measure a clip (duration, shape, audio) via ``ffmpeg -i``.
* :mod:`.edl`         — the Edit Decision List + its deterministic FFmpeg compiler.
* :mod:`.moments`     — deterministic highlight detection (+ optional AI labelling).
* :mod:`.reframe`     — saliency-tracked aspect reframe (16:9 ↔ 9:16 ↔ 1:1).
* :mod:`.captions`    — the editable styled caption layer over the ASR seam.
* :mod:`.render`      — render an EDL to MP4, cache-keyed, server-side, honest.
* :mod:`.clip_maker`  — Clip-Maker-for-sport: footage → branded cut (the centrepiece).
* :mod:`.matting`     — video background removal, behind a provider slot (flagged).
* :mod:`.avatars`     — opt-in, disclosed AI avatars, behind a provider slot (flagged).
* :mod:`.ingest`      — bring footage into the media library (consent-aware).
* :mod:`.projects`    — per-profile persistence for saved timelines + approval state.

The standing rules hold throughout: detection/ranking/compilation are
**deterministic**; the one judgement surface (moment labelling) is AI and
honest-erroring; rendering is **server-side** and cached; a **human approves
before export**; and synthetic people are opt-in and disclosed.
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
