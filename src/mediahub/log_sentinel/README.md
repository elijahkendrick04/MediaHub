# log_sentinel

The app's own night guard. It reads MediaHub's production logs on Render every
minute, spots known problems (crashed search backend, stuck workers, out of
memory, full disk, failing requests), and sends the operator a push message
saying what happened and what to do. For a small, explicitly approved list of
problems it can also apply the fix itself (restart the service) — but only when
you turn that on, never more than a few times a day, and it writes everything it
sees and does into an audit log. Full guide: `docs/LOG_SENTINEL.md`.
