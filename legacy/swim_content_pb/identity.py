"""
swim_content_pb/identity.py
Multi-strategy swimmer matcher.

NO FUZZY MATCHING. canonicalise_name is normalisation only:
  - uppercase
  - strip punctuation
  - collapse whitespace
  - normalise name order (sort components)

If names disagree after canonicalisation, mark needs_verification.
"""
from __future__ import annotations

import re
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .schema import IdentityMatch, ParsedSnapshot
    from .corrections import CorrectionsStore

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")

# Titles/suffixes/initials that we strip before comparison
_STRIP_WORDS = frozenset(["JR", "SR", "II", "III", "IV", "MR", "MRS", "MS", "DR"])


def canonicalise_name(name: str) -> str:
    """Normalise a name for comparison: uppercase, strip punctuation,
    collapse whitespace, sort given/family components.

    Handles formats:
      - "BRADLEY, MATHEW J"    (HY3 — LASTNAME, FIRSTNAME INITIAL)
      - "Mathew Bradley"       (SR  — Firstname Lastname)
      - "MATHEW J BRADLEY"

    Returns a canonical form like "BRADLEY MATHEW" (surname first, given names
    sorted alphabetically, no middle initials — single letters stripped).

    NO FUZZY MATCHING. This only normalises format differences.
    """
    if not name:
        return ""

    # 1. Uppercase
    s = name.upper()

    # 2. Strip punctuation (but NOT the comma first — we need it for HY3 format detection)
    #    Handle HY3 "LASTNAME, FIRSTNAME" format by splitting on comma
    if "," in s:
        parts = s.split(",", 1)
        surname = parts[0].strip()
        given = parts[1].strip() if len(parts) > 1 else ""
        tokens = [surname] + given.split()
    else:
        # "Firstname Lastname" or "FIRSTNAME MIDDLE LASTNAME"
        # Assume last token is surname for sorting purposes — but we won't try to
        # guess which is surname, we just normalise and sort alphabetically
        # so both "MATHEW BRADLEY" and "BRADLEY MATHEW" yield the same canonical form
        s_clean = _PUNCT_RE.sub(" ", s)
        tokens = _WS_RE.sub(" ", s_clean).strip().split()

    # 3. Strip punctuation from each token
    tokens = [_PUNCT_RE.sub("", t).strip() for t in tokens]

    # 4. Remove empty tokens and single-letter initials and known suffixes
    tokens = [t for t in tokens if t and len(t) > 1 and t not in _STRIP_WORDS]

    if not tokens:
        return ""

    # 5. Sort tokens alphabetically so "MATHEW BRADLEY" == "BRADLEY MATHEW"
    tokens.sort()

    return " ".join(tokens)


def match_swimmer(
    *,
    hy3_name: str,
    asa_id: Optional[str],
    sr_snapshot: Optional["ParsedSnapshot"],
    corrections: "CorrectionsStore",
    run_id: str,
) -> "IdentityMatch":
    """Apply the matching strategy in priority order:
      1. corrections.has_override(run_id, hy3_swimmer_key) → manual_override
      2. asa_id present + sr_snapshot.fetch_ok + canonical names match
         → asa_id_verified, safe_to_use=True, confidence=1.0
      3. asa_id present + sr_snapshot.fetch_ok + names DON'T match
         → needs_verification, safe_to_use=False, confidence=0.0
      4. asa_id present + sr_snapshot.fetch_failed
         → asa_id_unverified, safe_to_use=False, confidence=0.0
      5. No asa_id at all
         → no_id, safe_to_use=False, confidence=0.0
    """
    from .schema import IdentityMatch

    swimmer_key = asa_id if asa_id else f"name:{hy3_name}"
    canonical_hy3 = canonicalise_name(hy3_name)

    # 1. Check for manual override
    override = corrections.get_override(run_id, swimmer_key)
    if override:
        action = override.get("action", "")
        if action == "ignore_pb":
            return IdentityMatch(
                asa_id=asa_id,
                hy3_name=hy3_name,
                sr_name=None,
                canonical_hy3_name=canonical_hy3,
                canonical_sr_name=None,
                method="manual_override",
                confidence=1.0,
                safe_to_use=False,
                notes=[f"User override: ignore PB for this swimmer. Reason: {override.get('reason', '')}"],
                alternative_matches=[],
            )
        if action == "override_asa_id":
            new_id = override.get("new_asa_id", "")
            return IdentityMatch(
                asa_id=new_id,
                hy3_name=hy3_name,
                sr_name=None,
                canonical_hy3_name=canonical_hy3,
                canonical_sr_name=None,
                method="manual_override",
                confidence=1.0,
                safe_to_use=True,
                notes=[f"User override: ASA ID changed to {new_id}. Original: {asa_id}. Note: {override.get('note', '')}"],
                alternative_matches=[],
            )

    # 2-5: No override — apply rules
    if not asa_id:
        return IdentityMatch(
            asa_id=None,
            hy3_name=hy3_name,
            sr_name=None,
            canonical_hy3_name=canonical_hy3,
            canonical_sr_name=None,
            method="no_id",
            confidence=0.0,
            safe_to_use=False,
            notes=["No ASA member ID in HY3 file."],
            alternative_matches=[],
        )

    if sr_snapshot is None or not sr_snapshot.fetch_ok:
        error_note = ""
        if sr_snapshot and sr_snapshot.error:
            error_note = f" Error: {sr_snapshot.error}"
        return IdentityMatch(
            asa_id=asa_id,
            hy3_name=hy3_name,
            sr_name=None,
            canonical_hy3_name=canonical_hy3,
            canonical_sr_name=None,
            method="asa_id_unverified",
            confidence=0.0,
            safe_to_use=False,
            notes=[f"Fetch failed for ASA ID {asa_id}.{error_note}"],
            alternative_matches=[],
        )

    # Fetch succeeded — compare names
    sr_name = sr_snapshot.swimmer_name
    canonical_sr = canonicalise_name(sr_name) if sr_name else ""

    if not sr_name or not canonical_sr:
        # SR page returned no name — can't verify
        return IdentityMatch(
            asa_id=asa_id,
            hy3_name=hy3_name,
            sr_name=sr_name,
            canonical_hy3_name=canonical_hy3,
            canonical_sr_name=canonical_sr or None,
            method="asa_id_unverified",
            confidence=0.0,
            safe_to_use=False,
            notes=["SR page returned no swimmer name; cannot verify identity."],
            alternative_matches=[],
        )

    if canonical_hy3 == canonical_sr:
        return IdentityMatch(
            asa_id=asa_id,
            hy3_name=hy3_name,
            sr_name=sr_name,
            canonical_hy3_name=canonical_hy3,
            canonical_sr_name=canonical_sr,
            method="asa_id_verified",
            confidence=1.0,
            safe_to_use=True,
            notes=[
                f"HY3 name '{hy3_name}' → canonical '{canonical_hy3}'",
                f"SR name '{sr_name}' → canonical '{canonical_sr}'",
                "Canonical names match.",
            ],
            alternative_matches=[],
        )
    else:
        return IdentityMatch(
            asa_id=asa_id,
            hy3_name=hy3_name,
            sr_name=sr_name,
            canonical_hy3_name=canonical_hy3,
            canonical_sr_name=canonical_sr,
            method="needs_verification",
            confidence=0.0,
            safe_to_use=False,
            notes=[
                f"HY3 name '{hy3_name}' → canonical '{canonical_hy3}'",
                f"SR name '{sr_name}' → canonical '{canonical_sr}'",
                "Canonical mismatch — human verification required before PB claims are made.",
            ],
            alternative_matches=[],
        )
