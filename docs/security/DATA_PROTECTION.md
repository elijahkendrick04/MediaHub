# Data protection in depth — TLS, at-rest, backups

> security/data-protection-in-depth (THREAT_MODEL §7). Everything here is
> free to operate — no paid services.

## TLS assumptions per deploy target

| Target | TLS termination | Operator action |
|---|---|---|
| **Render** (reference) | Render's edge terminates TLS and forwards over its private network; `RENDER`/`RENDER_EXTERNAL_URL` env makes the app set `Secure` session cookies + HSTS | None — verify the service URL is https and HTTP→HTTPS redirect is on (Render default) |
| **Fly.io** | Fly edge terminates TLS (`force_https = true` in fly.toml) | Set `MEDIAHUB_SESSION_COOKIE_SECURE=true` |
| **Docker / VPS** | **The container itself serves plain HTTP on :5000.** A reverse proxy (Caddy/nginx + Let's Encrypt) MUST terminate TLS in front of it; never expose :5000 to the internet | Proxy config; set `MEDIAHUB_SESSION_COOKIE_SECURE=true`; pass `X-Forwarded-For` (login throttling keys on it) |

Internal egress (LLM APIs, image APIs, swimmingresults.org) is
HTTPS via `requests`/SDK defaults with certificate verification — never
disable verification.

## At-rest position (honest)

- SQLite + JSON/JSONL stores under `DATA_DIR` are **not application-layer
  encrypted**. Free, feasible protections in place instead:
  - sensitive files are `0600` (users ledger, compliance ledgers,
    security log, session secret);
  - the container runs **non-root**, so a worker compromise doesn't own
    the volume;
  - retention purges bound how much history is exposed by any disk
    compromise.
- Disk-level encryption is the platform's job and is in place on managed
  targets (Render/Fly volumes are encrypted at rest by the provider; on a
  VPS, use LUKS for the data volume — documented operator step).
- Application-layer encryption (e.g. SQLCipher) was considered and
  deferred: key management inside the same container yields little real
  protection against the threat it would aim at (host compromise) — see
  the residual-risk register in `SECURITY_REPORT.md`.

## Backups

`scripts/backup_mediahub.sh` produces an **encrypted, integrity-checked**
tarball of the data the platform can't recreate:

- includes: `DATA_DIR` (compliance ledgers, club profiles, users, data.db,
  security log), `runs_v4/`, `uploads_v4/`
- excludes: rebuildable caches (`.cache/`, `data/discovered/`,
  `motion_cache/`)
- encryption: OpenSSL AES-256-CBC with PBKDF2 (free, works headless under
  cron — `age` passphrase mode needs a TTY); passphrase from `MEDIAHUB_BACKUP_PASSPHRASE` (never on the
  command line, never in the repo)
- **restore-test mode**: `--verify <archive>` decrypts to a temp dir,
  checks the tar integrity and the presence of the critical stores, and
  reports — a backup that hasn't been restore-tested is a hope, not a
  backup. Run `--verify` on the latest archive at least monthly.

Schedule it with cron on a VPS or a scheduled job on the platform; keep
copies off the primary host (the 3-2-1 floor: 2 media, 1 off-site).
Backups contain children's personal data: store them only where the
retention schedule and erasure duties can still be honoured — long-lived
backup archives are listed as a residual in erasure reports.
