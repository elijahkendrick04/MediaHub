# imagine_providers

The picture-making backends for the generative-imagery seam (P6.3). Each one
turns a request ("draw this", "make a variation") into image bytes — or says
honestly that it can't, instead of faking a picture.

- `base.py` — the shared shape every backend follows.
- `gemini_imagine.py` — makes pictures with Google's Imagen (needs a Gemini key).
- `local_imagine.py` — the in-house model that will run for free on our own
  server. It's the planned default, but it isn't built yet (that's P5.6), so for
  now it politely says "not available".

The chooser (`__init__.py`) picks a backend: your explicit choice first, then the
in-house one if it's ready, then Gemini if a key is set, otherwise nothing.

The friendly front door that the rest of the app talks to is
`../imagine.py` — start there. Plain-English words: see the top-level GLOSSARY.md.
