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
