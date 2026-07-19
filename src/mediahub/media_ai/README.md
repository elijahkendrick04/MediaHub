# media_ai

The everyday AI helper for writing captions, describing pictures and cutting people
out of photos. It uses `ai_core` underneath to reach the AI services.

- `llm.py` — writes captions and reads pictures. (The network call to Gemini
  itself lives in `ai_core/gemini_transport.py`, shared with `ai_core`.)
- `providers/` — cuts the background out of a photo.
- `imagine.py` + `imagine_providers/` — **makes and edits pictures** (the P6.3
  generative-imagery seam): generate from a prompt, lift a subject, and more.
  Every made picture is stamped as AI-made and counts against the club's monthly
  allowance. With no picture model set up it says so honestly instead of faking
  one.

Plain-English words: see ../../../GLOSSARY.md
