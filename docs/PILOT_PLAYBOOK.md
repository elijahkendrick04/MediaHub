# MediaHub Pilot Playbook

> **Audience:** the operator (you) standing up the first real pilot of
> MediaHub against one volunteer club. This is the runbook for the
> month-long Phase 1.5 pilot — *not* general user documentation.

The Phase 1 product is complete. The remaining unknown is whether the
operator-managed, single-org-per-deployment model holds up under real
volunteer-club usage. This playbook is the answer to "how do I run the
first pilot without breaking the club's faith in the product".

---

## Pre-flight (T-7 days)

Before the pilot club touches anything, the operator must:

1. **Confirm Phase 1 is green.**
   ```bash
   python -m pytest tests/ -q
   ```
   Expect: `0 failed`. Skips are legitimate (Playwright browser,
   sample-data corpora, reportlab, MEDIAHUB_RUN_MOTION_TESTS gate).
   If anything fails, fix before standing up the pilot.

2. **Render service ready.** Deploy from `render.yaml`. Verify
   `/healthz`, `/healthz/deps`, `/status` all return 200 from the
   public URL. The status page should show "no data yet" on the first
   24h window — that's expected.

3. **Environment variables set on Render.** Required:
   - `GEMINI_API_KEY` — free key from aistudio.google.com
   - `MEDIAHUB_SECRET_KEY` — random 64-char hex (web sessions)
   - `DATA_DIR` — `/var/data` (or wherever the Render disk is mounted)

   Recommended:
   - `BUFFER_ACCESS_TOKEN` — only if the pilot club doesn't yet have
     its own Buffer; otherwise leave unset and let the club connect
     inline from the publishing modal.
   - `ANTHROPIC_API_KEY` + `MEDIAHUB_LLM_PROVIDER=anthropic` — only
     if quality on Gemini Flash isn't enough for the pilot brand.

4. **Render disk attached.** Without a disk, every redeploy wipes
   `DATA_DIR` and the club's runs disappear. The pilot dies on the
   first surprise redeploy.

5. **Backups configured.** `DATA_DIR/data.db` + `DATA_DIR/runs_v4/` +
   `DATA_DIR/club_profiles/` is the entire state. A daily Render disk
   snapshot is enough.

6. **Status page subscribed to.** Add the deployment's `/status` URL
   to your personal uptime monitor (UptimeRobot free tier is enough).
   When uptime drops below 99% for a day, the pilot is informed
   *before* the club asks why content didn't post.

---

## Day 0 — first conversation with the pilot club

The club needs to know three things:

1. **Manual approval is non-negotiable.** Nothing goes live without a
   human pressing "schedule". MediaHub is an assistant; it never
   publishes autonomously. (The dissertation §4 governance argument
   in plain English.)

2. **One club per deployment.** Their data is on their MediaHub
   instance, not pooled with anyone else's. Other clubs would get a
   separate instance.

3. **Pilot scope and exit.** The pilot runs for one full month. At
   the end the club either:
   - Continues self-hosted (we hand over the Render instance), or
   - Drops the pilot and we delete their data on request via
     `/privacy/cache/clear` + dropping the Render instance.

Capture a one-line agreement on each of these before any data is
loaded. A Signal message is sufficient.

---

## Day 1 — onboarding session

Live walkthrough (45 minutes, screen-share):

1. **Land them on `/organisation/setup`.** They paste their club
   website URL + up to 5 social profiles + (optionally) drag in a
   brand-guidelines PDF. The org-first gate enforces this before
   anything else is reachable.

2. **First meet upload.** They drop a single result file from a
   recent meet (HY3 / PDF / SportSystems). Watch the recognition flow
   run live; explain the confidence pills.

3. **Review one card together.** Pick one PB card and walk through
   the explainer ("Why this card?"). Edit the caption with them.
   Demonstrate Sponsor Variant and Motion Video.

4. **Buffer connect.** From the schedule modal, paste their Buffer
   access token. Schedule one card to their *test* channel. Verify
   the post lands in Buffer's queue (Buffer staging, not their main
   channels — until they trust it).

5. **`/activity` tour.** Show them where to see scheduled vs published
   vs failed. Show them the "Recent posting activity" panel. Show
   them where to find "Why did this run fail?" if a run errors out.

6. **`/status` link.** Point them at the public status page. "If
   anything looks broken, check here first."

Don't show them `/healthz/usage` — that's operator-only. If they ask
about cost, the answer is "the operator covers it for the pilot".

---

## Week 1 — daily touch (operator side)

Every day for the first week, the operator checks:

| What | Where | Action threshold |
|---|---|---|
| Uptime over 24h | `/status` | < 99.5% → diagnose |
| Failed runs in last 24h | `/activity` failure callout | ≥ 1 → screenshot, message club |
| Buffer failures in last 24h | `/activity` "Recent posting activity" | ≥ 1 → check Buffer token, channel state |
| Last LLM error | `/healthz/usage` | non-null + recent → check Gemini key or paid Anthropic fallback |
| Gemini quota headroom | `/healthz/usage` | < 200 calls left at noon UTC → switch to Anthropic for the day |

No daily message to the club unless something needs them to act.

---

## Week 2–4 — weekly check-in

Once-weekly 15-minute call:

- What worked? (Specific cards, specific captions.)
- What didn't? (Walk through any failures together.)
- What's missing? (Capture as backlog items, do not commit to
  implementing during the pilot.)
- One screenshot of the published content from their Buffer queue.

Send a written follow-up:
> "This week MediaHub generated N pieces of content from M meet
> uploads. K of N were published. The status page shows
> X.XX% uptime. Next week we're processing the [meet name] file."

---

## Failure modes and responses

| Symptom | Likely cause | Fix |
|---|---|---|
| `/healthz` returns 5xx | Render service down, disk unmounted | Check Render dashboard; redeploy with disk |
| `/status` shows long gap | Render scaled to zero, or app crash loop | Check Render logs; if crash, revert deploy |
| All cards have heuristic captions | LLM key missing/invalid | Check `/healthz/usage` "Last LLM error"; rotate key |
| Buffer posts all failing | Token expired or channel disconnected | Pilot club re-pastes Buffer token via schedule modal |
| Pipeline error on every upload | Format change in result file | Capture file → reproduce locally → fix parser → redeploy |
| One run failed mysteriously | Could be transient (parse, LLM timeout) | Show the club "Why did this run fail?" on /activity; re-upload |
| Uptime dropping | Render free tier sleeps after 15 min | Move to Render Starter (paid) |
| Anthropic spend rising | Pilot is heavier than free-tier Gemini covers | Either accept the cost or set `MEDIAHUB_LLM_PROVIDER=gemini` to force free path |

---

## Success criteria (end of month)

The pilot is a success if:

- [ ] **Uptime ≥ 99.5%** over the 30 days (read from `/status`).
- [ ] **Zero unmasked pipeline errors** the club had to escalate.
- [ ] **At least one weekly meet processed** end-to-end with the
  club hitting publish.
- [ ] **Buffer publish success rate ≥ 95%** (from the posting log).
- [ ] **Club says "we'd keep using this"** without prompting.

Anything less means iterate, don't ship.

---

## Exit path

At the end of the pilot:

- **Keep going self-hosted:** transfer Render service ownership
  to the club. They take over `GEMINI_API_KEY` billing (still free at
  small-club volume) and Buffer access token rotation. Operator
  remains available for two weeks of post-handover support.

- **Stop:** delete the Render service and the disk. Confirm to the
  club in writing that `DATA_DIR` is gone. Any local data the
  operator captured for debugging gets deleted too.

In both cases, ask the club: "What would have made you tell other
clubs about this?" Capture the answer verbatim; it's the marketing
brief for Phase 2.
