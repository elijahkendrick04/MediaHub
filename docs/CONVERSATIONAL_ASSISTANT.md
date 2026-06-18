# Conversational Creative Assistant — the club content copilot (P6.2)

> **In plain words.** Once a card has a design, you can just *tell it* what to
> change — "make the headline punchier and more navy", "switch this to a square
> post", "why did this rank first?". The copilot makes safe, on-brand changes
> for you and shows you exactly what it did, so you stay in control. It never
> posts anything; a human still approves and exports. New here? Read
> [`START_HERE.md`](START_HERE.md) first.

This realises roadmap item **P6.2**. Design record:
[`adr/0022-conversational-assistant-spec-patch.md`](adr/0022-conversational-assistant-spec-patch.md).
Feature map vs Canva/Adobe: [`CREATIVE_SUITE_PARITY.md`](CREATIVE_SUITE_PARITY.md) §P6.2.

## How it works (and why it's safe)

The copilot never paints pixels and never publishes. Each turn it:

1. **Reads** the current design, the club's brand, and the card's verified
   facts — through a small, fixed set of read-only tools.
2. **Proposes a "spec patch"** — a short list of structured edits from a closed
   menu (change the headline, the mood, the layout, the format, a colour role,
   …). It cannot invent an edit that isn't on the menu, and it cannot invent a
   stat or a hex colour.
3. The system **validates every edit**: out-of-vocabulary edits are dropped, and
   a colour change that would be unreadable is rejected by the same
   readability (APCA) check the renderer uses — never painted illegibly.
4. The valid edits are applied to a **new version** of the design (the old one is
   kept, so any edit is reversible), and you can preview the result.

You see a clear list of what was applied and what was skipped (and why). Every
turn is logged against the card, so the whole conversation is auditable.

The same engine answers questions ("why did this rank first?") from the verified
facts without changing anything.

## The pieces

- **`src/mediahub/assistant/`** — the copilot package (`patch`, `tools`,
  `copilot`, `session`, `memory`, `asr`). See its README for each module.
- **Caption text-tools** — Summarise / Expand / Rewrite join the existing
  Shorter / Punchier / Tidy on the caption editor
  (`src/mediahub/web/caption_assist.py`). A tone shift just re-voices the same
  caption (warm / hype / precise).
- **Org memory** — standing preferences you save explicitly ("remember this"),
  visible and deletable, that the copilot respects every turn.
- **Voice** — a microphone button uses your browser's on-device speech
  recognition to fill the chat box (free, nothing leaves your device); a server
  speech seam exists for uploaded audio and errors honestly until a provider is
  configured.

## Using it

On the **content builder**, each card has a **Copilot…** button that opens a
chat panel: type (or speak) a change, see what it did, preview it, and save a
standing preference. Behind the scenes:

- `POST /api/runs/<run>/card/<card>/assistant` — one conversation turn (returns
  the reply + the applied/skipped edits).
- `GET /api/runs/<run>/card/<card>/assistant/suggestions` — prompt chips, seeded
  from the planner's ranked ideas (not generic filler).
- `GET/POST /api/assistant/memory` + `…/<id>/delete` — the preference book.
- `POST /api/assistant/transcribe` — the server speech seam (honest error today).

No AI key configured? The copilot says so plainly and changes nothing — every
manual control (edit the caption, pick a format, change the photo or accent)
keeps working.

## What's deliberately *not* here yet

- Generating brand-new images, backgrounds or objects → **P6.3** image AI.
- Other languages → **P6.23**.
- Tagging the assistant in a review comment → **P6.17**.
- Exposing the copilot inside ChatGPT/Claude/Gemini (an MCP server) → **P6.20**.
- Pixel-level point-and-click editing → **P6.3 / P6.4**.
