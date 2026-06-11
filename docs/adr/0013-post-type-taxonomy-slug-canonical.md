# ADR 0013 — Post-type taxonomy realised as a slug-canonical layer (P1.2)

**Status:** Accepted
**Date:** 2026-06-10
**Deciders:** Maintainer (Council-pressure-tested per `docs/COUNCIL_GOVERNANCE.md`)

## Context

Roadmap item **P1.2** required reconciling the cross-sport post-type taxonomy
([`POST_TYPE_TAXONOMY.md`](../POST_TYPE_TAXONOMY.md): ~13 universal + ~5
sport-specific slugs per sport, 4 axes each) with the existing
`club_platform.content_types.ContentType` registry — a 6-value str Enum where
every member is a *clickable product surface* (Create-page tile, Settings →
Autonomy policy row, publish-gate key, route endpoint). The roadmap marked the
extend-vs-layer choice a **Council-gated data-model call** because it is the
spine for the P1.3 planner, P2.2 per-type autonomy, and P3 multi-sport
expansion. Two slug mismatches existed (`weekend_preview` vs taxonomy
`event_preview`; `sponsor_post` vs `sponsor_activation`), and the enum strings
already persist in per-org autonomy policy files and saved stub packs under
`DATA_DIR`.

A full LLM Council was convened (five advisors + anonymous peer review).
Verdict in brief: **unanimously reject extending the enum** with ~32
unimplemented types (they would leak into Create tiles and policy rows of a
sellable product); **slug becomes the canonical post-type identity**; the enum
is demoted to an *implemented-surface badge* over a subset of slugs; and the
two name mismatches are fixed **now**, before the planner hardens them into a
third persisted namespace. Peer review's catches, all encoded below: the
policy schema must not simply move the 38-row leakage into policy defaults;
the key rename must be read-tolerant so operator-set autonomy levels are never
silently reset; and whatever P1.3 persists must use canonical slugs from day
one.

## Decision

**Layer, on a slug-canonical spine** (`club_platform/post_types.py`):

1. **Canonical identity = the taxonomy slug.** Universal slugs are declared in
   code (`UNIVERSAL_POST_TYPES`); sport-specific slugs live in
   `data/sport_profiles/*.yaml`. New surfaces (the P1.3 planner, plan
   persistence, gates) speak slugs only.
2. **`ContentType` = the implemented-surface badge.** It never grows an
   unimplemented member; every enum value MUST itself be a canonical slug
   (subset invariant, test-pinned by `tests/test_post_types.py`).
3. **The two mismatched members are renamed to their canonical slugs**
   (`WEEKEND_PREVIEW`/"weekend_preview" → `EVENT_PREVIEW`/"event_preview";
   `SPONSOR_POST`/"sponsor_post" → `SPONSOR_ACTIVATION`/"sponsor_activation")
   under CLAUDE.md's gated 15+15-step process. Route endpoint names
   (`stub_weekend_preview`, `stub_sponsor_post`) are implementation artifacts,
   not vocabulary, and are kept.
4. **Read-tolerant legacy aliases at every persistence boundary.**
   `post_types.canonical_slug()` maps the two legacy strings; the per-type
   policy store canonicalises keys on load *and* save (operator-set levels
   survive the rename); the stub-pack store canonicalises `stub_type` on load;
   the publish gate canonicalises incoming type strings. Fail direction is
   safe by construction (unknown → `approval_required`).
5. **Policy/UI scope stays the implemented set.** Settings → Autonomy keeps
   one row per implemented surface; planner-only slugs take their default
   autonomy from the sport profile YAML until a publishable surface exists —
   no "Coming soon" leakage.

## Deviation note (premise correction)

The Council deliberated on the premise that per-org policy JSON was the only
persisted carrier of the legacy strings. The pre-removal breakage check found
two more: saved stub packs (`stub_type`) and ~15 literal-string surfaces in
`web.py`/`stubs.py`/`humanise.py`. The verdict's direction held; the migration
grew pack-store load-time normalisation and the mechanical surface updates.
With zero paying customers at decision time, this was judged the cheapest
moment the rename will ever have.

## Consequences

- The P1.3 planner enumerates `SportProfile.post_types` slugs and bridges to
  implemented surfaces via `post_types.implemented_content_type()`.
- Adding a sport's post types is YAML-only; adding a *product surface* is the
  deliberate engineering act of adding an enum member + registry entry whose
  value is the canonical slug.
- Legacy aliases are a permanent but tiny, test-pinned shim (2 entries) at the
  read/write boundaries — the price of zero-downtime hosted data.
