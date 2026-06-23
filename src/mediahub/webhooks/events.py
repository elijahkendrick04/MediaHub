"""mediahub/webhooks/events.py — the webhook event catalogue + payloads.

The four events MediaHub emits, and the whitelisted payload each carries. Like
the API scopes, this catalogue is the single source of truth: the registry, the
delivery layer, the management UI, and the docs all read it from here.

Payloads are deliberately small and whitelisted — ids, counts, names — never a
``DATA_DIR`` path, provider key, or athlete personal data beyond what already
appears on an approved card. The envelope mirrors common webhook shapes:

    {"id": "<delivery-or-event id>", "type": "card.approved",
     "created": "<iso8601>", "org": "<profile_id>", "data": { … }}
"""

from __future__ import annotations

from datetime import datetime, timezone

EVENT_RUN_FINISHED = "run.finished"
EVENT_CARD_APPROVED = "card.approved"
EVENT_PACK_EXPORTED = "pack.exported"
EVENT_FORM_SUBMITTED = "form.submitted"

# stable name -> human label (shown when picking events in the UI / docs)
EVENTS: dict[str, str] = {
    EVENT_RUN_FINISHED: "A pipeline run finished (cards are ready to review)",
    EVENT_CARD_APPROVED: "A card was approved",
    EVENT_PACK_EXPORTED: "A content pack was exported",
    EVENT_FORM_SUBMITTED: "A form was submitted",
}

ALL_EVENTS: tuple[str, ...] = tuple(EVENTS.keys())


def is_known(event: str) -> bool:
    return event in EVENTS


def event_label(event: str) -> str:
    return EVENTS.get(event, event)


def validate_events(events) -> list[str]:
    """Filter to known events, de-duplicated and in catalogue order."""
    if not events:
        return []
    wanted = {str(e).strip().lower() for e in events if str(e).strip()}
    return [e for e in ALL_EVENTS if e in wanted]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def envelope(event: str, profile_id: str, data: dict, *, event_id: str = "") -> dict:
    """Wrap a payload in the standard delivery envelope."""
    return {
        "id": event_id or "",
        "type": event,
        "created": _now(),
        "org": profile_id,
        "data": dict(data or {}),
    }


# --- whitelisted payload builders ------------------------------------------
def run_finished(profile_id: str, run_id: str, *, card_count: int = 0, meet_name: str = "") -> dict:
    return envelope(
        EVENT_RUN_FINISHED,
        profile_id,
        {"run_id": run_id, "card_count": int(card_count or 0), "meet_name": meet_name or ""},
    )


def card_approved(profile_id: str, run_id: str, card_id: str, *, via: str = "web") -> dict:
    return envelope(
        EVENT_CARD_APPROVED,
        profile_id,
        {"run_id": run_id, "card_id": card_id, "via": via},
    )


def pack_exported(profile_id: str, run_id: str, *, format: str = "all-formats") -> dict:
    return envelope(
        EVENT_PACK_EXPORTED,
        profile_id,
        {"run_id": run_id, "format": format},
    )


def form_submitted(
    profile_id: str, form_id: str, *, submission_id: str = "", site_id: str = ""
) -> dict:
    return envelope(
        EVENT_FORM_SUBMITTED,
        profile_id,
        {"form_id": form_id, "submission_id": submission_id, "site_id": site_id},
    )


__all__ = [
    "EVENT_RUN_FINISHED",
    "EVENT_CARD_APPROVED",
    "EVENT_PACK_EXPORTED",
    "EVENT_FORM_SUBMITTED",
    "EVENTS",
    "ALL_EVENTS",
    "is_known",
    "event_label",
    "validate_events",
    "envelope",
    "run_finished",
    "card_approved",
    "pack_exported",
    "form_submitted",
]
