# backup — daily archives + the rehearsed way back (PC.14)

In plain words: this folder makes sure a disk failure can't kill the
business. Once a day it zips up the things a recovery actually needs — the
databases (copied safely while the app runs), every account/membership/legal
ledger, club profiles and logos, the sell-side ledgers, and each run's
parsed results + approval states — into `mediahub-backup-<time>.zip`, keeps
the newest few, and can push each archive off-site over plain HTTP. Renders
and caches are left out on purpose: they can be rebuilt from the runs.

The other half is getting back: `python -m mediahub.backup restore <zip>`
rebuilds a data directory from an archive, and the test suite rehearses that
restore on every run — so the backup is proven to work, not assumed.
Nothing here runs until the operator sets `MEDIAHUB_BACKUP_DIR` (or an
upload URL); unconfigured means honestly off. Human steps live in
`docs/SUPPORT_INCIDENT_RUNBOOK.md`.
