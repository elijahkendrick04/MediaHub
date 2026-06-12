"""Data-protection compliance engine.

In plain words: the law gives swimmers and parents rights over their data
(complain, see it, fix it, delete it, say "don't post my child"), and gives
clubs duties (a lawful basis, retention limits, honest notices). This package
is where those rights and duties become working code instead of paperwork.

Modules
-------
- ``store``      — shared append-only JSONL ledger under ``DATA_DIR/compliance/``
- ``complaints`` — s.164A DPA 2018 complaints intake + 30-day acknowledgement
- ``incidents``  — internal incident / breach register (Art 33(5))

The evidence documents live in ``docs/compliance/``.
"""
