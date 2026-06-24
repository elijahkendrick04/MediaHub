# scripts

Small helper programs the team runs by hand — build steps, reports and checks.
These are tools *around* MediaHub, not part of the running app itself.

## Operator tasks

- **`purge_all_runs.py`** — permanently delete **every** run, for **every**
  organisation (the deployment-level "wipe all previous runs" reset). Uses the
  same deletion cascade as the in-app per-run Delete, then clears the re-derivable
  caches; club profiles and the media library are left alone. Point `DATA_DIR`
  at the deployment's data volume and run with the web service stopped:

  ```bash
  python scripts/purge_all_runs.py --dry-run   # show what would go
  python scripts/purge_all_runs.py             # prompts to confirm
  ```

  Day-to-day, people clear their own history from the app instead — the per-run
  **Delete** and the **Clear all runs** button on *My Season* and *Activity*.
