# The deterministic engine is off-limits to AI

Accuracy of "is this a PB?" and "which card outranks which?" matters more than
flexibility. LLMs are too non-deterministic for these. Do **not** propose
Gemini-ifying any of the following without explicit user approval.

## Modules that stay deterministic

| Concern | Module(s) |
|---|---|
| Result parsing | `interpreter/`, `pb_discovery/parse_pbs.py` |
| Achievement detection | `recognition/`, `recognition_swim/achievements/` |
| Ranking / content-worthiness | `legacy/swim_content_v5/ranker_v3.py` |
| Colour science (contrast, ΔE2000, CVD, palette maths) | `theming/` (incl. `logo_chip.py`) |
| Mathematical asset scoring | `media_library/selector.py::score_asset` (fixed weights) |

## Why

- **Parsers / detectors / ranker:** a hallucinated PB or a reordered ranking
  destroys the trust the product is sold on. The same input must give identical
  output, every time.
- **Colour science:** brand colour and accessibility (APCA, ΔE2000, colour-vision
  deficiency) are *computed*, not guessed — an LLM can't guarantee a contrast
  ratio.
- **`score_asset`:** fixed weights are fast, reproducible, and tuned. An LLM call
  per asset would add seconds per content pack for no quality win.

## You MAY

- Read these modules' outputs and feed them into an AI judgement surface.
- Improve them with **deterministic** code (better parse rules, new detectors,
  ranking tweaks) — with tests proving identical-or-better behaviour for the
  same input.

## You MUST NOT

- Replace any of the above with an LLM call.
- Add an AI "fallback" that guesses a PB / rank / colour when the deterministic
  path is uncertain. Flag uncertainty instead — the pipeline surfaces
  low-confidence rows for human review; never silently guess.
