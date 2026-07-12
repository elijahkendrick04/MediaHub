# scripts

Small helper programs the team runs by hand — build steps, reports and checks.
These are tools *around* MediaHub, not part of the running app itself.

## Operator tasks

- **`wipe_all_runs.py`** — permanently delete **every** run, for **every**
  organisation (the deployment-level "wipe all previous runs" reset). Reuses the
  app's own per-run erasure cascade, then clears run rows, uploads, semantic
  caption memory, and the re-derivable caches; club profiles and the media
  library are left alone. **Dry-run by default** and it refuses a mis-pointed /
  unwritable `DATA_DIR`, so point `DATA_DIR` at the deployment's data volume and
  run with the web service stopped:

  ```bash
  DATA_DIR=/var/data python scripts/wipe_all_runs.py         # dry run — shows what would go
  DATA_DIR=/var/data python scripts/wipe_all_runs.py --yes   # actually delete
  ```

  Day-to-day, people clear their own history from the app instead — the per-run
  **Delete** and the **Clear all runs** button on *My Season* and *Activity*.
