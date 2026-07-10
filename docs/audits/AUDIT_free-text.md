# Audit — Free Text (create)

**Feature:** the "Free Text" surface under _Create_ — describe a post in plain
English and get a branded draft. Two entry paths: a one-shot quick build
(`POST /free-text/quick-build`) and an iterative chat brief builder
(`/free-text/chat/...`).

**Mode:** AUDIT+FIX. **Verdict:** **WORKS** (see §9).

> **Note on a parallel audit.** While this audit ran, a sibling session audited
> the same feature and merged first (**PR #1103**, branch
> `claude/audit-free-text-bb9chy`, on `main` as of `d1efec6`). It independently
> landed fixes for most of what this audit found — cross-tenant isolation,
> hashtag normalisation, the misleading "Assistant uses Claude" strap, an
> LLM-input length cap, and basic accept-idempotency. Rather than force in
> duplicate/conflicting commits, this PR was **rebuilt on top of #1103** and now
> contributes only the two genuinely-additive fixes #1103 did **not** make
> (§5). The full findings are recorded below for the audit trail, each annotated
> with who fixed it.

---

## 1. Scope contract

- **Definition.** Turn a free-text description (optionally with photos) into a
  structured brief and then a saved draft pack that renders a branded graphic
  and flows into the normal approve/export path. "Working" = the brief faithfully
  becomes the draft, malformed model output fails honestly (never a fake post,
  never a 500), and one org can never see or mutate another org's chats.
- **Routes owned:** `GET /free-text`; `GET,POST /free-text/quick`;
  `POST /free-text/quick-build`; `GET,POST /free-text/chat/new`;
  `GET /free-text/chat/<chat_id>`;
  `POST /free-text/chat/<chat_id>/{send,accept,decline,generate}`.
- **Files owned:** `src/mediahub/free_text_chat/{agent,session,__init__}.py`;
  the Free Text routes + helpers in `src/mediahub/web/web.py`;
  `tests/test_free_text_*.py`.
- **Shared deps (not freely rewritten):** `save_pack`
  (`club_platform/stub_pack_store.py`), `_active_profile_id` / `_active_profile`,
  `_render_stub`, `_recovery_page`, `ai_core` (`ask`, `ask_with_tools`), the
  media library, the CSRF layer.
- **Inputs → outputs:** prompt text + optional photos / library picks → a brief
  (`headline/body/hashtags/platform/visual_concept/tone/wants_reel/title`) →
  a saved stub pack under `DATA_DIR` that auto-renders its graphic
  (`?autographic=1`). Chats persist as JSON under `DATA_DIR/free_text_chats/`.
- **Happy path:** quick — prompt → one LLM call → brief → draft renders on
  arrival. Chat — send → assistant asks/researches/proposes a brief → accept →
  draft renders. No provider configured → an honest error, never a fabricated
  brief.

---

## 2. Environment

- Ran locally from a stub `.env` (`DATA_DIR`/`RUNS_DIR`/`UPLOADS_DIR`/
  `SWIM_CONTENT_PROFILES_DIR` under a temp dir), no real provider keys — the
  honest-error path is exercised directly.
- App boots clean on `python -m mediahub.web.web` (port 8811); `/`, `/drafts`,
  `/settings`, `/healthz` all 200. `/free-text` 302s to sign-in when signed out
  (org gate working).
- LLM stubbed by monkeypatching `ai_core.ask` (mirrors the existing
  `test_free_text_quick.py` pattern); no network, no spend.

---

## 3. Test matrix

| # | Dimension | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Functional correctness | PASS | Quick + chat both build a faithful pack; brief fields map to the card. |
| 2 | Interactive controls | PASS | Every button/form posts to the route its label implies (enumerated the rendered HTML for both pages). |
| 3 | Input validation / edge cases | PASS (fixed) | Malformed model output (non-list hashtags, non-string headline/body) now fails honestly instead of 500/garbage; empty/whitespace prompt bounces cleanly; huge prompt capped (#1103). |
| 4 | UI state | PASS | Loading/empty/error/success states render; provider error surfaces visibly; store-failure is fail-soft. |
| 5 | Server-side errors | PASS (fixed) | The one reachable unhandled 500 (chat brief → pack with a non-string headline) is closed; no stack trace / DATA_DIR leak in surfaced errors. |
| 6 | Data integrity | PASS (fixed) | `save_session` now atomic; brief→pack mapping verified; accept builds a draft once (#1103). |
| 7 | Security | PASS | Cross-tenant read+write closed (#1103, re-verified here); CSRF auto-injected on every POST form; user/LLM text HTML-escaped via `_h`; `chat_id` validated before path use. |
| 8 | Performance | CAVEAT | O(all-chats) landing scan, O(N²) transcript resend, un-deadlined `/send` — logged as residual (§8). Input-size cost bounded by #1103's length cap. |
| 9 | Responsive / a11y | PASS | Prompt + reply fields have `<label>`s; "Add photos" is keyboard-operable (#1103); error flash `role="alert"`. (One alt-less `<img>` is shared nav chrome, out of scope.) |
| 10 | Rendered-graphic correctness | PASS | Draft auto-renders via the shared graphic pipeline; unchanged by these fixes. |
| 11 | Copy quality | PASS | British English; the misleading "Assistant uses Claude" strap corrected to provider-neutral (#1103). |

---

## 4. Findings

| ID | Sev | Title | Status |
|----|-----|-------|--------|
| F1 | P0 | Cross-tenant IDOR + listing leak across all chat routes (`can_access_session`/scoped `list_sessions` existed but were never wired into the web layer; new chats were ownerless) | Fixed by **#1103**; re-verified here |
| F2 | P2 | `_chat_brief_to_pack` 500s **and bricks the chat** when a chat brief has a non-string `headline`/`body` (frozen brief → every retry re-crashes) | **Fixed here** (§5) |
| F3 | P2 | `save_session` non-atomic → a crash/overlapping write can truncate and lose the whole chat | **Fixed here** (§5) |
| F4 | P2 | Non-list `hashtags` from the model 500'd (quick) / char-split into per-letter tags | Fixed by **#1103** (`normalise_hashtags`) |
| F5 | P2 | Accept + follow-up Generate (and double-clicks) minted duplicate drafts | Fixed by **#1103** (accept builds once) |
| F6 | P2 | Unbounded prompt / chat-message length forwarded to the provider | Fixed by **#1103** (8k-char cap) |
| F7 | P2 | A brief revised after acceptance is stranded (the post-accept `pending_brief` is never shown; Generate keeps using the stale accepted brief) | **Logged** — #1103 restructured that route; a fix here would be an entangled judgement call, so it is left as a coordination item (§8) rather than guessed at |
| F8 | P3 | Misleading "Assistant uses Claude" strap (agent is provider-agnostic / Gemini-first) | Fixed by **#1103** |
| F9 | P3 | Chat first-render didn't pass `&photo=`, so its first auto-render differed from the quick path | Superseded by #1103's route changes; first render still uses the pack's attached photo — logged, not re-fixed |
| F10 | P1→residual | O(all-chats) full-corpus read on every `/free-text` load; O(N²) transcript resend per chat turn; un-deadlined `/send` | **Logged** (§8) — each needs a deliberate schema/architecture change |

---

## 5. Fixes applied (this PR, on top of #1103)

1. **F2 — non-string brief fields no longer 500 the chat.** `_chat_brief_to_pack`
   (`web.py`) now coerces `headline`/`body`/`visual_concept`/`platform` to
   strings before the caption join. A `propose_brief` tool call uses an
   unconstrained schema, so the model can hand back a list of headline lines or a
   nested object; joining those raised a `TypeError` that 500'd Accept/Generate,
   and because the brief was already `accepted_brief`, the chat was permanently
   bricked. Files: `src/mediahub/web/web.py`.
2. **F3 — atomic `save_session`.** Writes to a same-dir `.json.tmp` then
   `os.replace`, mirroring `stub_pack_store._atomic_write`, so a crash or an
   overlapping write can't truncate the file and lose the conversation (the chat
   is the only record of the brief). Files:
   `src/mediahub/free_text_chat/session.py`.

Both compose with #1103 without conflict (verified: #1103's full free-text test
suite still passes).

---

## 6. Tests added

- `tests/test_free_text_chat_robustness.py` (new):
  - `save_session` atomicity + no leftover temp file + overwrite-doesn't-truncate.
  - Parametrised `/generate` with non-string `headline`/`body` (list, dict,
    numbers) → **302, not 500**, and a draft is actually built.
  - Bare-string hashtags normalise to one clean tag, not per-character.

(My earlier route-level isolation test was dropped as redundant with #1103's
`test_free_text_chat_tenant_isolation.py` — no duplicate coverage.)

---

## 7. Cross-cutting changes

- **None.** Product edits are confined to `_chat_brief_to_pack` (owned Free Text
  helper) and `save_session` (owned module). No shared
  hook/template/CSS/config/`requirements`/`pyproject` touched. The final diff is
  four files: this report, `session.py`, the `web.py` Free Text helper, and the
  new test.
- _An earlier revision of this branch also carried the `end-of-file-fixer` fix
  for two sibling audit reports (`AUDIT_meet-recap.md`, `AUDIT_season-wraps.md`)
  that were failing the repo's "Hygiene hooks" check on every PR based on `main`.
  Sibling sessions fixed those on `main` first (commits `5dfb118a`, `c9262832`),
  so after the final rebase those edits dropped out as no-ops — this PR now
  carries no cross-cutting changes at all._

---

## 8. Residual risks / needs coordination

- **F7 — revised-brief stranding.** After acceptance, a newly-proposed brief is
  hidden (`if s.pending_brief and not s.accepted_brief`) and Generate reuses the
  stale accepted brief. #1103 restructured the accept route; the correct fix
  (let a newer proposal supersede) is a judgement call layered on their new
  structure, so it is left as a coordination item rather than guessed at.
- **F10 — performance.** `list_sessions` reads+parses every chat JSON on each
  `/free-text` load (O(total chats), no index); the chat resends the whole
  transcript each turn (O(N²), no windowing); `/send` can fire up to 4 web
  searches + several LLM round-trips with no overall deadline (worker-timeout
  risk on a long refinement). Each needs a deliberate schema/architecture change
  (a chat index table; transcript windowing; an async/deadline budget) — out of
  scope for a tight feature fix, but worth scheduling before free-text usage
  scales.

---

## 9. Verdict

**WORKS.** The P0 cross-tenant leak is closed (by #1103, re-verified here) and
the last reachable unhandled 500 in the chat→draft path is closed by this PR,
along with the data-loss window in `save_session`. Remaining items are
scale/architecture (F10) and one entangled UX refinement (F7), both logged.

---

## 10. Handover and merge status

- **Branch:** `claude/audit-free-text-buoqrt` (harness-designated). Rebuilt on
  `origin/main` @ `d1efec6` after the parallel #1103 free-text audit merged
  first — carries only the two additive fixes (§5) plus their tests, so it
  applies with **no conflict** on top of #1103.
- **Merge:** the operator authorised "merge on green"; landed on `main` via
  **PR #1104** once the green gate passed on the integrated result.
- **Green gate:** feature + broad regression subset green locally (incl. #1103's
  own free-text tests); app boots and unrelated routes load; hygiene/ruff green;
  no `.env`/secret staged. Final merge SHA recorded on the PR.
- **Review the diff:** `git diff origin/main...claude/audit-free-text-buoqrt`.
