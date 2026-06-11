# publishing

Sends an approved post to an outside service (like Buffer) to be scheduled.
By default a human must connect an account and click Schedule.

Since Phase 2, a club can also opt one post type at a time into **autonomous
publishing** (Settings → Autonomy). That path goes through `publish_gate.py` —
one checkpoint that only says yes when *everything* passes: the global kill
switch is off, the type was explicitly opted in (`per_type_policy.py` /
`type_gate.py`), the card's facts are verified safe, its confidence clears the
type's bar, the caption contains nothing banned, it doesn't concern a minor,
and the club isn't posting too often (`posting_log.py` keeps the tally).
Anything less goes back to the human queue, and every decision is written to
the club's audit ledger.
