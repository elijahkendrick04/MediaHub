# PB Verification

Why this is hard: a meet result file contains the swimmer's time today, but it
doesn't tell you whether that time is a personal best. To know that we must
look up the swimmer's prior best from an authoritative source.

## Sources

| Source | Trust | Where |
| --- | --- | --- |
| Swimming Results (swimmingresults.org) | High — official Swim England rankings | `pb_discovery.fetch_profile` |
| Same-meet earlier sessions | High — first-party | computed in pipeline |
| User-supplied historical CSVs | Medium — depends on import quality | `legacy/sample_data_v4/` |

## Flow

1. `pb_discovery.discover_swimmer_pbs(swimmer)`:
   - Builds an identity key from swimmer name + DOB (`identity.MeetIdentity`).
   - Looks up `data/discovered/swimmers/<key>.json`.
   - If cache is missing or older than `STALE_AFTER_DAYS` (default 7):
     - `fetch_profile.fetch_profile_page(swimmer)` pulls the public profile.
     - `parse_pbs.parse_pbs_from_page(html)` returns rows of `(event, course, time, date)`.
     - Result is cached.
2. `pb_bridge.build_pb_snapshots(meet)` returns one `PBSnapshot` per swimmer
   in this meet's results.
3. The detector (`recognition_swim.achievements.official_pb`) compares each
   row against the snapshot and emits an `Achievement` with `pb_status`:

   | Status | Condition |
   | --- | --- |
   | `NEW_PB` | Today's time < cached PB by ≥ epsilon, AND profile fetched within `STALE_AFTER_DAYS` |
   | `LIKELY_PB` | Today's time < cached PB but cache is stale, OR profile fetch failed but no contradicting evidence exists |
   | `NOT_PB` | Today's time ≥ cached PB |
   | `UNKNOWN` | No identity match found and no cache entry |

## Confidence-aware language

The caption layer uses `pb_status` to choose phrasing:

- `NEW_PB` → "🎉 NEW PB!"
- `LIKELY_PB` → "Likely PB — pending verification"
- `NOT_PB` → no PB callout (other angles take over)
- `UNKNOWN` → "Strong swim — couldn't verify history"

This is enforced in `mediahub.web.humanise.humanise` and in the achievement
prose the AI prompt is built from (`mediahub.ai_core.narrate.narrate_achievement`,
whose `_PB_PHRASES` mapping distinguishes confirmed / likely / unverified PBs).

## Trust ledger

Every fetch attempt against a domain is recorded by
`context_engine.trust.record_attempt(domain, success)` and stored in
`data/discovered/search_cache/`. A domain that fails repeatedly is
deprioritised by `context_engine.trust.score_domain`.

## Cache layout

```
data/discovered/
  swimmers/<key>.json     # parsed PBs per swimmer
  meets/<key>.json        # per-meet identity + venue
  pbs/<key>.json          # consolidated PB ledger
  clubs/<key>.json        # club profile (logo, colours, meet history)
  search_cache/<hash>.json   # raw HTML responses + trust attempts
```

All files in `data/discovered/` are runtime artefacts — they are gitignored
and a fresh deploy will rebuild them on demand.

## Known limitations

- Only swimmingresults.org is supported; the V8.3 roadmap adds USA
  Swimming and SwimCloud.
- Identity matching by name + DOB is brittle for swimmers with very common
  names; a manual match override UI is in `KNOWN_ISSUES.md`.
- PB confidence does not account for short-course vs. long-course conversion
  beyond exact-course matching.
