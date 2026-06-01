# Post-Type Taxonomy

> **In plain words.** MediaHub doesn't just turn results into posts. It decides
> *what kinds of posts* a team should make at all — match previews, score recaps,
> player spotlights, birthdays, sponsor thank-yous, "this day in history," and so
> on. This page is the master list of those post types. Most of them are the same
> for **every** sport (a fixture announcement is a fixture announcement whether
> it's swimming or football). A few are special to one sport (swimming has
> "relay splits"; football has "matchday XI"). A **sport profile** then picks which
> ones a sport uses. New here? Read [`../START_HERE.md`](../START_HERE.md) and
> [`SPORT_PROFILES.md`](SPORT_PROFILES.md) first.

This taxonomy is part of the multi-sport, autonomy-first roadmap rebuild. Evidence
base: [`research/ROADMAP_RESEARCH_2026.md`](research/ROADMAP_RESEARCH_2026.md) §A.2.
Related docs: [`SPORT_PROFILES.md`](SPORT_PROFILES.md) (how a sport selects post
types), [`AUTONOMY_MODEL.md`](AUTONOMY_MODEL.md) (the autonomy column),
[`ARCHITECTURE_TARGET.md`](ARCHITECTURE_TARGET.md) (where this sits).

---

## 1. The two layers: universal vs sport-specific

Roughly **70% of post volume is sport-agnostic.** The taxonomy is therefore split:

- **Universal post types** — meaningful for any team in any sport. These are the
  backbone; building them once serves every sport.
- **Sport-specific post types** — only make sense (or need bespoke data/templates)
  within one sport.

A **sport profile** ([`SPORT_PROFILES.md`](SPORT_PROFILES.md)) parameterises each
post type along four axes:

| Axis | Meaning |
|---|---|
| **enabled** | Does this sport produce this post type? |
| **data inputs** | Which ingestion inputs feed it (keys, not files). |
| **template set** | Which graphic/reel template namespace renders it. |
| **default autonomy** | Starting [`AutonomyLevel`](AUTONOMY_MODEL.md): `draft_only` · `approval_required` · `fully_autonomous`. Gated by default. |

## 2. How this maps onto today's code (verified)

The post-type idea is **not new** to MediaHub — it already ships, narrowly, as
`club_platform.content_types`:

- `ContentType` is a `str` enum with `MEET_RECAP`, `ATHLETE_SPOTLIGHT`,
  `WEEKEND_PREVIEW` (titled "Event Preview"), `SPONSOR_POST`, `SESSION_UPDATE`,
  `FREE_TEXT`.
- `REGISTRY: dict[ContentType, ContentTypeMeta]` is the single source of truth,
  with `is_implemented` flags and `input_contract` strings.

This taxonomy **generalises that registry**: the universal types below subsume the
existing enum values (e.g. `meet_recap` ↔ `MEET_RECAP`, `athlete_spotlight` ↔
`ATHLETE_SPOTLIGHT`, `sponsor_activation` ↔ `SPONSOR_POST`, `event_preview` ↔
`WEEKEND_PREVIEW`), and add the ones the strategy brain needs. The migration path
(extend the enum/registry vs. layer a profile-driven set on top) is a Phase-1
decision tracked in [`../docs/ROADMAP.md`](ROADMAP.md), not settled here.

Post-type keys in this doc are the canonical slugs used in the sport-profile YAML
(`data/sport_profiles/*.yaml`).

## 3. Universal post types

| Post type (slug) | What it is | Typical data inputs | Existing `ContentType`? |
|---|---|---|---|
| `fixture_announcement` | Upcoming game/meet/race announcement | `fixtures`, `manual_entry` | — |
| `result_recap` | Score/result summary after an event | parsed results, `manual_entry` | ≈ `MEET_RECAP` |
| `athlete_spotlight` | One athlete's story / achievement | parsed results, history, `media_library` | `ATHLETE_SPOTLIGHT` |
| `event_preview` | Tease athletes & angles before an event | `entry_list`, `manual_entry` | `WEEKEND_PREVIEW` |
| `milestone_celebration` | Caps, records, anniversaries, "first-ever" | `manual_entry`, `*_history` | — |
| `birthday` | Athlete/club birthday | roster, `manual_entry` | — |
| `signings_recruitment` | New member / signing announcement | `manual_entry` | — |
| `sponsor_activation` | Sponsor thank-you / activation | `manual_entry`, `sponsor_kit` | `SPONSOR_POST` |
| `ticket_merch_promo` | Tickets / merch / fundraiser push | `manual_entry` | — |
| `behind_the_scenes` | Training, travel, community moments | `media_library`, `manual_entry` | — |
| `season_recap` | End-of-season / mid-season wrap | season history, parsed results | — |
| `this_day_in_history` | "On this day…" archive post | `*_history`, archive | — |
| `session_update` | Live, mid-event Stories update | `manual_entry`, partial results | `SESSION_UPDATE` |
| `free_text` | Any described moment → drafted cards | `free_text` | `FREE_TEXT` |

## 4. Sport-specific tables

Each table lists the **divergent** post types for that sport (universal types from
§3 also apply). "Autonomy (default)" shows a sensible shipped default — **gated by
default** ([`AUTONOMY_MODEL.md`](AUTONOMY_MODEL.md)); a workspace may flip a
low-risk, source-grounded type (e.g. final scores) to `fully_autonomous` itself.

### 4.1 Swimming  *(shipped reference sport)*

| Post type | Data inputs | Template set | Autonomy (default) |
|---|---|---|---|
| `meet_recap` | Hy-Tek `HY3`/`HYV`, SDIF `SD3`/`CL2`, PDF/HTML results | `swim/meet_recap` | approval_required |
| `pb_spotlight` | parsed results, PB ledger (swimmingresults.org verified) | `swim/pb_spotlight` | approval_required |
| `heat_lane_preview` | entry list, heat sheet | `swim/heat_preview` | approval_required |
| `relay_splits` | parsed results | `swim/relay_splits` | approval_required |
| `club_record_board` | parsed results, club records | `swim/record_board` | approval_required |

Inputs verified against the shipped `interpreter/` (HY3/SDIF/PDF/HTML) and
`pb_discovery/` (web-verified PB ledger).

### 4.2 Football / soccer

| Post type | Data inputs | Template set | Autonomy (default) |
|---|---|---|---|
| `matchday_lineup` | lineup, fixtures, `manual_entry` | `football/matchday_xi` | approval_required |
| `full_time_score` | `openfootball_json`, `manual_entry` | `football/full_time` | approval_required |
| `goal_assist_leader` | `openfootball_json`, `statsbomb_open_data` † | `football/scorer` | approval_required |
| `league_table` | `openfootball_json` | `football/standings` | approval_required |
| `fixture_run_in` | `openfootball_json` | `football/run_in` | approval_required |

† `statsbomb_open_data` is free to access but governed by a non-OSS data agreement
(attribution / responsible use) — see [`DEPENDENCY_LICENSING.md`](DEPENDENCY_LICENSING.md).
`openfootball` is public-domain and the genuinely-free default.

### 4.3 Basketball

| Post type | Data inputs | Template set | Autonomy (default) |
|---|---|---|---|
| `game_day_matchup` | `nba_api`, fixtures, `manual_entry` | `bball/matchup` | approval_required |
| `final_box_score` | `nba_api`, `manual_entry` | `bball/box_score` | approval_required |
| `player_of_the_game` | `nba_api` | `bball/potg` | approval_required |
| `standings` | `nba_api` | `bball/standings` | approval_required |
| `highlight_clip` | game video, `nba_api` | `bball/highlight` | approval_required |

`nba_api` (swar/nba_api) is open-source and keyless-free; it powers the
NBA-Gameday-Generator pattern referenced in the research catalogue (§C.3, §C.5).

### 4.4 Running / athletics

| Post type | Data inputs | Template set | Autonomy (default) |
|---|---|---|---|
| `race_preview` | start list, `manual_entry` | `run/race_preview` | approval_required |
| `finish_time_spotlight` | chip-timing CSV, PB history | `run/finish_time` | approval_required |
| `podium_recap` | results CSV | `run/podium` | approval_required |
| `club_championship_table` | results CSV, club records | `run/championship` | approval_required |
| `training_block_milestone` | Garmin `FIT` files, `manual_entry` | `run/training_block` | approval_required |

Running ingestion is the sparsest in open source; chip-timing CSV + client-side
`FIT` parsing (the swim-data-analyser pattern, research §C.17) is the starting
point. This sport will need custom parsers (research §D.5).

## 5. Adding or changing a post type

1. Add the slug to the relevant sport profile(s) in `data/sport_profiles/*.yaml`
   with its four axes (see [`SPORT_PROFILES.md`](SPORT_PROFILES.md)).
2. If it is genuinely new platform-wide, decide whether to extend
   `club_platform.content_types.ContentType` (the engine-side registry) — a
   Council-gated data-model change ([`COUNCIL_GOVERNANCE.md`](COUNCIL_GOVERNANCE.md)).
3. Author its template set under `graphic_renderer/layouts/` (and a Remotion scene
   if it needs a reel) — see [`EXTENSION_GUIDE.md`](EXTENSION_GUIDE.md).
4. Wire its data inputs into the relevant ingestion spoke
   ([`ARCHITECTURE_TARGET.md`](ARCHITECTURE_TARGET.md)).
