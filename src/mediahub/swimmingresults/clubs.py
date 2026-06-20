"""
swimmingresults/clubs.py — resolve a club name to its swimmingresults.org code.

The event-rankings search keys clubs by an 8-character code (e.g. Torfaen
Dolphins Performance → ``TDOYEWAY``). The full registry of ~1,266 clubs is the
``TargetClub`` <select> on the event-rankings page; we fetch it once, cache it,
and fuzzy-match the club's display name to a code (the meet file may say
"Torfaen Dolphins" while the register says "Torfaen Dolphins Performance").

Generic swim words ("swimming", "club", "SC", …) are stripped before matching so
they don't dominate the overlap; a match must share the *distinctive* tokens.
"""

from __future__ import annotations

import html as _html
import logging
import re
import threading
import time
from typing import Optional

from .names import fold
from .transport import SR_BASE, SRFetchError, fetch

log = logging.getLogger(__name__)

_REGISTRY_URL = SR_BASE + "/eventrankings/"
_SELECT_RE = re.compile(r'<select[^>]*name=["\']TargetClub["\'][^>]*>(.*?)</select>', re.I | re.S)
_OPTION_RE = re.compile(r'<option[^>]*value=["\']([^"\']+)["\'][^>]*>(.*?)</option>', re.I | re.S)

# Truly generic tokens that carry no club identity.
# Distinctive words ("dolphins", "performance", "city", …) are kept: the matcher
# only requires the QUERY's tokens to be covered by the candidate, so a shorter
# meet-file name still matches a longer official name without stripping them.
_CLUB_GENERIC = {
    "sc", "asc", "club", "swimming", "swim", "swimmers", "aquatics", "aquatic",
    "amateur", "the", "of", "and", "team", "squad",
}

# Process-lifetime cache of {code: name}; the register changes rarely, so one
# fetch per worker is plenty. Guarded for the gunicorn-threads case.
_LOCK = threading.Lock()
_CACHE: dict[str, str] = {}
_CACHE_AT: float = 0.0
_TTL = 24 * 3600.0


def _distinctive(name: str) -> set[str]:
    return {t for t in fold(name).split() if t and t not in _CLUB_GENERIC}


def _load_registry(force: bool = False) -> dict[str, str]:
    """Return {code: club_name}, fetching + caching the TargetClub register."""
    global _CACHE_AT
    with _LOCK:
        fresh = _CACHE and (time.time() - _CACHE_AT) < _TTL
        if fresh and not force:
            return dict(_CACHE)
    try:
        body = fetch(_REGISTRY_URL)
    except SRFetchError as exc:
        log.warning("swimmingresults: could not load club register: %s", exc)
        with _LOCK:
            return dict(_CACHE)  # stale-but-usable beats nothing
    sel = _SELECT_RE.search(body)
    reg: dict[str, str] = {}
    if sel:
        for code, label in _OPTION_RE.findall(sel.group(1)):
            code = code.strip()
            label = _html.unescape(re.sub(r"<[^>]+>", " ", label)).strip()
            if code and code.upper() != "XXXX" and label:
                reg[code] = label
    if reg:
        with _LOCK:
            _CACHE.clear()
            _CACHE.update(reg)
            _CACHE_AT = time.time()
        log.info("swimmingresults: loaded %d clubs into the register", len(reg))
    return reg


def resolve_club_code(club_name: str, *, force_refresh: bool = False) -> Optional[str]:
    """Best swimmingresults.org club code for ``club_name``, or None.

    Exact (folded) name wins; otherwise the club whose distinctive tokens best
    cover the query's distinctive tokens, requiring full coverage of the query
    so a partial/garbage name doesn't snap to an unrelated club.
    """
    if not (club_name or "").strip():
        return None
    reg = _load_registry(force=force_refresh)
    if not reg:
        return None

    q_fold = fold(club_name)
    by_fold = {fold(name): code for code, name in reg.items()}
    if q_fold in by_fold:
        return by_fold[q_fold]

    q_tokens = _distinctive(club_name)
    if not q_tokens:
        return None

    best_code: Optional[str] = None
    best_score = 0.0
    for code, name in reg.items():
        c_tokens = _distinctive(name)
        if not c_tokens:
            continue
        shared = q_tokens & c_tokens
        if not shared:
            continue
        # Require the query's distinctive tokens to be (almost) fully present in
        # the candidate, then prefer the tightest club (fewest extra tokens).
        coverage = len(shared) / len(q_tokens)
        if coverage < 1.0:
            continue
        tightness = len(shared) / len(c_tokens)
        score = coverage + tightness
        if score > best_score:
            best_score, best_code = score, code
    return best_code
