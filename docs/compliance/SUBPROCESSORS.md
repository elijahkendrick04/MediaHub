# Sub-processors and third-party recipients

> **DRAFT — FOR LEGAL REVIEW.** Engineering inventory of every third party
> that touches personal data processed by MediaHub, for inclusion in the
> club-facing Art 28 DPA (sub-processor authorisation) and the public
> sub-processor disclosure page. Verify each provider's current DPA and
> certification status at procurement and at least annually. Companion:
> [`LEGAL_FRAMEWORK.md`](LEGAL_FRAMEWORK.md) §4, [`DATA_MAP.md`](DATA_MAP.md).
>
> Last reviewed: 2026-06-12.

## Active sub-processors (engaged by the operator as processor)

| Provider | Role | Personal data received | Processing location | Transfer mechanism (UK exporter) | DPA / terms | Optional? |
|---|---|---|---|---|---|---|
| **Render Services, Inc.** (reference host) | Hosting: app, SQLite DB, persistent disk (uploads, runs, rendered cards, PB cache, logs) | **Everything the platform stores** — athlete names, YOB, sex category, club, times, photos, rendered cards, account emails | United States (region-dependent) | UK–US data bridge (Render is **DPF-certified**, incl. UK Extension); DPA incorporates SCCs as fallback | [render.com/dpa](https://render.com/dpa) · [certifications](https://render.com/docs/certifications-compliance) (ISO 27001) | No — it is the deployment |
| **Google LLC** (Gemini API, paid tier) | Primary LLM: captions, creative briefs, brand interpretation, media description tagging, operating-profile derivation | Prompt payloads: athlete name, event, time, achievement context, club/brand text; media descriptions. **Must never include DOB/YOB or unneeded fields after the Phase 2 minimisation capability** | US/global; EU/UK regional endpoints available via Vertex AI | Google Cloud Data Processing Addendum: SCCs + UK Addendum incorporated; paid-tier data not used for training; EEA/UK/CH commitments extend paid-tier handling | [Gemini API terms](https://ai.google.dev/gemini-api/terms) · [Cloud DPA](https://cloud.google.com/terms/data-processing-addendum) | Provider-configurable (`GEMINI_API_KEY`) |
| **Anthropic, PBC** (Claude API) | Secondary LLM (failover for the same surfaces) | Same payload shape as Gemini | United States | DPA incorporated in Commercial Terms: SCCs + UK IDTA/Addendum; no training on API business data by default | [Anthropic DPA](https://privacy.claude.com/en/articles/7996862-how-do-i-view-and-sign-your-data-processing-addendum-dpa) · [Trust Center](https://trust.anthropic.com/) | Provider-configurable (`ANTHROPIC_API_KEY`) |
| **Photoroom SAS** (cutout API) | Photo background removal | Full photo bytes — images of identifiable athletes, frequently children | France HQ; sub-processors may be outside EEA | GDPR processor terms; confirm signed DPA + sub-processor list before production use | [Privacy policy](https://www.photoroom.com/legal/privacy) | Yes — `MEDIAHUB_CUTOUT_PROVIDER=photoroom`; default is in-process `server` (rembg) |
| **Replicate, Inc.** (cutout API) | Photo background removal | Full photo bytes (as above) | United States | Processor terms per privacy policy; obtain DPA; SCCs/IDTA required | [Privacy](https://replicate.com/privacy) | Yes — `MEDIAHUB_CUTOUT_PROVIDER=replicate`; default is `server` |
| **Buffer, Inc.** (publishing) | Scheduling/relay of approved posts to social platforms | Approved card images + captions: names and photos of athletes, incl. children | United States | DPA required; SCCs/IDTA | buffer.com legal | Yes — `BUFFER_ACCESS_TOKEN`; publishing is opt-in per club |
| **Operator-configured OpenAI-compatible endpoint** (LLM failover / embeddings) | Additional LLM provider and caption-memory embeddings | Generation prompts and caption text (athlete names included) | Wherever the operator's chosen provider runs | The operator must hold processor terms with their chosen provider before configuring it | provider-specific | Yes — `MEDIAHUB_LLM_ENDPOINTS` / `MEDIAHUB_EMBED_ENDPOINT`; inert unset |
| **Microsoft** (edge-tts voiceover) | Synthesises reel narration audio | The narration text: athlete name, event, time | United States | Public synthesis endpoint with **no contractual terms** — voiceover is OFF by default and opt-in for exactly this reason; treat enabling it as a procurement decision | none available | Yes — `MEDIAHUB_VOICEOVER=1`; off by default |
| **Resend, Inc.** (transactional email, PC.14) | Password resets, email verification, workspace invites, service/breach notices | Account email addresses and the message content | United States | DPA; SCCs/IDTA | [resend.com/legal/dpa](https://resend.com/legal/dpa) | Yes — `RESEND_API_KEY` + `MEDIAHUB_EMAIL_FROM`; honest-unavailable unset |
| **Stripe, Inc.** (billing) | Payment processing (controller-side, listed for transparency) | Account email, plan, payment details (collected by Stripe directly) | United States | Stripe DPA; UK–US data bridge / SCCs | [stripe.com/legal/dpa](https://stripe.com/legal/dpa) | Yes — `STRIPE_SECRET_KEY`; billing is honest-503 unset |
| **Operator's off-site backup target** (PC.14) | Stores backup archives (ledgers, databases, runs JSON) | Everything a backup archive holds — see `mediahub/backup` | Operator-chosen | Part of the hosting/storage surface: the operator must hold processor terms with the target's provider | provider-specific | Yes — `MEDIAHUB_BACKUP_UPLOAD_URL`; off unset |

## Recipients that are NOT sub-processors

| Party | Relationship | Notes |
|---|---|---|
| **Meta (Instagram/Facebook), TikTok** | **Independent controllers** on publication | Once a club approves publication, the platform processes the content under its own terms (indexing, recommendation, ad systems). The club's Art 13/14 notices and the consent registry must cover publication itself; MediaHub cannot recall platform-side copies (stated honestly in the erasure tooling). |
| **swimmingresults.org (Swim England rankings)** | **Data source**, not a recipient | MediaHub sends only an HTTP search request containing athlete name (+ club) and receives public ranking history. Legal analysis (Art 14, fairness, lawful basis, site terms) tracked as Q4 in [`OPEN_LEGAL_QUESTIONS.md`](OPEN_LEGAL_QUESTIONS.md). |
| **ntfy / operator webhooks** (optional) | Operational notification channel | Policy: notification payloads must contain **no athlete personal data** (run IDs and counts only) — enforced by the Phase 2 minimisation capability. If an operator configures a third-party ntfy server and includes personal data, that channel becomes a sub-processor and needs a DPA. |
| **SearXNG / DuckDuckGo** (web research) | Search intermediary | Queries may contain club names; must not contain athlete names for minors. Same minimisation policy as ntfy. |

## Standing obligations (to encode in the Art 28 DPA template)

1. **Prior authorisation list** — this table is the authorised sub-processor
   list referenced by the DPA; clubs get notice (and an objection right)
   before a new sub-processor is added.
2. **Flow-down** — each sub-processor must be bound by equivalent Art 28(3)
   terms; transfer mechanism recorded above.
3. **Minimisation at the boundary** — payloads to LLM and image APIs carry
   only the fields the caption/cutout needs (Phase 2
   `compliance/retention-and-minimisation`); DOB/YOB never leaves the
   platform.
4. **DPF contingency** — where a transfer relies on the UK–US data bridge /
   EU–US DPF, the contract must also embed SCCs/IDTA so a DPF invalidation
   (CJEU appeal C-703/25 P pending) does not strand the transfer (Q7).
5. **Annual review** — re-verify each provider's DPA, certification, and
   sub-processor list; update this file and the public disclosure page.
