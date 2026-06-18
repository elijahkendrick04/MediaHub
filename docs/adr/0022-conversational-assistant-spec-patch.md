# ADR 0022 — Conversational creative assistant via validated spec-patches (P6.2)

- **Status:** accepted (2026-06-18). Implements roadmap item **P6.2**, the
  second Phase-2 (creative-suite) work package. Builds directly on P6.1's
  format catalogue ([ADR-0021](0021-format-catalogue-transformer.md)) and the
  shipped Tier-B design-spec director. Coverage map:
  [`CREATIVE_SUITE_PARITY.md`](../CREATIVE_SUITE_PARITY.md) §P6.2.
- **Context:** Canva AI / Adobe AI Assistant offer conversational, iterative,
  voice-driven editing of a design. MediaHub needs the same *feel* without
  surrendering its two non-negotiables: the deterministic engine stays
  deterministic, and a human approves before anything is published. The shipped
  pieces are already most of the way there — `ai_core.ask_with_tools` (a bounded
  tool loop), the editable `CreativeBrief`/`DesignSpec`, the APCA compliance
  gate, the caption engine, the planner, and the `free_text_chat` brief-builder.

## Decision

**A conversational copilot that edits by emitting validated, structured
patches to the persisted `CreativeBrief` — it never paints pixels and never
publishes.** New `assistant/` package; the renderer, engine and caption engine
are reused, not modified.

1. **`assistant/patch.py` — the deterministic heart.** A `SpecPatch` is a
   bounded list of ops from a **closed vocabulary** (`set_headline`,
   `set_hook`, `set_mood`, `set_archetype`, `set_format`, `set_colour_role`,
   `set_motion_intent`, `set_accent_treatment`, `set_tone`, `clear_photo`).
   `parse_patch` drops anything out-of-vocabulary (never guesses); `apply_patch`
   applies the valid ops to a **copy** of the brief and returns the new brief
   plus an explicit applied/rejected audit trail. A colour-role change is
   re-checked through the *same* APCA legibility gate the renderer uses
   (`quality.compliance.check_roles` over `resolved_role_vars_for_brief`) and
   reverted if it would be illegible — never blindly painted. No LLM here; fully
   unit-testable.

2. **`assistant/tools.py` — a bounded allow-list.** The agent gets read-only
   tools (`read_design`, `read_brand`, `read_facts`, `list_formats`) plus one
   action (`propose_edit`). There is **no** publish/post/schedule/fetch tool —
   the human-approval-before-publish rule is enforced by simply never granting
   the capability. Anthropic-shape schemas, so `ask_with_tools` normalises them
   for Gemini/OpenAI-compatible providers too.

3. **`assistant/copilot.py` — the orchestrator.** Runs one turn over
   `ask_with_tools`, applying each proposed patch to a working brief and feeding
   the real applied/rejected result back so the model reacts to what landed.
   Honest about failure: **no provider → an honest message, design unchanged**,
   and every deterministic/manual control keeps working (the honest-error rule).

4. **`assistant/session.py` + `memory.py`.** Each (run, card) has a conversation
   + **edit log** (auditable; each turn is a new brief version, so edits are
   reversible). Org **assistant memory** is a preference book — explicit
   "remember this" writes, an org-visible/deletable list, deterministic keyword
   recall (no embedding provider needed, so it works on a no-AI deployment). It
   is the *preference* sibling to the semantic caption memory in `memory/`
   (which stays caption-specific), injected into the system prompt each turn.

5. **Magic-Write caption text-tools** are added to the shipped
   `web/caption_assist.py` (Summarise / Expand / Rewrite alongside the existing
   Shorter / Punchier / Tidy), all through the same "revise, keep every fact"
   channel. A tone shift is the existing `tone` argument, not a new op.

6. **Voice** rides the browser's on-device speech recognition (free, nothing
   leaves the device) feeding the chat box; a server ASR seam (`assistant/asr.py`)
   exists for uploaded audio and honestly errors until a provider lands (the
   P5.3 seam).

7. **Web surface** mirrors the existing per-card routes: `POST
   …/card/<card>/assistant` (a turn, persists the edited brief so the existing
   render/reformat surfaces pick it up), `…/assistant/suggestions` (planner-seeded
   chips), `/api/assistant/memory` (+ delete), `/api/assistant/transcribe`. A
   **Copilot…** panel joins the per-card toolbar. All tenant-gated; JSON POSTs
   are CSRF-exempt by content-type.

## Consequences

- The intelligence-layer moat deepens: the design-spec director pattern extends
  from generate-time (P6.1) to **edit-time**, and the patch validator means a
  hallucinated or illegible edit can never reach the renderer.
- Deterministic-engine boundary holds: the catalogue, renderer and compliance
  maths stay deterministic; the only judgement (which edit to propose) goes
  through the AI with a closed, validated vocabulary and a hard no-publish line.
- The edited brief persists as a new version, so the existing reformat/render
  and the reel/motion paths automatically reflect copilot edits.
- **Deferred to owning packages:** generative image edits → P6.3/P6.4; other
  languages → P6.23; review-thread @assistant → P6.17; an MCP server exposing
  the copilot to external agents → P6.20.

## Alternatives considered

- **Let the model edit the brief JSON directly.** Rejected: it would let a
  hallucinated value or an illegible colour reach the renderer. The closed-op
  patch + APCA re-check is the safety contract.
- **Free-text "describe the whole card again".** That is the shipped
  `free_text_chat` create path; P6.2 is specifically *iterative edit of an
  existing approved design*, which needs the patch/diff model, not regeneration.
- **Store preferences as embeddings in `memory/`.** Rejected for v1: it would
  make the preference book honest-error without an embedding provider, breaking
  "manual controls keep working". Deterministic keyword recall is enough for
  short policy lines; an embedding upgrade can ride the same API later.
