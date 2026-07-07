# governance

The rules around the AI. Three jobs:

- **Quotas** — counts how much AI each club uses and can put a cap on it. By
  default there are no caps — usage is just counted and shown. If the operator
  sets a limit for a feature, going over it gives an honest "quota reached"
  message instead of quietly running up a cloud bill. Honest status: today the
  caption, translate and generative-imagery surfaces are wired through the
  meter; brand interpretation, palette resolution, media tagging, brand-DNA
  capture and web research are registered in `features.py` but **not yet
  metered** — a `MEDIAHUB_QUOTA_*` limit for those cannot enforce until their
  routes go through `context.feature_scope`. The raw counting lives next door in
  [`observability/feature_quota.py`](../observability/feature_quota.py); the
  rules about limits live here in `quota.py`. The signed-in developer/operator
  is fully exempt — never blocked, and their test runs are never counted against
  a club's usage (real cost is still tracked globally in `llm_usage`).

- **Permissions** — which team members are allowed to use which AI features. A
  viewer can look but not generate; an editor can draft; and so on. This builds
  on the role list in [`collab/permissions.py`](../collab/permissions.py).

- **Provenance** — a little honesty label stamped on anything the AI makes, so
  you can always answer "what made this picture, from what, and when".

We deliberately do **not** moderate or censor generated content here — a human
always reviews and approves before anything is posted.
