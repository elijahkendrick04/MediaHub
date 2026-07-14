# recognition

The "what's special here?" brain that works for *any* sport — it runs the detectors
and the ranker. On its own it doesn't know swimming; sport-specific parts plug into
it (see `recognition_swim`).

`swim_tiers.py` sits on top of the ranker's output: it groups the several
achievements one race can emit back into distinct swims, scores every swim, and
labels the standouts — so the UI can say "5 standout swims" instead of the
inflated raw detection count, list every swim ranked (standouts first), and let
a human promote an unflagged swim to a custom highlight. Deterministic and
read-only over the persisted report — it never re-ranks.

Plain-English words ("detector bus", "ranker"): see ../../../GLOSSARY.md
