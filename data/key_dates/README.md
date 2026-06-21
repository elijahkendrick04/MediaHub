# Key-date packs

Shipped, read-only, **provenance-stamped** annual hooks the Plan calendar
preloads per sport (roadmap **1.14**). They are the always-on calendar markers a
club can build content around — UN/governing-body world days and sport
observances — **not** a club's own fixtures.

- A club's precise fixtures, meet dates and deadlines are entered by the
  operator on the **Plan** page (`content_engine.inputs`) and merged onto the
  calendar alongside these packs. The packs never invent a club's fixtures.
- One file per sport: `<sport>.yaml` (e.g. `swimming.yaml`, `football.yaml`),
  matching the `sport` slug used by `data/sport_profiles/`.
- This is config, not runtime state — it resolves relative to the repo `data/`
  dir, not `DATA_DIR` (env override `MEDIAHUB_KEY_DATES_DIR` for tests/ops).

## Schema

Each entry resolves to an **exact** calendar date deterministically — nothing is
approximated onto the calendar:

```yaml
key_dates:
  - name: World Water Day        # display name
    kind: awareness              # awareness | observance | sport | governance | season
    rule: { type: fixed, month: 3, day: 22 }
    note: "One-line why-it-matters for a club."
    source: "Provenance — where the date/observance comes from."
```

`rule.type`:

- `fixed` — `month` + `day` (e.g. a UN world day on a fixed calendar date).
- `nth_weekday` — `month` + `weekday` (0=Mon … 6=Sun) + `n` (1 = first, `-1` =
  last). Computed in code, so an event like "the fourth Wednesday of September"
  resolves to the right date every year.

Only dates that can be stated **with confidence** ship here. An event whose real
date genuinely moves year to year and can't be expressed as a rule is left to
operator entry rather than guessed onto the calendar (honesty over volume).
Loaded by `mediahub.content_engine.key_dates.load_key_date_pack(sport)`.
