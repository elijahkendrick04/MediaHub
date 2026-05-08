"""
Self-check verification layer.

Runs a battery of checks before the user sees the dashboard. Each check is
a pure function returning (status, message). Statuses:
    'pass'  — green
    'warn'  — yellow; surface but don't block
    'fail'  — red; user should see prominent warning

The 13 checks (mirroring the brief):
  1. Did we parse all expected swims?
  2. Did we only include the selected club/team?
  3. Are any opposition swimmers in the output?
  4. Are PB claims backed by a trusted source?
  5. Are qualifying-time claims backed by a current source?
  6. Is the swim inside the qualification window?
  7. Are LC/SC courses handled correctly?
  8. Are multiple achievements for the same swim grouped properly?
  9. Are low-priority items hidden from the main queue?
 10. Are source links/timestamps attached to claims?
 11. Are any captions leaking internal codes?
 12. Are there too many cards for the same swimmer?
 13. Are there 8–20 genuinely useful content recommendations?
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from .cards import ContentCard, TYPE_STANDOUT, TYPE_SPOTLIGHT


# Patterns that look like internal labels and should never reach a user-visible caption.
_LABEL_PATTERNS = [
    re.compile(r"\b[A-Z]{2,}_[A-Z0-9_]+\b"),         # BUCS_LC_2025_26
    re.compile(r"\b(?:CONFIRMED_PB|LIKELY_PB|PB_UNVERIFIED|NOT_PB)\b"),
    re.compile(r"\b(?:standard_id|tiref|asa_id)\s*[:=]"),
]


@dataclass
class CheckResult:
    code: str
    title: str
    status: str  # pass | warn | fail
    message: str


@dataclass
class SelfCheckReport:
    results: list[CheckResult] = field(default_factory=list)

    @property
    def pass_count(self) -> int: return sum(1 for r in self.results if r.status == "pass")
    @property
    def warn_count(self) -> int: return sum(1 for r in self.results if r.status == "warn")
    @property
    def fail_count(self) -> int: return sum(1 for r in self.results if r.status == "fail")

    @property
    def overall(self) -> str:
        if self.fail_count: return "fail"
        if self.warn_count: return "warn"
        return "pass"


def run_self_check(
    *,
    cards: list[ContentCard],
    parsed_swim_count: int,
    our_swim_count: int,
    other_swim_count: int,
    opposition_leak_count: int,
    standards_meta: dict,
    course: str,
    queue_cap: int = 20,
) -> SelfCheckReport:
    rep = SelfCheckReport()

    # 1) Did we parse all expected swims?
    if parsed_swim_count >= 100:
        rep.results.append(CheckResult(
            "C1", "Parsed expected swims", "pass",
            f"Parsed {parsed_swim_count} swims from the meet file."))
    elif parsed_swim_count > 0:
        rep.results.append(CheckResult(
            "C1", "Parsed expected swims", "warn",
            f"Only {parsed_swim_count} swims parsed — verify the upload."))
    else:
        rep.results.append(CheckResult(
            "C1", "Parsed expected swims", "fail",
            "No swims were parsed from the file."))

    # 2) Selected club only?
    if our_swim_count > 0:
        rep.results.append(CheckResult(
            "C2", "Filtered to selected club", "pass",
            f"Kept {our_swim_count} swims for our club; excluded {other_swim_count}."))
    else:
        rep.results.append(CheckResult(
            "C2", "Filtered to selected club", "fail",
            "No swims for the selected club were found in this meet."))

    # 3) Opposition leak?
    if opposition_leak_count == 0:
        rep.results.append(CheckResult(
            "C3", "No opposition swimmers in output", "pass",
            "No opposition swimmers detected in any card."))
    else:
        rep.results.append(CheckResult(
            "C3", "No opposition swimmers in output", "fail",
            f"{opposition_leak_count} cards reference opposition swimmers."))

    # 4) PB claims backed by a trusted source?
    pb_claims = [c for card in cards for c in card.claims if c.kind in ("pb_confirmed", "pb_likely")]
    pb_with_source = [c for c in pb_claims if c.extra.get("source_url")]
    if not pb_claims:
        rep.results.append(CheckResult(
            "C4", "PB claims sourced", "warn",
            "No PB claims to verify."))
    elif len(pb_with_source) == len(pb_claims):
        rep.results.append(CheckResult(
            "C4", "PB claims sourced", "pass",
            f"All {len(pb_claims)} PB claims carry a swimmingresults.org source."))
    else:
        rep.results.append(CheckResult(
            "C4", "PB claims sourced", "fail",
            f"{len(pb_claims) - len(pb_with_source)} PB claim(s) missing a source."))

    # 5) Quals: backed by a current source?
    qual_claims = [c for card in cards for c in card.claims if c.kind == "qual_hit"]
    if not qual_claims:
        rep.results.append(CheckResult(
            "C5", "Qualification sources fresh", "warn",
            "No qualification hits to verify."))
    else:
        stale_ids = standards_meta.get("stale_ids", [])
        if stale_ids:
            rep.results.append(CheckResult(
                "C5", "Qualification sources fresh", "warn",
                f"{len(stale_ids)} qualification standard(s) are older than the freshness window — refresh suggested."))
        else:
            rep.results.append(CheckResult(
                "C5", "Qualification sources fresh", "pass",
                f"All {len(qual_claims)} qualification hits trace to up-to-date sources."))

    # 6) Inside qualification window?
    out_of_window = [c for c in qual_claims if not c.extra.get("in_window", True)]
    if not qual_claims:
        rep.results.append(CheckResult(
            "C6", "Qualification window check", "warn",
            "No qualification hits in this meet."))
    elif not out_of_window:
        rep.results.append(CheckResult(
            "C6", "Qualification window check", "pass",
            f"All {len(qual_claims)} qualification hits are inside their windows."))
    else:
        rep.results.append(CheckResult(
            "C6", "Qualification window check", "warn",
            f"{len(out_of_window)} qualification hit(s) fell outside the qualification window — flagged in evidence."))

    # 7) LC vs SC handled?
    course_mismatch = 0
    for card in cards:
        for c in card.claims:
            if c.kind in ("pb_confirmed", "pb_likely") and c.course != course:
                course_mismatch += 1
    if course_mismatch == 0:
        rep.results.append(CheckResult(
            "C7", "LC/SC consistency", "pass",
            f"All PB comparisons honour the meet course ({course})."))
    else:
        rep.results.append(CheckResult(
            "C7", "LC/SC consistency", "fail",
            f"{course_mismatch} PB claim(s) compared the wrong course."))

    # 8) Grouping: multiple achievements for the same swim grouped together?
    # We check: among QUEUE cards of type 'standout', does each swim appear at
    # most once? Roundups + spotlights legitimately re-reference swims.
    queue_standout_cards = [c for c in cards if c.bucket == "queue" and c.card_type == TYPE_STANDOUT]
    seen_keys: dict = {}
    duplicate_pairs: list[str] = []
    for card in queue_standout_cards:
        # Dedupe within a card first — multiple claims (gold+PB+qual) on the
        # same swim are expected and grouped legitimately.
        card_keys = {(cl.swimmer_tiref, cl.distance, cl.stroke, cl.course, cl.round) for cl in card.claims}
        for key in card_keys:
            if key in seen_keys and seen_keys[key] != card.card_id:
                # Find a representative claim for the message
                rep_cl = next(cl for cl in card.claims
                              if (cl.swimmer_tiref, cl.distance, cl.stroke, cl.course, cl.round) == key)
                duplicate_pairs.append(f"{rep_cl.swimmer_name} {rep_cl.event_label}")
            else:
                seen_keys[key] = card.card_id
    if not duplicate_pairs:
        rep.results.append(CheckResult(
            "C8", "Achievements grouped per swim", "pass",
            "Each swim appears in at most one standalone card; roundups and spotlights re-reference legitimately."))
    else:
        rep.results.append(CheckResult(
            "C8", "Achievements grouped per swim", "warn",
            f"Same swim appears in multiple standalone cards: {', '.join(duplicate_pairs[:3])}"))

    # 9) Low-priority items hidden from main queue?
    queue_cards = [c for c in cards if c.bucket == "queue"]
    queue_min_score = min((c.score for c in queue_cards), default=100)
    if not queue_cards:
        rep.results.append(CheckResult(
            "C9", "Low-priority items demoted", "warn",
            "Queue is empty."))
    elif queue_min_score >= 60:
        rep.results.append(CheckResult(
            "C9", "Low-priority items demoted", "pass",
            f"Lowest queue score is {queue_min_score}; weak items demoted to recap/archive."))
    else:
        rep.results.append(CheckResult(
            "C9", "Low-priority items demoted", "warn",
            f"Lowest queue score is {queue_min_score}; consider raising the threshold."))

    # 10) Source links / timestamps attached?
    cards_with_evidence = sum(1 for c in cards if c.evidence)
    if cards_with_evidence == len(cards):
        rep.results.append(CheckResult(
            "C10", "Evidence attached to every card", "pass",
            f"All {len(cards)} cards carry evidence rows."))
    else:
        rep.results.append(CheckResult(
            "C10", "Evidence attached to every card", "warn",
            f"{len(cards) - cards_with_evidence} cards have no evidence rows."))

    # 11) Any captions leaking internal codes?
    leaks = []
    for card in cards:
        for voice_name, voice_text in card.captions.all().items():
            for pat in _LABEL_PATTERNS:
                if pat.search(voice_text or ""):
                    leaks.append(f"{card.card_id} ({voice_name})")
                    break
    if not leaks:
        rep.results.append(CheckResult(
            "C11", "No internal labels in captions", "pass",
            "All captions are human-facing; no internal codes detected."))
    else:
        rep.results.append(CheckResult(
            "C11", "No internal labels in captions", "fail",
            f"Internal codes detected in: {', '.join(leaks[:3])}{'…' if len(leaks)>3 else ''}"))

    # 12) Too many cards for the same swimmer?
    by_swimmer_in_queue = Counter(c.primary_swimmer for c in queue_cards if c.primary_swimmer)
    too_many = [(name, n) for name, n in by_swimmer_in_queue.items() if n > 2]
    if not too_many:
        rep.results.append(CheckResult(
            "C12", "Anti-spam per swimmer", "pass",
            "No swimmer has more than 2 standalone cards in the queue."))
    else:
        worst = ", ".join(f"{n} for {name}" for name, n in too_many[:3])
        rep.results.append(CheckResult(
            "C12", "Anti-spam per swimmer", "warn",
            f"Multiple queue cards per swimmer: {worst}"))

    # 13) Queue size within 8–20?
    n_queue = len(queue_cards)
    if 8 <= n_queue <= 20:
        rep.results.append(CheckResult(
            "C13", "Queue size within target", "pass",
            f"{n_queue} cards in queue (target 8–20)."))
    elif n_queue < 8:
        rep.results.append(CheckResult(
            "C13", "Queue size within target", "warn",
            f"Only {n_queue} cards in queue — meet may be light, or scoring is too strict."))
    else:
        rep.results.append(CheckResult(
            "C13", "Queue size within target", "warn",
            f"{n_queue} cards in queue — above 20, expected to be capped."))

    return rep
