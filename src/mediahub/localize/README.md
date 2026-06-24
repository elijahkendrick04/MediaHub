# `localize/` — say it in their language (roadmap 1.24)

This folder turns one finished piece of club content into the **same content in
another language** — a Welsh version of a caption, a French meet recap, an
Arabic story card — without losing the bits that matter.

Welsh comes first on purpose: lots of clubs in Wales post bilingually, and "we
do proper Welsh, not Google-Translate Welsh" is a real reason a club picks us.

## The golden rules (same as everywhere in MediaHub)

- **A human still says yes.** A translated card goes into the review queue next
  to the original, as a pair, and a person approves the pair before anything is
  exported. Nothing auto-posts.
- **No faking it.** Translation is done by the AI provider. If no provider is
  set up, we show an honest error — we never hand back the English text
  pretending it's Welsh, and never a word-for-word mangle.
- **The important words are protected.** "PB" stays "PB". Swimmers' names, club
  names, times and hashtags are never changed. Stroke and event names use the
  *right* word in the language (verified Welsh terms are built in).

## What's in here

| File | What it does (in plain words) |
|------|-------------------------------|
| `translate.py` | Does the translating. Sends the card's words to the AI with strict rules, checks the answer, and reports anything that looks off. Does a whole card in one go. |
| `glossary.py` | The list of words to protect or translate a fixed way (PB, DQ, freestyle → *dull rhydd*…). One list per sport. |
| `scripts.py` | Facts the picture-maker needs for other alphabets: which writing system a language uses, whether it reads right-to-left (Arabic, Urdu), and which font covers its letters. |

## What lives elsewhere

- **Which languages exist** (and their names + caption hints) is in
  `web/languages.py` — the one registry, shared with the caption writer. This
  folder reuses it for language names.
- **Re-drawing the card** in the new language (fonts, right-to-left, making long
  words fit) is the graphic renderer's job; `scripts.py` is the bit of shared
  knowledge it reads from here.
