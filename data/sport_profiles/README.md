# `data/sport_profiles/` — one config file per sport

**In plain words:** each file here describes what one sport should post. They are
plain text (YAML) so a non-coder can read and edit them. Think of it as the
"settings sheet" for a sport.

| File | Sport |
|---|---|
| `swimming.yaml` | Swimming (the first reference sport) |
| `football.yaml` | Football / soccer (the "second sport" example) |

Each file lists, per post type: whether it's **enabled**, the **data inputs** that
feed it, the **template set** that renders it, and its **default disposition**
(`draft_only` · `approval_required`, the default). Every type is reviewed by a
human before its content is used.

These are **read-only shipped config** (like `data/ontology/` and
`data/voices/seed/`), loaded by `mediahub.sport_profiles.load_sport_profile(...)`.
They are not yet wired into the running product.

- Schema & "how to add a new sport": [`docs/SPORT_PROFILES.md`](../../docs/SPORT_PROFILES.md)
- The post types themselves: [`docs/POST_TYPE_TAXONOMY.md`](../../docs/POST_TYPE_TAXONOMY.md)
