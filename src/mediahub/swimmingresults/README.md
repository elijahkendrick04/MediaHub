# swimmingresults — official online PB baseline

This package answers **"is this swim a personal best?"** by looking up the
swimmer's *real, complete* best times on
[swimmingresults.org](https://www.swimmingresults.org) (British Swimming's
public rankings) — fresh on every run.

## Why look it up online every time?

The alternative — remembering best times from the meets you've uploaded to
MediaHub — is an **incomplete** record. If a swimmer sets a PB at a meet you
never upload, MediaHub can't see it, and a later *slower* swim would look like a
PB. A baseline built from partial data manufactures **false** PBs, which is
worse than missing one. swimmingresults.org has the swimmer's complete
licensed-meet history, so it's the only baseline that can't make that mistake.

## How a swimmer is found (the chain)

1. **Member id (tiref) — fast path.** If the results file already carries the
   swimmer's ASA number (common in HY3/SDIF), we use it directly.
2. **Name + club + age — roster path.** Otherwise we look the swimmer up in
   their club's online rankings:
   - club name → club code (`clubs.py`, the site's 1,266-club register, cached);
   - club + sex + age + event → a roster slice of `{member id: name}`
     (`roster.py`, the event-rankings page);
   - match the meet swimmer to a roster name (`names.py`) — **same club + same
     age + a close name = the same person** (the maintainer's rule; this is what
     lets "Charlie" match "Charles"). A non-unique or distant match is refused.
3. **Personal bests.** Fetch and parse the swimmer's
   `personal_best.php` page (`parse.py`, a clean port of the proven legacy
   parser) into best time per event + the date it was set.

The result is a `BridgedSnapshot` per swimmer — the exact shape the existing
deterministic PB detectors already consume — so nothing downstream changes.

## Safety properties

- **Misses, never wrong PBs.** A swimmer we can't confidently resolve gets *no*
  baseline rather than a guessed one.
- **GB-scoped, honestly.** swimmingresults.org covers British Swimming clubs; a
  club it doesn't list simply gets no online baseline (no error).
- **Deterministic.** No LLM anywhere in this path — fetch, parse, match, compare.
- **Free + first-party.** Plain HTTPS with a browser User-Agent, verified
  reachable from the production server. No paid API, no proxy, no rate ceiling.

## Files

| File | Responsibility |
|------|----------------|
| `transport.py` | One browser-UA HTTP GET; raises `SRFetchError` on any failure. |
| `clubs.py` | Club name → club code (cached register, fuzzy match). |
| `roster.py` | Event-number map + one roster slice (club/sex/age/event → ids). |
| `names.py` | Name folding + nickname/spelling-tolerant matching. |
| `parse.py` | Personal-best page → best time per event. |
| `lookup.py` | Orchestration → `{swimmer_key: BridgedSnapshot}`. |

## Tuning (env)

- `MEDIAHUB_SR_TIMEOUT` — per-request timeout seconds (default 25).
- `MEDIAHUB_SR_MAX_FETCHES` — ceiling on roster-resolution fetches per run
  (default 600); guards a huge meet with no age data. Cached slices are free.
