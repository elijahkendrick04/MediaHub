# `export_engine/` — the one export & conversion engine (roadmap 1.19)

When a club is happy with something MediaHub made — a card, a reel, a document, a
photo from the library — they need to **get it out** in the right file type. One
person wants a **JPG** for WhatsApp, another a **GIF** for the group chat, the
treasurer a **Word** doc, the print shop a **print-ready PDF**. This folder is the
single place that turns content into whatever file is asked for.

Think of it as the club's **conversion desk**: hand it a file and the format you
want, it hands back the new file. It also powers the **"quick actions"** toolbox on
the media library — convert / resize / trim a photo or clip without making a whole
post.

The most important rule: **it never makes anything up.** Every conversion is plain,
repeatable maths (Pillow for pictures, FFmpeg for video/sound) — the same file in,
with the same settings, always gives the same file out. If the tool to do a job
isn't installed (say the server has no video engine), it says so honestly instead
of handing back a broken or empty file.

## What's in here

| File | What it does (in plain words) |
|------|-------------------------------|
| `formats.py` | The **menu** of file types we can make (PNG, JPG, WebP, AVIF, SVG, MP4, GIF, WebM, WAV, MP3, PDF, PowerPoint, Word, CSV, JSON, Excel, ZIP) and which settings each one listens to. |
| `options.py` | The **settings dial**: quality (10–100), size (scale), keep-the-background-see-through, and screen-vs-print. Always kept inside safe limits. |
| `images.py` | Converts a **picture** to another picture type (e.g. PNG → JPG), resizing and flattening the background when needed. |
| `transcode.py` | Converts **video**: make a GIF or WebM from a clip, or turn a GIF back into a playable MP4. The one new tool this build adds. |
| `engine.py` | The **front desk**: you ask "turn this file into that type", it picks the right tool, remembers the answer, and hands the file back. |
| `quick_actions.py` | The **toolbox**: one-click convert / resize / crop a photo, trim / crop / resize / speed / mute / reverse / merge a clip, video→GIF (and back), and photos→PDF — without making a whole post. |
| `bulk.py` | **Export everything at once**: turn a whole pack of items into every format you ask for and bundle it into one ZIP, with a manifest that honestly lists anything it couldn't make. |
| `cache.py` | Remembers finished conversions so asking for the exact same one again is instant. |
| `README.md` | This file. |

## What can turn into what

- **Pictures** → PNG, JPG, WebP, AVIF
- **Video** → MP4, WebM, GIF (and you can pull just the **sound** out as WAV/MP3)
- **GIF** → MP4, WebM
- **Sound** → WAV, MP3, M4A, OGG, Opus, FLAC

(Cards becoming **SVG** or **print-PDF**, and documents becoming **PowerPoint /
Word**, are made by their own specialist folders — `graphic_renderer` and
`documents` — and listed on the same menu here so everything advertises through one
catalogue.)

## The rules this folder follows

- **Plain maths, never a guess:** same input + same settings → same file, every time.
- **Honest when it can't:** no video engine or no AVIF support → a clear error, never
  a fake or empty file.
- **Tidy storage:** finished files live under `DATA_DIR/export_cache`, following the
  `DATA_DIR` rule like everything else.
- **In-house:** Pillow and FFmpeg do the work on our own server — nothing is sent to
  an outside service to convert.

## Where to find it in the app

The download buttons and the media-library **quick actions** toolbox call this
engine. The web routes that wire it up live in `web/web.py` (search for "export
engine").
