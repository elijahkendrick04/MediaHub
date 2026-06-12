# PECR Cookie Audit — MediaHub web UI

> Engineering audit, verified against the codebase on 2026-06-12.
> Re-run this audit whenever a frontend dependency, analytics tool, or
> third-party embed is added. Law: PECR reg 6 as amended by the DUAA
> (see [`LEGAL_FRAMEWORK.md`](LEGAL_FRAMEWORK.md) §1.4).

## Findings

| Storage | Set by | Purpose | PECR position |
|---|---|---|---|
| `session` cookie (signed, HttpOnly, SameSite=Lax, Secure on HTTPS) | Flask, implicit (`web.py` session config) | Login state, active organisation, operator flag — authentication and security | **Strictly necessary → exempt from consent** (reg 6(4)) |

That is the complete list:

- `grep -rn "set_cookie"` over `src/mediahub/web/` returns **nothing** —
  no explicit cookies are set anywhere.
- No `document.cookie` or `localStorage` use in the inline JS.
- No third-party analytics, tag managers, pixels, or embeds.
- Fonts are **self-hosted** on every surface (CLAUDE.md invariant; enforced
  by `tests/test_self_hosted_fonts.py`) — no CDN request, no third-party
  cookie surface, and no Munich-ruling GDPR exposure from font delivery.

## Conclusion

**No consent banner is required.** The only storage is strictly necessary
for the service the user explicitly requests (signing in and using the app).

## If analytics are ever added

The DUAA (in force 5 Feb 2026) created a narrow PECR exemption for
**first-party statistical purposes** cookies, conditional on:

1. clear and comprehensive information being given, and
2. a **simple, free opt-out** being offered (and honoured).

Third-party analytics that profile users do **not** fit the exemption and
would need prior consent (with PECR fines now at UK GDPR levels). Any such
addition must update this audit, the privacy notices, and — if non-exempt —
ship a consent mechanism in the same change.
