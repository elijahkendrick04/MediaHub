# assistant

The **club content copilot** (P6.2): edit an already-designed card by *talking
to it*. You type "make the headline punchier, more navy" and the assistant makes
the change — but it never paints pixels and it never posts anything. Instead it
proposes a small, structured list of edits (a "spec patch"), the system checks
every edit is allowed and still readable, applies the good ones, and re-renders.

Plain-English words: see ../../../GLOSSARY.md · full guide: docs/CONVERSATIONAL_ASSISTANT.md

What's in here:

- `patch.py` — the heart. The closed list of edits the assistant may make
  (`set_headline`, `set_mood`, `set_archetype`, `set_format`, `set_colour_role`,
  …), and the validator that applies them to a **copy** of the design. Unknown
  edits are dropped; a colour change that would be unreadable is rejected (the
  same readability/APCA check the renderer uses). Every edit is listed
  (applied vs skipped + why) and reversible. No AI here — pure and testable.
- `tools.py` — the small, fixed set of tools the AI may use: *read* the design,
  brand and facts, *list* the formats, and *propose* an edit. There is
  deliberately **no** tool to publish, post, schedule or fetch — the AI simply
  can't do those things.
- `copilot.py` — runs one conversation turn over `ai_core.ask_with_tools`,
  applies the validated edits, and records the turn. If no AI provider is
  configured it says so honestly and leaves the design untouched (your manual
  controls keep working).
- `session.py` — the chat history + edit log for each card (auditable,
  reversible — each turn is a new design version).
- `memory.py` — the org's preference book ("we never show times for
  8-and-unders"). You add to it explicitly ("remember this"), and you can see
  and delete everything in it. The copilot reads the relevant ones each turn.
- `asr.py` — the voice seam. The browser transcribes speech on-device (free, no
  provider); this server seam handles uploaded audio by delegating to the local
  ASR engine (`../visual/transcribe.py` — faster-whisper / whisper.cpp, roadmap
  1.4) and returning just the text. With no provider configured it honestly
  errors (the browser path stays the live default).

Magic-Write-style caption tools (Summarise / Expand / Rewrite, on top of the
existing Shorter / Punchier / Tidy) live on the caption engine
(`../web/caption_assist.py`).
