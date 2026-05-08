# V7 Build Specification — Platform Shape + Workflow Depth

**Strategic frame:** the long-term product is a club content automation platform; swimming results is the wedge. V7 makes the platform shape visible AND deepens the wedge so a real social-media-volunteer can use it end to end.

**Scope:** strictly two surfaces — platform shape (mostly UI scaffolding) and wedge depth (real workflow). No new sports, no image generation, no LLM rewriting, no auth, no billing, no new file formats.

## Locked decisions

1. **Stubs:** honest "coming soon" pages with input contracts.
2. **Captions:** tone selector + 3 template slots per content type, editable from the profile page.
3. **Workflow:** full per-card status (queue/approved/rejected/posted) + edit-in-place captions.

## Architecture

Three new top-level packages. Each is small and focused.

```
swim_content_v4/                       (existing — minor wiring changes)
swim_content_v5/                       (existing — small ranker hook)
swim_content_pb/                       (existing — untouched)

platform/                              (NEW)
├── __init__.py
├── content_types.py                   ContentType enum, ContentTypeMeta dataclass, REGISTRY
├── meet_recap.py                      MeetRecapContentType (concrete, references existing pipeline)
├── athlete_spotlight.py               AthleteSpotlightContentType (concrete, single-swimmer filter on V5 report)
└── stubs.py                           WeekendPreviewStub, SponsorPostStub, SessionUpdateStub (placeholder ContentType subclasses with input_contract documentation)

brand/                                 (NEW)
├── __init__.py
├── kit.py                             BrandKit dataclass: name, primary_colour, secondary_colour, logo_path, governing_body
├── tone.py                            Tone enum: WARM_CLUB, HYPE, DATA_LED; Tone.label, Tone.description
├── templates.py                       CaptionTemplate dataclass with {placeholder} support; render_template(template_str, context)
├── store.py                           load_brand(profile_id), save_brand(profile_id, kit, tone, templates_dict)
└── apply.py                           apply_brand(card, kit, tone, content_type) → card with rendered captions

workflow/                              (NEW)
├── __init__.py
├── status.py                          CardStatus enum: QUEUE, APPROVED, REJECTED, POSTED, EDITED
├── store.py                           WorkflowStore: get_status(run_id, card_id), set_status(...), set_edits(...)
│                                      persisted to runs_v4/<run_id>__workflow.json
└── pack.py                            build_content_pack(run_id, profile_id) → ordered list of approved cards
```

## File-by-file specification

### `platform/content_types.py`

```python
class ContentType(str, Enum):
    MEET_RECAP = "meet_recap"
    ATHLETE_SPOTLIGHT = "athlete_spotlight"
    WEEKEND_PREVIEW = "weekend_preview"
    SPONSOR_POST = "sponsor_post"
    SESSION_UPDATE = "session_update"

@dataclass
class ContentTypeMeta:
    type: ContentType
    title: str                      # "Meet Recap"
    description: str                # short — what it produces
    input_contract: str             # what input is required (long-form)
    is_implemented: bool            # if False, route renders a stub page
    icon_svg: str                   # tiny inline SVG for navigation cards
    primary_route_endpoint: str     # url_for endpoint, e.g. 'upload' or 'spotlight_landing'

REGISTRY: dict[ContentType, ContentTypeMeta] = {
    ContentType.MEET_RECAP: ContentTypeMeta(
        type=ContentType.MEET_RECAP,
        title="Meet Recap",
        description="Turn a meet results file into ranked, source-grounded content cards.",
        input_contract="Upload a Hytek Meet Manager file (.hy3) or a zip containing one. Optional: pre-meet PB snapshot will be fetched from swimmingresults.org for accurate PB claims.",
        is_implemented=True,
        icon_svg='<svg viewBox="0 0 24 24" ...>',  # waves
        primary_route_endpoint='upload',
    ),
    ContentType.ATHLETE_SPOTLIGHT: ContentTypeMeta(...,
        title="Athlete Spotlight",
        description="One swimmer's story from the meet — every achievement, ranked.",
        input_contract="Pick a swimmer from any processed meet. We'll generate a single-athlete recognition view.",
        is_implemented=True,
        primary_route_endpoint='spotlight_landing',
    ),
    ContentType.WEEKEND_PREVIEW: ContentTypeMeta(...,
        is_implemented=False,
        input_contract="Upload an upcoming meet entry list or paste an entry block. We'll surface athletes to watch and angles to tease.",
    ),
    # SPONSOR_POST and SESSION_UPDATE similar
}
```

### `platform/athlete_spotlight.py`

Single-swimmer view: takes a `run_id` + `swimmer_asa_id` (or canonical key), filters the V5 RecognitionReport's achievements to that swimmer only, re-ranks within that scope, returns a "spotlight pack" — the same data shape as the meet recap but scoped.

This is **not** a new pipeline. It's a filter + re-rank pass over existing recognition data. ~80 lines.

### `brand/kit.py`

```python
@dataclass
class BrandKit:
    profile_id: str
    display_name: str
    primary_colour: str             # "#A30D2D" (Swansea red)
    secondary_colour: str           # "#000000"
    accent_colour: str | None
    logo_svg: str | None            # inline SVG (uploaded or pasted)
    governing_body: str | None
    short_name: str | None
    
    @classmethod
    def default_swansea(cls) -> "BrandKit":
        return cls(
            profile_id="swansea-uni",
            display_name="Swansea University Swimming",
            primary_colour="#A30D2D",
            secondary_colour="#000000",
            accent_colour=None,
            logo_svg=None,
            governing_body="Swim England",
            short_name="Swansea Uni",
        )
```

### `brand/tone.py`

```python
class Tone(str, Enum):
    WARM_CLUB = "warm-club"     # default; conversational, member-facing
    HYPE = "hype"                # energetic, exclamation-friendly, race-day
    DATA_LED = "data-led"        # numbers-first, formal, sponsor-friendly

TONE_META = {
    Tone.WARM_CLUB: {
        "label": "Warm club",
        "description": "Conversational and member-facing. Defaults to first-name use.",
        "example": "Mathew dropped 1.4s on his 100 fly — biggest improvement of the weekend.",
    },
    Tone.HYPE: {
        "label": "Hype",
        "description": "Energetic, race-day language, full names with 'goes sub-X' framing.",
        "example": "MATHEW BRADLEY GOES SUB-58 ON 100 FLY — first time under the barrier.",
    },
    Tone.DATA_LED: {
        "label": "Data-led",
        "description": "Numbers first, formal, sponsor-friendly, lower exclamation density.",
        "example": "Mathew Bradley: 100m Butterfly LC — 57.95 (PB, −1.4s). New club record.",
    },
}
```

### `brand/templates.py`

A `CaptionTemplate` is a string with `{placeholder}` variables that get filled from the achievement context. Three template slots per (content_type × tone): `headline`, `body`, `cta`.

```python
@dataclass
class CaptionTemplate:
    slot: str                       # 'headline' | 'body' | 'cta'
    template: str
    
    def render(self, ctx: dict) -> str:
        # Safe templating — never raises on missing keys, returns "—" instead.
        # Supports {swimmer}, {swimmer_short}, {event}, {course}, {time},
        # {prev_pb}, {drop_seconds}, {drop_pretty}, {place}, {medal}, {meet}, etc.
```

Templates are stored per profile + content_type + tone. Defaults are seeded for Swansea. The profile editor lets the user override any of them.

### `workflow/status.py` + `workflow/store.py`

```python
class CardStatus(str, Enum):
    QUEUE = "queue"
    APPROVED = "approved"
    REJECTED = "rejected"
    POSTED = "posted"
    EDITED = "edited"               # has user edits but not yet approved

@dataclass
class CardWorkflowState:
    card_id: str
    status: CardStatus
    edited_captions: dict[str, str] | None   # tone_slot → user override
    notes: str | None
    posted_at: str | None
    last_changed_at: str

class WorkflowStore:
    def __init__(self, runs_dir: Path):
        self.runs_dir = runs_dir
    
    def _path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}__workflow.json"
    
    def load(self, run_id: str) -> dict[str, CardWorkflowState]:
        ...
    
    def set_status(self, run_id: str, card_id: str, status: CardStatus, **kwargs) -> None:
        ...
    
    def set_edits(self, run_id: str, card_id: str, edits: dict) -> None:
        ...
    
    def summary(self, run_id: str) -> dict:
        # {"queue": 12, "approved": 5, "rejected": 2, "posted": 1, "total": 20}
        ...
```

### Per-profile achievement priorities feeding the ranker

`club_profiles/<profile_id>.json` gains an optional `achievement_priorities` block:

```json
{
  "profile_id": "swansea-uni",
  "display_name": "Swansea University Swimming",
  ...
  "achievement_priorities": {
    "pb_confirmed": 1.5,
    "first_sub_barrier": 1.3,
    "biggest_drop_of_meet": 1.3,
    "medal_gold": 1.0,
    "medal_silver": 0.8,
    "medal_bronze": 0.6,
    "qualifying_time": 0.7,
    "top_of_field": 0.7,
    "fastest_since_date": 1.0,
    "multi_pb_weekend": 1.2,
    "return_to_form": 1.1,
    "_default": 1.0
  }
}
```

The V5 ranker's priority calculation gets a new factor: `profile_priority_factor = priorities.get(achievement.type, priorities.get("_default", 1.0))`. Add it to the `factors` list with reason "Club priority for {type} = {value}". This means Swansea can dial down qualifying-time emphasis if they don't post about quals, and dial up first-sub-barrier if those land best on their feed.

The default Swansea priorities are seeded with values above. Other profiles get all-1.0 unless they edit.

### Editing UI (Profiles page)

The existing `/profiles` page is currently a CRUD form for the basic fields. V7 expands it to tabs:

- **Identity** (existing: short_name, codes, governing body)
- **Brand kit** (new: colours, logo SVG paste, accent colour)
- **Voice** (new: tone selector + 3 template slots per content type with live preview)
- **Priorities** (new: slider/number per achievement type, with explanation)

Each tab is a separate POST endpoint so partial saves don't lose data on other tabs.

### Approval workflow UI

On `/review/<run_id>` (the recognition page), every card row gets:

- **Status pill** (queue/approved/rejected/posted/edited) — clickable to cycle
- **Inline edit button** — opens a modal-or-collapsible with the current rendered caption (3 tones), edit field for each, save button
- **Mark posted** — moves to "posted" with timestamp

A new top-of-page filter: **Show: All / Queue / Approved / Posted**.

A small **Workflow summary** card next to "Recognition summary": "12 in queue, 5 approved, 1 posted".

### Content Pack page

New route `/pack/<run_id>` shows only `approved` cards in posting order (priority desc), with:

- The rendered caption in the profile's selected tone
- A copy-to-clipboard button per caption
- A "scheduled for" hint (free-text field — not a real scheduler, just a label)
- A "mark all posted" bulk action
- A printable layout (CSS print stylesheet) for handing off as a doc
- Header carries the brand kit (logo + colours)

### Navigation: content type chooser

New top-level route `/make` (or rename Home to `/make`). Card grid:

```
What do you want to make?

[Meet Recap]            [Athlete Spotlight]      [Weekend Preview]
ready                   ready                    coming soon
Upload a meet results   Pick a swimmer from a    Upload an upcoming meet
file. Get ranked        processed meet. Get a    entry list. Get athletes
content cards.          single-athlete content   to watch and angles to
                        pack.                    tease.

[Sponsor Post]          [Session Update]         
coming soon             coming soon               
...                     ...                      
```

Each tile links to the content type's `primary_route_endpoint`. Stubs render a clean page with: title, description, input_contract, "we'll add this when [X dependency] is in place", and a back link.

The existing `/upload` route remains, just becomes one of several entry points. The Home page (today shows "recent runs" + upload CTA) stays as the recent-runs landing.

## Files to modify

- `swim_content_v4/web.py` — add 9 new routes:
  - `/make` (content-type chooser)
  - `/spotlight` (landing — pick a meet, then pick a swimmer)
  - `/spotlight/<run_id>/<swimmer_key>` (the spotlight view)
  - `/weekend-preview`, `/sponsor-post`, `/session-update` (stub pages)
  - `/pack/<run_id>` (content pack)
  - `/api/workflow/<run_id>/<card_id>` (POST: set status / edits)
  - `/api/profile/<profile_id>/brand` (POST: save brand kit)
  - `/api/profile/<profile_id>/voice` (POST: save tone + templates)
  - `/api/profile/<profile_id>/priorities` (POST: save priorities)
  
  Plus modify `review()` to render status pills + filters, and `profiles_page()` to render the new tabs.

- `swim_content_v5/ranker.py` — add `profile_priority_factor` to the factors list. Read priorities from the profile object (already passed in via `ctx`).

- `swim_content_v4/canonical.py` — `Profile` dataclass already has a `branding` dict; add `brand_kit` (BrandKit), `tone` (Tone), `caption_templates` (dict), `achievement_priorities` (dict) as optional fields.

- `swim_content_v4/club_profile.py` — extend the profile JSON loader to read the new fields with sensible defaults.

- `club_profiles/swansea-uni.json` — seed the new fields with sensible Swansea defaults.

## What NOT to change

- The pipeline (run_pipeline_v4). All V7 changes are pre-pipeline (profile config) or post-pipeline (workflow + presentation).
- The PB subsystem (`swim_content_pb/`).
- The recognition engine (`swim_content_v5/`) except the one ranker hook.
- Existing run JSON schema. Workflow state lives in a sidecar file.

## Test plan

```bash
cd /home/user/workspace/swim-content

# 1. Syntax + imports
python3 -c "
import ast, glob
for f in sorted(glob.glob('platform/**/*.py', recursive=True) + glob.glob('brand/**/*.py', recursive=True) + glob.glob('workflow/**/*.py', recursive=True)):
    ast.parse(open(f).read())
print('syntax OK')
import platform_pkg as platform_  # if 'platform' shadows stdlib, will need rename
"

# IMPORTANT: 'platform' shadows the Python stdlib 'platform' module.
# Use 'club_platform' as the package name instead. Update spec accordingly.

# 2. Pipeline regression
python3 -c "
from pathlib import Path
from swim_content_v4.pipeline_v4 import run_pipeline_v4
zp = Path('/home/user/workspace/Meet-Results-Swansea-Aquatics-May-Long-Course-2026-02May2026-001.zip')
run = run_pipeline_v4(file_bytes=zp.read_bytes(), filename=zp.name, profile_id='swansea-uni',
                     fetch_pbs=True, use_pb_cache=True, run_id='v7_check')
print('cards:', len(run.cards))
audit = getattr(run, 'pb_audit', None)
print('verified:', audit.swimmers_matched_verified if audit else 'no audit')
rep = getattr(run, 'recognition_report', None)
print('elite/strong/story:', rep.get('n_elite'), '/', rep.get('n_strong'), '/', rep.get('n_story'))
"

# 3. Web smoke
python3 -c "
from swim_content_v4.web import create_app
app = create_app()
c = app.test_client()
for path in ['/', '/make', '/upload', '/profiles', '/weekend-preview', '/sponsor-post', '/session-update', '/spotlight']:
    r = c.get(path)
    print(f'{path:25s} -> {r.status_code}')
"

# 4. Workflow store smoke
python3 -c "
from pathlib import Path
from workflow.store import WorkflowStore
from workflow.status import CardStatus
ws = WorkflowStore(Path('runs_v4'))
ws.set_status('test_run', 'card_1', CardStatus.APPROVED)
state = ws.load('test_run')
assert 'card_1' in state
assert state['card_1'].status == CardStatus.APPROVED
print('workflow store OK')
import os; os.unlink('runs_v4/test_run__workflow.json')
"

# 5. Brand application smoke
python3 -c "
from brand.kit import BrandKit
from brand.tone import Tone
from brand.apply import apply_brand
kit = BrandKit.default_swansea()
print('brand kit:', kit.display_name, kit.primary_colour)
"

# 6. URL hygiene
grep -nE 'href=\"/[a-z]|action=\"/[a-z]' swim_content_v4/web.py | grep -v '^\s*#' | head
```

## IMPORTANT: package naming

`platform` is a Python stdlib module. Using it as a package name shadows the stdlib. Use `club_platform` instead. Update all imports accordingly.

## Definition of done

1. All test plan steps pass.
2. The Swansea zip uploaded fresh produces 45 cards, 36 verified swimmers, 261 V5 achievements (the same as V6).
3. The `/make` page renders 5 content type tiles (2 ready, 3 coming soon).
4. Clicking a "coming soon" tile renders the input contract page, no errors.
5. Clicking a card status pill on the recognition page persists the change and shows it on reload.
6. Editing a caption inline persists per-card overrides.
7. The `/pack/<run_id>` page shows only approved cards.
8. The `/profiles` page shows 4 tabs: Identity, Brand kit, Voice, Priorities.
9. Saving achievement priorities for Swansea changes the V5 ranking on the next upload (verifiable by changing pb_confirmed weight from 1.5 to 0.1 and seeing PB cards drop in rank).
10. No regression in URL hygiene, no console errors in the browser walkthrough.

Build it.
