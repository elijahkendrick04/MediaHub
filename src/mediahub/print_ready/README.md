# `print_ready/` — getting club designs ready for the printers (roadmap 1.20)

Clubs don't only post online. They pin **posters** to the leisure-centre
noticeboard, hand out **flyers** at open days, frame **PB certificates**, stand a
**roll-up banner** at the gala, and sell **t-shirts, mugs and tote bags** to raise
money. Printing is different from posting: a file that looks perfect on a phone can
come back from the print shop with a white edge where it was cut, blurry because
the picture was too small, or the wrong colours because screens and ink don't match.

This folder is the part of MediaHub that **gets a design ready for a real printer**
so it won't bounce — and explains, in plain words, anything that needs fixing first.
A volunteer never has to know what "bleed" or "CMYK" means.

## What's in here

| File | What it does (in plain words) |
|------|-------------------------------|
| `products.py` | The **menu of things you can print** — business cards, postcards, flyers, A3/A2 posters, stickers, a roll-up banner, plus merch: a club t-shirt (front *and* back), a mug and a tote bag. For each one it remembers the real size, the paper or fabric, how it's printed, how much ink it can take, and which preview picture to show. |
| `proof.py` | The **safety check** (we call it *proofing*). Before you print, it looks at your design against the thing you're printing it on and lists anything that might go wrong — picture too small to print sharp, writing too tiny to read, artwork not reaching the edge, colours that will look duller in ink, too much ink to dry. Every warning says *what* is wrong and *how to fix it*. |
| `pdfx.py` | Makes the **proper print file** (a "PDF/X" — the file type print shops ask for), with the colours converted for ink. If the tool to do that isn't installed it says so honestly and still gives you the normal print-ready PDF. |
| `engine.py` | The **front desk**: hand it a design and what you want to print it on, it runs the safety check, then makes the print-ready file with the cut marks and edge bleed, and a matching preview. |
| `fulfilment.py` | The **"order it for me" slot** — *switched off for now*. The normal way to use MediaHub is to download the print-ready file and take it to any printer. One day an operator can plug a print company in here; until then it says so honestly and never pretends an order went through. |

## The most important rules

- **It never makes anything up.** The safety check is plain, repeatable maths — the
  same design and the same product always give the same warnings. It is not an AI
  guess; it's a ruler and a calculator.
- **Honest when a tool is missing.** If the colour-conversion or PDF/X tool isn't on
  the server, it tells you and still hands back the ordinary print-ready PDF — never
  a broken file or a fake "this is print-perfect" badge.
- **Download first, always.** MediaHub's job is to give the club a file it owns and
  can take anywhere. Ordering through a print company is an optional extra that an
  operator can switch on later — it is never required, and a human always approves a
  design before it's exported.

## How it fits with the rest of MediaHub

- The real sizes (bleed, dpi) live on each **`FormatSpec`** in
  `club_platform/format_catalog.py`. This folder adds the *product* around the canvas.
- The cut marks, edge bleed and colour science come from
  `graphic_renderer/print_export.py` — this folder uses them, it doesn't repeat them.
- The preview pictures come from `mockups/compose.py`.
- Turning one design into a print size ("magic resize for print") reuses the existing
  `turn_into/transform.py` — a poster becomes a tee design with a real re-layout.
