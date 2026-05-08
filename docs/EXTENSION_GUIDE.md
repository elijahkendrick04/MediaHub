# Extension Guide

How to extend MediaHub safely. Every extension point already has a seam — you
should not need to fork the core.

## Add a new detector for swim

1. Create `src/mediahub/recognition_swim/achievements/<name>.py`.
2. Implement the `AchievementDetector` protocol (see [`DETECTOR_BUS.md`](DETECTOR_BUS.md)).
3. Register it in `recognition_swim/__init__.py`.
4. Add a unit test under `tests/test_v8_*.py` that builds a synthetic
   `DetectorContext` and asserts firing conditions.

## Add a new sport

1. Create `src/mediahub/recognition_<sport>/` mirroring `recognition_swim/`.
2. Provide:
   - At least one detector
   - A `register_sport("<sport>", SportConfig(...))` call in `__init__.py`
3. Add an interpreter pass (or extend `interpreter/patterns.py` with a new
   pattern set) for your sport's input formats.
4. Add `mediahub.web.web` upload-form copy if needed; otherwise the sport
   is auto-detected by the interpreter.

## Add a new card layout

1. Create `src/mediahub/graphic_renderer/layouts/<your_layout>.html` —
   Jinja2 template that consumes a `RenderResult.brief` payload.
2. Optional CSS overrides in `_<your_layout>.css`.
3. Reference it from `creative_brief/generator.py` by adding to the
   `_TEMPLATE_REGISTRY`.
4. Add a snapshot test under `tests/test_v8_graphic_renderer.py`.

## Add a new voice

Two paths:

**Hand-tuned seed voice** — create `data/voices/seed/<voice_id>.json`:

```json
{
  "voice_id": "punchy",
  "display_name": "Punchy",
  "tone_words": ["bold", "kinetic", "celebratory"],
  "max_emoji": 2,
  "exemplars": ["…three sample captions…"]
}
```

**Learned voice** — feed exemplars to `mediahub.voice.learned.induce`:

```python
from mediahub.voice.learned.induce import induce_voice
profile = induce_voice(exemplars=[...], voice_id="my_voice")
profile.save()
```

The learned voice will appear in the brand-kit voice dropdown automatically.

## Add a new cutout / background-removal provider

1. Create `src/mediahub/media_ai/providers/<name>_provider.py`.
2. Implement the `BackgroundRemover` protocol from `providers.base`.
3. Register in `providers/__init__.py::_RESOLVERS`.
4. Make it switchable via `MEDIAHUB_CUTOUT_PROVIDER=<name>`.
5. Add a contract test in `tests/test_v8_cutout_providers.py`.

## Add a new content type

1. Create `src/mediahub/club_platform/<your_type>.py` implementing the
   `ContentType` protocol from `club_platform.content_types`.
2. Register in `REGISTRY` in `content_types.py`.
3. Add the matching media requirement in
   `src/mediahub/media_requirements/rules.py`.
4. Optional: a dedicated layout under `graphic_renderer/layouts/`.

## Add a new ingest format

1. Add a parser under `src/mediahub/interpreter/<format>_parser.py` exposing
   `detect_<format>(blob) -> bool` and `parse_<format>(blob) -> InterpretedMeet`.
2. Hook it into `interpreter/__init__.py::interpret_document` in the
   detection chain.
3. Train a pattern in `data/patterns.jsonl` if the parser benefits from the
   pattern store.
4. Add fixtures under `samples/learning_corpus/level1/<example>/`.

## Override the PB source

Implement an alternative `PBSource` in `pb_discovery.discover` and wire it
through `pb_bridge.build_pb_snapshots`. See `legacy/swim_content_pb/` for the
older PB stack — it shows how multiple sources used to be combined.
