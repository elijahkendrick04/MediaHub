# `data_hub/connectors/` — keep a table fresh from somewhere else (roadmap 1.13)

A **connector** is a little pipe that fills a table from another source and keeps
it up to date — for example a CSV published at a web link, or (later) the
official Swim England times service. Whatever it brings in is stamped with
**where it came from and when**, so you can always trust-check it.

The rule for outside services is strict: they are **optional** and sit behind a
clean "plug". If a connector isn't set up yet, it says so honestly — it never
makes up data to fill the gap.

## What's in here

| File | What it does (in plain words) |
|------|-------------------------------|
| `base.py` | The shape every connector follows: how it fetches, and the "where from / when / how sure" trust note it must attach. |
| `builtin.py` | The connectors we ship: **CSV-from-a-link** (our own code, works today) and the **Swim England official times** plug (registered but switched off until access is granted). |
| `registry.py` | The list of connectors, plus running one, saving its rows into a club table, and a hook so it can refresh on a schedule. |
| `README.md` | This file. |

## The rules this folder follows

- **Trust on every sync.** Each pulled value records its source, the time, and a
  confidence — and shows as "Synced" in the grid.
- **Outside services are optional and honest.** A connector that isn't configured
  raises a clear "not set up" error; it never invents data.
- **Synced tables are read-only.** A refresh would overwrite hand-edits, so synced
  rows can't be edited by hand (make a copy if you need to).
- **Per club.** A connector fills one club's table; another club never sees it.
