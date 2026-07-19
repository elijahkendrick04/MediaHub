"""
swimmingresults/names.py — name normalisation + safe fuzzy matching.

The hard part of the swimmingresults.org adapter is not fetching a PB page — it
is matching the swimmer in a meet file to the swimmer in a club's online roster
when the two spell the name differently ("Charlie" vs "Charles", "Sam" vs
"Samuel", a missing accent, an initial). Per the maintainer's rule:

    same club + same age + a close name  ==  the same person.

Two people at one club, the same age, with confusably-similar names is
vanishingly rare, so this risk is accepted deliberately. Club and age are
enforced by the CALLER (it only ever compares names already filtered to one
club + one age group); this module supplies the "close name" half.

A non-match is a miss (no PB asserted), never a wrong PB — so the matcher is
tuned to be confident, not greedy.
"""

from __future__ import annotations

import re
import unicodedata

_NONALNUM = re.compile(r"[^a-z0-9 ]")
_WS = re.compile(r"\s+")

# Common English given-name nicknames ↔ formal forms. Folded to a shared
# canonical token so "Charlie"/"Charles" compare equal. Deliberately small and
# high-precision — obscure or ambiguous nicknames are left out so the matcher
# never merges two genuinely different names. Each set maps to its first member.
_NICKNAME_GROUPS: list[set[str]] = [
    {"charles", "charlie", "chas"},
    {"samuel", "sam", "sammy"},
    {"william", "will", "bill", "billy", "liam"},
    {"robert", "rob", "robbie", "bob", "bobby"},
    {"thomas", "tom", "tommy"},
    {"james", "jamie", "jim", "jimmy"},
    {"joseph", "joe", "joey"},
    {"benjamin", "ben", "benji"},
    {"matthew", "matt", "matty"},
    {"daniel", "dan", "danny"},
    {"michael", "mike", "mick", "micky"},
    {"nicholas", "nick", "nicky"},
    {"christopher", "chris"},
    {"alexander", "alex", "alexandra", "alexandria", "lex", "sandy"},
    {"edward", "ed", "eddie", "ted", "teddy", "ned"},
    {"anthony", "tony", "ant"},
    {"andrew", "andy", "drew"},
    {"david", "dave", "davy"},
    {"jonathan", "jon", "jonny", "john", "johnny"},
    {"katherine", "katharine", "catherine", "kate", "katie", "kathy", "cat", "kat"},
    {"elizabeth", "liz", "lizzie", "beth", "betsy", "eliza", "libby", "betty"},
    {"isabel", "isabella", "isabelle", "isobel", "isobella", "izzy", "izzie", "bella", "belle"},
    {"olivia", "liv", "livvy"},
    {"amelia", "amy", "millie", "mia"},
    {"emily", "em", "emmy", "millie"},
    {"jessica", "jess", "jessie"},
    {"rebecca", "becca", "becky", "bex"},
    {"charlotte", "lottie", "lotty", "charlie", "char"},
    {"sophie", "sophia", "soph"},
    {"abigail", "abi", "abby", "gail"},
    {"georgia", "georgina", "george", "georgie"},
    {"victoria", "vic", "vicky", "tori"},
    {"eleanor", "ellie", "nell", "nelly", "lenny"},
    {"madeline", "madeleine", "maddie", "maddy"},
    {"grace", "gracie"},
    # "freya" is its own name — it was wrongly grouped with "freddie", which (being
    # the alphabetically-first, first-wins canonical) hijacked "freddie" so
    # Freddie↔Frederick failed while Freya↔Freddie matched. "freddie" belongs only
    # to the Frederick group below.
    {"frederick", "fred", "freddie", "freddy"},
    {"patrick", "pat", "paddy"},
    {"theodore", "theo", "ted", "teddy"},
    {"zachary", "zach", "zack"},
    {"maximilian", "max"},
    {"oliver", "olly", "ollie"},
    {"harrison", "harry", "harris"},
    {"henry", "harry", "hank"},
    {"raphael", "raffaelle", "raffaele", "raffy", "rafe", "raff"},
    {"rafferty", "rafferty", "raff"},
    {"laurence", "lawrence", "laurie", "loz", "laz"},
    {"lauren", "laurie", "loz", "ren"},
    {"jacob", "jake", "jakey"},
    {"dylan", "dyl"},
    {"evelyn", "evie", "eve", "evi"},
    {"florence", "flo", "florrie", "flossie"},
    {"penelope", "penny", "pen"},
    {"imogen", "immy", "imo"},
    {"martha", "marty", "mattie"},
    {"phoebe", "phoebs", "bee"},
]

# Build a token -> canonical-token map once.
_NICK_CANON: dict[str, str] = {}
for _grp in _NICKNAME_GROUPS:
    _canon = sorted(_grp)[0]
    for _member in _grp:
        # If a member appears in two groups (e.g. "millie", "harry"), keep the
        # first mapping; ambiguity means we should NOT collapse it aggressively.
        _NICK_CANON.setdefault(_member, _canon)


def fold(text: str) -> str:
    """Lowercase, strip accents, drop punctuation, collapse whitespace."""
    s = unicodedata.normalize("NFKD", text or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _NONALNUM.sub(" ", s.lower())
    return _WS.sub(" ", s).strip()


def _canon_token(tok: str) -> str:
    return _NICK_CANON.get(tok, tok)


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _close(a: str, b: str, *, max_budget: int | None = None) -> bool:
    """A conservative single-token similarity: nickname-equal, or one a prefix
    of the other (≥3 chars, e.g. "ben"/"benjamin"), or within a small edit
    distance scaled to length (handles "Eleanor"/"Elanor", "Sophie"/"Sofie").

    ``max_budget`` caps the length-scaled edit budget. Surname matching passes
    ``max_budget=1`` (deep-review #53) so a two-edit surname like Wilson/Watson
    is NOT treated as the same family, while first names keep the wider budget."""
    if not a or not b:
        return False
    if a == b:
        return True
    if _canon_token(a) == _canon_token(b):
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= 3 and long.startswith(short):
        return True
    # Allow 1 edit for very short names, 2 for longer ones — enough for spelling
    # variants ("Sophie"/"Sofie", "Aiden"/"Aidan") while staying tight. The
    # caller's club+age narrowing and unique-match requirement are the real
    # guard against collapsing two genuinely different people.
    budget = 1 if len(long) <= 4 else 2
    if max_budget is not None:
        budget = min(budget, max_budget)
    return _levenshtein(a, b) <= budget


def name_match(first_a: str, last_a: str, first_b: str, last_b: str) -> bool:
    """True if two names plausibly denote the same person.

    Requires the **last name** to match closely (surnames are stable) and the
    **first name** to match closely (nickname/spelling tolerant). The caller has
    already constrained the comparison to one club and one age group, so a close
    name here is the maintainer's accepted "same person" signal.
    """
    fa, la = fold(first_a), fold(last_a)
    fb, lb = fold(first_b), fold(last_b)
    if not (fa and la and fb and lb):
        return False

    # Surnames: exact-or-very-close (double-barrelled order tolerated by token
    # overlap). A surname mismatch is a hard no.
    la_toks, lb_toks = set(la.split()), set(lb.split())
    surname_ok = (
        la == lb
        or bool(la_toks & lb_toks)
        or _close(la.replace(" ", ""), lb.replace(" ", ""), max_budget=1)
    )
    if not surname_ok:
        return False

    # First names: compare leading given tokens (ignore middle names/initials).
    return _close(fa.split()[0], fb.split()[0])


def surname_match(last_a: str, last_b: str) -> bool:
    """True if two surnames plausibly denote the same family name — exact (folded),
    a shared token (double-barrelled), or a single typo away ("Galagher" /
    "Gallagher"). No nickname list involved: surnames are stable, so this lets the
    matcher lean on surname + age + time instead of a hand-maintained first-name
    dictionary."""
    la, lb = fold(last_a), fold(last_b)
    if not la or not lb:
        return False
    if la == lb:
        return True
    if set(la.split()) & set(lb.split()):
        return True
    return _close(la.replace(" ", ""), lb.replace(" ", ""), max_budget=1)


def first_lead(name: str) -> str:
    """The folded leading given-name token of a full name."""
    f = fold(name)
    return f.split()[0] if f else ""


def split_full_name(full: str) -> tuple[str, str]:
    """Split a roster display name ("Holly Greenslade", "Greenslade, Holly")
    into (first, last). Best-effort; the matcher is order-tolerant anyway."""
    full = (full or "").strip()
    if "," in full:
        last, _, first = full.partition(",")
        return first.strip(), last.strip()
    parts = full.split()
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    return full, ""
