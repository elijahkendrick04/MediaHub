# ADR-0028 — Member-confined organisation access and direct sign-in landing

Date: 2026-07-10
Status: Accepted
Relates to: ADR-0014 (org→workspace membership binding), ADR-0019 (operator sign-in)

## Context

ADR-0014 made bound organisations (≥1 active membership) members-only at the
pinning choke points, but deliberately left unbound organisations open to
every session — anonymous or signed-in — as the pilot/standalone mode. Two
consequences surfaced in the org-access audit:

1. A signed-in account could roam into any *unbound* organisation (see it on
   the `/sign-in` picker, pin it, edit it). On a shared deployment that is a
   cross-tenant exposure: real customer orgs are bound, but pilot orgs and
   freshly-captured orgs are not.
2. Every member was routed through the organisation picker after login, even
   when they belong to exactly one club — an org-selection step that both
   confused the sign-in experience and normalised the idea that orgs are
   something you browse.

Sign-out had two further gaps: `/logout` answered GET (a cross-site link
could end a session), left the org pin in the session, and — because Flask
sessions are client-side — a replayed pre-logout cookie silently restored
both the account and its organisation access.

Separately, the route-entitlement sweep this audit ran found the
`/api/visual/<vid>` and `/api/visual/<vid>/png/<format>` endpoints resolving
a visual id by scanning ALL of RUNS_DIR with no tenant check — a cross-org
IDOR on the sidecar payload (caption, alt text, athlete names) and rendered
PNG. Fixed under the same audit (the org-access audit report has since been
removed now that the findings are closed; see git history if needed).

## Decision

1. **Member confinement.** A signed-in (non-operator) account may use ONLY
   the organisations it holds an ACTIVE membership in — bound or unbound.
   Anonymous sessions keep the ADR-0014 pilot behaviour (unbound orgs open,
   bound orgs invisible). Cross-org roaming is exclusively the authenticated
   dev operator's capability (ADR-0019 sign-in). This extends the ADR-0014
   ownerless-run blast-radius rule ("refuse signed-in foreign accounts,
   preserve anonymous/legacy and operator") from run routes to the org
   pinning choke point itself (`_session_can_use_profile`).
2. **Direct landing (no picker for members).** Login, 2FA login, and signup
   auto-pin the account's own organisation (`_auto_pin_member_org`) and land
   on the app. `/sign-in` redirects a single-org member straight to the app;
   only the rare multi-org member sees a picker, filtered server-side to
   their own workspaces. The nav offers "Switch organisation" only to
   sessions that can actually switch (operator, anonymous pilot, 2+-org
   member) and "Leave organisation" only to operator/anonymous sessions.
3. **Real sign-out.** `/logout` and `/sign-out` perform their state change on
   POST only (CSRF-protected like every form); GET renders a confirmation
   page. Logout clears the whole session (the org pin never outlives the
   identity) and revokes server-side: each account carries a
   `session_epoch` (users.jsonl) that logout bumps — every outstanding
   cookie for that account dies, on every device. Operator logout writes a
   dev-session watermark file (`DATA_DIR/.dev_sessions_revoked_at`);
   operator cookies minted before it are refused. Signed-in HTML responses
   carry `Cache-Control: no-store`.

## Multi-organisation membership (P4)

The membership ledger allows one email to hold seats in several
organisations, and that stays supported. The landing rule is: keep the
already-pinned org when it is one of the member's own; otherwise pin the
alphabetically-first member org (deterministic). Multi-org members keep a
confined picker as their switcher. Single-org members — the overwhelmingly
common case — never see any org-selection step.

## Consequences

- The ADR-0014 "transitional cross-tenant exposure of unbound orgs" residual
  is now closed for signed-in accounts; it remains (by design) for anonymous
  pilot sessions until a pilot's owner is invited and signs up.
- A signed-in account with no memberships can no longer walk into an
  existing unbound org; its path is create-your-own (which binds it as
  owner, per ADR-0014) or an operator invite.
- Logout signs the account out everywhere (all devices), which is the
  intended semantic for a shared-computer world; per-device revocation would
  need a session table and was deliberately not built.
- users.jsonl gains an optional `session_epoch` int (missing → 0), so
  existing ledgers keep working unchanged; no migration required.
