"""The single per-type autonomous-publish gate (P2.3).

One chokepoint answers "may this card publish without a human?" — and shows
its working. A ``fully_autonomous`` post must clear **every** guardrail in
``docs/AUTONOMY_MODEL.md`` §4 before it may publish; anything else stays in
the human review queue (``TypeGated``-equivalent behaviour). The checks, in
order:

  1. **Global kill switch** (``publishing.kill_switch``) — one env var halts
     all autonomous publishing instantly, checked first on every evaluation.
  2. **Per-type policy** (``publishing.per_type_policy``, P2.4) — the org must
     have explicitly opted this post type into ``fully_autonomous``.
  3. **Provenance / trust** — the card's deterministic safe-to-post verdict
     (``recognition.schema.SafeToPost`` levels or the run trust report's
     post/review/hold vocabulary) must be affirmatively safe. No verdict =
     no autonomy (fail closed).
  4. **Confidence gate** — the card's deterministic confidence must clear the
     per-type threshold (operator-tunable, default 0.85, floor 0.5). Below
     it the card falls back to human approval (AUTONOMY_MODEL §2.2).
  5. **Brand safety** — deterministic caption checks: non-empty, no AI-tell
     ban-list phrases, none of the org's ``brand_phrases_to_avoid``, within
     platform length. (Prose brand-guideline rules are enforced upstream in
     generation prompts and by human review — a regex cannot honestly
     enforce prose, so it does not pretend to.)
  6. **Safeguarding** (ADR-0003 posture) — a card known to concern a minor
     (age < 18 present in its facts) never auto-publishes; minors' content
     is always a human decision.
  7. **Rate limit** — per-org posting caps over the posting log (hourly +
     daily, env-tunable) so autonomy can never flood a club's channels.

Every evaluation — allowed or blocked — is appended to the org's immutable
audit ledger (``workflow.autonomy.AuditLog``), satisfying the Phase-2 exit
criterion that every autonomous decision is recorded and explainable.

This gate decides *publishability*; it never generates, edits, or chooses
content. The narrow ``type_gate.assert_type_publishing_allowed`` (P2.4)
remains the policy+kill-switch subset for callers without card context.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from mediahub.club_platform.post_types import canonical_slug
from mediahub.publishing.kill_switch import publish_kill_switch_engaged
from mediahub.publishing.per_type_policy import AutonomyLevel, load_policy

DEFAULT_CONFIDENCE_THRESHOLD = 0.85
MIN_CONFIDENCE_THRESHOLD = 0.5
MAX_CAPTION_CHARS = 2200  # the strictest mainstream platform cap (Instagram)

# Rate-cap env vars: MEDIAHUB_AUTONOMOUS_HOURLY_CAP / _DAILY_CAP (see
# _hourly_cap/_daily_cap — read with literal names so ENV_INVENTORY sees them).
DEFAULT_HOURLY_CAP = 4
DEFAULT_DAILY_CAP = 12

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")
_LOCK = threading.Lock()

# Both deterministic safe-to-post vocabularies in the codebase, normalised:
# recognition.schema.SafeToPost uses safe/needs_review/do_not_post; the run
# trust report uses post/review/hold. Only the affirmative levels pass.
_SAFE_LEVELS = frozenset({"safe", "post"})
_KNOWN_UNSAFE_LEVELS = frozenset({"needs_review", "review", "do_not_post", "hold"})


class PublishGateBlocked(RuntimeError):
    """Raised by ``assert_publish_gate`` when any guardrail fails.

    Callers treat this as "queue for human review" — the system's default
    state — never as an error to retry around.
    """

    def __init__(self, verdict: "GateVerdict"):
        self.verdict = verdict
        super().__init__(
            f"Autonomous publishing blocked for {verdict.content_type!r} "
            f"(org {verdict.org_id!r}): " + "; ".join(verdict.blockers())
        )


@dataclass
class GateCheck:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class GateVerdict:
    """The gate's full, explainable decision for one card."""

    org_id: str
    content_type: str  # canonical slug (ADR-0013)
    allowed: bool
    checks: list[GateCheck] = field(default_factory=list)
    run_id: str = ""
    card_id: str = ""
    evaluated_at: str = ""

    def blockers(self) -> list[str]:
        return [f"{c.name}: {c.detail}" for c in self.checks if not c.passed]

    def to_dict(self) -> dict:
        return {
            "org_id": self.org_id,
            "content_type": self.content_type,
            "allowed": self.allowed,
            "checks": [c.to_dict() for c in self.checks],
            "run_id": self.run_id,
            "card_id": self.card_id,
            "evaluated_at": self.evaluated_at,
        }


# ---------------------------------------------------------------------------
# Per-type confidence thresholds (operator-tunable, separate file so the
# P2.4 policy file's shape — and every consumer of it — stays untouched)
# ---------------------------------------------------------------------------


def _sanitise_org(org_id: str) -> str:
    s = _SAFE.sub("_", (org_id or "unknown").strip()) or "unknown"
    return s[:120]


def _thresholds_path(org_id: str, data_dir: Optional[Path] = None) -> Path:
    base = Path(data_dir) if data_dir is not None else Path(os.environ.get("DATA_DIR", "."))
    d = base / "per_type_autonomy"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{_sanitise_org(org_id)}__thresholds.json"


def _clamp_threshold(value: object) -> Optional[float]:
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return max(MIN_CONFIDENCE_THRESHOLD, min(1.0, f))


def load_thresholds(org_id: str, *, data_dir: Optional[Path] = None) -> dict[str, float]:
    """The org's per-type confidence thresholds (canonical slugs → float)."""
    path = _thresholds_path(org_id, data_dir)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        clamped = _clamp_threshold(value)
        if clamped is not None:
            out[canonical_slug(key)] = clamped
    return out


def save_thresholds(
    org_id: str, thresholds: dict, *, data_dir: Optional[Path] = None
) -> dict[str, float]:
    """Validate, clamp and persist per-type thresholds; returns the saved map."""
    clean: dict[str, float] = {}
    for key, value in (thresholds or {}).items():
        slug = canonical_slug(key)
        clamped = _clamp_threshold(value)
        if slug and clamped is not None:
            clean[slug] = clamped
    path = _thresholds_path(org_id, data_dir)
    with _LOCK:
        path.write_text(json.dumps(clean, indent=2, sort_keys=True), encoding="utf-8")
    return clean


def threshold_for(org_id: str, content_type: str, *, data_dir: Optional[Path] = None) -> float:
    return load_thresholds(org_id, data_dir=data_dir).get(
        canonical_slug(content_type), DEFAULT_CONFIDENCE_THRESHOLD
    )


# ---------------------------------------------------------------------------
# Individual guardrails
# ---------------------------------------------------------------------------


def _provenance_level(card: Optional[dict]) -> tuple[Optional[str], str]:
    """Normalised safe-to-post level from either vocabulary, plus its reason."""
    if not isinstance(card, dict):
        return None, ""
    raw = card.get("safe_to_post")
    if isinstance(raw, dict):
        return str(raw.get("level") or "").strip().lower(), str(raw.get("reason") or "")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower(), ""
    return None, ""


def _check_provenance(card: Optional[dict]) -> GateCheck:
    level, reason = _provenance_level(card)
    if level is None:
        return GateCheck(
            "provenance",
            False,
            "no safe-to-post verdict on this card — autonomy requires affirmative provenance",
        )
    if level in _SAFE_LEVELS:
        return GateCheck(
            "provenance",
            True,
            f"safe-to-post verdict {level!r}" + (f" ({reason})" if reason else ""),
        )
    if level in _KNOWN_UNSAFE_LEVELS:
        return GateCheck(
            "provenance",
            False,
            f"safe-to-post verdict {level!r} requires human review"
            + (f" ({reason})" if reason else ""),
        )
    return GateCheck(
        "provenance", False, f"unrecognised safe-to-post verdict {level!r} — failing closed"
    )


def _check_confidence(card: Optional[dict], threshold: float) -> GateCheck:
    raw = (card or {}).get("confidence")
    try:
        conf = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return GateCheck(
            "confidence",
            False,
            "no numeric confidence on this card — autonomy requires the deterministic score",
        )
    if 0.0 <= conf <= 1.0 and conf >= threshold:
        return GateCheck("confidence", True, f"{conf:.2f} ≥ threshold {threshold:.2f}")
    return GateCheck(
        "confidence",
        False,
        f"{conf:.2f} < threshold {threshold:.2f} — falls back to human approval",
    )


def _ai_tell_hits(caption: str) -> list[str]:
    try:
        from mediahub.web.ai_caption import AI_TELL_BAN_LIST  # noqa: PLC0415
    except Exception:  # pragma: no cover - core module
        AI_TELL_BAN_LIST = frozenset()
    low = caption.lower()
    return sorted({phrase for phrase in AI_TELL_BAN_LIST if phrase in low})


def _avoid_phrase_hits(caption: str, avoid_phrases: list[str]) -> list[str]:
    low = caption.lower()
    return [p for p in avoid_phrases if p and p.strip() and p.strip().lower() in low]


def _check_brand_safety(caption: str, *, avoid_phrases: Optional[list[str]] = None) -> GateCheck:
    text = (caption or "").strip()
    if not text:
        return GateCheck(
            "brand_safety", False, "no caption text to check — nothing may publish unchecked"
        )
    if len(text) > MAX_CAPTION_CHARS:
        return GateCheck(
            "brand_safety",
            False,
            f"caption is {len(text)} chars (> {MAX_CAPTION_CHARS} platform cap)",
        )
    tells = _ai_tell_hits(text)
    if tells:
        return GateCheck("brand_safety", False, "AI-tell phrase(s) present: " + ", ".join(tells))
    hits = _avoid_phrase_hits(text, avoid_phrases or [])
    if hits:
        return GateCheck(
            "brand_safety",
            False,
            "contains the org's banned phrase(s): " + ", ".join(repr(h) for h in hits),
        )
    return GateCheck("brand_safety", True, f"caption clear ({len(text)} chars, no banned phrases)")


def _age_of(card: Optional[dict]) -> Optional[int]:
    if not isinstance(card, dict):
        return None
    for source in (card, card.get("raw_facts") or {}):
        if not isinstance(source, dict):
            continue
        raw = source.get("age")
        try:
            age = int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if 0 < age < 130:
            return age
    return None


def _check_safeguarding(card: Optional[dict]) -> GateCheck:
    age = _age_of(card)
    if age is not None and age < 18:
        return GateCheck(
            "safeguarding",
            False,
            f"card concerns a minor (age {age}) — minors' content is always a human decision (ADR-0003)",
        )
    detail = "no minor's age in the card's facts" if age is None else f"athlete age {age}"
    return GateCheck("safeguarding", True, detail)


def _check_consent(org_id: str, card: Optional[dict]) -> GateCheck:
    """ONE consent answer at the gate — both registries, fail closed.

    Two consent systems exist by design history: the W.2 safeguarding
    registry (per-athlete levels: full/no_photo/initials_only/
    do_not_feature, resolved onto cards at pack build) and the compliance
    ledger (refusals/revocations, Art 18 restriction, opt-in mode with
    parental flags, erasure suppression records). A card publishes only
    when NEITHER blocks; if either registry is unreadable the card is
    BLOCKED, never waved through.
    """
    # 1. W.2 safeguarding policy (card-resolved when present, else live).
    consent = (card or {}).get("consent")
    if isinstance(consent, dict) and consent.get("level"):
        if consent.get("blocked"):
            return GateCheck(
                "consent",
                False,
                consent.get("reason") or "athlete consent does not allow featuring",
            )
    else:
        name = ""
        for source in (card or {}), ((card or {}).get("achievement") or {}):
            name = (source.get("swimmer_name") or "").strip()
            if name:
                break
        if name:
            try:
                from mediahub.safeguarding import effective_policy, regime_active  # noqa: PLC0415

                if regime_active(org_id):
                    policy = effective_policy(org_id, name)
                    if policy.blocked:
                        return GateCheck("consent", False, policy.reason)
            except Exception:
                # Registry unreadable must fail CLOSED at the publish gate —
                # autonomous publishing without consent visibility is the
                # exact failure W.2 exists to prevent.
                return GateCheck(
                    "consent", False, "consent registry unavailable — blocked pending review"
                )

    # 2. Compliance ledger (opt-outs, Art 18 restriction, opt-in/parental
    # mode, erasure suppression) — same decision function as the approval
    # route and the pack filter.
    try:
        from mediahub.compliance.gate import consent_block_reason_for_card  # noqa: PLC0415

        reason = consent_block_reason_for_card(org_id, card)
    except Exception as exc:  # pragma: no cover - defensive
        return GateCheck("consent", False, f"consent registry unreadable ({exc}) — blocking")
    if reason:
        return GateCheck("consent", False, reason)
    return GateCheck("consent", True, "no consent registry blocks this athlete")


def _parse_cap(raw: object, default: int) -> int:
    try:
        value = int(raw if raw not in (None, "") else default)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(0, value)


def _hourly_cap() -> int:
    return _parse_cap(os.environ.get("MEDIAHUB_AUTONOMOUS_HOURLY_CAP"), DEFAULT_HOURLY_CAP)


def _daily_cap() -> int:
    return _parse_cap(os.environ.get("MEDIAHUB_AUTONOMOUS_DAILY_CAP"), DEFAULT_DAILY_CAP)


def _check_rate_limit(org_id: str, *, now: Optional[datetime] = None) -> GateCheck:
    hourly_cap = _hourly_cap()
    daily_cap = _daily_cap()
    try:
        from mediahub.publishing.posting_log import recent_attempts  # noqa: PLC0415

        attempts = recent_attempts(org_id, limit=200)
    except Exception:
        attempts = []
    ts_now = now or datetime.now(timezone.utc)
    hour_ago = ts_now - timedelta(hours=1)
    day_ago = ts_now - timedelta(days=1)
    in_hour = in_day = 0
    for row in attempts:
        if (row.get("status") or "") != "ok":
            continue
        raw = str(row.get("attempted_at") or "")
        try:
            when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when >= day_ago:
            in_day += 1
        if when >= hour_ago:
            in_hour += 1
    if hourly_cap and in_hour >= hourly_cap:
        return GateCheck(
            "rate_limit", False, f"{in_hour} posts in the last hour ≥ hourly cap {hourly_cap}"
        )
    if daily_cap and in_day >= daily_cap:
        return GateCheck(
            "rate_limit", False, f"{in_day} posts in the last 24h ≥ daily cap {daily_cap}"
        )
    return GateCheck(
        "rate_limit",
        True,
        f"{in_hour} posts last hour (cap {hourly_cap}), {in_day} last 24h (cap {daily_cap})",
    )


def _avoid_phrases_for(org_id: str) -> list[str]:
    try:
        from mediahub.web.club_profile import load_profile  # noqa: PLC0415

        prof = load_profile(org_id)
    except Exception:
        prof = None
    phrases = list(getattr(prof, "brand_phrases_to_avoid", []) or [])
    return [str(p) for p in phrases if str(p or "").strip()]


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def evaluate_publish_gate(
    org_id: str,
    content_type: str,
    *,
    card: Optional[dict] = None,
    caption: str = "",
    run_id: str = "",
    card_id: str = "",
    data_dir: Optional[Path] = None,
    now: Optional[datetime] = None,
    audit: bool = True,
) -> GateVerdict:
    """Evaluate every guardrail; return the full, explainable verdict.

    Never raises. All checks are evaluated (no short-circuit) so a blocked
    card's verdict answers "what ALL would have to change?", not just the
    first failure. ``audit=True`` appends the decision to the org's immutable
    audit ledger.
    """
    slug = canonical_slug(content_type)
    checks: list[GateCheck] = []

    if publish_kill_switch_engaged():
        checks.append(GateCheck("kill_switch", False, "global publish kill switch is engaged"))
    else:
        checks.append(GateCheck("kill_switch", True, "kill switch disengaged"))

    policy_level = AutonomyLevel.from_str(load_policy(org_id, data_dir=data_dir).get(slug))
    if policy_level.can_auto_publish:
        checks.append(GateCheck("type_policy", True, f"{slug!r} is fully_autonomous for this org"))
    else:
        checks.append(
            GateCheck(
                "type_policy",
                False,
                f"{slug!r} is {policy_level.value!r} — autonomous publishing not opted in",
            )
        )

    checks.append(_check_provenance(card))
    checks.append(_check_confidence(card, threshold_for(org_id, slug, data_dir=data_dir)))
    checks.append(_check_brand_safety(caption, avoid_phrases=_avoid_phrases_for(org_id)))
    checks.append(_check_safeguarding(card))
    checks.append(_check_consent(org_id, card))
    checks.append(_check_rate_limit(org_id, now=now))

    verdict = GateVerdict(
        org_id=org_id,
        content_type=slug,
        allowed=all(c.passed for c in checks),
        checks=checks,
        run_id=run_id,
        card_id=card_id,
        evaluated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )

    if audit:
        try:
            from mediahub.workflow.autonomy import AuditLog  # noqa: PLC0415

            AuditLog().record(
                org_id,
                f"gate:{run_id or '-'}:{card_id or uuid.uuid4().hex[:8]}",
                "publish_gate",
                tool="evaluate_publish_gate",
                args={"content_type": slug, "run_id": run_id, "card_id": card_id},
                result=(
                    "ALLOWED — all guardrails passed"
                    if verdict.allowed
                    else "BLOCKED — " + "; ".join(verdict.blockers())
                ),
            )
        except Exception:  # pragma: no cover - auditing must never break the gate
            pass

    return verdict


def assert_publish_gate(
    org_id: str,
    content_type: str,
    *,
    card: Optional[dict] = None,
    caption: str = "",
    run_id: str = "",
    card_id: str = "",
    data_dir: Optional[Path] = None,
) -> GateVerdict:
    """Raise :class:`PublishGateBlocked` unless every guardrail passes."""
    verdict = evaluate_publish_gate(
        org_id,
        content_type,
        card=card,
        caption=caption,
        run_id=run_id,
        card_id=card_id,
        data_dir=data_dir,
    )
    if not verdict.allowed:
        raise PublishGateBlocked(verdict)
    return verdict


def publish_gate_status(org_id: str, *, data_dir: Optional[Path] = None) -> dict:
    """Informational summary for /healthz/deps (never raises)."""
    try:
        thresholds = load_thresholds(org_id, data_dir=data_dir)
    except Exception:
        thresholds = {}
    return {
        "default_confidence_threshold": DEFAULT_CONFIDENCE_THRESHOLD,
        "thresholds": thresholds,
        "hourly_cap": _hourly_cap(),
        "daily_cap": _daily_cap(),
        "kill_switch_engaged": publish_kill_switch_engaged(),
    }


__all__ = [
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "GateCheck",
    "GateVerdict",
    "PublishGateBlocked",
    "assert_publish_gate",
    "evaluate_publish_gate",
    "load_thresholds",
    "publish_gate_status",
    "save_thresholds",
    "threshold_for",
]
