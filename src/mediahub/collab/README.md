# collab

The collaboration & review layer (roadmap 1.18). It sits on top of the
`workflow` spine and the `tenancy` membership ledger and lets a club's people
work together on content the way a committee actually does: one volunteer
drafts, a coach checks the names, the chair approves.

- `permissions.py` — who-can-do-what. A small, pure table mapping each
  workspace seat (Owner, Member, Editor, Approver, Reviewer, Viewer) to the
  five things you can do here: **view**, **comment**, **edit**, **approve**,
  **manage**. No files, no database — just the rules, so every check in the
  app asks the same question and gets the same answer. The legacy "Member"
  seat keeps its old powers (edit + approve) so nothing changes for clubs that
  were here before 1.18.

More pieces land here as 1.18 is built out (comments & tasks, version history,
element locks, share links, collections). Each is a thin, testable module — no
AI in the engine sense, just careful bookkeeping around the human review.
