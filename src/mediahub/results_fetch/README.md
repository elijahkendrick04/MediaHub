# results_fetch

Reads a competition's results **straight from a web link**, the way a person with
a browser would.

You paste a results-page URL; this package visits the site and gathers every
result on it. It reads each page in the cheapest way that works and only tries
harder when it has to:

1. **Just download the page** — plain HTML, a PDF, a spreadsheet, a JSON feed.
2. **Open it in a real (headless) browser** — for modern app-style sites that
   need JavaScript to show their results. It runs the page, reads the finished
   text, watches the data the page fetches in the background, and takes a picture.
3. **Let the AI look at the picture** — a last resort for pages whose results are
   only in an image (handled in a later part of the feature).

Whatever it finds is saved into a little folder of files, zipped up, and handed to
the same pipeline that already handles uploaded files — so nothing downstream has
to change.

It works for **any sport** (it looks for the *shapes* of results — times, scores,
placings, distances — never specific sports or websites) and it is careful about
safety: it never visits private/internal addresses, it stays on the site you gave
it, and it has hard limits on how much it will fetch.

Plain-English words: see ../../../GLOSSARY.md
