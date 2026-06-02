# `sport_profiles/` — what each sport should post

**In plain words:** this folder holds the "rulebook reader" for sports. A
**sport profile** is a simple list, written by a human, that says — for one sport —
which kinds of posts it makes, what information each post needs, which design it
uses, and how much it's allowed to post on its own. The files themselves live in
[`data/sport_profiles/`](../../../data/sport_profiles/) (one `.yaml` per sport);
the code here just loads and checks them.

This package is **new scaffolding** from the roadmap rebuild. It is deliberately
**not plugged into the live app yet** — importing it does nothing on its own.
Later roadmap phases will use it.

## What's inside

| File | What it does |
|---|---|
| `autonomy.py` | `AutonomyLevel` — the three settings for "how much a post type can do by itself": `draft_only`, `approval_required` (the default), `fully_autonomous`. |
| `schema.py` | `SportProfile` + `PostTypeConfig` — the typed shape of a profile. |
| `loader.py` | `load_sport_profile("swimming")` / `list_sport_profiles()` — read the YAML files. |

## How it fits the existing code

- It is **separate from** `recognition.registry.SportConfig`. That one is the
  *engine* (the deterministic detectors for a sport). A `SportProfile` is the
  *strategy/config* on top. `SportProfile.engine_sport` names the registered sport
  it draws detections from, so the two stay linked without merging.
- Post-type keys line up with `club_platform.content_types.ContentType` where an
  equivalent already exists (e.g. `meet_recap`, `athlete_spotlight`).

## Learn more

- Authoring guide & schema: [`docs/SPORT_PROFILES.md`](../../../docs/SPORT_PROFILES.md)
- Post types: [`docs/POST_TYPE_TAXONOMY.md`](../../../docs/POST_TYPE_TAXONOMY.md)
- Autonomy model: [`docs/AUTONOMY_MODEL.md`](../../../docs/AUTONOMY_MODEL.md)
- Target architecture: [`docs/ARCHITECTURE_TARGET.md`](../../../docs/ARCHITECTURE_TARGET.md)
