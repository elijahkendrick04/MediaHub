"""forms.submit — validate a submission and record it as a data-hub row (1.16).

The submit flow is deterministic and honest: every field is validated against the
:class:`~forms.models.FormSpec` (required, email/phone/number shape, length,
select options, required consent), and anything invalid is **reported, never
guessed** (CLAUDE.md: make uncertainty explicit). A clean submission becomes one
**typed row in the 1.13 data hub** (:mod:`mediahub.data_hub`) with
``hand``-entered provenance, so responses are exportable and GDPR-deletable in the
one place the club already manages its data.

Spam defence at this layer is a **honeypot** (a hidden field a human leaves empty);
per-IP rate-limiting lives at the web layer. Where a field is a child's personal
data, the cell carries a safeguarding note and the response table is flagged, so the
minors'-data rules (ADR-0003 / Children's-Code pass) apply to it downstream.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from mediahub.data_hub import store as dh_store
from mediahub.data_hub.models import DataCell, DataColumn, Provenance

from .models import _EMAIL_RE, _TEL_RE, FormField, FormSpec

DEFAULT_HONEYPOT = "_hp"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "checked")


def _validate_field(f: FormField, raw: Any) -> tuple[Any, str]:
    """Return (clean_value, error). ``error`` is "" when the value is acceptable."""
    if f.type in ("checkbox", "consent"):
        val = _truthy(raw)
        if f.required and not val:
            msg = (
                "Please tick this box to continue."
                if f.type == "consent"
                else "This box is required."
            )
            return val, msg
        return val, ""

    s = "" if raw is None else str(raw).strip()
    if not s:
        return ("", "This field is required." if f.required else "")
    if len(s) > f.effective_max_len:
        return s[: f.effective_max_len], f"Too long (max {f.effective_max_len} characters)."
    if f.type == "email" and not _EMAIL_RE.match(s):
        return s, "Enter a valid email address."
    if f.type == "tel" and not _TEL_RE.match(s):
        return s, "Enter a valid phone number."
    if f.type == "number":
        try:
            return (float(s) if ("." in s or "e" in s.lower()) else int(s)), ""
        except ValueError:
            return s, "Enter a number."
    if f.type == "select" and f.options and s not in f.options:
        return s, "Choose one of the listed options."
    return s, ""


def validate(form: FormSpec, data: dict) -> tuple[dict, dict]:
    """Validate every field. Returns (clean_values, errors_by_key)."""
    clean: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for f in form.fields:
        value, err = _validate_field(f, (data or {}).get(f.key))
        clean[f.key] = value
        if err:
            errors[f.key] = err
    return clean, errors


def is_spam(data: dict, *, honeypot_field: str = DEFAULT_HONEYPOT) -> bool:
    """True when the honeypot field was filled (a human never sees it)."""
    return bool(str((data or {}).get(honeypot_field, "")).strip())


# ---------------------------------------------------------------------------
# Data-hub response table
# ---------------------------------------------------------------------------


def _columns_for(form: FormSpec) -> list[DataColumn]:
    cols = [DataColumn(key="submitted_at", title="Submitted", type="date", editable=False)]
    for f in form.fields:
        cols.append(
            DataColumn(
                key=f.key,
                title=f.label,
                type=f.column_type,
                editable=True,
                description="Minor's personal data" if f.minors_sensitive else "",
            )
        )
    return cols


def ensure_response_table(
    profile_id: str, form: FormSpec, *, db_path: Optional[Path] = None
) -> tuple[str, FormSpec]:
    """Make sure the form has a live data-hub response table; return
    (table_id, form) where ``form`` carries the table_id (possibly new)."""
    if form.table_id:
        existing = dh_store.get_org_table(profile_id, form.table_id, db_path=db_path)
        if existing is not None:
            return form.table_id, form
    desc = "Form responses"
    if form.has_minor_sensitive_field:
        desc = "Form responses (contains minors' personal data — handle per safeguarding policy)"
    table_id = dh_store.create_table(
        profile_id,
        f"{form.title} — responses",
        _columns_for(form),
        description=desc,
        db_path=db_path,
    )
    updated = FormSpec.from_dict({**form.to_dict(), "table_id": table_id})
    return table_id, updated


def _cells_for(form: FormSpec, clean: dict, *, source: str) -> dict:
    now = datetime.now(timezone.utc)
    cells: dict[str, DataCell] = {
        "submitted_at": DataCell(
            value=now.isoformat(timespec="seconds"),
            display=now.strftime("%Y-%m-%d %H:%M"),
            provenance=Provenance.HAND_ENTERED,
            source=source,
        )
    }
    for f in form.fields:
        v = clean.get(f.key)
        if f.type in ("checkbox", "consent"):
            display = "Yes" if v else "No"
        else:
            display = "" if v is None else str(v)
        cells[f.key] = DataCell(
            value=v,
            display=display,
            provenance=Provenance.HAND_ENTERED,
            source=source,
            note="Minor's personal data" if f.minors_sensitive else "",
        )
    return cells


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------


def _notify(form: FormSpec) -> None:
    try:
        from mediahub.notify import notify

        notify(
            f"New form response: {form.title}",
            f"A new submission to '{form.title}' was received.",
            tags=("inbox_tray",),
        )
    except Exception:
        pass  # notifications are best-effort; a submission is never lost on a notify error


def record_submission(
    profile_id: str,
    form: FormSpec,
    data: dict,
    *,
    source: str = "",
    honeypot_field: str = DEFAULT_HONEYPOT,
    db_path: Optional[Path] = None,
) -> dict:
    """Validate ``data`` and, if clean, record it as a data-hub row.

    Returns a result dict: ``{"ok": True, "row_id", "table_id", "form", "message"}``
    on success; ``{"ok": False, "error": "spam"|"validation", "errors"?}`` otherwise.
    The returned ``form`` may carry a freshly-created ``table_id`` — the caller
    should persist it (so the next submission reuses the same table)."""
    if is_spam(data, honeypot_field=honeypot_field):
        # Honeypot tripped: accept-and-discard so a bot gets no signal it failed.
        return {
            "ok": True,
            "row_id": "",
            "table_id": form.table_id,
            "form": form,
            "message": form.success_message,
            "discarded": True,
        }

    clean, errors = validate(form, data)
    if errors:
        return {"ok": False, "error": "validation", "errors": errors}

    table_id, form = ensure_response_table(profile_id, form, db_path=db_path)
    row_id = dh_store.upsert_row(
        profile_id,
        table_id,
        _cells_for(form, clean, source=source or f"form:{form.form_id}"),
        db_path=db_path,
    )
    if form.notify:
        _notify(form)
    return {
        "ok": True,
        "row_id": row_id,
        "table_id": table_id,
        "form": form,
        "message": form.success_message,
    }


__all__ = [
    "DEFAULT_HONEYPOT",
    "validate",
    "is_spam",
    "ensure_response_table",
    "record_submission",
]
