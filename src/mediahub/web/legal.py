"""Legal documents and acceptance ledger (UK legal baseline).

This module owns the four customer-facing legal documents — Terms of
Service, Privacy Notice, Cookie Policy, and the Article 28 Data Processing
Agreement — plus the append-only ledger that records who accepted which
version of which document, and when.

Drafting rules (docs/COMPLIANCE_AUDIT.md §4b):

- Every document is headed "DRAFT — requires solicitor review before going
  live" until a solicitor signs it off.
- Documents describe only behaviour that actually exists in this codebase.
  If the product changes, the document and its version below MUST change
  with it — an inaccurate privacy notice is a UK GDPR Art. 13/14 breach.
- Facts the repo cannot know (company identity, addresses) are
  ``[PLACEHOLDERS]`` and are listed in ``PLACEHOLDERS`` so the handover can
  enumerate them.
- No document ever claims the service "is fully compliant" with any law.

Versioning: bump the relevant ``*_VERSION`` constant (date-stamped) whenever
a document's substance changes. Signed-in users whose recorded Terms
acceptance predates ``TERMS_VERSION`` are routed through re-acceptance by
the web layer.

The acceptance ledger is a JSON-lines file at
``DATA_DIR/legal_acceptances.jsonl`` — same append-only, 0600-permission
pattern as ``users.jsonl`` (web/auth.py).
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Versions & identity placeholders
# ---------------------------------------------------------------------------

TERMS_VERSION = "2026-06-12"
PRIVACY_VERSION = "2026-06-12.1"
COOKIES_VERSION = "2026-06-12"
DPA_VERSION = "2026-06-12.1"

# Facts the repository cannot know. Fill these before launch; the handover
# (docs/COMPLIANCE_HANDOVER.md) lists them as operational items.
COMPANY_NAME = "[COMPANY_NAME]"
COMPANY_NUMBER = "[COMPANY_NUMBER]"
REGISTERED_ADDRESS = "[REGISTERED_ADDRESS]"
CONTACT_EMAIL = "[CONTACT_EMAIL]"
ICO_REGISTRATION_NUMBER = "[ICO_REGISTRATION_NUMBER]"

PLACEHOLDERS = (
    "[COMPANY_NAME]",
    "[COMPANY_NUMBER]",
    "[REGISTERED_ADDRESS]",
    "[CONTACT_EMAIL]",
    "[ICO_REGISTRATION_NUMBER]",
)

_DRAFT_BANNER = (
    '<div class="card" style="border-left:3px solid var(--accent)">'
    "<strong>DRAFT &mdash; requires solicitor review before going live.</strong> "
    "This document was drafted from the actual behaviour of the MediaHub codebase "
    "and is pending review by a qualified solicitor. Bracketed values like "
    "<code>[COMPANY_NAME]</code> are placeholders."
    "</div>"
)


# ---------------------------------------------------------------------------
# Sub-processor register (PC.11)
# ---------------------------------------------------------------------------
#
# The single source of truth for which external services can receive Club
# Data, keyed to the env flags that activate each one. The DPA §6 table is
# rendered FROM this register, and tests/test_subprocessor_register_guard.py
# fails the build when a provider-shaped env key appears in src/mediahub
# without being declared here (or in the documented non-sub-processor list
# below) — so a new provider cannot ship undisclosed.


@dataclass(frozen=True)
class Subprocessor:
    name: str
    processing: str
    location: str
    # The env keys that activate/configure this provider. Empty = always on
    # (the hosting platform itself).
    env_keys: tuple[str, ...] = ()
    # Public /legal/subprocessors columns (transparency page).
    transfer_mechanism: str = ""
    engaged_when: str = ""


SUBPROCESSORS: tuple[Subprocessor, ...] = (
    Subprocessor(
        name="Render Services, Inc. (hosting & backup storage)",
        processing=(
            "Runs the service and stores all Club Data, including the "
            "operator-configured off-site backup archives; the log sentinel "
            "reads the service's own logs through the Render API"
        ),
        location="United States",
        env_keys=(
            "MEDIAHUB_BACKUP_UPLOAD_URL",
            "MEDIAHUB_BACKUP_UPLOAD_TOKEN",
            "RENDER_API_KEY",
        ),
        transfer_mechanism="UK–US data bridge (DPF-certified); SCC fallback",
        engaged_when="Always",
    ),
    Subprocessor(
        name="GitHub, Inc. (log sentinel)",
        processing=(
            "Receives operational log excerpts filed as issues in the "
            "operator's repository by the log sentinel (logs are designed to "
            "carry no athlete personal data)"
        ),
        location="United States",
        env_keys=("MEDIAHUB_SENTINEL_GITHUB_TOKEN",),
        transfer_mechanism="GitHub DPA; SCCs/IDTA",
        engaged_when="Only if the log sentinel is configured",
    ),
    Subprocessor(
        name="Google LLC (Gemini API)",
        processing="Caption/creative generation; AI page reading",
        location="United States / global",
        env_keys=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        transfer_mechanism="Google Cloud DPA: SCCs + UK Addendum",
        engaged_when="When configured by the operator",
    ),
    Subprocessor(
        name="Anthropic, PBC (Claude API)",
        processing="Failover for the same generation calls",
        location="United States",
        env_keys=("ANTHROPIC_API_KEY",),
        transfer_mechanism="DPA with SCCs + UK IDTA/Addendum",
        engaged_when="When configured by the operator",
    ),
    Subprocessor(
        name="Operator-configured OpenAI-compatible endpoint",
        processing=(
            "Additional LLM failover and caption-memory embeddings "
            "(generation prompts and caption text, athlete names included)"
        ),
        location="Operator-chosen provider",
        env_keys=(
            "MEDIAHUB_LLM_ENDPOINTS",
            "MEDIAHUB_LLM_API_KEY",
            "MEDIAHUB_EMBED_ENDPOINT",
            "MEDIAHUB_EMBED_API_KEY",
        ),
        transfer_mechanism=("The operator must hold processor terms with their chosen provider"),
        engaged_when="Only if the operator configures an endpoint",
    ),
    Subprocessor(
        name="TinyFish AI, Inc. (Search API)",
        processing=(
            "Web search for PB-discovery bootstrap: the query carries a swimmer's "
            "name and club (personal data) to find their public results/profile "
            "page. Only first-seen swimmers (no club history yet) are looked up; "
            "returning swimmers are served from the club's own stored history"
        ),
        location="United States",
        env_keys=("TINYFISH_API_KEY", "MEDIAHUB_TINYFISH_TIMEOUT"),
        transfer_mechanism=(
            "Free-tier API — the operator must confirm processor terms (SCCs/IDTA "
            "for the US transfer) before enabling; OFF by default and opt-in for "
            "exactly this reason"
        ),
        engaged_when="Only if a TinyFish API key is configured",
    ),
    Subprocessor(
        name="Photoroom SAS",
        processing="Photo background removal",
        location="France (sub-processors may be outside the EEA)",
        env_keys=("PHOTOROOM_API_KEY", "PHOTOROOM_ENDPOINT"),
        transfer_mechanism="GDPR processor terms",
        engaged_when="Only if the club/operator enables cloud cutout",
    ),
    Subprocessor(
        name="Replicate, Inc.",
        processing="Photo background removal",
        location="United States",
        env_keys=("REPLICATE_API_TOKEN",),
        transfer_mechanism="Processor terms; SCCs/IDTA",
        engaged_when="Only if the club/operator enables cloud cutout",
    ),
    Subprocessor(
        name="Microsoft (edge-tts)",
        processing="Synthesises reel narration audio (athlete name, event, time)",
        location="United States",
        env_keys=("MEDIAHUB_VOICEOVER",),
        transfer_mechanism=(
            "Public synthesis endpoint, no contractual terms — voiceover is OFF "
            "by default, and even when enabled the default backend is local "
            "Piper (no transfer); this online backend is a deliberate opt-in"
        ),
        engaged_when="Only if voiceover is enabled AND the edge backend is selected (MEDIAHUB_TTS_PROVIDER=edge)",
    ),
    Subprocessor(
        name="Resend, Inc.",
        processing=(
            "Transactional email delivery: password resets, email "
            "verification, workspace invites and service/breach notices "
            "(account email addresses and the message content)"
        ),
        location="United States",
        env_keys=("RESEND_API_KEY", "MEDIAHUB_EMAIL_ENDPOINT"),
        transfer_mechanism="DPA; SCCs/IDTA",
        engaged_when="Only if transactional email is configured",
    ),
    Subprocessor(
        name="Stripe, Inc.",
        processing="Billing (controller-side, listed for transparency)",
        location="United States",
        env_keys=("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"),
        transfer_mechanism="Stripe DPA; UK–US data bridge / SCCs",
        engaged_when="Only if billing is configured",
    ),
)

# Provider-shaped env keys that deliberately do NOT appear in the DPA
# sub-processor table, each with the recorded reason. The guard test fails
# when a key is in neither this dict nor a SUBPROCESSORS entry.
NON_SUBPROCESSOR_PROVIDER_ENV: dict[str, str] = {
    "MEDIAHUB_NTFY_TOKEN": (
        "ntfy notifications carry human-readable status text only — no athlete "
        "or member personal data by design (Privacy Notice §3)."
    ),
    "MEDIAHUB_NOTIFY_WEBHOOK": (
        "the operator's own webhook endpoint; status text only, no athlete or "
        "member personal data by design (Privacy Notice §3)."
    ),
    "MEDIAHUB_SEARCH_ENDPOINT": (
        "personal-best verification queries (athlete name, club, birth year) go "
        "to DuckDuckGo by default or the operator's self-hosted SearXNG — "
        "disclosed in Privacy Notice §3–4. A public search engine is not an "
        "Art. 28 sub-processor; queries are transient and uncontracted."
    ),
    "PEXELS_API_KEY": (
        "the optional, flag-gated paid stock-photo source for the licence-clean "
        "stock pool (roadmap 1.10, elements/stock.py). Off by default — the pool "
        "harvests free open collections (Openverse, Wikimedia) unless an operator "
        "sets this key. Only an operator-typed stock-image search term is sent "
        "(e.g. 'swimming pool'); no Club/athlete personal data, uploads or results "
        "leave MediaHub, and Pexels returns public stock imagery. Transient and "
        "uncontracted — a stock-photo search API is not an Art. 28 sub-processor."
    ),
    "PIXABAY_API_KEY": (
        "the optional, flag-gated paid stock-photo source for the licence-clean "
        "stock pool (roadmap 1.10, elements/stock.py). Off by default — the pool "
        "harvests free open collections (Openverse, Wikimedia) unless an operator "
        "sets this key. Only an operator-typed stock-image search term is sent; no "
        "Club/athlete personal data, uploads or results leave MediaHub, and Pixabay "
        "returns public stock imagery. Transient and uncontracted — a stock-photo "
        "search API is not an Art. 28 sub-processor."
    ),
    "MEDIAHUB_IMAGINE_LOCAL_ENDPOINT": (
        "the operator's own self-hosted local diffusion image backend (the "
        "imagine seam's in-house default, roadmap 1.1). Inference runs on the "
        "operator's own infrastructure — a self-hosted model is not an Art. 28 "
        "sub-processor. Cloud image generation uses GEMINI_API_KEY (Google, "
        "already a declared sub-processor)."
    ),
    "MEDIAHUB_IMAGINE_LOCAL_TOKEN": (
        "optional bearer token guarding the operator's own self-hosted local "
        "diffusion endpoint (above). It authenticates MediaHub to the operator's "
        "own infrastructure — no third party, so not an Art. 28 sub-processor; "
        "the token is redacted from logs and error text."
    ),
    "DID_API_KEY": (
        "the opt-in, disclosed AI-avatar seam (roadmap 1.6, video/avatars.py). "
        "The D-ID network integration is NOT wired in this build — "
        "synthesize_avatar() honest-errors and the key is read only to report "
        "availability — so no Club Data is transmitted to D-ID and it is not yet "
        "an active Art. 28 sub-processor. When the integration is built and an "
        "org enables it, D-ID MUST move to legal.SUBPROCESSORS (and the club DPA) "
        "before any data flows."
    ),
    "HEYGEN_API_KEY": (
        "the opt-in, disclosed AI-avatar seam (roadmap 1.6, video/avatars.py). "
        "The HeyGen network integration is NOT wired in this build — "
        "synthesize_avatar() honest-errors and the key is read only to report "
        "availability — so no Club Data is transmitted to HeyGen and it is not "
        "yet an active Art. 28 sub-processor. When the integration is built and "
        "an org enables it, HeyGen MUST move to legal.SUBPROCESSORS (and the club "
        "DPA) before any data flows."
    ),
    "MEDIAHUB_SWIM_ENGLAND_API_KEY": (
        "the flag-gated Swim England Rankings / approved-systems connector seam "
        "(roadmap 1.13, data_hub/connectors/builtin.py; founder application F.5). "
        "The live fetch is NOT wired in this build — the connector honest-errors "
        "before any network call and the key is read only to report availability "
        "— so no Club Data is transmitted to Swim England and it is not yet an "
        "active Art. 28 sub-processor. When the integration is built and an org "
        "enables it, Swim England MUST move to legal.SUBPROCESSORS (and the club "
        "DPA) before any data flows."
    ),
}


def subprocessor_table_rows_html() -> str:
    """The DPA §6 table body, rendered from the register so the legal page
    can never drift from the declared provider surface."""
    return "".join(
        f"<tr><td>{s.name}</td><td>{s.processing}</td><td>{s.location}</td></tr>"
        for s in SUBPROCESSORS
    )


def subprocessor_public_rows_html() -> str:
    """The public /legal/subprocessors table body — same register, with the
    transfer-safeguard and when-engaged columns."""
    return "".join(
        f"<tr><td>{s.name}</td><td>{s.processing}</td><td>{s.location}</td>"
        f"<td>{s.transfer_mechanism}</td><td>{s.engaged_when}</td></tr>"
        for s in SUBPROCESSORS
    )


def identity_block() -> str:
    """The E-Commerce Regs 2002 / Companies Act 2006 service-provider block."""
    return (
        '<div class="card"><h2>Who provides this service</h2>'
        f"<p><strong>{COMPANY_NAME}</strong>"
        f" (company number {COMPANY_NUMBER}), registered office: "
        f"{REGISTERED_ADDRESS}.<br>"
        f"Contact: <a href='mailto:{CONTACT_EMAIL}'>{CONTACT_EMAIL}</a>.<br>"
        f"ICO registration number: {ICO_REGISTRATION_NUMBER}.</p></div>"
    )


# ---------------------------------------------------------------------------
# Acceptance ledger
# ---------------------------------------------------------------------------

DOC_TERMS = "terms"
DOC_DPA = "dpa"
DOC_DATA_ATTESTATION = "data_attestation"
# CCR 2013 regs 36/37: the buyer's express request for immediate supply +
# acknowledgement about the 14-day cancellation right, recorded per purchase
# (org_id field carries the plan).
DOC_COOLING_OFF = "cooling_off"

_LEDGER_LOCK = threading.Lock()


def current_version(doc: str) -> str:
    return {
        DOC_TERMS: TERMS_VERSION,
        DOC_DPA: DPA_VERSION,
        DOC_DATA_ATTESTATION: DPA_VERSION,
        DOC_COOLING_OFF: TERMS_VERSION,
    }.get(doc, TERMS_VERSION)


@dataclass(frozen=True)
class Acceptance:
    email: str
    doc: str
    version: str
    accepted_at: str
    org_id: str = ""


class AcceptanceStore:
    """Append-only ledger of legal-document acceptances.

    Last-write-wins per (email, doc, org_id) — the same JSONL pattern as
    ``users.jsonl``. Records are never personal beyond the account email
    that every record in ``users.jsonl`` already carries.
    """

    def __init__(self, path: Optional[Path] = None):
        base = Path(os.environ.get("DATA_DIR", "data"))
        self.path = path or (base / "legal_acceptances.jsonl")

    def record(self, email: str, doc: str, version: str, org_id: str = "") -> Acceptance:
        acc = Acceptance(
            email=(email or "").strip().lower(),
            doc=doc,
            version=version,
            accepted_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            org_id=org_id,
        )
        line = json.dumps(
            {
                "email": acc.email,
                "doc": acc.doc,
                "version": acc.version,
                "accepted_at": acc.accepted_at,
                "org_id": acc.org_id,
            },
            sort_keys=True,
        )
        with _LEDGER_LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            existed = self.path.exists()
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            if not existed:
                try:
                    os.chmod(self.path, 0o600)
                except OSError:
                    pass
        return acc

    def _rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        rows: list[dict] = []
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        row = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(row, dict):
                        rows.append(row)
        except OSError:
            return []
        return rows

    def latest(self, email: str, doc: str, org_id: str = "") -> Optional[Acceptance]:
        email = (email or "").strip().lower()
        found: Optional[Acceptance] = None
        for row in self._rows():
            if (
                row.get("email") == email
                and row.get("doc") == doc
                and (row.get("org_id") or "") == org_id
            ):
                found = Acceptance(
                    email=email,
                    doc=doc,
                    version=str(row.get("version") or ""),
                    accepted_at=str(row.get("accepted_at") or ""),
                    org_id=org_id,
                )
        return found

    def has_accepted(self, email: str, doc: str, version: str, org_id: str = "") -> bool:
        for row in self._rows():
            if (
                row.get("email") == (email or "").strip().lower()
                and row.get("doc") == doc
                and row.get("version") == version
                and (row.get("org_id") or "") == org_id
            ):
                return True
        return False

    def org_has_acceptance(self, org_id: str, doc: str, version: str) -> bool:
        """True when ANY account has accepted ``doc``@``version`` for this
        workspace — the DPA/attestation is per-workspace, recorded by the
        officer who set it up."""
        if not (org_id or "").strip():
            return False
        for row in self._rows():
            if (
                row.get("doc") == doc
                and row.get("version") == version
                and (row.get("org_id") or "") == org_id
            ):
                return True
        return False

    def needs_terms_reacceptance(self, email: str) -> bool:
        """True when the account has accepted *some* Terms version but not
        the current one. Accounts with no record at all are legacy accounts
        created before acceptance existed — they are also routed to accept."""
        if not (email or "").strip():
            return False
        return not self.has_accepted(email, DOC_TERMS, TERMS_VERSION)

    def erase_email(self, email: str) -> int:
        """Remove every ledger row for an email (right-to-erasure cascade).

        The acceptance history is contract evidence, so this is only called
        from full account deletion — where keeping a row keyed to the email
        would defeat the erasure.
        """
        email = (email or "").strip().lower()
        with _LEDGER_LOCK:
            rows = self._rows()
            kept = [r for r in rows if r.get("email") != email]
            removed = len(rows) - len(kept)
            if removed:
                tmp = self.path.with_suffix(".tmp")
                with tmp.open("w", encoding="utf-8") as fh:
                    for r in kept:
                        fh.write(json.dumps(r, sort_keys=True) + "\n")
                try:
                    os.chmod(tmp, 0o600)
                except OSError:
                    pass
                tmp.replace(self.path)
        return removed


# ---------------------------------------------------------------------------
# Document bodies (static HTML — no user input is interpolated)
# ---------------------------------------------------------------------------


def terms_html(*, privacy_url: str, cookies_url: str, dpa_url: str) -> str:
    """Terms of Service body. CRA 2015 / CCR 2013 / DMCCA-aware."""
    return f"""
{_DRAFT_BANNER}
<section class="mh-hero" style="padding-top:var(--sp-6);padding-bottom:var(--sp-5);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Legal</span>
  <h1>Terms of <em class="editorial">Service.</em></h1>
  <p class="lede">Version {TERMS_VERSION}. Plain-English terms for using MediaHub.</p>
</section>

{identity_block()}

<div class="card">
  <h2>1. What MediaHub is</h2>
  <p>MediaHub is a hosted web application for sports clubs. You upload competition
  results (files or links) and photos; MediaHub detects achievements, generates branded
  graphics, videos and captions, and queues them for <strong>your review and
  approval</strong> before anything is exported. MediaHub does not publish to
  social media on your behalf &mdash; once you approve content you export or
  download it and post it yourself.</p>
</div>

<div class="card">
  <h2>2. Your account</h2>
  <p>You need an account (email + password) to use the service. Keep your password
  confidential; you are responsible for activity under your account. You must be at
  least 18 to create an account &mdash; MediaHub accounts are for the adults who run a
  club's communications, not for athletes.</p>
</div>

<div class="card">
  <h2>3. Your content and your responsibilities</h2>
  <p>You (your club) remain responsible for the data you upload. By uploading results,
  rosters, photos, logos or brand material you confirm that:</p>
  <ul>
    <li>your club is entitled to process and share that data for club communications,
        and has collected any consents its own rules and the law require &mdash;
        <strong>including parental consent where you upload photos of, or publish
        content about, athletes under 18</strong>;</li>
    <li>you have the rights needed to use any logos, sponsor marks and photos you
        upload;</li>
    <li>you will review generated content for accuracy before approving it &mdash;
        MediaHub shows confidence scores and provenance to help, but the approval
        decision is yours;</li>
    <li>where generated content promotes a sponsor, you are responsible for labelling
        it as advertising where the CAP Code requires.</li>
  </ul>
  <p>For athlete and member personal data, your club is the data controller and
  {COMPANY_NAME} processes it on your instructions under the
  <a href="{dpa_url}">Data Processing Agreement</a>. Our
  <a href="{privacy_url}">Privacy Notice</a> describes every processing flow.</p>
</div>

<div class="card">
  <h2>4. Acceptable use</h2>
  <p>Don't use MediaHub to publish unlawful, defamatory or harassing content; don't
  upload data about people your club has no relationship with; don't attempt to access
  other organisations' data; don't probe, overload or disrupt the service.
  We may suspend accounts that do.</p>
</div>

<div class="card">
  <h2>5. Generated content and intellectual property</h2>
  <p>You own the content packs MediaHub generates for you (graphics, videos, captions),
  to the extent we hold any rights in them, and we assign those rights to you on
  creation. The MediaHub software, templates and brand remain ours. You grant us the
  licence we need to process your uploads and render your content &mdash; nothing more.</p>
</div>

<div class="card">
  <h2>6. Plans, billing, renewal and cancellation</h2>
  <p>The Free plan needs no payment details. Paid plans (Club, Federation) are
  subscriptions billed through Stripe at the price shown before checkout, and
  <strong>renew automatically</strong> (monthly or annually as stated at checkout)
  until cancelled.</p>
  <ul>
    <li><strong>Before you pay</strong>, the checkout page shows the total price, the
        renewal interval, and how to cancel.</li>
    <li><strong>Cancelling is as easy as subscribing:</strong> open
        <em>Billing &rarr; Manage billing</em> and cancel in the Stripe customer
        portal, any time. Cancellation stops future renewals; you keep access for the
        period already paid.</li>
    <li><strong>Renewal reminders:</strong> for annual plans we send a reminder before
        renewal so you can cancel first.</li>
  </ul>
</div>

<div class="card">
  <h2>7. Your 14-day cancellation right (Consumer Contracts Regulations 2013)</h2>
  <p>If you buy as a consumer you have the right to cancel within 14 days of purchase
  and receive a full refund. Because MediaHub is a digital service that begins
  immediately, at checkout we ask for your express agreement that the service starts
  during the cancellation period; if you then use the service, we may deduct an amount
  proportionate to the service already supplied when refunding. If you ask us to start
  immediately and expressly acknowledge that you lose the right to cancel once the
  service has been fully performed, that acknowledgement is recorded with your
  purchase. To cancel within the 14 days, email
  <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a> or use the model cancellation
  wording: <em>"I hereby give notice that I cancel my contract for the supply of the
  MediaHub service, ordered on [date], name [name], email [account email]."</em></p>
</div>

<div class="card">
  <h2>8. Service quality (Consumer Rights Act 2015)</h2>
  <p>We supply the service with reasonable care and skill, as described on this site
  and matching what we say it does. If it doesn't, you are entitled to ask us to fix
  it (repeat performance) and, where we can't within a reasonable time, to an
  appropriate price reduction. Nothing in these terms removes your statutory rights.</p>
</div>

<div class="card">
  <h2>9. What we don't promise</h2>
  <p>MediaHub detects achievements from the data you give it and from public results
  sources. We work to make detection accurate and we show confidence scores, but we do
  not guarantee that every detection is correct &mdash; that's why content waits for
  your approval. You're responsible for what your club publishes after approving it.
  We may change or withdraw features with reasonable notice where the change is
  material to a paid plan.</p>
</div>

<div class="card">
  <h2>10. Liability</h2>
  <p>We do not exclude or limit liability for death or personal injury caused by our
  negligence, for fraud, or for anything else that cannot lawfully be excluded. Subject
  to that, we are not liable for losses that are not a foreseeable result of our breach,
  and our total liability in any 12-month period is capped at the greater of the fees
  you paid us in that period and &pound;100.</p>
</div>

<div class="card">
  <h2>11. Changes to these terms</h2>
  <p>When we change these terms in substance we publish a new dated version and ask you
  to accept it the next time you sign in; your acceptance of each version is recorded
  with a timestamp. If you don't accept, you can export your data and close your
  account; material changes to paid plans take effect from your next renewal.</p>
</div>

<div class="card">
  <h2>12. Governing law and complaints</h2>
  <p>These terms are governed by the law of England and Wales and the courts of England
  and Wales have jurisdiction (consumers in Scotland or Northern Ireland keep the
  protections and courts of their home nation). Complaints: email
  <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a> &mdash; we aim to respond within
  14 days. Also see the <a href="{privacy_url}">Privacy Notice</a> and
  <a href="{cookies_url}">Cookie Policy</a>.</p>
</div>
"""


def privacy_html(
    *,
    terms_url: str,
    cookies_url: str,
    dpa_url: str,
    deployment_inventory_html: str = "",
) -> str:
    """Privacy Notice body — UK GDPR Articles 13/14, accurate to the code."""
    return f"""
{_DRAFT_BANNER}
<section class="mh-hero" style="padding-top:var(--sp-6);padding-bottom:var(--sp-5);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Legal</span>
  <h1>Privacy <em class="editorial">Notice.</em></h1>
  <p class="lede">Version {PRIVACY_VERSION}. What MediaHub actually does with personal
  data &mdash; written from the code, in plain English.</p>
</section>

{identity_block()}

<div class="card">
  <h2>1. The two roles we play</h2>
  <p><strong>For athlete and member data your club uploads</strong> (results files,
  rosters, photos), your club decides why and how that data is used &mdash; the club is
  the <em>controller</em> and {COMPANY_NAME} is its <em>processor</em>, acting under the
  <a href="{dpa_url}">Data Processing Agreement</a>.</p>
  <p><strong>For your account, billing, and the personal-best lookup cache</strong>
  (described in section 4), {COMPANY_NAME} is the <em>controller</em>.</p>
</div>

<div class="card">
  <h2>2. What we collect</h2>
  <ul>
    <li><strong>Account data:</strong> your email address and a bcrypt-hashed password.
        We never store the password itself.</li>
    <li><strong>Athlete data your club uploads:</strong> names, ages or dates of birth,
        gender, club, race results, age groups, and any athlete identifiers present in
        the results files (e.g. governing-body membership numbers). Photos you add to
        the media library, with any athlete names you link to them.</li>
    <li><strong>Billing data:</strong> handled by Stripe; we store your plan and Stripe
        customer reference, never card numbers.</li>
    <li><strong>Operational records:</strong> a log of publishing attempts (with a short
        caption excerpt), AI-call metadata (provider, token counts &mdash; never the
        prompt text), and run progress logs (no athlete names).</li>
  </ul>
</div>

<div class="card">
  <h2>3. What we do with it &mdash; and which services receive it</h2>
  <p>Each flow below exists in the code today. Services marked "only if configured /
  connected" receive nothing unless your deployment or club enables them.</p>
  <table>
    <tr><th>Flow</th><th>Personal data involved</th><th>Recipient</th></tr>
    <tr><td>Caption &amp; creative generation</td>
        <td>Athlete name, event, time, placement, personal-best detail, age group, club,
            venue (in the generation prompt)</td>
        <td>Google (Gemini API); Anthropic as failover</td></tr>
    <tr><td>Reading results from a link (AI page reader)</td>
        <td>Page screenshot/text including competitor names and results</td>
        <td>Google (Gemini API); Anthropic as failover</td></tr>
    <tr><td>Caption memory &amp; additional LLM endpoints</td>
        <td>Caption text and generation prompts (athlete names embedded)</td>
        <td>An operator-configured OpenAI-compatible provider &mdash; only if
            configured</td></tr>
    <tr><td>Photo background removal</td>
        <td>The athlete photo being processed</td>
        <td>Runs on our own server by default; Photoroom or Replicate only if
            configured</td></tr>
    <tr><td>Reel narration voiceover</td>
        <td>The narration text (athlete name, event, time)</td>
        <td>Local on our own server by default (Piper); Microsoft (edge-tts)
            only if voiceover is enabled and the edge backend is selected</td></tr>
    <tr><td>Personal-best verification</td>
        <td>Search queries containing athlete name, club and birth year; fetches of
            public results pages</td>
        <td>DuckDuckGo (or a self-hosted SearXNG instance)</td></tr>
    <tr><td>Payments</td><td>Email, plan, payment details (collected by Stripe
        directly)</td><td>Stripe</td></tr>
    <tr><td>Transactional email (password resets, verification, workspace
        invites, service/breach notices)</td>
        <td>Your account email address and the message content</td>
        <td>Resend &mdash; only if configured</td></tr>
    <tr><td>Notifications</td><td>Human-readable status messages (no athlete data by
        design)</td><td>ntfy / your webhook &mdash; only if configured</td></tr>
  </table>
  <p>We do not run third-party analytics or advertising trackers. See the
  <a href="{cookies_url}">Cookie Policy</a>.</p>
</div>

<div class="card">
  <h2>4. Personal-best lookup and caching</h2>
  <p>To verify "is this a personal best?", MediaHub searches public results sources for
  the athletes in your uploaded file and caches what it finds: a per-run cache, plus a
  shared cache of each swimmer's personal bests kept for <strong>7 days</strong>
  (search-page cache: 30 days). This lookup uses only already-public sports results,
  under our legitimate interest in verifying accuracy before your club publishes
  &mdash; and you can clear these caches yourself from the Privacy page.</p>
</div>

<div class="card">
  <h2>5. Children's data</h2>
  <p>Most competitive swimmers are under 18, so we treat athlete data as children's
  data by default:</p>
  <ul>
    <li>Your club must hold parental consent where its rules and the law require it
        &mdash; we ask the club to confirm this when it sets up its workspace, and the
        confirmation is recorded with a timestamp.</li>
    <li><strong>Content about an under-18 athlete is never published autonomously</strong> —
        it always waits for a human decision at the club, enforced in code.</li>
    <li>The public showcase wall shows athletes' initials, not full names, by
        default &mdash; and where the club keeps a per-athlete consent registry,
        the wall enforces each athlete's recorded consent: a "do not feature"
        athlete (or one with no consent on file) never appears on it.</li>
    <li>Accounts are for adult club officers; we don't offer accounts to children.</li>
  </ul>
</div>

<div class="card">
  <h2>6. Lawful bases</h2>
  <ul>
    <li><strong>Account &amp; billing:</strong> performance of our contract with you;
        legal obligation for accounting records.</li>
    <li><strong>Athlete data uploaded by your club:</strong> processed on the club's
        documented instructions under the DPA; the club is responsible for its own
        lawful basis and attests to it at onboarding.</li>
    <li><strong>Personal-best verification of public results:</strong> our legitimate
        interest in accuracy of club-approved content, balanced against athletes'
        rights (assessed in our Data Protection Impact Assessment).</li>
  </ul>
</div>

<div class="card">
  <h2>7. International transfers</h2>
  <p>Google (Gemini), Anthropic, Replicate, Microsoft (voiceover, where enabled),
  Resend (email, where configured) and Stripe process data in the United
  States; Photoroom processes data in [PHOTOROOM_REGION]; an operator-configured
  OpenAI-compatible endpoint (where one is configured) processes data wherever that
  chosen provider runs. Where a provider is
  certified under the UK&ndash;US Data Bridge we rely on that; otherwise we use the UK
  International Data Transfer Agreement/Addendum with that provider. The status for
  each provider is recorded in our processing records ([CONTACT_EMAIL] for a copy).</p>
</div>

<div class="card">
  <h2>8. How long we keep things</h2>
  <table>
    <tr><th>Data</th><th>Retention</th></tr>
    <tr><td>Runs, uploads, generated content packs</td>
        <td>Until you delete them, or automatically after the deployment's configured
            retention period where one is set (shown on the Privacy page)</td></tr>
    <tr><td>Personal-best warm cache</td><td>7 days</td></tr>
    <tr><td>Search/research cache</td><td>30 days</td></tr>
    <tr><td>Try-it demo uploads</td><td>24 hours</td></tr>
    <tr><td>Caption memory (used to avoid repeating past captions)</td>
        <td>Until the run it came from is deleted, or the account/club is deleted</td></tr>
    <tr><td>Publishing log / AI-usage metadata</td>
        <td>Trimmed automatically (ring buffer); caption excerpts are removed when the
            related run is erased</td></tr>
    <tr><td>Account record</td><td>Until you delete your account</td></tr>
  </table>
</div>

<div class="card">
  <h2>9. Your rights, and the buttons that exercise them</h2>
  <ul>
    <li><strong>Erasure:</strong> delete any run (with its uploads, generated content
        and caption memory) from the run page or Privacy page; delete your whole
        account from the Privacy page. Clubs can erase a single athlete across all
        stored data, and a workspace owner can delete the entire organisation —
        runs, media, registries, ledgers and the public wall — from the
        Organisation page.</li>
    <li><strong>Access / portability:</strong> export any run as JSON; export your
        account data from the Privacy page; workspace owners can download the
        whole organisation as one takeout ZIP from the Organisation page.</li>
    <li><strong>Rectification:</strong> edit captions before approval; request
        correction of a published item via the correction workflow on this
        Privacy page (it records the request, pulls the card from the public
        wall, and gives you the platform takedown checklist).</li>
    <li><strong>Objection / restriction:</strong> email
        <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>.</li>
  </ul>
  <p>Athletes and parents: MediaHub processes most athlete data on your club's behalf,
  so requests about club content are fastest through the club; you can also contact us
  directly and we will pass the request on and assist.</p>
</div>

<div class="card">
  <h2>10. Security</h2>
  <p>Passwords are hashed with bcrypt; sessions use signed, HttpOnly cookies; each
  organisation's data is isolated and access is checked on every request; uploads are
  validated against archive attacks; secrets live in the environment, never in code.
  Full measures are listed in the <a href="{dpa_url}">DPA</a> security annex.</p>
</div>

<div class="card">
  <h2>11. Complaints</h2>
  <p>Contact <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a> first &mdash; we aim
  to resolve privacy concerns within 14 days. You also have the right to complain to
  the Information Commissioner's Office: <a href="https://ico.org.uk/make-a-complaint/"
  rel="noopener">ico.org.uk/make-a-complaint</a> or 0303&nbsp;123&nbsp;1113.</p>
</div>

<div class="card">
  <h2>12. Changes</h2>
  <p>We publish a new dated version when this notice changes and flag material changes
  in the app. See also the <a href="{terms_url}">Terms of Service</a>.</p>
</div>

{deployment_inventory_html}
"""


def cookies_html(*, privacy_url: str) -> str:
    """Cookie Policy body — PECR disclosure for the essential-only cookie set."""
    return f"""
{_DRAFT_BANNER}
<section class="mh-hero" style="padding-top:var(--sp-6);padding-bottom:var(--sp-5);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Legal</span>
  <h1>Cookie <em class="editorial">Policy.</em></h1>
  <p class="lede">Version {COOKIES_VERSION}. One cookie. No trackers.</p>
</section>

<div class="card">
  <h2>The cookies MediaHub sets</h2>
  <table>
    <tr><th>Cookie</th><th>Purpose</th><th>Type</th><th>Lifetime</th></tr>
    <tr><td><code>session</code></td>
        <td>Keeps you signed in and remembers which club workspace you're working in.
            Signed and HttpOnly.</td>
        <td>Strictly necessary (first-party)</td>
        <td>Session; idle sign-out after a configurable period (default 30 minutes)</td></tr>
  </table>
  <p>That's the whole list. MediaHub sets <strong>no analytics, advertising, or
  third-party cookies</strong>, and loads no third-party scripts or fonts &mdash;
  everything is served from our own server.</p>
</div>

<div class="card">
  <h2>Consent</h2>
  <p>Strictly necessary cookies don't require consent under PECR, which is why you
  don't see a cookie banner. If we ever introduce a non-essential cookie or analytics,
  it will be blocked until you opt in &mdash; the code enforces this: non-essential
  cookies can only be set through a consent gate that requires your recorded opt-in.</p>
</div>

<div class="card">
  <h2>More</h2>
  <p>How we handle personal data generally: see the
  <a href="{privacy_url}">Privacy Notice</a>.</p>
</div>
"""


def dpa_html(*, privacy_url: str) -> str:
    """Article 28 Data Processing Agreement body."""
    return f"""
{_DRAFT_BANNER}
<section class="mh-hero" style="padding-top:var(--sp-6);padding-bottom:var(--sp-5);margin-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Legal</span>
  <h1>Data Processing <em class="editorial">Agreement.</em></h1>
  <p class="lede">Version {DPA_VERSION}. The Article 28 terms between your club (the
  controller) and {COMPANY_NAME} (the processor) for athlete and member data.</p>
</section>

{identity_block()}

<div class="card">
  <h2>1. Scope and roles</h2>
  <p>This DPA applies to all personal data your club uploads to or generates in
  MediaHub about its athletes, members and volunteers ("Club Data"). The club is the
  controller; {COMPANY_NAME} is the processor and processes Club Data only on the
  club's documented instructions &mdash; given through the product's controls (upload,
  configure, approve, publish, delete) &mdash; unless UK law requires otherwise, in
  which case we tell you before processing unless that law forbids it.</p>
</div>

<div class="card">
  <h2>2. Subject matter, duration, nature and purpose</h2>
  <ul>
    <li><strong>Subject matter:</strong> competition results, rosters, photos, brand
        material, and content generated from them.</li>
    <li><strong>Duration:</strong> the life of the club's MediaHub workspace, plus the
        deletion window in section 9.</li>
    <li><strong>Nature &amp; purpose:</strong> parsing results, detecting achievements,
        verifying personal bests against public sources, rendering branded graphics and
        video, generating captions with AI providers, and queueing content for the
        club's approval and export/publication.</li>
    <li><strong>Data subjects:</strong> athletes (predominantly children), members,
        coaches, volunteers.</li>
    <li><strong>Data categories:</strong> names, dates of birth/ages, gender, club
        affiliation, race results and rankings, photographs, governing-body
        identifiers. No special-category data is intentionally processed; the club
        must not upload health or disability data.</li>
  </ul>
</div>

<div class="card">
  <h2>3. Children's data</h2>
  <p>The club warrants that it is entitled to process the athlete data it uploads, and
  that it holds parental consent where required &mdash; in particular for photographs
  of under-18s and for publishing content about them. MediaHub enforces, in code, that
  content concerning an under-18 athlete is never published without a human decision
  at the club.</p>
</div>

<div class="card">
  <h2>4. Confidentiality and personnel</h2>
  <p>Persons we authorise to process Club Data are bound by confidentiality
  obligations.</p>
</div>

<div class="card">
  <h2>5. Security measures (Annex A summary)</h2>
  <ul>
    <li>bcrypt password hashing; signed HttpOnly/SameSite session cookies; idle
        session timeout.</li>
    <li>Per-organisation data isolation enforced on every request, with an automated
        test suite pinning the isolation invariants.</li>
    <li>Parameterised SQL throughout; HTML escaping of all user content; archive
        (zip-bomb/path-traversal) protections on uploads.</li>
    <li>Secrets held in the environment, never in source; secret files written with
        0600 permissions.</li>
    <li>Publishing guarded by a fail-closed gate (kill switch, confidence threshold,
        safeguarding check, rate caps) with an immutable per-organisation audit
        ledger.</li>
    <li>Transport encryption (HTTPS) terminated at the hosting platform.</li>
  </ul>
</div>

<div class="card">
  <h2>6. Sub-processors</h2>
  <p>The club authorises these sub-processors; data reaches a sub-processor only along
  the flows in the <a href="{privacy_url}">Privacy Notice</a>:</p>
  <table>
    <tr><th>Sub-processor</th><th>Processing</th><th>Location</th></tr>
    {subprocessor_table_rows_html()}
  </table>
  <p>We give at least 30 days' notice before adding or replacing a sub-processor; the
  club may object on reasonable data-protection grounds and terminate if we can't
  resolve the objection.</p>
</div>

<div class="card">
  <h2>7. International transfers</h2>
  <p>Transfers to the sub-processors above are protected by the UK&ndash;US Data Bridge
  where the provider is certified, otherwise by the UK IDTA/Addendum, as recorded in
  our processing records.</p>
</div>

<div class="card">
  <h2>8. Assistance, breach notification, audits</h2>
  <ul>
    <li>We assist the club with data-subject requests &mdash; the product's own
        export, erasure, rectification and correction tools are the primary
        mechanism.</li>
    <li>We notify the club <strong>without undue delay</strong> after becoming aware of
        a personal-data breach affecting Club Data, with enough detail for the club to
        meet its 72-hour ICO obligation.</li>
    <li>We make available the information reasonably necessary to demonstrate
        compliance, and allow audits (at most annually, on 30 days' notice, at the
        club's cost) where the documentation is insufficient.</li>
  </ul>
</div>

<div class="card">
  <h2>9. Deletion and return</h2>
  <p>The club can delete any run, athlete or its whole workspace through the product
  at any time. On termination we delete all Club Data within 30 days, except where UK
  law requires retention. Export tools allow the club to take a copy first.</p>
</div>

<div class="card">
  <h2>10. Acceptance</h2>
  <p>This DPA is presented at workspace setup and accepted by the club officer creating
  the workspace; the acceptance (account email, version {DPA_VERSION}, timestamp,
  workspace) is recorded in an append-only ledger.</p>
</div>
"""


__all__ = [
    "Acceptance",
    "AcceptanceStore",
    "COMPANY_NAME",
    "COMPANY_NUMBER",
    "CONTACT_EMAIL",
    "COOKIES_VERSION",
    "DOC_COOLING_OFF",
    "DOC_DATA_ATTESTATION",
    "DOC_DPA",
    "DOC_TERMS",
    "DPA_VERSION",
    "ICO_REGISTRATION_NUMBER",
    "NON_SUBPROCESSOR_PROVIDER_ENV",
    "PLACEHOLDERS",
    "PRIVACY_VERSION",
    "REGISTERED_ADDRESS",
    "SUBPROCESSORS",
    "Subprocessor",
    "TERMS_VERSION",
    "cookies_html",
    "current_version",
    "dpa_html",
    "identity_block",
    "privacy_html",
    "subprocessor_public_rows_html",
    "subprocessor_table_rows_html",
    "terms_html",
]
