# Prompt Inventory

Every Claude / LLM prompt template in the source. Search performed across all `*.py` for triple-quoted strings containing `system:` or `\nUser:` markers, plus explicit `_SYSTEM_PROMPT`/`SYSTEM`/`PROMPT` variables.

| File | Constant | First line of prompt |
|---|---|---|
| `src/mediahub/web/ai_caption.py` | `_SYSTEM_PROMPT` | Kept for back-compat with tests that import it. The new pipeline |

## Where to read the full prompts

- AI caption — `src/mediahub/web/ai_caption.py`
- Vision creative direction — `src/mediahub/creative_brief/generator.py`
- Media description — `src/mediahub/media_library/describe.py`
- Voice render guidance — `src/mediahub/voice/multi_tone_renderer.py`
