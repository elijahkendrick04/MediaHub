# brand

A club's brand kit: its colours, fonts and tone of voice. MediaHub reads this so
every post looks and sounds like it came from that club.

Brand-DNA-from-URL (P1.5) lives here too: `dna_capture.py` reads a club's
website (safely — it refuses private/internal addresses) and
`palette_evidence.py` finds the real brand colours inside the club's own logo
pixels using the same free colour science as the theming engine. The AI only
*chooses roles* (which colour is primary vs accent) from that evidence — it can
never invent a colour the site doesn't actually use, and it runs just as well
on a local model as a hosted one.

The **brand platform** (1.12) lets one club hold more than one identity:

- `kits.py` — multiple **brand kits** per club (the primary livery, plus
  sponsor co-brands, event sub-brands, team/section kits and personal kits).
  A club that never touches this still gets exactly one "primary" kit made
  from its existing brand, so nothing changes for them.
- `check.py` — **Brand Check**: does a design obey the kit? It scores the
  colours, contrast, fonts and logo using only the same maths the rest of the
  engine uses (no guessing). **Brand Assist** adds optional AI notes and an
  auto-fix, and an auto-fix is only kept if it still passes the maths.
- `palette_file.py` — import a colour theme from an Adobe `.ase` or Color
  JSON file straight into a kit.
- `resweep.py` — when a kit changes, work out which old posts would look
  different and re-make them (after a human re-approves — nothing is posted
  automatically).

A kit can **lock** its colours/fonts/logo so a volunteer can't approve an
off-brand post, and can ask for more than one person to approve — those rules
are enforced in `workflow/` at approval time.
