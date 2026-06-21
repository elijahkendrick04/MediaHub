"""data_hub._aiutil — tiny helpers for the AI *suggestion* surfaces (1.13).

The data hub uses AI only to *suggest* — a derivation formula, or the columns
for a new table — never to compute a value or fill a cell. These helpers peel a
JSON object/array out of an LLM reply (mirroring ``creative_brief.ai_director``)
so a suggestion can be turned into a structured proposal for a human to confirm.

There is no template fallback here: the callers raise ``ProviderNotConfigured``
when no provider is set, so the operator sees an honest error.
"""

from __future__ import annotations

import json
from typing import Optional


def _strip_fences(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s.lstrip("`")
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    return s


def parse_json_object(text: str) -> Optional[dict]:
    s = _strip_fences(text)
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(s[start : end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def parse_json_array(text: str) -> Optional[list]:
    s = _strip_fences(text)
    start, end = s.find("["), s.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        arr = json.loads(s[start : end + 1])
    except json.JSONDecodeError:
        return None
    return arr if isinstance(arr, list) else None


__all__ = ["parse_json_object", "parse_json_array"]
