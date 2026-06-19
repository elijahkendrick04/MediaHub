# pb_discovery

Finds a swimmer's *historical* personal-best times on the web (to confirm an
all-time PB) and remembers them with a "trust" score so we know how sure we are.

This is the **enrichment** layer, not the only way PBs are found. Most PBs are
detected offline, straight from the results file: when a swim is faster than the
swimmer's own entry/seed time in that file, the engine flags a PB with no web
lookup at all (see `interpreter/` → `seed_time` and the `pb_likely` detector).
That offline path is what keeps the PB count honest and fast even when the web
is throttled or no search backend is configured.

When web lookups do run, the candidate pages for one swimmer are fetched
concurrently and the search short-circuits as soon as a trusted, high-confidence
source is found (`MEDIAHUB_PB_FETCH_WORKERS`).

Plain-English words ("PB", "trust ledger"): see ../../../GLOSSARY.md
