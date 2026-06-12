"""Account data export (UK GDPR Art. 15 access / Art. 20 portability).

One JSON bundle per account: the stored account fields, the legal-acceptance
history, and workspace memberships. Run-level content (parsed results,
cards, captions) already exports per run via ``/api/runs/<id>/export`` —
this covers the account-scoped remainder. The bcrypt password hash is
deliberately summarised, not exported: shipping password material in a
browser download is a security harm with no access-right upside.
"""

from __future__ import annotations

from datetime import datetime, timezone


def account_export(email: str) -> dict:
    norm = (email or "").strip().lower()
    out: dict = {
        "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "email": norm,
        "account": None,
        "legal_acceptances": [],
        "workspace_memberships": [],
        "note": (
            "Run-level content (results, cards, captions) exports per run from "
            "each run page. The password is stored only as a bcrypt hash and is "
            "not included in exports."
        ),
    }
    if not norm:
        return out

    from mediahub.web.auth import UserStore

    user = UserStore().get(norm)
    if user is not None:
        out["account"] = {
            "email": user.email,
            "plan": user.plan,
            "stripe_customer_id": user.stripe_customer_id,
            "created_at": user.created_at,
            "password": "stored as bcrypt hash (not exported)",
        }

    try:
        from mediahub.web.legal import AcceptanceStore

        store = AcceptanceStore()
        out["legal_acceptances"] = [
            row for row in store._rows() if row.get("email") == norm
        ]
    except Exception:
        pass

    try:
        from mediahub.web.tenancy import MembershipStore

        ms = MembershipStore()
        for pid in ms.member_profile_ids(norm):
            m = ms.get(norm, pid)
            if m is not None:
                out["workspace_memberships"].append(m.to_record())
    except Exception:
        pass

    return out
