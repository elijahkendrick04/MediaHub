# privacy/ — data-subject rights engine

The code behind the buttons in the Privacy Notice: erasure that genuinely
cascades, and account export.

- **`erasure.py`** — the cascades.
  - *Run cascade* (used by run deletion in `web.py`): per-run PB cache,
    caption-memory rows for the run, motion cache entries for the run.
  - *Athlete cascade* (`erase_athlete`): removes one named athlete from an
    organisation's runs (cards, swims, recognition entries, rendered assets),
    the PB warm + per-run caches, the research cache and the caption memory
    — and redacts remaining mentions inside multi-athlete content.
  - *Account cascade* (`erase_account`): users ledger row, legal-acceptance
    rows, workspace memberships, session-independent.
- **`export.py`** — `account_export()`: the Art. 15/20 JSON bundle for one
  account (profile of stored fields, acceptances, memberships). Run-level
  data export already exists at `/api/runs/<id>/export`.
- **`org_lifecycle.py`** (PC.13) — the whole-workspace versions of both:
  `delete_org()` cascades an organisation out of every store under
  `DATA_DIR` (runs through the run cascade, media, logos, consent +
  athletes registries, records, corrections, approval telemetry,
  caption memory, sponsor + audit ledgers, memberships, the profile — which
  kills the public-wall link), keeping the Stripe customer and acceptance
  evidence per the DPA and saying so; `org_export_zip()` is the one-ZIP
  takeout (profile, runs + approval states, media, consent CSV, athletes,
  ledgers, audit log) that serves SARs and portability. Routes:
  `/organisation/export` and `/organisation/delete` (owner/operator).

Everything here is deliberately conservative: erasure prefers removing too
much of a matched athlete's content (a whole card) over leaving fragments
behind, and every function returns counts so the UI can show what happened.
