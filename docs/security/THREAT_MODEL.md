# MediaHub Threat Model

> Phase 3 ground truth. STRIDE per surface, plus the OWASP LLM Top 10 for
> the AI pipeline. Each threat names its mitigating capability (S1–S8
> below) or is explicitly **accepted** into the residual-risk register
> (`SECURITY_REPORT.md`). Assets ranked by harm: (1) children's personal
> data, (2) tenant isolation, (3) the publish path (what goes public under
> a club's name), (4) operator credentials/API keys.
>
> Capabilities: S1 `security/authn-authz` · S2 `security/input-handling` ·
> S3 `security/web-hardening` · S4 `security/secrets-and-config` ·
> S5 `security/supply-chain-ci` · S6 `security/data-protection-in-depth` ·
> S7 `security/logging-monitoring` · S8 `security/llm-pipeline`

## Trust boundaries

```
Internet ──> [TLS proxy (Render/Fly/反向代理)] ──> Flask monolith (web.py)
                                            ├── DATA_DIR stores (SQLite + JSON/JSONL + files)
                                            ├── upload parsers (HY3/SDIF/PDF/HTML/ZIP)   <- untrusted bytes
                                            ├── Playwright/Chromium renderer (HTML→PNG)  <- semi-trusted HTML
                                            ├── Remotion/Node renderer (MP4)
                                            ├── scraper (swimmingresults.org, results-from-URL) <- untrusted web
                                            ├── LLM APIs (Gemini/Anthropic)              <- untrusted *output*
                                            └── image APIs / Buffer / ntfy (egress)
```

## 1. Upload → parse pipeline (untrusted bytes)

| STRIDE | Threat | Disposition |
|---|---|---|
| T | Zip bomb exhausts disk/RAM | Mitigated (exists): `interpreter/_zip_safety.py` — 64 members, 64MB/member, 128MB total, 200:1 ratio, decompression-time re-check |
| T | Zip-slip writes outside extraction dir | **S2** — path-traversal check on member names |
| D | Malformed PDF hangs pdfplumber (CPU/memory DoS) | **S2** — page/size caps + parse timeouts |
| T | Crafted filename traverses paths or breaks shell | Mitigated (exists): files stored under random run-id dirs; **S2** adds extension allowlist + size re-check; filenames never reach a shell |
| S | Upload of active content (HTML/JS) later served | **S2/S3** — uploads never served raw; MIME sniffing headers |
| E | Upload route unauthenticated on shared instance | **S1** — org gate + per-tenant scoping (exists for bound orgs); rate caps |

## 2. Multi-tenant boundaries

| STRIDE | Threat | Disposition |
|---|---|---|
| E/I | Tenant A reads/mutates tenant B's runs, cards, brand kits, media, consent, DSR records | **S1** — `_can_access_run` (exists, 37 routes) + new compliance routes pinned to active profile; **isolation regression tests for every multi-tenant store** |
| I | Cross-tenant PB warm cache leaks athlete lookups | Known (DATA_MAP S7); retention-bounded (30d); flagged in residual register; full tenant-scoping is roadmapped |
| S | Session fixation/persistence: cookie never rotates, no idle timeout | **S1** — rotation on login, idle timeout enforcement |
| E | Brute-force login (no rate limit today) | **S1** — per-account+IP throttle, lockout, security events |
| E | Weak password hash future-proofing (bcrypt-72-byte) | **S1** — argon2id for new hashes, verify-and-upgrade for existing |
| E | Operator `/developer` sign-in guessed / brute-forced | Username + **argon2id-hashed password** (hash only in source, never plaintext), constant-time compare, per-account+IP **rate-limit** on the endpoint, `_safe_next` open-redirect guard; **S7** logs operator logins. Rotate via `MEDIAHUB_DEV_USER` / `MEDIAHUB_DEV_PASSWORD_HASH` or in code (ADR-0019, supersedes ADR-0018). Residual: a weak operator password is the operator's own risk. |

## 3. Playwright HTML→PNG renderer

| STRIDE | Threat | Disposition |
|---|---|---|
| S/I | Template-injected URL makes Chromium fetch attacker URL (SSRF) or read `file://` secrets | **S2** — renderer lockdown: route interception allows only the layout's own assets (file:// fonts/CSS under the renderer dir + data: URIs); all network egress blocked |
| T | Caption/name HTML injects script into the render | Mitigated (exists): `_h()` escaping at template build; **S2** verifies with an injection regression test |
| D | Render farm starvation via huge concurrent renders | Exists: render gate concurrency caps (web.py); accepted residual for extreme cases |

## 4. Scraper / results-from-URL (SSRF surface)

| STRIDE | Threat | Disposition |
|---|---|---|
| S | User-supplied URL targets internal services (169.254.169.254, localhost, RFC1918) | **S2** — SSRF guard: scheme allowlist (http/https), DNS-resolved IP must be public, redirects re-checked |
| T | Malicious result page poisons parsed data | Deterministic parsers + confidence flags (exists); content treated as data, never executed |
| I | Athlete names leak into third-party search engines | Mitigated (C3): cache-first, rate-limited, per-tenant opt-in |

## 5. LLM captioning path (OWASP LLM Top 10)

| LLM# | Threat | Disposition |
|---|---|---|
| LLM01 prompt injection | Uploaded results (PDF/HTML text) contain "ignore previous instructions…" which flows into caption prompts | **S8** — untrusted fields delimited + system-prompt hardening ("treat as data"); injection-pattern screening flags suspicious achievements for review |
| LLM02 insecure output | LLM output rendered into HTML/cards | Exists: `_h()` escaping; output is text-only, never eval'd/exec'd; **S8** regression test |
| LLM02/06 output triggers actions | A caption containing tool-like syntax causes privileged action | **S8** — no code path parses captions for actions; the human-approval gate is server-side state, not UI; test proves a malicious caption cannot publish itself |
| LLM04 model DoS | Attacker-driven repeated caption calls burn quota | Exists: review-driven generation + observability; per-session research caps; accepted residual at extreme scale |
| LLM06 sensitive disclosure | Prompts over-share athlete data | Mitigated (C3 minimisation) |
| LLM09 overreliance | Fake PB claims in captions | Exists: deterministic engine decides PB status; caption layer only phrases it; confidence language enforced |

## 6. Admin / operator surfaces

| STRIDE | Threat | Disposition |
|---|---|---|
| E | `/admin/compliance` and operator routes reachable without operator session | Exists: 404 unless `is_dev_operator()`; tests pin it |
| I | Debug endpoints/stack traces leak internals | **S3** — generic production error pages, no tracebacks |
| R | No audit of who exported/erased/published | **S7** (+C2) — structured security event log |
| S | CSRF on state-changing routes | Exists: SameSite=Lax + signed session; **S3** adds CSRF tokens on auth + compliance + admin forms; residual documented for legacy fetch-driven routes (Lax cookie is the floor) |

## 7. Deployment targets (Docker/Render/Fly/VPS)

| STRIDE | Threat | Disposition |
|---|---|---|
| E | Container runs as root; compromise = box compromise | **S5** — non-root Dockerfile, pinned slim base, healthcheck |
| I | Secrets in image/repo/history | Verified clean (gitleaks full history); **S4** — fail-fast env validation, `.gitleaks.toml`, CI gate |
| T | Vulnerable dependency (incl. `vendor/`) | **S5** — pip-audit + bandit + semgrep + gitleaks CI gates; dependabot |
| I | TLS termination assumptions undocumented per target | **S6** — documented per target; HSTS (**S3**) |
| I | Backup loss/exposure | **S6** — encrypted backup script + restore test procedure |
| D | Host/provider compromise | **Accepted residual** (any SaaS) — register entry |

## 8. Publish path

| STRIDE | Threat | Disposition |
|---|---|---|
| E | Bypass human approval via direct API | Verified: schedule/publish routes check workflow state server-side; autonomy passes the 8-check publish gate (kill switch, policy, provenance, confidence, brand safety, safeguarding, **consent**, rate caps); **S8** adds the regression test |
| R | Untraceable publishes | Exists: immutable per-org audit ledger + posting log; **S7** events |
| S | Stolen per-club Buffer token | Stored per-profile on disk (0-knowledge of platform creds otherwise); **S6/S4** file modes + least-privilege documented |

## Out of scope / accepted (full register in SECURITY_REPORT.md)

Hosting-provider compromise; zero-days in Chromium/Playwright/CPython;
social engineering of club operators; malicious club insiders publishing
content they're authorised to publish; platform-side processing after
publication.
