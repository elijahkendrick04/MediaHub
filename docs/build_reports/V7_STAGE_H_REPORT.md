# Swim Content V7 — Stage H Report
**Generated**: 2026-05-05T18:30 BST  
**Status**: ALL STAGES COMPLETE ✓

---

## Bug Fixed (Stage H)

**Bug**: `TypeError: unhashable type: 'dict'` in `profiles_page()` voice tab  
**Root cause**: The Python heredoc injection produced `{{}}` literal in regular Python code (outside an f-string body), which Python parsed as an empty `dict` literal inside a set comprehension `{...}` — causing an "unhashable type" error when used as a `.get()` default.  
**Fix applied**: In `swim_content_v4/web.py` lines 2083–2084, changed:
```python
# BEFORE (broken)
defaults = {{}}
saved_tmpl = cur_templates.get(ct_key, {{}}).get(t_str, {{}})

# AFTER (fixed)
defaults = {}
saved_tmpl = cur_templates.get(ct_key, {}).get(t_str, {})
```
The two remaining `{{}}` occurrences in the file (lines 862 and 1553) are both inside f-string JavaScript blocks where `{{}}` correctly escapes to `{}` in the HTML output — those are untouched and correct.

---

## Smoke Test Results — All 6 Pass

### Test 1: Syntax + Imports
```
PASS: web.py syntax OK (AST parses cleanly)
PASS: import club_platform
PASS: import club_platform.content_types
PASS: import club_platform.meet_recap
PASS: import club_platform.athlete_spotlight
PASS: import club_platform.stubs
PASS: import brand
PASS: import brand.kit
PASS: import brand.tone
PASS: import brand.templates
PASS: import brand.store
PASS: import brand.apply
PASS: import workflow
PASS: import workflow.status
PASS: import workflow.store
PASS: import workflow.pack
```

### Test 2: Pipeline Regression
```
Profile loaded: Swansea University Swimming
  brand_kit: True (loaded from profile)
  tone: warm-club
  achievement_priorities: 17 keys including pb_confirmed, first_sub_barrier, etc.
Pipeline: 45 cards, 212 total claims
PASS: pipeline regression OK — no errors, correct card count
```

### Test 3: Web Smoke (Flask test client)
```
PASS: /                      -> 200
PASS: /make                  -> 200
PASS: /upload                -> 200
PASS: /profiles              -> 200
PASS: /weekend-preview       -> 200
PASS: /sponsor-post          -> 200
PASS: /session-update        -> 200
PASS: /spotlight             -> 200
PASS: /profiles?tab=identity -> 200
PASS: /profiles?tab=brand    -> 200
PASS: /profiles?tab=voice    -> 200  ← previously 500 (BUG FIXED)
PASS: /profiles?tab=priorities -> 200
```

### Test 4: Workflow Store
```
Empty workflow: 0 cards
set_status(APPROVED): OK
Sidecar at test_wf_run__workflow.json: OK
Main run JSON untouched: OK
Status cycling (APPROVED → EDITED → POSTED → QUEUE): OK
mark_all_posted: 2 cards APPROVED → POSTED, QUEUE cards unaffected: OK
Sidecar persists status as string value: OK
PASS: workflow store OK
```

### Test 5: Brand Application (3 tones, pb_confirmed card)
```
Card: Mathew Bradley, 100m Butterfly (LC), 57.95, prev_pb=59.35, drop=-1.40s, place=1

[warm-club] headline: Mathew goes 57.95 in the 100m Butterfly — a new PB!
[hype]      headline: Mathew Bradley GOES 57.95 IN THE 100m Butterfly — NEW PB!
[data-led]  headline: Mathew Bradley: 100m Butterfly — 57.95 (PB, −1.40s)
PASS: brand application OK — captions generated for all 3 tones
```

### Test 6: URL Hygiene
```
PASS: URL hygiene OK — app routes use url_for(), external links use target=_blank
No hardcoded href/action/fetch paths found pointing to app routes.
```

---

## Files Created (V7 NEW) — 1,274 lines total

| File | Lines | Description |
|------|-------|-------------|
| `club_platform/__init__.py` | 25 | Package init with exports |
| `club_platform/content_types.py` | 152 | ContentType enum, ContentTypeMeta dataclass, REGISTRY |
| `club_platform/meet_recap.py` | 34 | MeetRecapContentType |
| `club_platform/athlete_spotlight.py` | 164 | AthleteSpotlightContentType + build_spotlight_pack + list_swimmers_in_run |
| `club_platform/stubs.py` | 66 | WeekendPreviewStub, SponsorPostStub, SessionUpdateStub |
| `brand/__init__.py` | 26 | Package init with exports |
| `brand/kit.py` | 60 | BrandKit dataclass with default_swansea() factory |
| `brand/tone.py` | 44 | Tone enum (WARM_CLUB/HYPE/DATA_LED), TONE_META |
| `brand/templates.py` | 124 | CaptionTemplate, render_template, DEFAULTS, get_default_templates |
| `brand/store.py` | 114 | load_brand, save_brand functions |
| `brand/apply.py` | 132 | apply_brand function with context building |
| `workflow/__init__.py` | 18 | Package init |
| `workflow/status.py` | 54 | CardStatus enum (QUEUE/APPROVED/EDITED/POSTED/REJECTED), CardWorkflowState dataclass |
| `workflow/store.py` | 150 | WorkflowStore class with thread-safe load/save; sidecar pattern |
| `workflow/pack.py` | 111 | build_content_pack function |

## Files Modified

| File | Lines (now) | Key Changes |
|------|-------------|-------------|
| `swim_content_v4/web.py` | 2,738 | V7 imports, WorkflowStore init, Make nav, 9+ new routes, review() workflow pills + JS, profiles_page() 4-tab version |
| `swim_content_v4/club_profile.py` | 266 | V7 fields on ClubProfile: brand_kit, tone, caption_templates, achievement_priorities; get_achievement_priority/get_brand_kit/get_tone methods; _maybe_seed_v7_fields() |
| `swim_content_v5/ranker.py` | 277 | profile_priority factor (additive, weight=0, multiplicative multiplier) |
| `swim_content_v5/schema.py` | 280 | profile: Optional[object] field on MeetContext (not serialised) |
| `swim_content_v5/report.py` | 409 | ctx.profile = profile wiring |
| `club_profiles/swansea-uni.json` | 52 | Added brand_kit, tone, caption_templates, achievement_priorities |

---

## New Routes Summary

| Route | Method | Description |
|-------|--------|-------------|
| `/make` | GET | Platform home — content type selector with ready/coming-soon labels |
| `/spotlight` | GET | Swimmer picker for Athlete Spotlight |
| `/spotlight/<run_id>/<swimmer>` | GET | Build spotlight pack for one swimmer |
| `/weekend-preview` | GET | Stub — renders input_contract form |
| `/sponsor-post` | GET | Stub — renders input_contract form |
| `/session-update` | GET | Stub — renders input_contract form |
| `/pack/<run_id>` | GET | Content pack for a run |
| `/api/workflow/<run_id>/<card_id>` | POST | Update single card workflow status |
| `/api/workflow/<run_id>/mark-all-posted` | POST | Bulk mark approved cards as posted |
| `/api/profile/<id>/brand` | POST | Save brand kit settings |
| `/api/profile/<id>/voice` | POST | Save tone + caption template overrides |
| `/api/profile/<id>/priorities` | POST | Save achievement priority weights |

---

## Sample Workflow Sidecar JSON

**Path pattern**: `runs_v4/<run_id>__workflow.json`  
**Rule**: Never modifies the main `runs_v4/<run_id>.json`

```json
{
  "card_pb_mathew_100fly": {
    "status": "approved",
    "edited_captions": null,
    "notes": null,
    "posted_at": null,
    "last_changed_at": "2026-05-05T17:42:11+00:00"
  },
  "card_pb_emma_200free": {
    "status": "posted",
    "edited_captions": {
      "warm-club": "Emma smashes 200m Free PB at Swansea May LC!"
    },
    "notes": "Edited headline for social",
    "posted_at": "2026-05-05T18:00:00+00:00",
    "last_changed_at": "2026-05-05T18:00:00+00:00"
  },
  "card_medal_gold_relay": {
    "status": "queue",
    "edited_captions": null,
    "notes": null,
    "posted_at": null,
    "last_changed_at": "2026-05-05T17:35:00+00:00"
  },
  "card_first_sub_60_james": {
    "status": "edited",
    "edited_captions": {
      "hype": "James BREAKS THE 60 SECOND BARRIER in 100m Breast!"
    },
    "notes": "Changed to hype tone for this milestone",
    "posted_at": null,
    "last_changed_at": "2026-05-05T17:55:00+00:00"
  }
}
```

---

## Sample Brand Captions (3 tones)

**Card**: Mathew Bradley, 100m Butterfly (LC), 57.95s (-1.40s PB, gold)  
**Profile**: Swansea University Swimming

### warm-club
- **headline**: Mathew goes 57.95 in the 100m Butterfly — a new PB!
- **body**: Mathew dropped 1.40s in the 100m Butterfly at Swansea May LC 2026. Previous best was 59.35. Great swim!

### hype
- **headline**: Mathew Bradley GOES 57.95 IN THE 100m Butterfly — NEW PB!
- **body**: Mathew Bradley smashes a 1.40s PB in the 100m Butterfly. Previous best: 59.35. Swansea May LC 2026.

### data-led
- **headline**: Mathew Bradley: 100m Butterfly — 57.95 (PB, −1.40s)
- **body**: Mathew Bradley recorded 57.95 in the 100m Butterfly at Swansea May LC 2026. Previous personal best: 59.35 (−1.40s improvement).

---

## Achievement Priorities (swansea-uni.json defaults)

| Type | Priority |
|------|---------|
| pb_confirmed | 1.5 |
| first_sub_barrier | 1.3 |
| biggest_drop_of_meet | 1.3 |
| multi_pb_weekend | 1.2 |
| return_to_form | 1.1 |
| medal_gold | 1.0 |
| fastest_since_date | 1.0 |
| _default | 1.0 |
| pb_likely | 1.0 |
| medal_silver | 0.8 |
| qualifying_time | 0.7 |
| qual_hit_in_window | 0.7 |
| top_of_field_top_3 | 0.7 |
| medal_bronze | 0.6 |
| top_of_field_top_5 | 0.6 |
| qual_hit_out_of_window | 0.5 |
| top_of_field_top_10 | 0.5 |

**Ranker factor entry** (one per achievement):
```json
{
  "factor": "profile_priority",
  "weight": 0,
  "value": 1.5,
  "reason": "profile priority multiplier (pb_confirmed: 1.50)"
}
```
The factor is **additive** (appended to factors list, weight=0 means it doesn't contribute to the weighted sum directly) and applied **multiplicatively** as a final post-sum multiplier — existing priority calculations are fully preserved.

---

## Key Architecture Decisions

1. **`club_platform` not `platform`** — avoids shadowing Python stdlib `platform` module
2. **Workflow sidecar files** — `runs_v4/<run_id>__workflow.json` never touches the main run JSON
3. **Profile priority factor** — weight=0 (transparent, recorded for audit), applied as multiplicative multiplier after base weighted sum; fully additive/non-breaking to V5 ranker
4. **MeetContext.profile** — added as `Optional[object]` field, excluded from `to_dict()` serialisation
5. **`profiles_page()` POST routing** — Identity tab POSTs to `/profiles`; Brand/Voice/Priorities tab APIs POST to `/api/profile/<id>/<tab>` with JSON responses
6. **Workflow JS** — status pill cycling via click event delegation; `fetch()` to `/api/workflow/<run_id>/<card_id>`; no page reload needed
7. **`_h()` wrapping** — all user/file-derived strings HTML-escaped before interpolation
8. **Stub routes** — render real HTML with `input_contract` displayed; not 501 pages
9. **`/make` honesty** — only Meet Recap and Athlete Spotlight have "ready" badges; others show "coming soon" plainly

---

## Completion Status

| Stage | Status |
|-------|--------|
| A: club_platform/, brand/, workflow/ packages | ✓ DONE |
| B: ClubProfile V7 fields + swansea-uni.json | ✓ DONE |
| C: V5 ranker profile_priority factor | ✓ DONE |
| D: web.py new routes | ✓ DONE |
| E: review() workflow pills + summary | ✓ DONE |
| F: profiles_page() 4-tab version | ✓ DONE |
| G: Nav Make entry | ✓ DONE |
| H: Smoke tests (6/6 pass) + bug fix | ✓ DONE |

**All 8 stages complete. Ready for parent agent to redeploy.**
