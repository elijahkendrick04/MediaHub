# workflow

Keeps track of each card's status — waiting, approved or rejected — and the
review queue, so nothing gets posted before someone (or something accountable)
says yes.

- `status.py` / `store.py` — the card lifecycle (QUEUE → APPROVED → POSTED)
  and where it's saved.
- `approval.py` — *who* approves (P2.2): normally the human on the review
  page; for a post type a club has explicitly set to fully autonomous, the
  publish gate can approve and post a card by itself — but only when every
  safety check passes, and it's all written to the audit ledger.
- `autonomy.py` — that audit ledger: an append-only, per-club record of every
  autonomous decision.
- `schedule.py` — the exactly-once task scheduler the background jobs ride.
- `pack.py` — bundles the approved cards into the final content pack.
