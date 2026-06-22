"""mediahub.forms — public club forms whose responses land in the data hub (1.16).

A :class:`~forms.models.FormSpec` is a typed, JSON-round-trippable form (trial
sign-up, volunteer rota, kit order, RSVP) that a club embeds on a microsite page.
Submissions are validated (:mod:`forms.submit`), honeypot-filtered, and recorded as
**typed rows in the 1.13 data hub** (:mod:`mediahub.data_hub`) — one submission per
row, exportable and GDPR-deletable in the one place the club already manages its
data. The renderer (:mod:`forms.render`) emits an accessible, self-contained HTML
form with a nonce-stamped submit script (no third-party form service).

Where a form gathers a child's personal data, the response table is flagged and each
sensitive cell carries a safeguarding note, so the minors'-data rules (ADR-0003 /
the Children's-Code pass) apply to it hard.
"""

from __future__ import annotations

from .models import (
    FIELD_TYPES,
    FormField,
    FormSpec,
    new_form,
    rsvp_fields,
    trial_signup_fields,
)
from .render import render_form_html
from .store import delete_form, list_forms, load_form, save_form
from .submit import is_spam, record_submission, validate

__all__ = [
    "FIELD_TYPES",
    "FormField",
    "FormSpec",
    "new_form",
    "trial_signup_fields",
    "rsvp_fields",
    "render_form_html",
    "save_form",
    "load_form",
    "list_forms",
    "delete_form",
    "validate",
    "is_spam",
    "record_submission",
]
