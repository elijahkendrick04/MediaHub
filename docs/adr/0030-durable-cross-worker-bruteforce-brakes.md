# ADR-0030 — Durable, cross-worker brute-force brakes (SEC-27)

**Status:** Accepted (2026-07-13)
**Area:** Security / authentication (ASVS L2 V2.2 credentialed recovery &
brute-force resistance)
**Supersedes:** the per-worker in-memory brake state described in
`web/auth.py` and `web/web.py` (unchanged design intent, new storage).

---

## Context — the problem (deep-review finding #27)

MediaHub runs under gunicorn with **two workers** and worker recycling:

```
Procfile: gunicorn ... --workers 2 --worker-class gthread --threads 4
          --max-requests 200 --max-requests-jitter 50
```

Three brute-force brakes were each a **per-worker, in-process dict**:

| Brake | Where | State |
|-------|-------|-------|
| Account lockout (5 failures / 15 min, per email) | `web/auth.py` `_failed_logins` | per-worker dict |
| Per-IP auth limiter (10 attempts / 10 min, per bucket+IP) | `web/web.py` `_auth_attempts` | per-worker dict |
| TOTP replay guard (reject a re-used counter) | `web/auth.py` `_totp_last_counter` | per-worker dict |

Because each worker holds its **own** copy:

1. **~2× the intended budget.** gunicorn spreads requests across both workers,
   so an attacker gets up to two independent counters — e.g. 10 account
   failures before lockout instead of 5.
2. **`--max-requests` wipes the counters mid-attack.** Each worker is recycled
   roughly every 150–250 requests (200 ± 50 jitter); the fresh process starts
   with empty dicts, so a sustained attacker's counters reset continuously.
   In practice this makes the per-IP volume brake *barely functional* against a
   determined sprayer — every recycle hands back the full budget.
3. **The `/login/2fa` POST had no per-IP brake at all** — its password-step
   sibling (`/login`) did. Automated TOTP-code guessing was bounded only by the
   per-account lockout (itself process-local per #1/#2).

None of this is a data-loss bug, but it materially weakens online-guessing
resistance for a hosted, internet-facing auth surface.

## Decision

Move all three brakes into the **shared SQLite database** already used for the
runs index (`DATA_DIR/data.db`, opened via the existing `_db()` convention and
snapshotted across deploys by `publish_website`). A new self-contained module
`web/auth_brakes.py` owns the mechanics; `auth.py` and `web.py` keep their
existing public functions and simply delegate.

**SQLite, not Redis.** This is a hosted-only, single-container app (CLAUDE.md:
"Cloud-hosted SaaS, no self-host tier"; Render reference target). `data.db` is
already the shared, deploy-durable store and already tuned for two-worker
contention (`timeout=5s` + `PRAGMA busy_timeout=5000`). Adding Redis would
introduce a new piece of infrastructure, a new failure mode, and a new
operational surface for **three low-volume counters**. Login/2FA/reset traffic
is a rounding error next to the run-status writes `data.db` already absorbs, so
there is no contention argument for Redis. SQLite-only was the maintainer's
explicit preference for this finding, and nothing here needs more.

### Storage model

Two tables, created lazily (`CREATE TABLE IF NOT EXISTS`) on first use so the
module is self-bootstrapping and never depends on `web.py`'s `_init_db()`:

```sql
-- Sliding-window event log: one row per attempt/failure.
CREATE TABLE IF NOT EXISTS auth_events (
    scope TEXT NOT NULL,   -- 'fail' (account lockout) | 'ip:<bucket>' (per-IP)
    ident TEXT NOT NULL,   -- normalised email  |  client IP
    ts    REAL NOT NULL    -- unix seconds
);
CREATE INDEX IF NOT EXISTS ix_auth_events ON auth_events(scope, ident, ts);

-- TOTP replay guard: the last accepted 30-second counter per secret.
CREATE TABLE IF NOT EXISTS totp_replay (
    secret_hash TEXT PRIMARY KEY,  -- sha256(secret); the secret is NEVER stored
    last_counter INTEGER NOT NULL,
    updated_at   REAL NOT NULL
);
```

**Why one row per event (a log), not an aggregate counter.** It is an exact
translation of the in-memory `list[timestamp]` sliding window — a count is
`COUNT(*)` of rows inside the window — and it is inherently **race-free**: each
`INSERT` commits independently, so there is no read-modify-write to lose an
update when both workers record a failure at once. A single aggregate row would
need `BEGIN IMMEDIATE` on every hit and would only approximate the window
(fixed-window bursts). The log is simpler *and* more correct.

**Why hash the TOTP secret.** `data.db` is snapshotted by `publish_website`; the
raw secret must not travel into a snapshot. The replay guard only needs a stable
per-secret key, so `sha256(secret)` is sufficient and leaks nothing. (The
plaintext secret already lives only in `users.jsonl`, mode-0600.)

### Concurrency & atomicity

- **Event log (lockout + per-IP):** plain autocommitted `INSERT` / `COUNT` —
  no cross-statement invariant, so no transaction needed. SQLite's
  `busy_timeout` turns a two-worker write collision into a brief stall, exactly
  as the runs DB already relies on.
- **TOTP replay guard:** a genuine read-modify-write (accept only a counter
  strictly newer than the stored one), so it runs inside `BEGIN IMMEDIATE`.
  SQLite's single-writer lock serialises it across workers, so two concurrent
  verifies of the *same* code can never both be accepted — the second blocks on
  the write lock, then sees the advanced counter and is rejected as a replay.

### Clock handling

All timestamps are real unix seconds supplied by the caller (`now=`), so tests
inject a clock exactly like `totp_verify(at=...)`. Both workers share the one
host clock, so cross-worker comparison is sound, and wall time keeps advancing
across a restart — which is precisely what makes the brakes recycle-durable. A
backward NTP step is the only pathological case; TOTP is inherently
wall-clock-bound already, and the ±1-step skew absorbs small corrections.

### Cleanup of expired rows

- **Inline:** every write prunes stale rows *for that key* first, so a hot key
  never accumulates.
- **Opportunistic global GC:** at most once per 60 s per process, delete
  `auth_events` older than 1 h (comfortably past the 15-min window) and
  `totp_replay` older than 24 h. Correctness never depends on GC — the count
  queries are window-bounded regardless — so the GC cadence is best-effort and
  each worker GCs independently (idempotent `DELETE`s).

### Failure posture (availability vs. security)

The login path must never 500 on a locked/corrupt DB. Every operation is
best-effort and **fails toward the same decision an empty in-memory dict would
have made**:

- `login_locked` / per-IP limiter → on DB error return "not locked / not
  limited" (fail-open). A DB outage degrades to today's just-restarted state;
  it never bricks login. Failures are still written to the security-event log.
- TOTP replay guard → on DB error **accept** the (already cryptographically
  valid) code. The HMAC check has already passed; the guard only ever
  *downgrades* a valid code, so failing open costs at most the ~90-second replay
  window the old in-process guard also forfeited on every restart.

## The shared-NAT question (explicitly required by the finding)

> "Confirm the per-IP brake can't lock out legit users behind a shared NAT more
> aggressively than today."

The per-IP limiter counts **all** attempts (not just failures) per (bucket, IP),
so a club, school, or CGNAT that NATs many legitimate users behind one address
is the population at risk of a false lockout.

- **Today (buggy):** budget is `10 × (workers a request happens to hit)`.
  gunicorn spreads a client's requests across both workers, so the *effective*
  ceiling before a `429` is **non-deterministic between 10 and 20** — and reset
  frequently by `--max-requests`.
- **Now (durable, shared):** to *guarantee* we never regress a NAT'd user, the
  shared nominal limit is set to **20** = the previous per-worker budget × the
  two-worker deployment. So a shared NAT is locked out no sooner than today's
  most-lenient case (20) and strictly later than today's worst case (10). Legit
  NAT users are **never** worse off; they are often better off (the ceiling is
  now a stable 20 instead of "10 if you're unlucky").
- Against a **sustained attacker**, durable-20 is dramatically stronger than the
  old per-worker-10-that-resets-every-200-requests, because the counter no
  longer evaporates on recycle. So this choice tightens the brake against abuse
  while loosening (never tightening) it for legitimate NAT traffic.
- The new **`/login/2fa`** per-IP brake uses its **own bucket** (`login_2fa`),
  not the `login` bucket, so a burst of legitimate logins (password step +
  code step) from one NAT does not compound the two steps against a single
  budget. Each step independently gets the 20/10-min ceiling.

The **account lockout** (5 failures / 15 min) is keyed on the *email*, not the
IP, so one clumsy user can never lock out others on the same NAT; making it
cross-worker only removes the accidental 2× (a fumbling user is now locked at
the intended 5, never a lucky 10) and has no shared-NAT dimension.

## Consequences

- Lockout, the per-IP limiter, and the TOTP replay guard are now **consistent
  across both workers** and **survive `--max-requests` recycles and restarts**.
- `/login/2fa` gains the per-IP brake it was missing.
- No new infrastructure, no new dependency, no schema migration for existing
  data (the two tables are additive and self-creating). Existing `users.jsonl`
  records and `data.db` runs rows are untouched.
- Three per-worker dicts (`_failed_logins`, `_totp_last_counter`,
  `_auth_attempts`) and their locks are removed; the public functions that wrap
  them keep the same names and signatures, so no caller changes.

## Alternatives considered

- **Redis / Memcached** — rejected: new infra for three tiny counters on a
  hosted-only app; SQLite already provides the shared, durable store. (Would
  require maintainer sign-off per the finding; not pursued.)
- **Aggregate counter row per key** — rejected: needs a transaction per hit and
  only approximates the sliding window; the event-log is both simpler and more
  faithful.
- **Signed-cookie / stateless brake** — rejected: a client-held counter is
  trivially reset by dropping the cookie, which is the exact dodge the per-IP
  limiter exists to prevent.
- **Keep it in-process but share via a file lock / mmap** — rejected: reinvents
  a database; `data.db` is right there.
