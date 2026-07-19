# ADR-0030 — One shared Gemini transport under two deliberate LLM wrappers

Date: 2026-07-13
Status: Accepted
Relates to: deep-review 2026-07 finding #43 (the two LLM wrappers have
materially drifted), findings #32/#33/#35/#36/#38 (previously fixed
symptoms of the same drift), ADR-0007 (official env-keyed providers only)

## Context

MediaHub carries two LLM wrapper modules by design:

- `media_ai/llm.py` — the tolerant content-generation surface
  (`generate` / `generate_json` / `generate_vision`): helpers return text
  or `None`, `generate()` walks the provider chain, and
  `ClaudeUnavailableError` is raised only when everything failed. ~33
  caller files (captions, brand, charts, video, localize, documents).
- `ai_core/llm.py` — the strict agentic surface (`ask` /
  `ask_with_tools`): helpers raise `ProviderError(transient=…)` so
  failover can branch, plus the bounded tool loop. ~22 caller files
  (copilot, free-text chat, club Q&A, deep research, autonomy, triage).

The 2026-07 deep review (finding #43) showed the *transport underneath*
them had drifted into near line-for-line duplication with real
divergence: `ai_core` hardcoded 45/60s timeouts while `media_ai`
honoured `MEDIAHUB_GEMINI_TIMEOUT`; `ai_core` sent `temperature: 0.7`
while `media_ai` sent none; the model was resolved import-time in one
and per-call in the other; and the Gemini overload circuit breaker was
one-directional — `ai_core` read it but never recorded into it, so an
outage seen only via chat/copilot never tripped the switch the caption
hot path consults.

A full repo/test dependency map was built before changing anything
(CLAUDE.md 15-step breakage check); ~150 references across prod, tests
and docs informed the design below.

## Decision

1. **Keep both wrappers.** The tolerant-`None` and strict-`raise`
   contracts serve genuinely different caller populations; merging them
   (one module, one contract) was considered and rejected — it would
   force one error philosophy onto ~55 callers for no capability gain.
2. **Extract one shared Gemini transport** —
   `src/mediahub/ai_core/gemini_transport.py` — owning exactly the layer
   that had duplicated: URL/headers (key in `x-goog-api-key`, never the
   URL), per-call model + timeout env resolution, the
   generationConfig/thinking-budget clamp, key redaction,
   transient-vs-permanent status classification, and the overload
   circuit breaker (state moved here from `media_ai/llm.py`; both
   wrappers now record into it via the transport — the breaker is
   bidirectional). Failures raise a classified, key-redacted
   `GeminiTransportError(kind, status, transient)`; each wrapper
   translates it into its own contract. This finishes the pattern
   `ai_core/llm_client.py` already established for the
   OpenAI-compatible path.
3. **Temperature policy: send none.** Both wrappers sample at the API
   default. (`ai_core`'s former `0.7` was the drift, not the design.)
4. **Timeout policy: `MEDIAHUB_GEMINI_TIMEOUT` governs every Gemini
   call**, resolved per call; call-site defaults preserved when unset
   (45s plain asks and media_ai calls, 60s tool rounds).
5. **What stays wrapper-side, deliberately:** provider failover order,
   usage-ledger rows (`observability.llm_usage`), the tolerant/strict
   error contracts, and breaker *policy* — media_ai skips Gemini
   entirely while the breaker is open (hot path, ~24-call capture
   batches); ai_core demotes Gemini to the tail of its chain but still
   tries it last.

## Unchanged invariants

- **Gemini-first** provider order, Anthropic as failover
  (CLAUDE.md rule) — untouched.
- **Honest errors** — no provider configured still surfaces
  `ProviderNotConfigured` / `ClaudeUnavailableError`; no heuristic
  fallback was added anywhere. Empty model output raises/`None`s
  honestly, citing `finishReason`.
- **Keys are env/`.env` only**, and ride the header, never the URL;
  every transport error message is key-redacted before it can reach a
  log or a user-facing error.

## Accepted residual drift (out of scope, recorded)

- The Anthropic path keeps its per-wrapper client caching (~15 lines
  each): the official SDK *is* the shared transport there, and
  consolidating the cache would couple the two error contracts for
  negligible dedup.
- `media_ai.DEFAULT_MODEL` / `ALT_MODEL` stay import-time constants
  (exported, used by tests/fixtures); `ai_core._anthropic_model()` stays
  per-call.
- `llm_client.py` keeps its own (narrower) transient-status set: same-key
  multi-*endpoint* failover treats auth as permanent, while the
  cross-*provider* set in `gemini_transport.status_transient` treats
  401/403 as transient because another provider holds a different key.
  These are different semantics, not duplication.

## Post-review amendments (same PR)

An adversarial multi-lens review of the diff (six findings, each
independently verified against the code) led to four fixes before merge:

- **Vision payloads build lazily again.** `_call_gemini_vision` had
  started base64-encoding up to 5 images *before* the no-key /
  breaker-open short-circuits; `_gemini_via_transport` now accepts a
  payload builder so a skipped call costs zero encode work, matching the
  pre-convergence hot path.
- **Redact before truncate.** Non-200 bodies were truncated to 300 chars
  and then redacted — a key straddling the cut could leave an
  un-redacted fragment. The transport (and the imagine provider's log
  line) now redact the full body first.
- **The documented empty-output shape is not "malformed".** A candidate
  whose content has no `parts` key (safety block, or MAX_TOKENS spent on
  thinking) now yields `[]` from `first_candidate_parts`, so the honest
  `Gemini returned no text (finishReason=…)` error is reachable again on
  both wrappers; the ai_core tool loop raises it too when a conversation
  produced no tool calls and no text (tool records are preserved when
  tools did run).
- **Recorded, not reverted:** gemini-vision ledger rows now use the text
  path's `auth` / `rate_limited` error kinds instead of the raw
  `http_401/403/429` they historically carried (one vocabulary across
  both Gemini surfaces). External dashboards filtering the old vision
  kinds should update their queries.

## Consequences

- A Gemini API change (endpoint, payload shape, thinking-budget rules)
  is now a one-file edit.
- An outage first seen by copilot/chat/deep-research trips the breaker
  captions consult, and vice versa; `/healthz/breaker` reads the shared
  snapshot from the transport.
- Historical monkeypatch seams preserved: tests patch
  `media_ai.llm._resolve_gemini_key` / `ai_core.llm._key_for` (wrappers
  resolve keys themselves and pass them to the transport) and the global
  `requests.post` (the transport calls it as a module attribute).
- Breaker-focused tests now target `gemini_transport` directly — the
  canonical home moved, and the old `media_ai` aliases were removed
  rather than kept as shims (CLAUDE.md dead-code rule).
