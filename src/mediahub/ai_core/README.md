# ai_core

The low-level plumbing that talks to the AI services. If the first one (Gemini)
fails, it automatically switches to a backup (Claude), so the app keeps working.

- `llm.py` — ask the AI a question, with or without tools; picks the provider
  and switches to the backup on a passing failure.
- `gemini_transport.py` — the one place that actually talks to Gemini over the
  network, for both AI helpers (this one and `media_ai`): one HTTP call, one
  secret-scrubber for error messages, and one overload switch that pauses
  Gemini briefly when it keeps failing.
- `llm_client.py` — the same idea for optional OpenAI-compatible servers.
- `narrate.py` — turns swim data into plain English before asking the AI.
- `prompt_guard.py` — keeps untrusted web text from steering the AI.

Plain-English words: see ../../../GLOSSARY.md
