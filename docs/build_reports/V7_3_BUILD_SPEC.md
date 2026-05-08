# V7.3 Build Specification — Engine Spine + Content Pack Depth

**Strategic frame:** This is the inflection version. We're moving from "swim content app" to "sport-agnostic content automation engine that ships swimming first". Get the foundation right now so basketball/athletics/rowing/etc. don't require rewrites later.

**Owner:** Elijah Kendrick (vice-chair, Swansea University Swimming). Strong founder-market fit in swimming. Long-term vision: structured data → meaningful moments → branded content for any club/team/business.

## Locked decisions

1. **Refactor depth: HEAVY.** Rename `swim_content_v4` → `engine_v4`, `swim_content_v5` → `recognition`. Promote `swim_content_pb` → keep as `swim_content_pb` but expose its contract via a new generic `history` interface module that swimming implements.
2. **Post angle taxonomy: BOTH.** Detectors emit a suggested `post_angle` on every Achievement; the Recommender can override based on combined evidence (e.g. medal + PB → `medal_and_pb_combo`).
3. **PB layered evidence: BOTH FIRE.** When the new `CONFIRMED_OFFICIAL_PB` rule matches AND we also have prior-PB history showing improvement, both fire. Card headline: official-PB confirmed; sub-evidence: improvement magnitude.
4. **Voice profile: data only, no runtime enforcement.** Build the configuration UI as a tab on the profile page. Capture all the voice fields. Surface them in the editor for the user, but don't auto-block or auto-rewrite. ALSO: add "voice exemplars" — paste/upload posts from teams the club admires, stored as text. These become future LLM few-shot context.

## Architectural direction (post-V7.3)

```
┌─────────────────────────────────────────────────────────────┐
│ engine_v4/          The thin orchestration + Flask web layer │
│   web.py            HTTP routes, HTML rendering              │
│   pipeline_v4.py    Adapter dispatch + recognition + brand   │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│ recognition/        Sport-agnostic recognition engine        │
│   schema.py         Achievement, RankFactor, RecognitionReport│
│   ranker.py         Multi-factor weighted scorer            │
│   recommender.py    Quality bands + post angles + post types│
│   explainer.py      Per-event traces                         │
│   report.py         build_recognition_report(...)            │
│   registry.py       Sport registry: register_sport(name,...) │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│ recognition_swim/   Swimming detectors (was V5 achievements/)│
│   pb.py, barrier.py, medal_final.py, etc. (15 detectors)    │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│ history/            Generic history provider interface       │
│   schema.py         PreviousBest, IdentityMatch, HistoryAudit│
│   provider.py       HistoryProvider ABC                     │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│ swim_content_pb/    Swimming history provider impl (existing)│
│   (now implements history.HistoryProvider interface)        │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│ canonical/          Canonical event schema (was canonical.py)│
│   __init__.py       Re-exports                              │
│   event.py          SportEvent (new generic top-level)      │
│   swim.py           SwimMeet (subtype, was Meet)            │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│ brand/, workflow/, club_platform/  Already sport-agnostic    │
│ content_pack/       NEW: grouped pack builder                │
│ voice/              NEW: voice profile + exemplars           │
└─────────────────────────────────────────────────────────────┘
```

## Phase A: Renames and shims (do first, end-to-end test before continuing)

### Files to create

- `engine_v4/__init__.py` — re-export from `swim_content_v4` for backward compat during transition
- `recognition/__init__.py` — re-exports + new spine
- `recognition/registry.py` — `register_sport()`, `get_sport()`, `list_sports()`
- `recognition_swim/__init__.py` — `register_swim()` that calls `recognition.register_sport("swimming", detectors=[...])`
- `history/__init__.py` — abstract `HistoryProvider` + dataclasses
- `canonical/__init__.py` — re-exports `SportEvent` and the swim-specific `SwimMeet`
- `canonical/event.py` — base `SportEvent` dataclass with `sport: str` field
- `canonical/swim.py` — `SwimMeet(SportEvent)` (inherits + adds course, swimmers, results, etc.)

### Files to rename (preserving git history via git mv if applicable, but renaming via simple file ops if not)

- `swim_content_v5/` → keep content but ADD `recognition/` package that re-exports the generic parts (schema, ranker, recommender, explainer, report, registry) AND `recognition_swim/` that re-exports the achievements/. Delete `swim_content_v5/` ONLY after all imports updated.
- `swim_content_v4/canonical.py` → split contents: keep `Meet`/`Swimmer`/`RaceResult` types, but rename `Meet` → `SwimMeet` AND introduce a parent `SportEvent`. Add `Meet = SwimMeet` alias for back-compat.

### Critical invariant

**Every existing import path must still work for at least V7.3.** Use module-level shims:

```python
# swim_content_v5/__init__.py (after refactor)
import warnings
warnings.warn("swim_content_v5 is renamed; use 'recognition' for generic engine and 'recognition_swim' for swimming detectors", DeprecationWarning, stacklevel=2)
from recognition.schema import *
from recognition.ranker import *
# ... etc, re-exporting everything that was previously imported
from recognition_swim.achievements import *  # the detectors
```

Same for `swim_content_v4` (keep, don't delete; new code uses `engine_v4`).

### Smoke gate before continuing

After renames, run the full Swansea regression (1665/88/36) end to end. If anything fails, debug before adding new features.

## Phase B: SportEvent canonical schema

```python
# canonical/event.py
from dataclasses import dataclass, field
from typing import Any

@dataclass
class SportEvent:
    """Generic canonical schema. Every sport adapter outputs a SportEvent
    or a subclass."""
    sport: str                     # "swimming" | "basketball" | "athletics" | ...
    event_id: str                  # uniquely identifies this competition/match
    name: str                      # human-readable e.g. "Swansea Aquatics May LC 2026"
    start_date_iso: str | None
    end_date_iso: str | None
    venue: str | None
    governing_body: str | None
    
    # Sport-specific data lives here. Detectors for that sport know its shape.
    sport_data: dict[str, Any] = field(default_factory=dict)
    
    # Common entities
    participants: list = field(default_factory=list)   # SportParticipant or sport-specific
    results: list = field(default_factory=list)        # SportResult or sport-specific
    warnings: list = field(default_factory=list)
```

```python
# canonical/swim.py
@dataclass
class SwimMeet(SportEvent):
    """Swim-specific extension of SportEvent."""
    course: str = "LC"             # LC | SC
    
    # Swim-specific entities (existing types)
    swimmers: dict = field(default_factory=dict)       # asa_id -> Swimmer
    clubs: dict = field(default_factory=dict)
    races: list = field(default_factory=list)
    relays: list = field(default_factory=list)
    standards_meta: dict = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.sport:
            self.sport = "swimming"

# Back-compat alias
Meet = SwimMeet
```

Existing code uses `Meet` everywhere; the alias keeps it working. New code uses `SwimMeet` or accepts `SportEvent`.

## Phase C: Sport registry

```python
# recognition/registry.py
from dataclasses import dataclass, field
from typing import Callable

@dataclass
class SportConfig:
    sport: str
    display_name: str
    detectors: list                # list[AchievementDetector] instances
    history_provider: object | None  # HistoryProvider implementation (or None)
    default_voice_templates: dict   # for the brand layer
    
_SPORTS: dict[str, SportConfig] = {}

def register_sport(sport: str, **kwargs) -> None:
    _SPORTS[sport] = SportConfig(sport=sport, **kwargs)

def get_sport(sport: str) -> SportConfig:
    return _SPORTS.get(sport)

def list_sports() -> list[str]:
    return sorted(_SPORTS.keys())
```

```python
# recognition_swim/__init__.py
from recognition.registry import register_sport
from .achievements import (PBConfirmedDetector, PBLikelyDetector, ... ALL 15 ...)

def init():
    register_sport(
        "swimming",
        display_name="Swimming",
        detectors=[
            PBConfirmedDetector(), PBLikelyDetector(), ...
        ],
        history_provider=None,  # set later when swim_content_pb is wired
        default_voice_templates={...},
    )

init()
```

The pipeline becomes:

```python
sport = meet.sport  # "swimming"
config = recognition.get_sport(sport)
detectors = config.detectors
# run detectors, build report
```

## Phase D: post_angle taxonomy

Add to `recognition/schema.py`:

```python
class PostAngle(str, Enum):
    # PB family
    CONFIRMED_OFFICIAL_PB = "confirmed_official_pb"
    PB_IMPROVEMENT = "pb_improvement"
    LIKELY_PB = "likely_pb"
    FIRST_SUB_BARRIER = "first_sub_barrier"
    
    # Meet performance
    MEDAL_GOLD = "medal_gold"
    MEDAL_SILVER = "medal_silver"
    MEDAL_BRONZE = "medal_bronze"
    MEDAL_AND_PB_COMBO = "medal_and_pb_combo"  # recommender override
    FINALIST = "finalist"
    HEAT_TO_FINAL_DROP = "heat_to_final_drop"
    
    # Field context
    TOP_OF_FIELD = "top_of_field"
    QUALIFYING_TIME = "qualifying_time"
    
    # Historical
    BIGGEST_DROP = "biggest_drop"
    FASTEST_SINCE = "fastest_since"
    MULTI_PB_WEEKEND = "multi_pb_weekend"
    RETURN_TO_FORM = "return_to_form"
    
    # Team / aggregate
    TEAM_DEPTH = "team_depth"
    RELAY_HIGHLIGHT = "relay_highlight"
    WEEKEND_IN_NUMBERS = "weekend_in_numbers"
    ATHLETE_SPOTLIGHT = "athlete_spotlight"
    RECAP_MENTION = "recap_mention"

POST_ANGLE_LABELS = {
    PostAngle.CONFIRMED_OFFICIAL_PB: "Official PB confirmed",
    PostAngle.MEDAL_AND_PB_COMBO: "Medal + PB combo",
    # ... human-readable labels
}
```

Add `post_angle: PostAngle` field to `Achievement` dataclass. Each detector sets it. Recommender has a precedence map and can override.

## Phase E: CONFIRMED_OFFICIAL_PB rule

Edit `swim_content_pb/matcher.py` `decide_pb()`:

NEW logic, BEFORE the existing checks:

```python
# Rule 0 (highest precedence): If snapshot exists AND has an entry for this event
# AND that entry's time matches our current swim time (within 0.005s)
# AND that entry's date matches the meet date (or is within 1 day)
# → this swim IS the swimmer's official all-time PB on swimmingresults.org.
# This is the strongest possible PB confirmation. Don't downgrade just because
# we lack pre-meet history.
if snapshot and snapshot.fetch_ok and meet_date_iso:
    for entry in snapshot.entries_for(event_distance, event_stroke, course):
        if abs(entry.time_seconds - current_time_seconds) <= 0.005:
            entry_date = entry.date_iso
            if entry_date and (
                entry_date == meet_date_iso
                or _date_within_days(entry_date, meet_date_iso, 1)
            ):
                # CONFIRMED OFFICIAL PB — this swim is the swimmer's listed PB on SR
                return PBDecision(
                    status="CONFIRMED_OFFICIAL_PB",
                    ...
                    reason="Time matches swimmingresults.org all-time PB and PB date matches the meet. This swim is the swimmer's official PB.",
                    safe_to_post=True,
                    confidence="high",
                )
```

Then the existing previous-PB check still runs. If we ALSO have prior-PB history showing improvement, BOTH fire — the official_pb is the headline, the improvement adds the magnitude.

Update `recognition_swim/achievements/pb.py`:
- New `OfficialPBDetector` that fires on `CONFIRMED_OFFICIAL_PB` decisions
- Existing `PBImprovementMagnitudeDetector` still fires when prior history supports it
- Cards may have BOTH achievements; the recommender decides which is the headline (official_pb wins)

Update `PBDecision` status enum to include:
- `CONFIRMED_OFFICIAL_PB` — time + date match rule (NEW)
- `CONFIRMED_PB_IMPROVEMENT` — prior history proves improvement (renamed from CONFIRMED_PB)
- `MATCHED_PB` — uploaded time equals known PB but date doesn't prove it's new
- `LIKELY_PB` — strong but incomplete evidence
- `NOT_PB` — verified slower
- `PB_UNVERIFIED` — missing evidence
- `SUPPRESSED_NEEDS_VERIFICATION` — identity not safe

## Phase F: SafeToPost label on every card

Add to `recognition/schema.py`:

```python
@dataclass
class SafeToPost:
    level: str   # "safe" | "needs_review" | "do_not_post"
    reason: str  # short user-facing explanation

    def to_dict(self) -> dict:
        return {"level": self.level, "reason": self.reason}
```

Add `safe_to_post: SafeToPost` to `RankedAchievement`.

Logic in `recommender.py`:

```python
def derive_safe_to_post(achievement, ranked_factors, pb_decision=None) -> SafeToPost:
    # do_not_post if confidence < 0.4 OR explicit suppression
    if achievement.confidence < 0.4:
        return SafeToPost("do_not_post", "Evidence is weak or ambiguous.")
    if pb_decision and pb_decision.status == "SUPPRESSED_NEEDS_VERIFICATION":
        return SafeToPost("do_not_post", "Swimmer identity could not be verified.")
    
    # needs_review if any uncertainty notes OR confidence < 0.7
    if achievement.uncertainty_notes:
        return SafeToPost("needs_review", "; ".join(achievement.uncertainty_notes))
    if achievement.confidence < 0.7:
        return SafeToPost("needs_review", "Some evidence is incomplete.")
    
    # safe with detailed reason
    if achievement.type == "official_pb_confirmed":
        return SafeToPost("safe", "Official PB confirmed by SwimmingResults time and date match.")
    if achievement.type == "medal_gold":
        return SafeToPost("safe", "Gold medal placement read directly from results file.")
    # ... per-type defaults
    return SafeToPost("safe", "Verifiable claim with high-confidence evidence.")
```

Render this prominently on every card with a coloured pill (green/amber/red).

## Phase G: Plain-text copy paths

In `engine_v4/web.py`, every "Copy" button must pass plain text — not HTML — to the clipboard.

Add a copy-text builder in `recognition/copy_text.py`:

```python
def build_caption_text(card: dict, mode: str = "caption_only") -> str:
    """
    Returns plain text suitable for clipboard.
    
    mode:
      - "caption_only"      headline + body, no hashtags, no formatting
      - "with_hashtags"     caption + " " + hashtags (from voice profile)
      - "full_brief"        caption + hashtags + sources + safe-to-post note + suggested post type
    """
    cap = card.get("active_caption") or {}
    parts = []
    if cap.get("headline"):
        parts.append(cap["headline"])
    if cap.get("body"):
        parts.append("")
        parts.append(cap["body"])
    if mode in ("with_hashtags", "full_brief"):
        hashtags = card.get("hashtags") or []
        if hashtags:
            parts.append("")
            parts.append(" ".join(hashtags))
    if mode == "full_brief":
        parts.append("")
        parts.append("---")
        parts.append(f"Suggested format: {card.get('suggested_post_type','main_feed')}")
        parts.append(f"Confidence: {card.get('confidence','medium')}")
        s2p = card.get("safe_to_post") or {}
        if s2p.get("level"):
            parts.append(f"Safe to post: {s2p['level']} — {s2p.get('reason','')}")
        sources = card.get("evidence") or []
        if sources:
            parts.append("Sources:")
            for s in sources[:3]:
                u = s.get("source_url") or s.get("url") or ""
                n = s.get("source_name") or s.get("name") or ""
                parts.append(f"  - {n}{(' '+u) if u else ''}")
    return "\n".join(parts)
```

Render three copy buttons per card:
- "Copy caption"
- "Copy + hashtags"
- "Copy full brief"

Frontend gets the plain text via either:
- A hidden `<textarea>` per card containing the pre-rendered text (cleanest)
- Or a fetch to `/api/runs/<id>/card/<card_id>/copy?mode=...`

Use option (a) for simplicity. The hidden textarea contains the plain text, no HTML wrapping.

## Phase H: Content Pack Builder grouped by recommended use

Replace the current flat `/pack/<run_id>` page with a grouped layout:

```
┌─ Main feed posts (n) ──────────────┐
│ ELITE achievements with safe-to-post = safe
│ Each: post angle, caption, copy buttons, mark posted
│
├─ Stories (n) ──────────────────────┤
│ STRONG achievements suited to story format
│
├─ Athlete spotlights (n) ───────────┤
│ Per-swimmer multi-achievement cards
│
├─ Weekend recap ────────────────────┤
│ One auto-generated meet summary card
│
├─ Weekend in numbers ───────────────┤
│ One auto-generated stats card
│
├─ Internal notes / nice mentions ───┤
│ NICE band achievements — for newsletter only
│
├─ Needs review (n) ─────────────────┤
│ Anything with safe_to_post = needs_review
│
├─ Rejected / not recommended (n) ───┤
│ NOT_WORTHY band + manually rejected
└────────────────────────────────────┘
```

Each section is collapsible. Each item shows the same controls: post angle pill, caption preview, three copy buttons, edit, mark posted, safe-to-post badge.

Build a new module `content_pack/builder.py`:

```python
def build_grouped_pack(run_data, profile_id) -> dict:
    """Returns:
    {
      "main_feed": [item, ...],
      "stories": [...],
      "athlete_spotlights": [...],
      "weekend_recap": item | None,
      "weekend_in_numbers": item | None,
      "internal_notes": [...],
      "needs_review": [...],
      "rejected": [...],
    }
    
    Each item is the existing card dict + post_angle + safe_to_post + caption_text variants.
    """
```

Bucketing rules:
- `main_feed`: quality_band == ELITE AND safe_to_post.level == "safe"
- `stories`: quality_band == STRONG AND safe_to_post.level == "safe"
- `athlete_spotlights`: any swimmer with ≥3 achievements (grouped)
- `weekend_recap`: the single auto-generated meet summary card
- `weekend_in_numbers`: the auto-generated stats card
- `internal_notes`: quality_band == NICE
- `needs_review`: safe_to_post.level == "needs_review"
- `rejected`: quality_band == NOT_WORTHY OR workflow status == REJECTED

## Phase I: Weekend-in-numbers auto card

Add `recognition/weekend_in_numbers.py`:

```python
def build_weekend_in_numbers(report: RecognitionReport) -> WeekendInNumbersCard:
    """Generate a single 'meet by the numbers' card from the recognition report.
    Includes:
      - n_swimmers, n_swims, n_pbs, n_medals, n_finals
      - top_of_field count
      - biggest drop (swimmer + amount)
      - most PBs by swimmer
      - relay highlights (count + best placement)
    """
```

Render a clean card with stats grid + a copyable text version like:

```
Swansea Aquatics May Long Course 2026 — by the numbers

36 swimmers · 88 swims
14 PBs · 12 medals · 36 finals
94 qualifying-time hits

Most PBs: Mathew Bradley (4)
Biggest drop: Oliver Gillett, 100m fly, −1.45s
Relays: 3 medals across 4 events
```

## Phase J: Grouped near-miss / not-generated review

In the existing recognition page, replace the flat "Not generated (0 swims)" panel with grouped subsections:

```
Near-miss review
├─ Almost PB (n)               — swims within 1% of prior PB
├─ Possible PB but uncertain   — no SR snapshot or ambiguous match
├─ Possible barrier (no history) — crossed a sub-X but couldn't verify "first"
├─ Good placing, weak field    — top-3 in events with <8 entrants
├─ Ambiguous swimmer match     — needs_verification swimmers
├─ Relay mention only          — relay swims that didn't trigger a card
└─ Lower-priority than other cards — outranked by stronger achievements
```

Add a `near_miss_category` field to swim traces. Group on render.

## Phase K: Voice profile tab

Add to `voice/` package (new):

```python
# voice/profile.py
@dataclass
class VoiceProfile:
    profile_id: str
    tone: str = "warm-club"           # professional | hype | friendly | formal | warm-club | data-led
    emoji_level: str = "moderate"     # none | sparing | moderate | heavy
    preferred_phrases: list[str] = field(default_factory=list)
    banned_phrases: list[str] = field(default_factory=list)
    hashtag_style: str = "club_only"  # club_only | meet_specific | none | full
    name_style: str = "first_name"    # first_name | full_name | surname
    sign_off: str = ""                # "—Swansea Uni"  or empty
    exemplars: list[VoiceExemplar] = field(default_factory=list)


@dataclass
class VoiceExemplar:
    title: str          # "Loughborough big PB post"
    source_url: str = ""
    text: str = ""      # the actual post text — used for future few-shot
    notes: str = ""
```

UI: new tab in profile editor: **Voice**.
- Tone selector (radio)
- Emoji level (radio)
- Preferred phrases (textarea, one per line)
- Banned phrases (textarea, one per line)
- Hashtag style (radio)
- Name style (radio)
- Sign-off (input)
- **Exemplars** — list of pasted post examples with title, URL, text. Add button. Stored persistently. Clear note: "These will be used by the future caption generator as examples of your preferred voice."

Wire VoiceProfile into:
- Brand template renderer respects `name_style` (uses first or full name)
- Brand template renderer respects `emoji_level` (strips emojis if "none")
- Brand template renderer respects `sign_off` (appends if set)

DON'T enforce banned/preferred phrases at runtime yet — just store. The future content generator (V8) consumes them.

## Phase L: Tests + smoke

Critical Swansea regression must survive:
- 1665 total swims, 88 our swims, 36 swimmers
- ≥40 V4 cards
- V5 recognition report present
- All routes 200
- No console errors

Add unit tests for:
- `recognition.registry.register_sport` works for two fake sports
- `swim_content_pb.matcher.decide_pb` returns CONFIRMED_OFFICIAL_PB on time+date match
- `recognition.copy_text.build_caption_text` returns plain text only
- `content_pack.builder.build_grouped_pack` buckets correctly
- `recognition.weekend_in_numbers.build_weekend_in_numbers` produces valid card

## Constraints

- Stdlib only.
- Every existing url_for endpoint name MUST resolve (no breaking nav).
- Every existing run JSON MUST load (no schema break in run files).
- `swim_content_v4`, `swim_content_v5`, `swim_content_pb` all keep working as deprecation shims.
- Wrap user-derived strings in `_h()` before HTML.
- No `href="/..."` hardcoded — use `url_for`.

## Definition of done

1. Renames complete; old import paths still resolve via shims.
2. SportEvent schema added; `Meet = SwimMeet` alias keeps existing code working.
3. Sport registry exists; swimming registers itself on import.
4. Every Achievement carries `post_angle`.
5. CONFIRMED_OFFICIAL_PB fires on Swansea swims that match the time+date rule.
6. Every ranked achievement carries `safe_to_post: SafeToPost(level, reason)`.
7. Every Copy button outputs plain text.
8. Content Pack page is grouped by 8 categories.
9. Weekend-in-numbers card auto-generates and appears in the pack.
10. Near-miss review is grouped into named sub-categories.
11. Voice profile tab works; exemplars persist.
12. Swansea regression: 1665/88/36/40+ cards, all routes 200, zero console errors.
13. Unit tests pass.

Build it.
