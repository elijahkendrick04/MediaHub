# remotion

The video-maker, written in JavaScript (a tool called Remotion). It turns cards
into short, club-branded MP4 videos for stories and reels. The Python app reaches
it through the `visual` folder.

What the videos can do:

- **Every still archetype has a matching video look.** A "big number" card
  becomes a big-number video; a medal card becomes a centred spotlight with a
  ring badge; a photo card becomes a broadcast-style lower third. Twelve still
  layouts map onto seven distinct video scenes, so a pack of videos doesn't
  all look the same.
- **The AI director's motion choice is obeyed.** The design spec's
  `motion_intent` (fade in, snap, slide up, kinetic type, parallax, …) picks
  the animation programme for that card.
- **Colours always match the approved still.** The exact same colour roles the
  still graphic painted (including medal gold/silver/bronze tints) ride into
  the video, so the video can never disagree with the card the club approved.
- **Three sizes from one composition:** story (1080×1920), square (1080×1080)
  and landscape (1920×1080) — `render.js` takes `--width`/`--height`.
- **Reels end properly.** A reel is: branded cover (with honest counts like
  "3 PBS" taken straight from the card labels) → one beat per top card (the
  top-ranked moment gets a little longer) → a club outro with the logo and a
  follow message.
- **Kinetic text can reveal letter by letter, in different orders.** For the
  "kinetic type" and "cascade" looks, a headline can animate one character at a
  time. The _order_ those letters appear in isn't always plain left-to-right:
  a small vocabulary (`compositions/sprint/rangeSelector.ts`, MediaHub's take on
  After Effects' text "range selectors") can reveal them in reverse, from the
  middle outwards, or in a shuffled scatter — and can bunch the timing early or
  late. Which order a card gets is decided only by the card's mood and its
  variation seed (never randomness), so calm/precise moods stay a plain sweep
  while energetic moods get the scatter, and two sibling cards differ. The
  default ("index", "linear") is exactly the plain left-to-right sweep, so a
  card that doesn't opt into the variety looks identical to before.

Two entry scripts call into these compositions:

- `render.js` — the production one: renders a whole composition to an **MP4**.
- `render_frame.js` — the test one: renders a few **single frames** to PNG (via
  Remotion's `renderStill`) so the Python side can pixel-diff them against
  saved reference pictures and catch a video that quietly stopped looking right.
  See `visual/motion_regression.py` and `scripts/motion_vr.py`.
