---
name: graphic-text-qa
description: Text-quality rules for every generated graphic (Playwright layouts in src/mediahub/graphic_renderer and the stub-card copy shaping in web.py). Use whenever you add or change a text slot on a graphic layout, write fill/truncation logic, or review rendered graphics for copy defects. Encodes the autofit-first rule, word-boundary truncation, the no-jargon rule for public copy, and the ban on filler stat tiles and emoji-only bullets.
metadata:
  tags: mediahub, graphics, rendering, copy-quality, autofit, truncation
---

## When to use

Load this before touching any text that lands on a rendered graphic: layout
templates (`src/mediahub/graphic_renderer/layouts/*.html`), fill functions
(`render.py` `_fill_*`), or the caption→graphic copy shaping in `web.py`
(`_stub_card_to_graphic_item`). These graphics are public-facing posts — a
clipped word or a "SPONSOR / RESULT" tile reads as a bug to every follower.

## The rules (all deterministic — no LLM calls in the render path)

1. **Every text slot must fit.** Variable-length text (surnames, meet names,
   headlines) gets its font size from `graphic_renderer/autofit.fit_font_px`
   (cap at the layout's design size, floor so it stays legible) — never a
   fixed `height * k` size that clips long input at the canvas edge.
   The giant surname watermark uses `_surname_font_px` in `render.py`.
2. **Truncate only at word boundaries.** Bullets/sentences: shorten at the
   last full word and append "…" (`web.py _truncate_words`). Stat tiles:
   drop trailing whole words, no ellipsis needed (`render.py _tile_text`).
   Hard mid-word cuts (`s[:80]`, `ev[:14]`) are forbidden — "North District
   Ope" is a defect. Only a single word longer than the budget may be
   hard-cut, with "…".
3. **No course/file jargon on public copy.** Strip trailing "(SC)"/"(LC)"
   from event names with `render.py _clean_event_name` before display; if a
   layout wants the course, render it as its own labelled cell ("Short
   Course"). Never show file names, run ids, or parser codes on a graphic.
4. **No emoji-only bullets.** A bullet must contain at least one letter or
   digit (`web.py _has_real_text`). "🏆🏆🏆" is not a bullet.
5. **No placeholder/filler stat tiles.** Tiles show real data (time, event,
   place, short meet name) or an honest derived count (e.g. bullet count as
   "HIGHLIGHTS"). Invented filler ("3 VOICES", "WEEK WINDOW") is banned. A
   meet name longer than ~18 chars skips its tile — it's already the kicker.
6. **Headlines read as natural phrases.** Fixed per-type pairs, not data
   glued to a noun: sponsor → "THANK YOU" / sponsor name (or "PARTNERS"),
   preview → "EVENT" / "PREVIEW", session → "SESSION" / "UPDATE". Never
   compose "<SPONSOR NAME> RECAP". Routing words ("SPONSOR", "PREVIEW",
   "LIVE", "HIGHLIGHT") must never land in a display slot such as
   `achievement_label`.

## How to check

Regression tests live in `tests/test_graphic_text_quality.py` — extend them
when adding a slot or a fill. For a manual check, render each layout with a
long surname ("REEKIE-AYALA"), a long meet name, an event with "(SC)", and an
emoji-only sentence, then confirm nothing clips, overflows, or reads as filler.
