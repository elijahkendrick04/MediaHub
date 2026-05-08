# Detector Bus

The detector bus is the seam where sport-specific achievement detectors plug
into the sport-agnostic ranker.

## Registration

Each sport registers a `SportConfig` via
`mediahub.recognition.registry.register_sport(name, config)`:

```python
from mediahub.recognition.registry import register_sport, SportConfig

register_sport("swim", SportConfig(
    detectors=[OfficialPBDetector(...)],
    ranker_weights={"pb_strength": 1.0, "rarity": 0.6, ...},
    copy_text_builder=build_caption_text,
))
```

Currently registered sports:

| Sport | Module | Detectors |
| --- | --- | --- |
| `swim` | `mediahub.recognition_swim` | `OfficialPBDetector` (V8) + the V5 detector suite via `swim_content_v5.achievements` |

## Detector contract

Every detector implements:

```python
class AchievementDetector(Protocol):
    def detect(self, swim: SwimRow, context: DetectorContext) -> list[Achievement]:
        ...
```

Where `DetectorContext` exposes:
- `swimmer_history` — past results from `mediahub.history.provider`
- `pb_snapshot` — verified PB data from `mediahub.pb_discovery`
- `meet_field` — peer swims in the same event
- `qualifying_times` — registered standards from `data/quals.json`
- `ontology` — `mediahub.interpreter.ontology_loader.OntologyLoader`

A detector returns zero or more `Achievement`s. Each carries:
- `kind` — the angle (e.g. `"first_sub_minute"`, `"medal_final"`, `"new_pb"`)
- `confidence` — 0.0–1.0
- `evidence` — pointers to the rows that triggered it
- `claim_text` — short factual description used in captions

## Ranker

`mediahub.recognition.ranker.rank_achievements` combines detector outputs into
ranked cards. The formula is documented in [`RANKING.md`](RANKING.md).

## Adding a detector for an existing sport

1. Add a file under `src/mediahub/recognition_swim/achievements/<your_thing>.py`.
2. Implement the `detect(...)` method.
3. Add it to the swim sport config (currently in
   `recognition_swim/__init__.py`).
4. Write a unit test under `tests/test_v8_*` that constructs a synthetic
   `DetectorContext` and asserts the achievement fires only on the intended
   rows.
5. Optionally tune the ranker weight in `data/ontology/levels.json`.

## Adding detectors for a new sport

1. Create `src/mediahub/recognition_<sport>/` with its own `achievements/`
   subpackage.
2. Implement detectors that consume your sport's row schema.
3. Call `register_sport("<sport>", SportConfig(...))` in your package's
   `__init__.py`.
4. Add an interpreter pass for your sport's input formats (or extend the
   existing one with patterns in `data/patterns.jsonl`).
5. Update `mediahub.web.web` if the upload-form copy needs a new sport label.

## Detector inventory

See [`DETECTOR_INVENTORY.md`](DETECTOR_INVENTORY.md) for the full list of
shipped detectors and their trigger conditions.
