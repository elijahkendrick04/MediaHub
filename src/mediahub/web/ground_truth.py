"""
Ground-truth validation mode.

The user pastes 5-15 expected "moments" from a meet (free text) and we
score the system: precision = how many of our cards match a ground-truth
moment; recall = how many ground-truth moments are surfaced by our cards.

Matching is fuzzy — we look for shared swimmer surname, distance, and
stroke. A moment can also be a free-text sentence; we tokenise.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field, asdict
from typing import Optional


_STROKE_WORDS = {
    "free": "FR", "freestyle": "FR",
    "back": "BK", "backstroke": "BK",
    "breast": "BR", "breaststroke": "BR",
    "fly": "FL", "butterfly": "FL",
    "im": "IM", "medley": "IM", "individual": "IM",
}


@dataclass
class GroundTruthMoment:
    raw: str
    swimmer: Optional[str] = None
    distance: Optional[int] = None
    stroke: Optional[str] = None


@dataclass
class GroundTruthMatch:
    moment: str
    matched_card: Optional[str] = None
    matched_headline: Optional[str] = None
    score: float = 0.0


@dataclass
class GroundTruthReport:
    moments: list[dict] = field(default_factory=list)
    matches: list[dict] = field(default_factory=list)
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    n_total_moments: int = 0
    n_total_cards: int = 0
    n_matched_moments: int = 0
    n_unmatched_moments: int = 0
    n_extra_cards: int = 0
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_moment(text: str) -> GroundTruthMoment:
    raw = text.strip()
    swimmer = None
    distance = None
    stroke = None

    # Distance: e.g. "100m", "200 m", "50"
    m = re.search(r"\b(\d{2,4})\s*m?\b", raw, re.IGNORECASE)
    if m:
        try:
            d = int(m.group(1))
            if d in (50, 100, 200, 400, 800, 1500, 25, 75):
                distance = d
        except Exception:
            pass

    # Stroke
    low = raw.lower()
    for word, code in _STROKE_WORDS.items():
        if re.search(rf"\b{word}\b", low):
            stroke = code
            break

    # Swimmer: very crude — look for capitalised two-word run
    m2 = re.search(r"\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\b", raw)
    if m2:
        swimmer = f"{m2.group(1)} {m2.group(2)}"

    return GroundTruthMoment(raw=raw, swimmer=swimmer, distance=distance, stroke=stroke)


def _score_match(moment: GroundTruthMoment, card) -> float:
    score = 0.0
    if moment.swimmer:
        last = moment.swimmer.split()[-1].lower()
        for nm in card.swimmer_names:
            if last in nm.lower():
                score += 0.5
                break
    # Card claims carry distance/stroke; check first
    for c in card.claims:
        if moment.distance and c.distance == moment.distance:
            score += 0.25
        if moment.stroke and c.stroke == moment.stroke:
            score += 0.25
        if score >= 0.75:
            break
    # Free-text fallback: surname appears anywhere in headline
    if score < 0.5 and moment.swimmer:
        last = moment.swimmer.split()[-1].lower()
        if last in card.headline.lower():
            score += 0.4
    return min(score, 1.0)


def evaluate(moments_text: str, cards: list) -> GroundTruthReport:
    moments = [_parse_moment(line) for line in moments_text.splitlines() if line.strip()]
    rep = GroundTruthReport(
        moments=[asdict(m) for m in moments],
        n_total_moments=len(moments),
        n_total_cards=len(cards),
    )

    matched_card_ids = set()
    n_matched = 0
    for m in moments:
        best_card = None
        best_score = 0.0
        for card in cards:
            s = _score_match(m, card)
            if s > best_score:
                best_score = s
                best_card = card
        if best_card and best_score >= 0.5:
            matched_card_ids.add(best_card.card_id)
            n_matched += 1
            rep.matches.append(asdict(GroundTruthMatch(
                moment=m.raw,
                matched_card=best_card.card_id,
                matched_headline=best_card.headline,
                score=round(best_score, 2),
            )))
        else:
            rep.matches.append(asdict(GroundTruthMatch(
                moment=m.raw, matched_card=None, score=round(best_score, 2),
            )))

    rep.n_matched_moments = n_matched
    rep.n_unmatched_moments = len(moments) - n_matched
    rep.n_extra_cards = max(0, len(cards) - len(matched_card_ids))

    rep.precision = (
        len(matched_card_ids) / len(cards) if cards else 0.0
    )
    rep.recall = (n_matched / len(moments)) if moments else 0.0
    if rep.precision + rep.recall:
        rep.f1 = (2 * rep.precision * rep.recall) / (rep.precision + rep.recall)

    rep.notes = (
        "Matching is fuzzy: swimmer surname + distance + stroke. "
        "A moment matches a card when score ≥ 0.5. "
        "Precision = matched / total cards. Recall = matched / total moments."
    )
    return rep
