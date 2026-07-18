# Detector Bus

Achievement detectors turn parsed swims into `Achievement`s, which the ranker
scores into cards. This doc describes the real detector contract, the
`Achievement` shape, and the sport registry.

> **Status — the sport registry is a scaffold, not the live seam.** A
> registry exists (`mediahub.recognition.registry`: `register_sport` /
> `get_sport` / `list_sports`), and importing `mediahub.recognition_swim`
> auto-registers `"swimming"` into it. **But the live pipeline does not read the
> registry.** `build_recognition_report_for_run`
> (`legacy/swim_content_v5/report.py`) calls
> `mediahub.recognition_swim.production_detectors()` directly to get the
> swimming detector set; `get_sport()` / `list_sports()` are currently consumed
> only by tests. Calling `register_sport("<new sport>", …)` therefore has **no
> effect on any run** until the pipeline is wired to consult the registry — and
> there is no sport-agnostic ranker behind it yet (the working ranker is
> swim-specific V5 code whose factor tables are keyed on swim achievement types;
> see [`RANKING.md`](RANKING.md)).

## The registry

`SportConfig` and `register_sport` live in
`src/mediahub/recognition/registry.py`:

```python
@dataclass
class SportConfig:
    sport: str
    display_name: str
    detectors: list                    # AchievementDetector instances
    history_provider: object | None = None
    default_voice_templates: dict = field(default_factory=dict)

def register_sport(
    sport: str,
    display_name: str = "",
    detectors: list | None = None,
    history_provider: object | None = None,
    default_voice_templates: dict | None = None,
) -> None:
    ...
```

`register_sport` takes **keyword arguments** and constructs the `SportConfig`
itself — it does not accept a `SportConfig` positional. `SportConfig` has **no**
`ranker_weights` and **no** `copy_text_builder` field. Swimming registers itself
in `recognition_swim/__init__.py`:

```python
register_sport(
    "swimming",
    display_name="Swimming",
    detectors=production_detectors(),
    default_voice_templates={...},
)
```

Currently registered sports:

| Sport key | Package | Detectors (`production_detectors()`) |
| --- | --- | --- |
| `swimming` | `mediahub.recognition_swim` | `OfficialPBDetector` + the V5 detector suite (`swim_content_v5.achievements.get_all_detectors()`) + `MilestoneDetector` + `ClubRecordDetector` |

## Detector contract

Every detector subclasses `AchievementDetector`
(`legacy/swim_content_v5/achievements/base.py`, an `abc.ABC`) and implements a
**five-parameter** `detect`:

```python
class AchievementDetector(ABC):
    name: str = "abstract"

    def detect(self, swim, ctx, history, all_results=None, extra=None) -> list[Achievement]:
        ...
```

- `swim` — one canonical race result (row) to evaluate
- `ctx` — a `MeetContext` (`legacy/swim_content_v5/schema.py`): `meet_name`,
  `venue`, `course`, `start_date` / `end_date`, `governing_body`, `meet_level`
  (`national` / `county` / `university` / `open` / `club`), `has_finals`,
  `has_age_groups`, `age_groups`, `host_club_code`, the `research_*` fields, and
  an optional `profile` (the run's `ClubProfile`)
- `history` — the swimmer's past results (the V5 `SwimmerHistory` wrapper over
  `mediahub.pb_discovery` snapshots)
- `all_results` — every swim in the meet (for peer-field / relay comparisons)
- `extra` — per-swim extras (the swimmer object, registered standards, etc.)

There is **no** `DetectorContext` class and **no** `SwimRow` type — earlier
drafts of this doc invented both. The base class also provides a default
`trace()` that runs `detect()` and summarises why it did or didn't fire.

## The Achievement

A detector returns zero or more `Achievement`s
(`legacy/swim_content_v5/schema.py`). The real fields are:

- `type` — the achievement type string, e.g. `"pb_confirmed"`, `"medal_gold"`,
  `"first_sub_barrier"`, `"club_record"` (there is **no** `kind` field, and
  `"first_sub_minute"` / `"new_pb"` are **not** real types — see
  `_TYPE_MAGNITUDE` in `legacy/swim_content_v5/ranker.py` for the full set)
- `headline` — the short factual statement used in captions (there is **no**
  `claim_text` field)
- `swim_id`, `swimmer_id`, `swimmer_name`, `event`
- `angle_hint`, `confidence`, `confidence_label`
- `evidence` — a list of `AchievementEvidence` provenance records
- `raw_facts`, `uncertainty_notes`, `detector_name`

(The V7.3 `mediahub.recognition.schema.Achievement` is a thin subclass that adds
an optional `post_angle`; it inherits `type` / `headline` from the V5 dataclass
above.)

## Ranker

`rank_achievements` — re-exported as `mediahub.recognition.rank_achievements`
from `swim_content_v5.ranker` — scores detector output into ranked achievements.
The scoring is documented in [`RANKING.md`](RANKING.md).

## Adding a detector for an existing sport

1. Add a detector class under
   `src/mediahub/recognition_swim/achievements/` (the Phase-W detectors
   `official_pb.py`, `milestones.py`, `club_record.py` live here) or, for a V5
   suite detector, under `legacy/swim_content_v5/achievements/`.
2. Subclass `AchievementDetector` and implement
   `detect(self, swim, ctx, history, all_results=None, extra=None)` returning
   `Achievement`s.
3. Add it to `production_detectors()` in
   `src/mediahub/recognition_swim/__init__.py` — **that** is the list the live
   pipeline actually runs (not the registry).
4. Write a unit test that constructs a swim + a `MeetContext` and asserts the
   achievement fires only on the intended rows.
5. If the new `type` should score differently, add it to `_TYPE_MAGNITUDE` /
   `_TYPE_NARRATIVE_BONUS` in `legacy/swim_content_v5/ranker.py`.

## Adding detectors for a new sport

Because the registry is not yet wired into the pipeline (see the status note
above), a new sport needs pipeline work — not just a `register_sport` call:

1. Create `src/mediahub/recognition_<sport>/` with its own `achievements/`
   subpackage and detectors that consume your sport's row schema.
2. Add an interpreter pass for your sport's input formats.
3. Wire `build_recognition_report_for_run` (or its caller) to select your
   sport's detector set — today it hardcodes swimming's `production_detectors()`.
4. Provide a ranker keyed on your sport's achievement types; the current V5
   factor tables are swim-specific.
5. Update `mediahub.web.web` if the upload form needs a new sport label.

Calling `register_sport("<sport>", …)` records the config in the in-memory
registry, but on its own changes nothing about what a run detects.

## Detector inventory

See [`DETECTOR_INVENTORY.md`](DETECTOR_INVENTORY.md) for the full list of
shipped detectors and their trigger conditions.
