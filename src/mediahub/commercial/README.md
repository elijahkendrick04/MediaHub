# commercial — the founder's sell-side ledgers (Phase C)

In plain words: this folder is the notebook MediaHub keeps while the founder
sells it to the first clubs. `wtp.py` records every real annual price quoted
to a club and what actually got paid (so the public price is set by evidence,
not guessing — the "≥5 clubs paid" rule). `pipeline.py` tracks the warm-first
sales funnel (local clubs → referrals; cold contact stays a small supplement)
and who still owes the two promised introductions. `referrals.py` (PC.9)
runs that referral promise in-product: each club gets a shareable signup
code, signups through it land in the funnel automatically, and when a
referred club's first annual payment is verified the referrer's free month
grants itself as a Stripe coupon (or records honestly as pending when the
value or billing identity can't be resolved). `ngb.py` remembers where
the Swim England data-API application stands. Everything shows up on the
operator-only `/operator/commercial` page — customers never see any of it.
