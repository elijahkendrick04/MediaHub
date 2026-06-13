"""club_qa — ask questions about the club's own results data.

A bounded tool-loop Q&A surface ("when did Ella last PB in 100 Free?"):
the model is given three read-only tools over this organisation's
processed runs and athlete registry and must answer only from what they
return, citing the meets it used. Grounded in the deterministic ledger —
no vector store, no web access, no invented facts. When no LLM provider
is configured the question fails honestly instead of guessing.
"""

from __future__ import annotations

from .agent import QAAnswer, QAEnv, answer_club_question

__all__ = ["QAAnswer", "QAEnv", "answer_club_question"]
