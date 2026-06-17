# Autonomy Model — withdrawn

> **In plain words.** MediaHub used to be able to publish some post types onto a
> social channel on its own (the "fully autonomous" opt-in, behind a publish
> gate). **That capability has been removed.** MediaHub no longer places content
> on a social account at all — every card is reviewed by a human and then
> exported or downloaded for manual posting.

## What was removed

The auto-publish-to-social path is gone, code and all:

- the publishing layer (`src/mediahub/publishing/` — the Buffer scheduler client,
  the publish gate, the per-type policy, the publish kill switch, the posting log);
- the autonomous approval signal (`src/mediahub/workflow/approval.py`) and its
  hourly `approval_signal` scheduler task;
- the user-facing "Schedule…" tool on cards and the Settings → **Auto scheduling**
  and **Autonomy** pages (now a "Coming soon" placeholder);
- the per-card `ScheduleStatus` workflow plumbing and the per-org scheduler token.

## What still stands

- **Human review is unchanged.** Cards move `QUEUE → APPROVED → POSTED` on the
  review page; approved cards are exported/downloaded for manual posting.
- **The "prepare a pack for review" runner** (`src/mediahub/autonomy/`) stays — it
  drafts and queues for review and **never publishes**.
- **The in-process job runner** (`src/mediahub/scheduler/`,
  `src/mediahub/workflow/schedule.py`) stays — it drives retention purges,
  backups, demo sweeps, live-meet polling and monthly season-wrap drafts. None of
  those post to social.

Reintroducing any machine path that schedules or publishes content onto an
external social account requires explicit user sign-off. If rebuilt, *human
approval before external publishing is the default, always.*
