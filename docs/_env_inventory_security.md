## API keys & secrets — least-privilege scoping (security/secrets-and-config)

All keys live in env/`.env` only (gitignored) — never in source, tests,
logs, or pushed artifacts (CLAUDE.md rule; gated in CI by gitleaks). Scope
each key to the minimum the deployment uses:

| Secret | Least-privilege scoping | Blast radius if leaked | Rotation |
|---|---|---|---|
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Paid-tier Generative Language API key, **API-restricted to the Gemini API only** (no other Google APIs), quota-capped in the console | Caption/brief generation quota abuse; prompt payloads are minimised so no DOB/IDs exposed | Edit `.env`, redeploy — no code change |
| `ANTHROPIC_API_KEY` | Standard API key; per-workspace key recommended so usage is attributable; spend cap in console | Same as Gemini (failover payloads) | `.env` only |
| `REPLICATE_API_TOKEN` | Only set when `MEDIAHUB_CUTOUT_PROVIDER=replicate`; default `server` needs no key | Photo-processing quota; photos of athletes transit only when enabled | `.env` only |
| `PHOTOROOM_API_KEY` | Only when `MEDIAHUB_CUTOUT_PROVIDER=photoroom` | As Replicate | `.env` only |
| `BUFFER_ACCESS_TOKEN` | Per-club token scoped to that club's channels (stored per-profile); never a master token in env on multi-tenant deployments | Posting to the connected channels | Revoke in Buffer, re-connect |
| `STRIPE_SECRET_KEY` | Restricted key: Checkout + Customer Portal + webhooks only | Billing actions (card data never touches MediaHub) | Stripe dashboard |
| `MEDIAHUB_DEV_KEY` | High-entropy (≥ 32 random chars); set only while the operator needs the override; **unsetting it instantly revokes all operator sessions** | Full operator access | Unset/replace in `.env` |
| `MEDIAHUB_NTFY_TOKEN` / webhook URLs | Notification payloads carry no athlete personal data by policy (tested) | Noise/spoofed ops alerts | `.env` only |
| `app.secret_key` (`DATA_DIR/.secret_key`, 0600) | Auto-generated per deployment; signs sessions | Session forgery → full account takeover: protect the data volume, rotate after any suspected exposure (logs everyone out) | Delete the file, restart |

Boot-time validation (`mediahub.web.env_check`, fail-fast in production):
unset `DATA_DIR` on a production host, malformed provider keys, and a weak
`MEDIAHUB_DEV_KEY` are refused at startup rather than discovered in an
incident.
