# Security Report — ASVS L2 programme

> Phase 4 deliverable. **This system is not "unhackable" — no system is.**
> What this report claims, exactly: MediaHub is *threat-modelled*
> ([`THREAT_MODEL.md`](THREAT_MODEL.md)), hardened with *defence in depth*,
> verified against the **OWASP ASVS Level 2** items below with every
> control covered by a test, and its **residual risks are listed honestly**
> at the end. Scan evidence from 2026-06-12.

## 1. Controls mapped to ASVS L2

| ASVS chapter | Items | Control | Evidence (tests) |
|---|---|---|---|
| **V1 Architecture** | 1.1.2 threat modelling | STRIDE threat model incl. OWASP LLM Top 10; every threat mapped to a capability or accepted | `THREAT_MODEL.md` |
| **V2 Authentication** | 2.2.1 anti-automation | Two layers: per-IP request limiter on auth endpoints (per-app, PR #352) + per-ACCOUNT failure lockout (5 failures/15 min per email, checked before verification — deliberately not IP-keyed so one bad actor behind a club's NAT can't lock out the club); lockouts logged | `test_authn_hardening.py` (lockout trio) |
| | 2.4.x password storage | **argon2id** (argon2-cffi defaults) for new + rehashed; legacy bcrypt verifies and upgrades on next login; constant-time, timing-equalised unknown-email path | `test_authn_hardening.py`, `test_auth.py` |
| | 2.7/2.8 MFA | Optional **TOTP 2FA** (RFC 6238, stdlib): enable/disable with valid code; password alone never grants a session when enabled; failures share lockout counters | `test_authn_hardening.py::test_2fa_*` |
| **V3 Session** | 3.2.1 rotation | `session.clear()` before login/signup grants | `test_session_rotated_on_login` |
| | 3.3 timeouts | Idle window (`MEDIAHUB_LOGIN_IDLE_MINUTES`, default 30) drops stale org pins | existing org-gate tests |
| | 3.4 cookies | Signed, HttpOnly, SameSite=Lax, Secure on HTTPS | `test_auth.py` cookie assertions |
| **V4 Access control** | 4.1/4.2 per-record authz | Tenant isolation on run routes (`_can_access_run`, 37 routes), media library, brand kits, consent registry, DSR requests, retention/child-policy settings; **publish route tenant-gated** | `test_run_route_isolation_invariant.py`, `test_cross_tenant_access.py`, `test_media_library_profile_isolation.py`, `test_compliance_tenant_isolation.py`, `test_llm_pipeline_security.py::test_schedule_is_tenant_scoped` |
| | 4.2.2 CSRF | Token auto-injected into every rendered POST form; form/multipart POSTs verified (constant-time); JSON exempt by content-type; webhook exempt by signature; rejections logged | `test_web_hardening.py` CSRF quartet |
| **V5 Input validation** | 5.1/5.2 | Upload extension allowlist; 50 MB cap; zip-bomb limits (members/size/ratio/decompression re-check); zip-slip structurally absent (static guard); PDF page cap; HY3/SDIF parsed deterministically as data | `test_input_handling_security.py` |
| | 5.3 output encoding | `_h()` (markupsafe) on user-influenced output; complaint-content XSS test; LLM output treated as inert text | `test_compliance_complaints.py::test_complaint_content_is_escaped`, `test_llm_pipeline_security.py::test_no_llm_output_reaches_eval_or_exec` |
| **V8 Data protection** | 8.1/8.3 | Minimised LLM payloads (no IDs/DOB); pseudonymised security log; 0600 sensitive files; retention purge; encrypted restore-tested backups | `test_retention_minimisation.py`, `test_dsr_rights.py`; `DATA_PROTECTION.md` |
| **V9/V10 Comms & malicious code** | | TLS per target documented; SSRF guard (public-IP-only, per-hop redirect revalidation, fail-closed); renderer **no-network lockdown** (live-tested) | `test_input_handling_security.py` SSRF + renderer tests |
| **V11 Business logic** | 11.1.5 | **Unbypassable publish gate**: the schedule route enforces tenant + recorded human approval + consent server-side; the consent answer unifies the W.2 safeguarding levels AND the compliance ledger (blocked if either blocks, fail-closed); autonomous path passes an 8-check gate with minors always excluded | `test_llm_pipeline_security.py`, `test_autonomous_publishing.py`, `test_consent_gating.py` |
| **V12 Files** | | Uploads stored as opaque bytes under random run ids; never served raw; media file route profile-scoped | `test_input_handling_security.py`, media isolation suite |
| **V13 API** | | JSON APIs tenant-scoped; IDOR tests on privacy delete; non-enumerable ids (random hex) | `test_privacy_delete_idor.py`, complaints id test |
| **V14 Config** | 14.1 build | Non-root Docker (uid 10001), pinned slim base, healthcheck; CI gates: pip-audit, bandit (0 high), semgrep p/python (0 ERROR), gitleaks (history clean); dependabot | `.github/workflows/security.yml`; bandit/semgrep runs below |
| | 14.4 headers | CSP, nosniff, XFO (embed-aware), Referrer-Policy, Permissions-Policy, HSTS-on-HTTPS; generic error pages | `test_web_hardening.py` |
| | 14.x secrets | Fail-fast boot validation (`web/env_check.py`); least-privilege key scoping table (ENV_INVENTORY); no secrets in tree or history | `test_authn_hardening.py` env fixtures; gitleaks |
| **LLM Top 10** | LLM01/02/06 | Prompt delimiting + system guard; injection scanning (flag-and-log, never silent rewrite); minimised payloads; output inert; human gate in code | `test_llm_pipeline_security.py` |

## 2. Scan results (2026-06-12)

| Scan | Scope | Result |
|---|---|---|
| **pip-audit** | `requirements.txt` | **0 known vulnerabilities** |
| **bandit** | `src/mediahub` (excl. legacy) | **0 high** (4 MD5-as-cache-key fixed with `usedforsecurity=False`); 29 medium / 196 low triaged as informational (subprocess-with-fixed-args in renderers, asserts, try/except patterns) |
| **semgrep** `p/python` | `src/` (excl. legacy/vendor) | **0 ERROR-severity findings** (55 rules, 257 files) |
| **gitleaks** | full git history (152+ commits) | **clean** — 9 historical hits are one synthetic test value (`swimmer_key="jane-smith-001"`), allowlisted in `.gitleaks.toml` |
| **OWASP ZAP 2.16.1** (spider + passive baseline, local deploy, 52 URLs) | `http://127.0.0.1:5050` | **0 High.** Medium: CSP `unsafe-inline` script/style (accepted residual, below) and missing `frame-ancestors` fallback (fixed post-scan: `frame-ancestors 'none'` everywhere except the by-design wall embed). Informational: reflected-attribute warnings (values pass `_h()` — verified escaped), suspicious-comments (TODO strings), session-management notices |

ZAP note: run against a **local** instance — never against production
(per CLAUDE.md). The baseline was spider + passive rules; an
authenticated active scan against a staging deploy is recommended before
any major release (residual register).

## 3. Residual-risk register (what is NOT covered)

Explicitly accepted, with rationale — revisit at least annually:

| # | Residual risk | Why accepted / compensating controls |
|---|---|---|
| R1 | **Hosting-provider compromise** (Render/Fly/VPS) — full data store exposure | Inherent to any hosted SaaS. Compensations: provider ISO 27001 + DPF, retention purge bounds exposure, breach playbook, 0600 modes, non-root |
| R2 | **Zero-days in Chromium/Playwright, CPython, Flask, SQLite** | Patch cadence via dependabot + pip-audit gate; renderer network lockdown shrinks Chromium's blast radius |
| R3 | **Social engineering of club operators** (credential phishing, rogue volunteer) | 2FA available; security event log for forensics; consent gate limits what any operator can publish about opted-out children; club-side controls are the club's duty (DPA) |
| R4 | **Malicious authorised insider** publishing content they are allowed to publish | Out of technical scope; audit ledger + posting log give attribution |
| R5 | **CSP `unsafe-inline`** for script/style | Required by the f-string monolith's inline idiom; CSP still blocks remote script injection, object embedding, base/form hijack. Tightening to nonces is a refactor of every inline block — roadmapped, not pretended |
| R6 | **CSRF on legacy JSON-fetch routes** relies on SameSite=Lax + content-type discipline rather than per-request tokens | Lax blocks cross-site POSTs in all evergreen browsers; token enforcement covers all form posts |
| R7 | **Cross-tenant PB warm cache** (`data/discovered/swimmers/`) not tenant-scoped | 30-day retention bound; erasure reaches it; full scoping needs a cache-key migration (roadmapped; DATA_MAP S7) |
| R8 | **In-memory lockout/limiter** reset on process restart; lockout is email-keyed so an attacker rotating emails is bounded only by the per-IP limiter | Lockouts are logged (pattern evidence survives); persistent counters would need a shared store — accepted at current scale |
| R9 | **Docker non-root build not build-verified in this environment** (no Docker daemon available) | Change is review-verified; CI/staging build will exercise it — verify before next deploy |
| R10 | **Published content** lives on social platforms beyond MediaHub's reach | Stated in notices, erasure reports, and the DPIA — a legal/communications control, not a technical one |
| R11 | **Backup archives** can outlive an erasure request | Erasure reports list them as residual; backup retention documented; operators must rotate backups within the retention window |

## 4. Verification status

- Full pytest suite: **green** — 4,153 passed, 1 environment skip,
  0 failures (2026-06-12), including ~120 new compliance/security tests.
- Every mitigated THREAT_MODEL row has a named regression test (§1 table).
- CI security gates active and calibrated green at introduction.
