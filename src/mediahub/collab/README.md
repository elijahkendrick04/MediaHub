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
- `threads.py` — the conversation store: comments and replies pinned to a run,
  a card, or an element on a card; @mentions; emoji reactions; and **tasks**
  (a comment with an assignee that must be ticked off before the card can be
  approved). Plain SQLite bookkeeping next to the review comments.
- `mentions.py` — turns `@name` in a comment into the teammate(s) meant, by
  email, the bit before the @, or their name. Pure text → people; the web
  layer does the notifying.
- `revisions.py` — version history for a card's design. Every edit already
  saves a new copy on disk, so this lists those versions, shows what changed
  between two of them, and rolls back to an earlier one (keeping the ones in
  between, so a rollback is itself undoable).
- `locks.py` — pin individual elements of a card (the sponsor strip, the
  headline, the photo) so a later edit — even the AI copilot's — can't change
  them.
- `share_tokens.py` — expiring, revocable links that let someone outside the
  club (a parent confirming a name) view, or comment on, one run or card
  without an account. The link is just an unguessable token; what it opens and
  when it dies lives in a ledger so it can be listed and switched off.

More pieces may land here as 1.18 finishes (collections, team context). Each is
a thin, testable module — no AI in the engine sense, just careful bookkeeping
around the human review.
