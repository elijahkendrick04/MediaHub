# Children's Code (Age Appropriate Design Code) pass — public surfaces

> Companion: [`CHILDRENS_CODE.md`](CHILDRENS_CODE.md) maps the 15 standards
> across the **whole product** (consent registry, identity controls, gates).
> This document is the *surface audit* of the four public, unauthenticated
> surfaces specifically — what a stranger can reach — with findings and
> fixes. Read both together.

**Scope.** The ICO's Age Appropriate Design Code applies to information
society services *likely to be accessed by children*. MediaHub's accounts are
adult club officers only (ToS §2), but four surfaces are reachable by anyone
— including children and their parents — and the content itself is largely
*about* children. This pass reviews those surfaces against the Code's 15
standards, with file evidence, and records the changes it forced.

**Surfaces in scope** (PC.12, ADR-0015):

| Surface | Routes | Code |
|---|---|---|
| Public achievements wall | `GET /wall/<token>` | `web/web.py` (`public_wall_page`) |
| Wall embed | `GET /wall/<token>/embed` | `web/web.py` (`public_wall_embed`) |
| Wall feeds | `GET /wall/<token>/feed.json`, `/feed.rss`, `/card/<run>/<card>.png` | `web/web.py` |
| Try-before-signup demo | `GET/POST /try`, `/api/try/status/<id>` | `web/web.py`, `web/demo_try.py` |

**Date:** 2026-06-12 · **Status:** pass recorded; two findings fixed in the
same change (see §3). Re-run this pass whenever a public surface gains a
feature.

---

## 1. The 15 standards, applied

1. **Best interests of the child.** The wall exists to *celebrate* athletes
   on the club's terms. Per-athlete consent (W.2) is enforced at every wall
   exit: a `do_not_feature` athlete — or any athlete with no consent on file
   under an active regime — never appears in wall text, feeds, or the card
   PNG route (`web/public_wall.py::wall_cards`, `::wall_image_path`).
   The demo's bundled sample is synthetic — no real child is used to sell
   the product (finding F1, fixed).

2. **Data protection impact assessments.** The DPIA
   (`docs/compliance/DPIA.md`) covers the wall and demo surfaces; its review
   triggers include any weakening of the safeguarding gate.

3. **Age appropriate application.** Not an age-gated service: the public
   surfaces are read-only showcases with no accounts, no interaction, no
   data collection from visitors of any age (no forms on the wall; the demo
   accepts a file but creates no profile of the uploader).

4. **Transparency.** The Privacy Notice (`/privacy`, public before sign-in)
   describes the wall's initials-first default and consent enforcement in
   §5 (children's data) and the demo's 24-hour retention in §8
   (`web/legal.py::privacy_html`). The wall page footer identifies the
   product ("Powered by MediaHub").

5. **Detrimental use of data.** Wall/feed/demo pages run **no analytics, no
   advertising, no third-party scripts or fonts** (Cookie Policy; fonts are
   self-hosted — `tests/test_self_hosted_fonts.py`). Demo uploads skip
   third-party PB lookups entirely (`demo_try` docstring: `fetch_pbs=False`).

6. **Policies and community standards.** Published ToS/Privacy/Cookies/DPA
   describe actual code behaviour; this document records the public-surface
   posture.

7. **Default settings.** Privacy-protective by default and cumulative:
   - wall **off** until a club enables it; enabling mints an unguessable
     token (`secrets.token_urlsafe(24)`);
   - **initials-only names on by default** (`public_wall_initials_only`,
     default `True`);
   - per-athlete consent, when a registry exists, is enforced **on top** of
     the blanket toggle — most restrictive always wins
     (`public_wall.py::_consent_policy`, `wall_cards`);
   - only club-**approved** cards ever appear (QUEUE/EDITED/REJECTED never).

8. **Data minimisation.** Wall text carries name-as-permitted, event, time,
   meet — nothing else. Feeds carry the same fields. The card PNG route
   serves only cards that would appear on the wall. Demo runs hold the
   uploaded file for ≤24 h then are swept (`demo_try.sweep_demo_runs`).

9. **Data sharing.** No visitor data is collected, so none is shared. Wall
   content reaches third parties only when a club embeds its own wall.

10. **Geolocation.** None on any surface.

11. **Parental controls.** Consent is the club's welfare-officer process:
    the registry supports CSV import of the club's own consent records and a
    welfare-officer export (`safeguarding/consent.py::import_csv/export_csv`),
    and a parent's withdrawal takes effect on the wall immediately (consent
    checks run per request; wall caching is ≤5 minutes). The correction
    workflow (`/privacy/correction`) pulls a published card off the wall.

12. **Profiling.** None: no visitor profiling on any public surface; the
    wall does no per-visitor processing at all.

13. **Nudge techniques.** The wall's only call-to-action is a product
    credit; the demo's signup CTA targets adult club officers and the demo
    refuses work past honest caps rather than nudging for data.

14. **Connected toys and devices.** Not applicable.

15. **Online tools.** Rights tools are one click from every page footer
    (Privacy page: athlete erasure, correction/takedown, account deletion,
    export).

## 2. Session/cookie posture on the public surfaces

Flask only emits `Set-Cookie` when the session is touched; the wall page,
embed, JSON/RSS feeds and card-PNG routes never write to the session, so an
anonymous wall visit sets **no cookie at all**. The demo flow stores only the
visitor's own demo-run ids in the (strictly necessary, signed, HttpOnly)
session cookie so the visitor can see their own preview. Pinned by
`tests/test_childrens_code_public_surfaces.py`.

## 3. Findings this pass produced (and their fixes)

- **F1 — the public demo shipped real children's data.** The bundled `/try`
  sample was a real meet's results PDF: real named under-18 swimmers, clubs
  and times, used as marketing collateral on an unauthenticated surface.
  Already-public origin does not make that proportionate (Standard 1/8).
  **Fixed:** replaced with a synthetic, deterministic sample
  (`samples/demo-meet-results.pdf`, generated by
  `scripts/make_demo_sample.py`; every swimmer/club fictional). The real
  file remains only as a parser-regression fixture under `sample_data/`,
  which no route serves — retained under the legitimate interest in parser
  accuracy over already-published results (Privacy Notice §4 basis), not as
  demo material.
- **F2 — the wall ignored per-athlete consent.** The wall applied only the
  blanket initials toggle; a `do_not_feature` athlete's approved card would
  still appear (initialled). **Fixed:** consent is resolved per card across
  wall text, feeds and the PNG route; blocked athletes are dropped
  everywhere, and the members-only settings page explains each hidden card
  ("Held off the wall by consent") so the club sees *why*
  (`web/public_wall.py`, `web/web.py::public_wall_settings`).

## 4. Standing rules for future public-surface work

- New public surface ⇒ extend this pass before shipping; add it to the
  scope table and the no-cookie/no-tracker tests.
- Anything that names an athlete on a public surface MUST resolve
  `safeguarding.consent.effective_policy` and obey it.
- `samples/` is for the public demo only and must stay synthetic;
  real-world fixtures live in `sample_data/` / `samples/learning_corpus/`
  (engineering corpus, never served; the corpus dir is excluded from any
  public route by construction — nothing maps it).
