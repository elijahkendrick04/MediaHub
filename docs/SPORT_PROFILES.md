# Sport Profiles

> **In plain words.** A **sport profile** is a simple settings sheet, one per
> sport, that tells MediaHub what that sport should post. For each kind of post it
> records four things: is it switched on, what information it needs, which design it
> uses, and how much it's allowed to post on its own. The files are plain text
> (YAML) so a non-coder can read and edit them. Adding a new sport mostly means
> *writing one of these files* (plus a parser and some templates) — not rewriting
> the engine. New here? Read [`POST_TYPE_TAXONOMY.md`](POST_TYPE_TAXONOMY.md) and
> [`AUTONOMY_MODEL.md`](AUTONOMY_MODEL.md) first.

Evidence base: [`research/ROADMAP_RESEARCH_2026.md`](research/ROADMAP_RESEARCH_2026.md)
§A.2. Related: [`ARCHITECTURE_TARGET.md`](ARCHITECTURE_TARGET.md),
[`EXTENSION_GUIDE.md`](EXTENSION_GUIDE.md) (the existing "add a sport" seam).

---

## 1. The concept

The sport profile is the **strategy/config layer**. It is deliberately separate
from the **engine layer** that already ships:

| Layer | Object | Where | Concern |
|---|---|---|---|
| Strategy / config | `SportProfile` (new) | `data/sport_profiles/<sport>.yaml` + `mediahub.sport_profiles` | *What* a sport posts, fed by what, rendered how, how autonomously. |
| Engine | `SportConfig` (shipped) | `mediahub.recognition.registry` | *How* a sport's deterministic detectors / history / ranker work. |

Keeping them separate is intentional: the engine is accuracy-critical and
deterministic (CLAUDE.md: *critical engine stays deterministic*), while the profile
is human-authored product config that changes often. `SportProfile.engine_sport`
names the `register_sport(...)` sport the profile binds to, so the two stay linked
without merging two very different kinds of change.

## 2. The schema

Typed in `mediahub.sport_profiles.schema` (plain `@dataclass`, repo style):

```python
@dataclass
class PostTypeConfig:
    post_type: str                 # canonical slug (see POST_TYPE_TAXONOMY.md)
    enabled: bool = True
    data_inputs: list[str] = []    # input keys, e.g. ["hytek_hy3", "pdf_results"]
    template_namespace: str = ""   # graphic/reel template set, e.g. "swim/meet_recap"
    default_autonomy: AutonomyLevel = AutonomyLevel.APPROVAL_REQUIRED

@dataclass
class SportProfile:
    sport: str                     # slug, e.g. "swimming"
    display_name: str
    engine_sport: str = ""         # recognition.registry name (defaults to sport)
    governing_bodies: list[str] = []
    post_types: dict[str, PostTypeConfig] = {}
    notes: str = ""
```

On-disk YAML (excerpt from `data/sport_profiles/swimming.yaml`):

```yaml
sport: swimming
display_name: Swimming
engine_sport: swimming
governing_bodies: [British Swimming, Swim England, World Aquatics]
post_types:
  meet_recap:
    enabled: true
    data_inputs: [hytek_hy3, sdif_sd3, pdf_results, html_results]
    template_namespace: swim/meet_recap
    default_autonomy: approval_required
  sponsor_activation:
    enabled: true
    data_inputs: [manual_entry, sponsor_kit]
    template_namespace: universal/sponsor
    default_autonomy: draft_only
```

**Why YAML, not JSON** (the rest of `data/` is JSON): profiles are read and edited
by humans, including non-coders, so comments and readability win. They are
read-only *shipped* config (like `data/ontology/` and `data/voices/seed/`), not
per-run runtime state — so they resolve relative to `data/`, not `DATA_DIR`.

**Safety invariant:** no shipped profile may default any post type to
`fully_autonomous` (enforced by `tests/test_sport_profiles.py`). Autonomy is opt-in
per workspace — see [`AUTONOMY_MODEL.md`](AUTONOMY_MODEL.md).

## 3. Loading a profile

```python
from mediahub.sport_profiles import load_sport_profile, list_sport_profiles

prof = load_sport_profile("swimming")          # FileNotFoundError if absent
prof.enabled_post_types()                        # ['athlete_spotlight', 'meet_recap', ...]
prof.autonomy_for("sponsor_activation")          # AutonomyLevel.DRAFT_ONLY
all_profiles = list_sport_profiles()             # every data/sport_profiles/*.yaml
```

Override the directory for tests/ops with `base_dir=...` or the
`MEDIAHUB_SPORT_PROFILES_DIR` env var. **This package is inert** — nothing in the
running product imports it yet; later roadmap phases consume it.

## 4. How to add a new sport (step by step)

Adding a sport is **profile + parser + templates + engine adapter** — four small,
mostly-independent pieces, none of which rewrite the core.

1. **Write the profile.** Create `data/sport_profiles/<sport>.yaml`. Pick post
   types from [`POST_TYPE_TAXONOMY.md`](POST_TYPE_TAXONOMY.md) (universal + any
   sport-specific). Set each one's `data_inputs`, `template_namespace`, and
   `default_autonomy` (keep it gated). Add a row to
   [`data/sport_profiles/README.md`](../data/sport_profiles/README.md).
2. **Register the engine sport.** Create `src/mediahub/recognition_<sport>/` with
   at least one detector and a `register_sport("<sport>", SportConfig(...))` call
   in its `__init__.py` (the existing seam — [`EXTENSION_GUIDE.md`](EXTENSION_GUIDE.md)
   "Add a new sport"). Point `engine_sport` at this name.
3. **Add ingestion.** Add a parser/spoke for the sport's `data_inputs` (e.g.
   `nba_api`, `openfootball_json`, chip-timing CSV). Normalise to the canonical
   schema — see [`ARCHITECTURE_TARGET.md`](ARCHITECTURE_TARGET.md) §ingestion.
4. **Author templates.** Add the `template_namespace` sets under
   `graphic_renderer/layouts/` (and Remotion scenes for reels).
5. **Test it.** Add the profile to the `test_sport_profiles.py` coverage and a
   detector test under `tests/`.
6. **Govern it.** A new sport is an architecture/data-model addition — Council-gated
   per [`COUNCIL_GOVERNANCE.md`](COUNCIL_GOVERNANCE.md); record the decision and
   link it from the PR.

The two shipped example profiles — `swimming.yaml` (full engine behind it) and
`football.yaml` (profile only, engine adapter pending) — show both ends of this:
swimming is end-to-end; football demonstrates a profile that loads and validates
*before* its engine exists, so the strategy layer can be designed ahead of the
parser.

## 5. Where this is going (roadmap)

Sport profiles are Phase-1 groundwork in [`ROADMAP.md`](ROADMAP.md). The forward
work: a profile-driven content planner (the strategy brain), then per-type autonomy
enforcement (Phase 2), then real second-sport ingestion (Phase 3).
