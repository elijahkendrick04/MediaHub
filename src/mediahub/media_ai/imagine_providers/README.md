# imagine_providers

The picture-making backends for the generative-imagery seam (P6.3). Each one
turns a request ("draw this", "make a variation") into image bytes — or says
honestly that it can't, instead of faking a picture.

- `base.py` — the shared shape every backend follows.
- `styles.py` — the curated "look" presets (editorial, poster, …) both backends
  share, so a style reads the same whoever draws it.
- `gemini_imagine.py` — makes pictures with Google's Imagen (needs a Gemini key).
- `local_imagine.py` — the **in-house default**: our own free model running on
  our own server. The big model runs as a separate program (like the video and
  graphics renderers do), and this file just talks to it over the network. Point
  it at the server with `MEDIAHUB_IMAGINE_LOCAL_ENDPOINT`; with no endpoint set it
  politely says "not available". This is roadmap item 1.1.

The chooser (`__init__.py`) picks a backend: your explicit choice first, then the
in-house one if it's ready, then Gemini if a key is set, otherwise nothing.

The friendly front door that the rest of the app talks to is
`../imagine.py` — start there. Plain-English words: see the top-level GLOSSARY.md.
