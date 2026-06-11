"""ai_core — the AI reasoning layer for MediaHub.

User direction: "I want there to be the option to run it on Claude
or Gemini APIs." So the public interface is provider-agnostic
— callers just say `ask(...)` and the active provider runs the call.

Per product direction it is also:

- Free of hand-coded action enums, JSON envelopes, or template
  fallbacks. Inputs are natural-language prose, outputs are
  natural-language prose. The model does the reasoning.
- Tool-equipped where possible (Claude (Anthropic) tool-use + Gemini
  function-calling). Tools let the model fetch web evidence so
  reasoning stays grounded.
- Honest about failures. If no provider is configured, callers get
  ``ProviderNotConfigured``. If the provider errors, callers get
  ``ProviderError`` and surface that to the user — no silent fake
  output from template strings.

Provider selection (operator-controlled at deploy time, env vars only):
  1. MEDIAHUB_LLM_PROVIDER env var ∈ {claude, gemini, auto}
  2. "auto" (the default) → Gemini first if configured, then Claude
"""

from .llm import (
    ProviderNotConfigured,
    ProviderError,
    ToolCallRecord,
    ToolConversation,
    ask,
    ask_with_tools,
    active_provider,
)
from .narrate import (
    narrate_achievement,
    narrate_brand,
    narrate_meet,
)

__all__ = [
    "ProviderNotConfigured",
    "ProviderError",
    "ToolCallRecord",
    "ToolConversation",
    "ask",
    "ask_with_tools",
    "active_provider",
    "narrate_achievement",
    "narrate_brand",
    "narrate_meet",
]
