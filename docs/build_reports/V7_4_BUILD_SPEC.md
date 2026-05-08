# V7.4 Build Specification — Foundation: Generic, Multi-Club, Multi-Tone

**Strategic frame:** the user wants to validate that the system works for ANY UK swimming club, not just Swansea. To do that we need: a SPORTSYSTEMS PDF adapter (the actual format most UK club meets publish in), the system to be honestly de-Swansea-fied, a multi-tone caption picker, all developer/code references hidden from the UI, and live web research that actually works in the published sandbox.

**Validation target:** upload `sample_data/MISM-2024-Results.pdf` (Arena Manchester International Meet 2024, SPORTSYSTEMS format), with a "City of Manchester Aquatics" club profile, and produce a working content pack with detected achievements, ranked cards, multi-tone captions, audit, etc. Without any Swansea hardcoding visible.

## Locked decisions

1. Build PDF adapter for SPORTSYSTEMS format. PDFs are the most common UK results format.
2. De-Swansea: when no profiles exist, show a friendly "Create your first club profile" wizard. Don't auto-seed Swansea.
3. Multi-tone picker: every card shows three pre-rendered tone variants (warm-club / hype / data-led); user clicks the tone they want, that becomes the active one. No retyping.
4. Hide code: rename internal references like `swansea-uni`, `Co Manch Aq`, `swim_content_v4`, etc. wherever they appear in user-visible text. Replace with friendly labels.
5. Live web research: use the `pplx` CLI via subprocess. The published sandbox doesn't have it, so we ALSO need a fallback path. The fallback: when the user uploads a meet, the app extracts the meet name + venue, and uses the HTTP `urllib` + a free public search to find context. Acceptance: research works in the published sandbox OR the failure is clearly handled with no broken UI.
6. Existing Swansea-uni profile stays in the codebase (so old runs continue to load) but is no longer auto-seeded as default.

## Files to create

### `engine_v4/adapters/sportsystems_pdf.py` (NEW — major)

A SPORTSYSTEMS PDF parser. Inputs a PDF file (extracted via `pdftotext -layout`); outputs a `SportEvent`/`SwimMeet` canonical object compatible with the rest of the pipeline.

Format characteristics:
- Header line: `ARENA Manchester International Meet 2024` (meet name)
- Session line: `Results - Session 1 (1NW240474)`
- Event line: `EVENT 101 Female 200m IM` (event number, gender, distance, stroke)
- Age group sub-headers: `16 Yrs/Under Age Group - Full Results`, `17 Yrs/Over Age Group - Full Results`
- Result rows: `Place. Name AaD Club Time WA-Pts splits...`
  - Example: `1. Amelie Blocksidge 15 Co Salford 2:23.14 684 31.60 1:09.47 1:51.10`
- DNC/DQ rows: `Anna Fenwick 16 Satellite DQ 1` or `Aoife Doran 18 Swim_Ireland DNC`
- Final events: `EVENT 430 FINAL OF EVENT 311 Open/Male 17 /Over 100m Freestyle`

Implementation:

```python
class SportSystemsPDFAdapter:
    """Parses a SPORTSYSTEMS-style PDF (the format used by most UK club meets
    via the SPORTSYSTEMS Live Results service)."""
    
    def parse(self, pdf_bytes: bytes) -> SwimMeet:
        # 1. Extract text via pdftotext -layout (subprocess) or pure-python fallback
        # 2. Walk lines, tracking state: meet_name → session → event → age_group → results
        # 3. Each result row creates a RaceResult (canonical type)
        # 4. Each unique (name, club) creates a Swimmer (without ASA ID)
        # 5. Return SwimMeet with all events populated
```

**Key implementation details:**
- Use `pdftotext -layout <input> -` via subprocess (already installed, see prior bash output). Time out at 30s.
- If pdftotext fails, try pdfminer.six if available, else raise a clean error.
- Parse event headers using regex: `r'EVENT\s+(\d+)\s+(Female|Male|Open/Male|Open/Female|Mixed)\s+(\d+)m\s+([A-Za-z ]+)'`
- Parse age groups: `r'(\d+\s*Yrs?/(?:Under|Over)|Open)\s+Age Group'`
- Parse result rows: `r'^\s*(\d+)\.\s+(.+?)\s+(\d+)\s+([A-Z][\w\s]*?)\s+([\d:.]+)\s+(\d+)?'` — but allow flexibility because clubs can have spaces.
- Map club abbreviations to canonical (a small dictionary `CLUB_ALIASES`): `Co Manch Aq` → `City of Manchester Aquatics`, `Co Salford` → `City of Salford`, etc. If not found, accept as-is.
- Distinguish heat from final: presence of "FINAL OF EVENT" header.
- Handle relays: events labelled "Mixed/Open 4x100m Freestyle Relay" etc.; relay row format different.

### `engine_v4/adapters/__init__.py` (NEW)

Adapter registry:

```python
ADAPTERS = {
    "hy3": HY3Adapter,        # existing
    "sportsystems_pdf": SportSystemsPDFAdapter,   # NEW
}

def detect_adapter(file_bytes: bytes, filename: str) -> str:
    """Inspect file bytes and filename to pick the right adapter."""
    if filename.lower().endswith(".hy3"):
        return "hy3"
    if filename.lower().endswith(".pdf"):
        return "sportsystems_pdf"
    if filename.lower().endswith(".zip"):
        # Look inside the zip
        ...
    return None
```

The pipeline (`engine_v4/pipeline_v4.py` or `swim_content_v4/pipeline_v4.py`) should call `detect_adapter` and dispatch.

### `voice/multi_tone_renderer.py` (NEW)

Pre-renders all three tones for every achievement so users can pick instantly:

```python
def render_all_tones(achievement, profile, content_type) -> dict[str, dict[str, str]]:
    """Returns {
      'warm-club': {'headline': '...', 'body': '...', 'cta': '...'},
      'hype':      {'headline': '...', 'body': '...', 'cta': '...'},
      'data-led':  {'headline': '...', 'body': '...', 'cta': '...'},
    }
    """
```

Plug into `brand/apply.py` so all three tones are computed at build time, not just the active one.

### `web_research/__init__.py` + `web_research/search.py` (NEW)

A simple web-research module that works in the published sandbox.

Strategy:
- Try `pplx search web` via subprocess first (works in dev sandbox)
- Fall back to a stdlib HTTP search (DuckDuckGo HTML or Bing scrape — both ToS-acceptable for low-volume metadata lookup)
- Cache results to `.cache/research/<key>.json` for 7 days
- Used by the meet-context builder

```python
class WebResearcher:
    def search(self, query: str, num: int = 5) -> list[SearchResult]:
        # Try pplx first, fall back to DuckDuckGo HTML
        ...
    
    def fetch_url(self, url: str) -> str | None:
        # urllib.request with sane headers and timeout
        ...

@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str
    source: str  # "pplx" | "duckduckgo"
```

The DuckDuckGo HTML endpoint: `https://html.duckduckgo.com/html/?q=<query>` returns plain HTML that can be parsed for results. **Cache aggressively** — once a meet's context is fetched, reuse for 30 days.

Wire this into `recognition/research.py` so meet-context fetching now works even without `pplx`.

## Files to modify

### `swim_content_v4/club_profile.py`

Change `_seed_swansea_profile()` to NOT run automatically. Instead:
- The profile system has zero seeded profiles by default.
- A new function `seed_demo_profile_if_empty()` is called by an explicit user action ("Try the demo with Swansea Uni" button on the empty-state).
- Existing `swansea-uni.json` files continue to load for backward compatibility.

```python
# OLD:
# At app startup, _seed_swansea_profile() runs.
# NEW:
# Profiles list can be empty. Empty state shows "Create your first club profile" UI.
```

### `swim_content_v4/web.py` — many changes

1. **First-launch UX**: when `list_profiles()` returns empty, the home page shows:
   ```
   Welcome to MediaHub.
   To get started, create your first club profile.
   [Create club profile]   [Try the Swansea demo]
   ```
   The "Try the demo" button calls `seed_demo_profile_if_empty()` and then proceeds normally.

2. **Profile creation flow** — improved profile create form. Make it work properly for any club (City of Manchester Aquatics, Bath, Loughborough, etc.). Required fields: display name, primary colour, governing body. All other fields optional. Auto-suggest sensible defaults. After save, redirect back to home.

3. **Multi-tone caption picker on every card** — replace the single-tone display with a tabbed picker:
   ```
   ┌──────────────────────────────────────────────┐
   │ Caption  [Warm club ●]  [Hype ○]  [Data-led ○] │
   ├──────────────────────────────────────────────┤
   │ Mathew goes 1:00.42 in the 100m Breaststroke │
   │ — a new PB!                                  │
   │ Mathew dropped 1.30s in the 100m Breaststroke│
   │ at Manchester International. Previous best   │
   │ was 1:01.72. Great swim!                     │
   ├──────────────────────────────────────────────┤
   │ [Copy caption]  [Copy + hashtags]  [Edit]    │
   └──────────────────────────────────────────────┘
   ```
   When the user clicks a tone tab, the visible caption swaps instantly (data already pre-rendered into hidden divs). The selected tone is the one used for copy. Implementation: each card has 3 hidden caption blocks (`data-tone="warm-club"`, etc.), JS toggles `display: none` on the others.

4. **Hide developer/code references from end-user UI:**
   - Replace any visible `swansea-uni` slug with the display name from the profile.
   - Hide `pb_confirmed`, `medal_gold`, `multi_pb_weekend`, etc. on cards — these should be human-readable: "Confirmed PB", "Gold medal", "Multi-PB weekend". Build a `format_post_angle(angle)` helper.
   - Hide `asa_id_verified`, `needs_verification`, `pb_unverified` etc. — convert to friendly labels: "Verified", "Needs check", "PB not verified".
   - Don't show `engine_v4`, `recognition_swim`, `swim_content_v5` anywhere visible.
   - Hide the "swansea-uni" run JSON's `profile_id` slug behind the display name.

5. **Live web research integration**: when a meet is uploaded, the recognition page's "Sources used" panel actually shows web sources (when found). Already wired to call `recognition/research.py` — just needs the new `web_research/` backend.

6. **First-class City of Manchester profile** — but seeded by the user, not auto. Add a simple "Quick start: COMA" button on the empty state in addition to "Try the Swansea demo". Each adds the named profile and proceeds. Both are optional; user can always create from scratch.

### Tests to add

```python
# tests/test_sportsystems_adapter.py
def test_parses_mism_2024_real_pdf():
    adapter = SportSystemsPDFAdapter()
    with open("sample_data/MISM-2024-Results.pdf", "rb") as f:
        meet = adapter.parse(f.read())
    assert meet.name.startswith("ARENA Manchester International")
    assert meet.sport == "swimming"
    # Should find at least 30 events
    assert len(meet.races) >= 30
    # Should find many swimmers
    assert len(meet.swimmers) >= 200
    # Co Manch Aq should be present
    coma_swimmers = [s for s in meet.swimmers.values() if 'Manch' in (s.club_name or '')]
    assert len(coma_swimmers) >= 5

def test_de_swansea_first_launch():
    """No profiles → home page shows create-profile wizard, not Swansea data."""
    # Wipe profiles dir
    # Hit /
    # Body should contain 'Create your first club profile' and NOT 'Swansea' (other than in the demo button)

def test_multi_tone_picker_renders_three_tones():
    """Each card has 3 caption blocks pre-rendered."""
    # Process Manchester PDF → recognition → render
    # On /review/<id>, expect data-tone="warm-club", data-tone="hype", data-tone="data-led"
```

## Definition of done

1. `sample_data/MISM-2024-Results.pdf` parses end-to-end with no errors.
2. The parsed `SwimMeet` has ≥30 events and ≥200 swimmers.
3. A "City of Manchester Aquatics" profile can be created via the UI (no shell access required).
4. Uploading the PDF with that profile produces:
   - A recognition report (some achievements detected for COMA swimmers)
   - A grouped content pack (some items in main_feed, etc.)
   - Multi-tone captions (3 tones available per card)
5. Empty-state home page shows a clean "Create your first club profile" panel with "Try the Swansea demo" + "Quick start: City of Manchester" + "Create from scratch" actions. NO Swansea data shown until user picks demo.
6. No user-visible text contains: `swansea-uni` (slug), `swim_content_v4`, `engine_v4`, `pb_confirmed`, `medal_gold`, raw type strings. All must be friendly labels.
7. Multi-tone picker on every card; clicking a tone tab swaps the visible caption instantly; copy buttons use the selected tone.
8. Live web research returns real results in the published sandbox (DuckDuckGo HTML fallback) OR fails cleanly with no UI breakage.
9. The existing Swansea zip pipeline still works (backward compatibility).
10. All previous test suites pass.

## Constraints

- DO NOT delete swansea-uni.json — back-compat.
- DO NOT remove the legacy `swim_content/` v3 package.
- Stdlib only for new modules where possible. `pdftotext` is allowed via subprocess (already installed in the sandbox).
- Every visible string must be friendly; tooltip with the raw type string is fine for the technical user.
- Don't break existing url_for endpoint names.

## Test plan

```bash
cd /home/user/workspace/swim-content

# 1. PDF adapter unit test
python3 -c "
from engine_v4.adapters.sportsystems_pdf import SportSystemsPDFAdapter
import os
data = open('sample_data/MISM-2024-Results.pdf', 'rb').read()
meet = SportSystemsPDFAdapter().parse(data)
print('meet name:', meet.name)
print('events:', len(meet.races))
print('swimmers:', len(meet.swimmers))
coma = [s for s in meet.swimmers.values() if 'Manch' in (getattr(s, 'club_name', '') or '')]
print('COMA swimmers:', len(coma))
"

# 2. Pipeline runs Manchester PDF end-to-end
python3 -c "
from pathlib import Path
from swim_content_v4.pipeline_v4 import run_pipeline_v4
data = Path('sample_data/MISM-2024-Results.pdf').read_bytes()
# First create COMA profile
from swim_content_v4.club_profile import save_profile
from swim_content_v4.canonical import Profile
save_profile(Profile(profile_id='coma', display_name='City of Manchester Aquatics', short_name='COMA', our_codes=['Co Manch Aq', 'COMA']))
run = run_pipeline_v4(file_bytes=data, filename='MISM-2024-Results.pdf', profile_id='coma', fetch_pbs=False, run_id='manc_test')
print('cards:', len(run.cards))
print('report:', getattr(run, 'recognition_report', {}).get('n_elite'), '/', getattr(run, 'recognition_report', {}).get('n_strong'))
"

# 3. De-Swansea verification
python3 -c "
import shutil, os
# Move profiles aside
if os.path.exists('club_profiles'): shutil.move('club_profiles', '/tmp/profiles_backup')
os.makedirs('club_profiles')
from swim_content_v4.web import create_app
c = create_app().test_client()
r = c.get('/')
body = r.get_data(as_text=True)
print('home status:', r.status_code)
print('has Create your first:', 'Create your first' in body)
print('Restore profiles')
shutil.rmtree('club_profiles')
shutil.move('/tmp/profiles_backup', 'club_profiles')
"

# 4. Multi-tone picker rendering
python3 -c "
from swim_content_v4.web import create_app
c = create_app().test_client()
# Hit a known existing run
import os
runs = [f for f in os.listdir('runs_v4') if f.endswith('.json')]
if runs:
    rid = runs[0].replace('.json','')
    r = c.get(f'/review/{rid}')
    body = r.get_data(as_text=True)
    print('has data-tone=warm-club:', 'data-tone=\"warm-club\"' in body)
    print('has data-tone=hype:', 'data-tone=\"hype\"' in body)
    print('has data-tone=data-led:', 'data-tone=\"data-led\"' in body)
"

# 5. Live web research (fallback path)
python3 -c "
from web_research.search import WebResearcher
r = WebResearcher()
results = r.search('Manchester Aquatics Centre swimming pool')
print('results:', len(results))
for x in results[:2]:
    print('  -', x.title, '|', x.url)
"

# 6. Friendly label test
python3 -c "
from swim_content_v4.web import create_app
c = create_app().test_client()
runs = __import__('os').listdir('runs_v4')
rid = next((r.replace('.json','') for r in runs if r.endswith('.json')), None)
if rid:
    body = c.get(f'/review/{rid}').get_data(as_text=True)
    # These slug strings should NOT appear visibly to a user
    bad_phrases = ['swim_content_v4', 'engine_v4', 'recognition_swim']
    for p in bad_phrases:
        if p in body:
            print('FOUND BAD:', p)
        else:
            print('OK no:', p)
"
```

All steps pass. Build it.
