# docs/security

How MediaHub is protected, written down. In plain words: we assume people
will try to break in, we wrote out exactly how they might try (the threat
model), built a defence for each way in, and we are honest about what's
left over — no system is unhackable, and this folder never claims it is.

- [`THREAT_MODEL.md`](THREAT_MODEL.md) — every way an attacker might come
  at the system (uploads, tenant boundaries, the renderer, the scraper,
  the AI pipeline, the servers), and which defence answers each.
- [`DATA_PROTECTION.md`](DATA_PROTECTION.md) — encryption in transit per
  hosting target, the honest at-rest position, and encrypted,
  restore-tested backups.
- [`SECURITY_REPORT.md`](SECURITY_REPORT.md) — the controls mapped to the
  OWASP ASVS Level 2 checklist, scan results, and the residual-risk
  register (what is NOT covered, stated plainly).
