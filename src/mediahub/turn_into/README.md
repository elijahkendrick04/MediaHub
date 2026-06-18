# turn_into

Takes one finished meet and "turns it into" eight ready-made things at once: a
recap, swimmer spotlights, a number thread, a parent newsletter (email-ready,
with a subject line), a long-form club website report, a sponsor thank-you, a
coach quote, and a next-meet preview. (`pipeline.py` + `templates.py`.)

## turn_into v2 — the format transformer (`transform.py`, P6.1)

Also "turns *this* into *that*": take a design you already approved and
re-target it to any size or format from the catalogue
(`club_platform/format_catalog.py`) — a Story, a square post, a poster, a
certificate, a YouTube thumbnail, a custom size. It **re-lays-out** the design
for the new shape (a layout that sings tall is wrong wide) instead of stretching
pixels — the "Magic Switch" idea. It keeps the approved palette, headline,
stats and photo; only the composition (which layout) is re-chosen, by the AI
art director when one is configured, or a deterministic per-shape picker when
it isn't (never a made-up layout). `blank_brief_for_format()` is the
start-from-blank escape hatch: a minimal on-brand canvas seeded from the club's
brand colours. The web surface is the "Reformat…" button on each approved card
(`/api/runs/<run_id>/card/<card_id>/reformat`) and the catalogue JSON at
`/api/formats`.

Plain-English words: see ../../../GLOSSARY.md · format guide: docs/FORMAT_CATALOGUE.md
