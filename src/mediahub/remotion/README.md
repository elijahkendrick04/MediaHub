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
