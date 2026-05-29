# AI judgement surfaces

Every judgement-based surface — which photo, which tone, which copy, brand /
palette interpretation, operating-profile derivation, media tagging — goes
through `media_ai.llm` / `ai_core.llm`. Never add a new hardcoded heuristic for
"which layout / which copy / which tone".

## Provider model

- **Gemini-first**, Anthropic as failover. `ai_core/llm.py` walks
  Gemini → Anthropic on transient errors (auth, rate-limit, HTTP 5xx). This is
  online multi-provider redundancy, **not** a local heuristic fallback.
- Usage and a coarse cost estimate are logged via
  `observability/llm_usage.py` (the operator-only `/healthz/usage` dashboard).

## Honest errors — never fabricate

When no provider is configured, surface `ProviderNotConfigured`
(`ai_core/__init__.py`) / `ClaudeUnavailableError` so the operator sees a real
error. A fake caption, stub profile, or made-up palette is **worse** than a
clear error. Do not reintroduce regex/template heuristic fallbacks for AI
surfaces.

> Distinct from this: a *real deterministic* visual — e.g. the procedural
> background in `visual/ai_background.py` — is a legitimate first-class
> fallback. It is a genuine rendered element, not a fabricated stand-in for AI
> output.

## Commercial data privacy (easy to miss)

Google's Gemini **free tier** uses submitted content and responses to improve
Google's models and permits human review of inputs/outputs. For real
customer / club data on a paid SaaS, run Gemini on **paid billing** (same key —
the train-on-data clause flips off). This is part of honouring multi-tenant
data isolation; don't ship features on real club data assuming the free tier is
private.
