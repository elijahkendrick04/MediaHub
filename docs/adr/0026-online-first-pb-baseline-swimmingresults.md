# 26. Online-first PB baseline from swimmingresults.org

- **Status:** Accepted (maintainer directive, 2026-06-20).
- **Date:** 2026-06-20
- **Supersedes:** [ADR-0025](0025-accumulating-pb-history-baseline.md) (accumulating
  per-club PB-history store).
- **Deciders:** MediaHub maintainer. Directives, in order: *"Ultimately, I want a
  95+% accurate model that finds the swimmers pbs online (typically from
  swimmingresults.org) … even if there isnt a time on the system, it should still
  find the swimmers pbs online first"*; *"the lookup … should match the swimmers
  club too"*; *"I dont want [the accumulating history store] anywhere. I solely
  want it to look up their pbs each time"*; *"Dont build in a paid version api"*.

## Context

ADR-0025 made the club's **own accumulating results history** the primary PB
baseline. The maintainer rejected it after identifying a correctness flaw the
store cannot fix:

> The store only knows the meets uploaded to MediaHub. If a swimmer sets a PB at
> a meet the club never uploads, the store never sees it; a later, *slower* swim
> then looks faster than anything on record and is mis-flagged as a PB.

**A baseline built from partial data manufactures false PBs** — the worst failure
mode (worse than a miss). The only baseline that avoids it is the swimmer's
*complete* competitive record. For British Swimming that record is public on
**swimmingresults.org**.

A probe (run from the production Render egress IP) established the full chain is
reachable with plain HTTPS + a browser User-Agent — **no paid API, no proxy, no
rate-limit ceiling**:

- `personal_best.php?mode=A&tiref=<id>` → a swimmer's official best per event
  (parsed by a clean port of the proven `legacy/swim_content_pb` parser:
  27 events for a real swimmer, validated against current live HTML);
- `eventrankings.php?…&Level=O&AgeGroup=NN&TargetClub=<code>` → a club's ranked
  swimmers as `{member id: name}` (club is a first-class filter);
- the `TargetClub` register (~1,266 clubs) → club name → club code.

## Decision

Make **swimmingresults.org the primary PB baseline, looked up fresh every run**
(`src/mediahub/swimmingresults/`). Per swimmer:

1. **Resolve the member id (tiref):** directly from the file's ASA number when
   present (HY3/SDIF), else from the club's online rankings roster.
2. **Match by name + club + age:** the roster is already filtered to one club and
   one age group; a close name within it is accepted as the same person — the
   maintainer's explicit rule (*"same club + same age ⇒ same person"*), which lets
   "Charlie" match "Charles". A non-unique or distant match is **refused**.
3. **Fetch + parse** the swimmer's personal-best page → `BridgedSnapshot` (the
   unchanged shape the deterministic detectors already consume).

The accumulating `pb_history` store, its pipeline load/record steps, its tests,
and its erasure hook are **removed**. The generic web-search discovery is
**demoted to a secondary gap-filler** for swimmers swimmingresults.org doesn't
list (non-GB / unranked); it never overrides the authoritative baseline.

The whole path is **deterministic** (resolve → fetch → parse → compare; no LLM),
so it runs whenever PB enrichment is permitted, regardless of LLM provider config.

## Consequences

- **Accuracy:** PBs are asserted against the swimmer's complete official record,
  eliminating the false-PB class the partial store could produce. Target: 95%+
  for British-Swimming-registered clubs — to be *measured* against a real meet,
  not assumed.
- **Honesty / misses:** a swimmer we can't confidently resolve (non-GB, unranked,
  name too different) gets **no baseline** — an honest miss, never a guess.
- **Privacy:** no new persistent athlete-PB store; the lookup caches are
  in-process only. This is still data collection *not* from the data subject
  (UK GDPR Art 14), so it stays behind the existing per-tenant PB-enrichment
  consent toggle. The `pb_history.db` erasure hook is removed (nothing persistent
  to erase); the `pb_discovery` cache erasure paths remain.
- **Cost / scale:** free, first-party HTTPS; the member id (tiref) is stable so
  resolution caches well. A bounded per-run fetch ceiling
  (`MEDIAHUB_SR_MAX_FETCHES`) guards a huge meet with no age data.
- **Scope:** swimmingresults.org is British Swimming; non-GB clubs get no online
  baseline from it (they fall to the secondary gap-filler or an honest miss). The
  maintainer accepted GB-first.
