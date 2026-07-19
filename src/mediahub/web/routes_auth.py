"""Identity & account lifecycle: sign-in/out, signup, password, account, onboarding.

Carved out of ``web.create_app`` (deep-review finding #15, final stage).
Handlers are byte-identical to their closure versions except that
web-module globals are reached as ``W.<name>`` (call-time resolution:
reload-safe, and ``mock.patch('mediahub.web.web.x')`` still lands) and
any captured ``app`` became ``current_app``. Endpoint names are
PRESERVED via ``add_url_rule`` (ADR-0031).
"""

from __future__ import annotations

from markupsafe import escape as _h
import threading
from flask import (
    abort,
    current_app,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)

from mediahub.web import web as W


def onboarding_sample():
    """U.4 — one-click sample-to-first-content-pack.

    Runs the real pipeline on the bundled synthetic meet, stamped to
    the signed-in org so the cards come out in the user's brand, and
    bounces to the standard run-progress page (which advances to the
    review queue on completion). The org gate already guarantees a
    ready profile before this route is reachable; the explicit check
    keeps it honest under TESTING (where the gate is bypassed).
    """
    prof = W._active_profile()
    if not (prof and prof.is_ready()):
        return redirect(url_for("organisation_setup"))
    if not W._SAMPLE_MEET_PDF.exists():
        return W._recovery_page(
            "Sample meet unavailable",
            "The bundled sample meet isn't present on this deployment, "
            "so there's nothing to generate from. Upload your own results "
            "file to create a content pack.",
            eyebrow="Sample pack",
            primary_cta=("Upload results", url_for("upload")),
            secondary_cta=("Back to create", url_for("make_page")),
            code=404,
        )
    file_bytes = W._SAMPLE_MEET_PDF.read_bytes()
    # Synthetic swimmers — there is nothing to web-verify, so PB web
    # verification is off (faster, and no PB-verification calls for demo
    # data). Meet-identity research inside the recognition report still
    # runs, but it is globally cached, so only the first uncached sample
    # generation on a deployment can trigger an outbound lookup. The hero
    # club is pre-selected so the pack shows its best spread of cards.
    run_id = W._start_run(
        file_bytes,
        W._SAMPLE_MEET_FILENAME,
        prof.profile_id,
        True,  # use_pb_cache
        False,  # fetch_pbs
        club_filter=W._SAMPLE_MEET_CLUB,
    )
    W._mark_run_sample(run_id)
    try:
        from mediahub.workflow.autonomy import AuditLog

        AuditLog().record(
            prof.profile_id,
            f"run:{run_id}",
            "sample_pack_started",
            tool="onboarding_sample",
            args={"run_id": run_id, "club": W._SAMPLE_MEET_CLUB},
            result="started",
        )
    except Exception:
        pass
    return redirect(url_for("run_status", run_id=run_id))


def account_export_route():
    email = W._auth.current_user_email()
    if not email:
        return redirect(url_for("login_page", next=url_for("account_export_route")))
    from mediahub.privacy import account_export

    payload = account_export(email)
    resp = jsonify(payload)
    resp.headers["Content-Disposition"] = 'attachment; filename="mediahub-account-export.json"'
    return resp


def account_delete():
    email = W._auth.current_user_email()
    if not email:
        return redirect(url_for("login_page"))
    # Deleting an account is irreversible — re-verify the password so a
    # hijacked session can't silently destroy the account.
    password = request.form.get("password") or ""
    # E-9: return the user to the page they deleted from (Settings account
    # or /privacy), not a hardcoded /privacy.
    _back = W._safe_next(request.form.get("return_to")) or url_for("privacy_page")
    try:
        W._user_store().authenticate(email, password)
    except W._auth.AuthError:
        return (
            W._layout(
                "Account not deleted",
                '<div class="card"><p class="tag bad">Password check failed '
                "&mdash; account NOT deleted.</p>"
                f'<p><a class="btn secondary" href="{_h(_back)}">'
                "&larr; Back</a></p></div>",
                active="settings",
            ),
            403,
        )
    from mediahub.privacy import erase_account

    erase_account(email)
    W._auth.logout_user()
    session.clear()
    # E-9: land on an explicit confirmation, not a silent bounce to home
    # that leaves the user unsure whether it worked.
    return W._layout(
        "Account deleted",
        '<section class="mh-hero" style="padding-top:var(--sp-7);'
        'padding-bottom:var(--sp-5);margin-bottom:var(--sp-5)">'
        '<span class="mh-hero-eyebrow">Account</span>'
        '<h1>Your account has been <em class="editorial">deleted.</em></h1></section>'
        '<div class="card"><p>Your MediaHub account and its personal data have been '
        "erased. You have been signed out.</p>"
        f'<p><a class="btn" href="{url_for("home")}">Back to home</a></p></div>',
        active="home",
    )


# PC.1 / PC.2 — self-serve account auth + Stripe billing (Phase C).
#
# These are ACCOUNT-level (email + password → who is paying), distinct
# from the organisation-level /sign-in picker below (which club's brand
# is active). A deployment with no STRIPE_* env and no accounts never
# forces anyone here — every existing route stays open. Billing routes
# honest-error with 503 when Stripe is unconfigured.
def signup_page():
    # Already signed in? Send them on to the app.
    if W._auth.current_user_email():
        return redirect(url_for("make_page"))
    return W._auth_form_page(
        title="Create account",
        heading='Create your <em class="editorial">account</em>.',
        lede=(
            "One account runs your club&rsquo;s content. Free to start &mdash; "
            "3 runs a month, no card required. "
            "Before you start, have your club&rsquo;s website, social profiles, and brand "
            "guidelines to hand &mdash; the engine needs them to produce on-brand content. "
            "Right after you sign up we&rsquo;ll walk you through pasting those links (or "
            "uploading a guidelines document) so the AI can build your brand kit &mdash; "
            "most fields are optional, and the whole thing takes about 5&nbsp;minutes."
        ),
        action_url=url_for("signup_post"),
        submit_label="Create account",
        alt_html=(
            f'Already have an account? <a href="{url_for("login_page")}" '
            'style="color:var(--accent);font-weight:600">Log in</a>.'
        ),
        min_password=True,
        extra_fields_html=(
            W._referral_field_html(request.args.get("ref") or "") + W._terms_checkbox_html()
        ),
    )


def signup_post():
    if W._auth_rate_limited("signup"):
        return W._auth_rate_limit_response()
    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""

    def _signup_error(message: str, status: int):
        return (
            W._auth_form_page(
                title="Create account",
                heading='Create your <em class="editorial">account</em>.',
                lede="One account runs your club's content. Free to start.",
                action_url=url_for("signup_post"),
                submit_label="Create account",
                alt_html=(
                    f'Already have an account? <a href="{url_for("login_page")}" '
                    'style="color:var(--accent);font-weight:600">Log in</a>.'
                ),
                prefill_email=email,
                error=message,
                min_password=True,
                extra_fields_html=(
                    W._referral_field_html(request.form.get("ref") or "") + W._terms_checkbox_html()
                ),
            ),
            status,
        )

    # Versioned ToS acceptance is a hard requirement at signup — the
    # browser's `required` attribute is convenience, this is the gate.
    if (request.form.get("accept_terms") or "") != "1":
        return _signup_error(
            "Please accept the Terms of Service and Privacy Notice to create an account.",
            400,
        )
    store = W._user_store()
    try:
        user = store.create(email, password)
    except W._auth.AuthError as exc:
        return _signup_error(str(exc), 400)
    # Session rotation on privilege change (signup = login) — clear the
    # pre-signup session BEFORE the acceptance marker lands in it.
    session.clear()
    # Record the timestamped, versioned acceptance before the session
    # starts; the session marker spares the ledger a read per request.
    W._legal.AcceptanceStore().record(user.email, W._legal.DOC_TERMS, W._legal.TERMS_VERSION)
    session["terms_ok_version"] = W._legal.TERMS_VERSION
    W._auth.login_user(user)
    from mediahub.compliance.security_log import record_event as _sec_event

    _sec_event("signup", actor=user.email)
    # PC.3 (ADR-0014): activate any operator-issued workspace invites for
    # this email — the zero-founder-involvement first-claim path. The org
    # binds the moment its invited owner signs up.
    try:
        W._tenancy.MembershipStore().activate_invites(user.email)
        W._invalidate_memberships_snapshot()
    except Exception:
        W.log.warning("invite activation failed for a new account", exc_info=True)
    # PC.14: verification mail (best-effort; only when the email seam
    # is configured — signup never blocks on it).
    _verify_sent = W._send_verification_email(user.email)
    # D-35 — tell the user their account was created (and, honestly, whether
    # a verification link is on its way) instead of a silent redirect.
    if _verify_sent:
        W._flash_toast(
            f"Account created — we've sent a verification link to {user.email}. "
            "Verify it so password resets and notices reach you.",
            "success",
        )
    else:
        W._flash_toast("Account created — you're signed in.", "success")
    # PC.9: a referral code records the new club as a code-tracked lead
    # in the PC.6 funnel — zero operator typing. Best-effort: a bad
    # code must never break a signup.
    ref_code = (request.form.get("ref") or "").strip()
    if ref_code:
        try:
            from mediahub.commercial.referrals import record_referred_signup

            record_referred_signup(ref_code, user.email)
        except Exception:
            W.log.warning("referral signup recording failed", exc_info=True)
    # First-run routing (A-4 + A1, org-access audit): an account that
    # signed up via an invite already belongs to a workspace — pin it and
    # land straight in the app, never on the picker. A brand-new account
    # with no membership goes straight to setup to create its own club
    # (sending it to /make would just trip the org-ready gate).
    if W._auto_pin_member_org():
        return redirect(url_for("make_page"))
    return redirect(url_for("organisation_setup"))


def login_page():
    if W._auth.current_user_email():
        return redirect(url_for("make_page"))
    nxt = W._safe_next(request.args.get("next"))
    action = url_for("login_post", next=nxt) if nxt else url_for("login_post")
    alt = (
        f'No account yet? <a href="{url_for("signup_page")}" '
        'style="color:var(--accent);font-weight:600">Create one</a>.'
        f'<br><a href="{url_for("password_forgot")}" '
        'style="color:var(--ink-muted);font-weight:600">Forgot your password?</a>'
    )
    alt += (
        f'<br><a href="{url_for("developer_login")}" '
        'style="color:var(--ink-muted);font-weight:600">'
        "Developer sign-in &rarr;</a>"
    )
    return W._auth_form_page(
        title="Log in",
        heading='Welcome <em class="editorial">back</em>.',
        lede="Log in to manage your content and billing.",
        action_url=action,
        submit_label="Log in",
        alt_html=alt,
    )


def login_post():
    from mediahub.compliance.security_log import record_event as _sec_event

    # Two layers by design: the W per-IP auth limiter (fast 429 on raw
    # request volume) + the per-email/per-address lockout below (counts
    # FAILURES, blocks before password verification).
    if W._auth_rate_limited("login"):
        return W._auth_rate_limit_response()
    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""
    # Lockout BEFORE password verification: a locked key gets the same
    # response whether or not the password would have been right.
    if W._auth.login_locked(email):
        _sec_event("login_locked_attempt", actor=W._auth.normalize_email(email), outcome="blocked")
        return W._login_error_page(
            email, "Too many failed attempts — try again in 15 minutes.", 429
        )
    store = W._user_store()
    try:
        user = store.authenticate(email, password)
    except W._auth.AuthError as exc:
        locked_now = W._auth.record_login_failure(email)
        _sec_event(
            "login_lockout" if locked_now else "login_failed",
            actor=W._auth.normalize_email(email),
            outcome="lockout" if locked_now else "failed",
        )
        return W._login_error_page(email, str(exc))
    # Optional second factor: password ok → park the email (NOT a login)
    # and ask for the TOTP code.
    if user.totp_secret:
        session["pending_2fa_email"] = user.email
        return redirect(url_for("login_2fa"))
    W._auth.clear_login_failures(email)
    # Session rotation on privilege change: drop everything the
    # pre-login session held before granting the signed-in identity.
    session.clear()
    W._auth.login_user(user)
    _sec_event("login", actor=user.email)
    # A1 (org-access audit): bind the member's own organisation into the
    # session at sign-in so they land straight on their club — the picker
    # is never part of a member's sign-in flow.
    W._auto_pin_member_org()
    nxt = W._safe_next(request.args.get("next") or request.form.get("next"))
    # Re-acceptance check: accounts whose recorded Terms acceptance
    # predates TERMS_VERSION (or legacy accounts with no record) are
    # routed through /legal/accept before they continue.
    if W._legal.AcceptanceStore().needs_terms_reacceptance(user.email):
        return redirect(
            url_for("legal_accept_page", next=nxt) if nxt else url_for("legal_accept_page")
        )
    session["terms_ok_version"] = W._legal.TERMS_VERSION
    return redirect(nxt or url_for("make_page"))


def login_2fa():
    from mediahub.compliance.security_log import record_event as _sec_event

    email = session.get("pending_2fa_email") or ""
    if not email:
        return redirect(url_for("login_page"))
    if request.method == "GET":
        if request.args.get("cancel"):
            # Back to log in: abandon the half-finished 2FA login.
            session.pop("pending_2fa_email", None)
            return redirect(url_for("login_page"))
        return W._login_2fa_page()
    # SEC-27: per-IP volume brake on the code-submission POST, matching the
    # password step's /login brake (it was previously missing here, so TOTP
    # guessing was bounded only by the per-account lockout). Its OWN bucket
    # ("login_2fa"), separate from "login", so a shared NAT completing both
    # steps doesn't compound the two against one budget.
    if W._auth_rate_limited("login_2fa"):
        return W._login_2fa_page(
            "Too many attempts from your network — wait a few minutes and try again.", 429
        )
    if W._auth.login_locked(email):
        return W._login_2fa_page("Too many failed attempts — try again in 15 minutes.", 429)
    store = W._user_store()
    user = store.get(email)
    code = request.form.get("totp") or ""
    ok = user is not None and W._auth.totp_verify(user.totp_secret, code)
    used_recovery = False
    if not ok and user is not None:
        # Same input doubles as the recovery-code field: a consumed code
        # (single-use, hash removed on success) logs in like a TOTP match.
        used_recovery = store.consume_recovery_code(email, code)
        ok = used_recovery
    if not ok:
        locked_now = W._auth.record_login_failure(email)
        _sec_event(
            "login_lockout" if locked_now else "login_2fa_failed",
            actor=email,
            outcome="lockout" if locked_now else "failed",
        )
        return W._login_2fa_page("That code did not match — try again.", 401)
    W._auth.clear_login_failures(email)
    session.clear()
    W._auth.login_user(user)
    _sec_event("login", actor=user.email, detail="2fa_recovery" if used_recovery else "2fa")
    # A1: same direct-to-their-club landing as the password-only path.
    W._auto_pin_member_org()
    return redirect(url_for("make_page"))


def account_2fa():
    from mediahub.compliance.security_log import record_event as _sec_event

    email = W._auth.current_user_email()
    if not email:
        return redirect(url_for("login_page"))
    store = W._user_store()
    user = store.get(email)
    if user is None:
        return redirect(url_for("login_page"))
    if request.method == "POST":
        action = request.form.get("action") or ""
        code = request.form.get("totp") or ""
        if action == "enable":
            secret = session.get("totp_setup_secret") or ""
            if secret and W._auth.totp_verify(secret, code):
                store.set_totp(email, secret)
                # Issue the one-time recovery codes: only salted hashes are
                # persisted; the plaintext is shown once on the next page.
                codes = W._auth.recovery_generate_codes()
                store.set_recovery_codes(email, [W._auth.recovery_hash(c) for c in codes])
                session.pop("totp_setup_secret", None)
                _sec_event("totp_enabled", actor=email)
                return W._twofa_codes_page(codes, "Two-factor authentication is on")
            # Inline re-render of the same setup page (QR + secret intact —
            # the session still holds the pending secret), not a dead end.
            return W._twofa_no_store(
                W._layout(
                    "Two-factor",
                    W._twofa_setup_body(
                        email, error="That code did not match — scan the code again and retry."
                    ),
                    active="",
                ),
                400,
            )
        if action == "disable":
            if user.totp_secret and W._auth.totp_verify(user.totp_secret, code):
                store.set_totp(email, "")  # also drops the recovery-code hashes
                _sec_event("totp_disabled", actor=email)
                return redirect(url_for("account_2fa"))
            return W._layout(
                "Two-factor",
                W._twofa_enabled_body(
                    user,
                    error="Enter a valid current code to switch 2FA off.",
                    error_action="disable",
                ),
                active="",
            ), 400
        if action == "regenerate":
            if user.totp_secret and W._auth.totp_verify(user.totp_secret, code):
                codes = W._auth.recovery_generate_codes()
                store.set_recovery_codes(email, [W._auth.recovery_hash(c) for c in codes])
                _sec_event("totp_recovery_regenerated", actor=email)
                return W._twofa_codes_page(codes, "Fresh recovery codes")
            return W._layout(
                "Two-factor",
                W._twofa_enabled_body(
                    user,
                    error="Enter a valid current code to issue fresh recovery codes.",
                    error_action="regenerate",
                ),
                active="",
            ), 400
        return jsonify({"error": "unknown action"}), 400
    if user.totp_secret:
        return W._layout("Two-factor", W._twofa_enabled_body(user), active="")
    return W._twofa_no_store(W._layout("Two-factor", W._twofa_setup_body(email), active=""))


def logout():
    """End the account (or operator) session.

    POST performs the logout — the state change rides the app-wide CSRF
    token like every other form (P3, org-access audit). GET only renders
    a confirmation page, so a cross-site link can no longer end (or
    probe) a session. Logout also revokes server-side: the account's
    session epoch moves on (dev sessions: the revocation watermark), so
    a replayed pre-logout cookie is dead, and the WHOLE session is
    cleared — the org pin must never outlive the identity that earned it.
    """
    if request.method == "GET":
        body = (
            '<div class="card" style="max-width:420px;margin:40px auto;padding:24px 28px">'
            "<h2>Sign out?</h2>"
            '<p class="dim" style="font-size:13px">This ends your session on every '
            "device you are signed in on.</p>"
            f'<form method="post" action="{url_for("logout")}">'
            '<button type="submit" class="btn" style="margin-top:12px;width:100%">'
            "Sign out</button></form>"
            f'<div class="dim" style="font-size:13px;margin-top:14px;text-align:center">'
            f'<a href="{url_for("home")}" style="color:var(--accent)">Cancel</a></div>'
            "</div>"
        )
        return W._layout("Sign out", body, active="")
    from mediahub.compliance.security_log import record_event as _sec_event

    email = W._auth.current_user_email()
    if email:
        W._user_store().bump_session_epoch(email)
        _sec_event("logout", actor=email)
    if W._auth.is_dev_operator():
        W._auth.revoke_dev_sessions()
        _sec_event("logout", actor="dev_operator")
    session.clear()
    return redirect(url_for("home"))


def password_forgot():
    from mediahub.notify.email import EmailSendError, email_configured, send_email
    from mediahub.web import account_tokens as _tokens

    if not email_configured():
        # Honest unavailable state: the GET page renders at 200 (no GET
        # surface may 5xx — B5 API contract); the POST action is a 503.
        return W._email_unavailable_page(
            "Password reset unavailable",
            status=503 if request.method == "POST" else 200,
        )
    if request.method == "POST":
        if W._auth_rate_limited("pwreset"):
            return W._auth_rate_limit_response()
        email = W._auth.normalize_email(request.form.get("email") or "")
        user = W._user_store().get(email) if email else None
        if user is not None:
            token = _tokens.mint_reset_token(
                current_app.secret_key, user.email, user.hashed_password
            )
            reset_url = url_for("password_reset", token=token, _external=True)
            mail_text = (
                "Someone (hopefully you) asked to reset the password for "
                f"this MediaHub account.\n\nReset it here (link valid for "
                f"{int(_tokens.RESET_MAX_AGE_HOURS)} hours, single use):\n"
                f"{reset_url}\n\nIf this wasn't you, ignore this email — "
                "your password is unchanged."
            )

            # Timing-oracle guard: the provider POST takes hundreds of ms,
            # so a synchronous send would make known-account requests
            # measurably slower than unknown ones even though the bodies
            # are identical. Fire-and-forget from a thread (send failures
            # were already log-only best-effort); the URL and text are
            # built above, inside the request context.
            def _send_reset_mail(to_email: str = user.email, text: str = mail_text) -> None:
                try:
                    send_email(to_email, "Reset your MediaHub password", text)
                except EmailSendError:
                    W.log.warning("password reset email failed", exc_info=True)

            threading.Thread(target=_send_reset_mail, name="pwreset-mail", daemon=True).start()
        # Identical response whether or not the account exists — the
        # form must not be an email-enumeration oracle.
        body = W._account_email_card(
            "<p>If an account exists for that address, a reset link is on "
            "its way. The link works once and expires in "
            f"{int(_tokens.RESET_MAX_AGE_HOURS)} hours.</p>"
            f'<p><a class="btn secondary" href="{url_for("login_page")}">'
            "&larr; Back to log in</a></p>",
            title="Check your email",
            heading='Check your <em class="editorial">email</em>.',
            lede="We've sent a reset link if the account exists.",
        )
        return W._layout("Check your email", body, active="signin")
    body = W._account_email_card(
        f'<form method="post" action="{url_for("password_forgot")}">'
        '<label style="display:block;font-size:12px;text-transform:uppercase;'
        'letter-spacing:0.06em;color:var(--ink-muted);margin-bottom:6px">Email</label>'
        '<input type="email" name="email" autocomplete="email" required '
        'style="width:100%" placeholder="you@club.org" />'
        '<button type="submit" class="btn" style="margin-top:20px;width:100%">'
        "Send reset link</button></form>",
        title="Forgot password",
        heading='Forgot your <em class="editorial">password</em>?',
        lede="Enter your account email and we'll send a single-use reset link.",
    )
    return W._layout("Forgot password", body, active="signin")


def password_reset(token: str):
    from mediahub.web import account_tokens as _tokens

    def _hash_for(email: str):
        u = W._user_store().get(email)
        return u.hashed_password if u else None

    try:
        email = _tokens.verify_reset_token(
            current_app.secret_key, token, current_hash_for_email=_hash_for
        )
    except _tokens.AccountTokenExpired:
        return W._layout(
            "Link expired",
            '<div class="card"><p class="tag bad">This reset link has '
            "expired.</p>"
            f'<p><a class="btn secondary" href="{url_for("password_forgot")}">'
            "Request a new one</a></p></div>",
            active="signin",
        ), 410
    except _tokens.AccountTokenError:
        return W._layout(
            "Invalid link",
            '<div class="card"><p class="tag bad">This reset link is invalid '
            "or has already been used.</p>"
            f'<p><a class="btn secondary" href="{url_for("password_forgot")}">'
            "Request a new one</a></p></div>",
            active="signin",
        ), 404
    if request.method == "POST":
        if W._auth_rate_limited("pwreset"):
            return W._auth_rate_limit_response()
        try:
            user = W._user_store().set_password(email, request.form.get("password") or "")
        except W._auth.AuthError as exc:
            body = W._account_email_card(
                f'<p class="tag bad">{_h(str(exc))}</p>'
                f'<form method="post" action="{url_for("password_reset", token=token)}">'
                '<label style="display:block;font-size:12px;text-transform:uppercase;'
                'letter-spacing:0.06em;color:var(--ink-muted);margin-bottom:6px">'
                "New password</label>"
                '<input type="password" name="password" required minlength="8" '
                'autocomplete="new-password" style="width:100%" />'
                '<button type="submit" class="btn" style="margin-top:20px;width:100%">'
                "Set new password</button></form>",
                title="Choose a new password",
                heading='Choose a new <em class="editorial">password</em>.',
                lede="At least 8 characters.",
            )
            return W._layout("Choose a new password", body, active="signin"), 400
        if user is None:
            abort(404)
        # Rotate the session before re-login: set_password bumped the epoch
        # (revoking pre-reset cookies), so re-mint the current browser under
        # the new epoch and drop any stale pre-reset session state.
        session.clear()
        W._auth.login_user(user)
        if not W._legal.AcceptanceStore().needs_terms_reacceptance(user.email):
            session["terms_ok_version"] = W._legal.TERMS_VERSION
        # D-35 — confirm the change instead of a silent login + redirect.
        W._flash_toast("Password updated — you're signed in.", "success")
        return redirect(url_for("make_page"))
    body = W._account_email_card(
        f'<form method="post" action="{url_for("password_reset", token=token)}">'
        '<label style="display:block;font-size:12px;text-transform:uppercase;'
        'letter-spacing:0.06em;color:var(--ink-muted);margin-bottom:6px">'
        f"New password for {_h(email)}</label>"
        '<input type="password" name="password" required minlength="8" '
        'autocomplete="new-password" style="width:100%" />'
        '<div class="dim" style="font-size:12px;margin-top:6px">At least 8 characters.</div>'
        '<button type="submit" class="btn" style="margin-top:20px;width:100%">'
        "Set new password</button></form>",
        title="Choose a new password",
        heading='Choose a new <em class="editorial">password</em>.',
        lede="This link works once.",
    )
    return W._layout("Choose a new password", body, active="signin")


def verify_email(token: str):
    from mediahub.web import account_tokens as _tokens

    try:
        email = _tokens.verify_verify_token(current_app.secret_key, token)
    except _tokens.AccountTokenError:
        return W._layout(
            "Invalid link",
            '<div class="card"><p class="tag bad">This verification link is '
            "invalid or has expired.</p></div>",
            active="signin",
        ), 404
    user = W._user_store().mark_email_verified(email)
    if user is None:
        abort(404)
    return W._layout(
        "Email verified",
        '<div class="card"><p class="tag good">Email address verified — '
        "thanks!</p>"
        f'<p><a class="btn secondary" href="{url_for("make_page")}">'
        "Continue &rarr;</a></p></div>",
        active="signin",
    )


def sign_in_page():
    # PC.3: the picker only offers workspaces this session may enter —
    # bound orgs are invisible to non-members (ADR-0014).
    profiles = [p for p in W.list_profiles() if W._session_can_use_profile(p.profile_id)]
    current_id = W._active_profile_id() or ""
    # A-6: a same-site destination threaded here by the org-ready gate, so
    # signing in resumes the page the user was heading to.
    _next_val = W._safe_next(request.args.get("next"))

    # A1 (org-access audit): a signed-in member with exactly one
    # organisation never routes through the picker — /sign-in IS their
    # club, so pin it and continue to the app (or the threaded next).
    # A pending error flash still renders the page so the message isn't
    # lost; the rare multi-org account keeps a picker that the server
    # filter above confines to its own workspaces; the dev operator
    # keeps the full picker (cross-org roaming is operator-only).
    if (
        len(profiles) == 1
        and W._auth.current_user_email()
        and not W._auth.is_dev_operator()
        and not session.get("sign_in_error")
    ):
        W._pin_active_profile(profiles[0].profile_id)
        return redirect(_next_val or url_for("make_page"))

    # Surface any error flashed by sign_in_post / a delete bounce / a
    # signed-out share-target (silent failures fixed). Computed up here so it
    # renders on BOTH the empty state and the picker.
    err = session.pop("sign_in_error", None)
    err_html = ""
    if err:
        err_html = (
            '<div class="mh-flash error" role="alert" style="'
            "margin: 0 0 var(--sp-5);"
            "padding: 14px 18px;"
            "border: 1px solid rgba(255,107,107,0.30);"
            "border-left: 3px solid var(--bad);"
            "background: var(--bad-bg);"
            "color: var(--ink);"
            "font-family: var(--font-mono);"
            "font-size: 12px;"
            "letter-spacing: 0.10em;"
            "text-transform: uppercase;"
            f'">[ ERROR ] {_h(err)}</div>'
        )

    # No profiles yet — render an honest empty state with a clear
    # path forward. Previously this redirected straight to
    # /organisation/setup, which made the home page "Sign in" button
    # appear broken (it'd land you back on the setup screen with no
    # explanation). Now the user sees what's going on and has both
    # the "Create" CTA and a way back home.
    if not profiles:
        new_org_url = url_for("organisation_setup")
        home_url = url_for("home")
        empty_body = (
            err_html + "<h1>Choose your organisation</h1>"
            '<p class="lede" style="margin-bottom:var(--sp-6)">'
            "You don't have access to any organisation yet. "
            "Create one and it will appear here next time."
            "</p>"
            '<div class="card" style="padding:24px 28px;margin-bottom:18px">'
            '<h2 style="margin-top:0;font-size:18px">Get started</h2>'
            '<p class="dim" style="margin-bottom:18px;font-size:13px">'
            "MediaHub needs to know who you are before it can produce "
            "on-brand content. Create your first organisation profile "
            "&mdash; it takes a minute &mdash; and the AI will read "
            "your website and social profiles so every caption it "
            "writes sounds like you."
            "</p>"
            f'<a class="btn" href="{new_org_url}">'
            "Create your first organisation &rarr;</a>"
            f'<a class="btn secondary" href="{home_url}" '
            'style="margin-left:10px">Back to home</a>'
            "</div>"
        )
        return W._layout("Choose organisation", empty_body, active="signin")

    def _initials(name: str) -> str:
        parts = [p for p in (name or "").strip().split() if p]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()

    from mediahub.brand import logos as logos_mod

    cards_html = ""
    for p in profiles:
        is_current = p.profile_id == current_id
        logo_html = ""
        # Every on-card logo is served FIRST-PARTY. The app CSP pins
        # ``img-src 'self'``, so a website-scraped ``brand_logo_url`` (an
        # external origin) can never render here — the browser blocks it
        # and the card shows a broken-image icon. That is exactly why "the
        # logos sometimes don't load on the sign-in cards": orgs with an
        # uploaded logo worked; orgs that only have a detected website logo
        # didn't. So: uploaded logo → per-profile serve route; else the
        # detected logo → first-party mirror route (downloads + caches the
        # bytes on first request); else initials.
        # Unified logo chip — the KEYED silhouette (opaque/white backgrounds
        # removed, so no white box) on a contrast-aware, brand-tinted backing,
        # with a built-in org-initials fallback. Every org tile reads at the
        # same size and weight whatever its logo's colour / shape / format; an
        # org with no usable logo simply shows its initials in the same frame.
        _chip_src = ""
        _chip_tone = "light"
        _uploaded = getattr(p, "brand_logos", None) or []
        _first = next(
            (
                e
                for e in _uploaded
                if isinstance(e, dict)
                and e.get("logo_id")
                and str(e.get("mime", "")).startswith("image/")
            ),
            None,
        )
        if _first:
            _lid = _first.get("logo_id")
            # Only emit the logo <img> when its keyed silhouette actually
            # renders. logo_bg_silhouette_path() returns None for a missing or
            # un-keyable upload — the SAME None that makes the ?bg=1&chip=1 serve
            # route 404. Previously the picker always emitted the <img> and leaned
            # on that 404 + the img's onerror to swap in the initials; the 404
            # still tripped the autotest crawler's "image sub-request failed"
            # check (#884). Emitting no <img> for an un-keyable logo shows the
            # initials with zero failed sub-requests. The silhouette is cached and
            # logo_chip_tone computes it too, so this adds no real cost.
            if logos_mod.logo_bg_silhouette_path(p.profile_id, _lid):
                _chip_src = url_for(
                    "organisation_logo_serve",
                    profile_id=p.profile_id,
                    logo_id=_lid,
                    bg=1,
                    chip=1,
                )
                _chip_tone = logos_mod.logo_chip_tone(p.profile_id, _lid)
        else:
            _cap = (getattr(p, "brand_logo_url", "") or "").strip()
            if _cap.startswith("http://") or _cap.startswith("https://"):
                _chip_src = url_for(
                    "organisation_logo_mirror", profile_id=p.profile_id, bg=1, chip=1
                )
                _chip_tone = logos_mod.mirror_chip_tone(p.profile_id, _cap)
        _ext_pal = getattr(p, "brand_palette_extracted", None) or {}
        _brand = (_ext_pal.get("primary") or "").strip() or (
            getattr(p, "brand_primary", "") or ""
        ).strip()
        logo_html = W._logo_chip_html(
            _chip_src,
            alt="",
            size="lg",
            tone=_chip_tone,
            brand_hex=_brand,
            initials=_initials(p.display_name),
        )

        ready = p.is_ready()
        captured = p.brand_capture_status in ("ok", "ok_heuristic")
        pill_html = ""
        if is_current:
            pill_html = (
                '<span class="pill" style="background:rgba(34,197,94,0.10);'
                'border-color:rgba(34,197,94,0.30);color:var(--good)">Active</span>'
            )
        if ready:
            pill_html += '<span class="pill">Brand ready</span>'
        elif captured:
            pill_html += (
                '<span class="pill" style="background:rgba(245,158,11,0.10);'
                'border-color:rgba(245,158,11,0.30);color:var(--warn)">'
                "Partial</span>"
            )
        else:
            pill_html += (
                '<span class="pill" style="background:rgba(255,255,255,0.06);'
                'border-color:rgba(255,255,255,0.10);color:var(--ink-muted)">'
                "Incomplete</span>"
            )

        sign_in_url = url_for("sign_in_post")
        delete_url = url_for("sign_in_delete")
        cards_html += (
            '<div class="mh-profile-card mh-spotlight-card">'
            f'<div class="logo">{logo_html}</div>'
            f'<div class="display-name">{_h(p.display_name)}</div>'
            f'<div class="meta-line">{pill_html}</div>'
            '<div class="actions">'
            f'<form method="post" action="{sign_in_url}" style="flex:1;display:flex" data-loader-text="Switching organisation">'
            f'<input type="hidden" name="profile_id" value="{_h(p.profile_id)}">'
            + (f'<input type="hidden" name="next" value="{_h(_next_val)}">' if _next_val else "")
            + '<button type="submit" class="btn-sign-in">'
            f"{'Continue' if is_current else 'Enter'} &rarr;</button>"
            "</form>"
            f'<form method="post" action="{delete_url}" data-no-loader="1" '
            f"onsubmit=\"return confirm('Remove &quot;{_h(p.display_name)}&quot; from this sign-in "
            f"list permanently? Its brand setup goes with it and this can\\u2019t be undone. "
            f"(Your processed results are kept.)')\">"
            f'<input type="hidden" name="profile_id" value="{_h(p.profile_id)}">'
            f'<button type="submit" class="btn-delete" aria-label="Delete profile" title="Delete profile">&times;</button>'
            "</form>"
            "</div>"
            "</div>"
        )

    new_org_url = url_for("organisation_setup", fresh="1")
    cards_html += (
        f'<a class="mh-new-profile" href="{new_org_url}">'
        '<div><div class="plus">+</div>'
        "Create new organisation</div></a>"
    )

    body = (
        '<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">'
        '<span class="mh-hero-eyebrow">Organisation</span>'
        '<h1>Choose your <em class="editorial">organisation</em>.</h1>'
        f'<p class="lede">{len(profiles):02d} saved {"profile" if len(profiles) == 1 else "profiles"} on this deployment. '
        "Picking one loads its brand voice, palette, logo, and history. "
        "Switch any time from the home page.</p>"
        "</section>"
        f"{err_html}"
        f'<div class="mh-profile-grid">{cards_html}</div>'
    )
    return W._layout("Choose organisation", body, active="signin")


def sign_in_post():
    """Pin the chosen profile into the session and redirect home.

    Failure paths now surface an error via the flash session so the
    sign-in picker can show the user why nothing happened.
    """
    # A-6: a same-site destination the picker carried through from the
    # gate; on success resume it, and preserve it across error re-renders.
    _nxt = W._safe_next(request.form.get("next"))

    def _back_to_picker():
        return redirect(url_for("sign_in_page", next=_nxt) if _nxt else url_for("sign_in_page"))

    pid = (request.form.get("profile_id") or "").strip()
    if not pid:
        session["sign_in_error"] = "Pick an organisation before signing in."
        return _back_to_picker()
    prof = W.load_profile(pid)
    if prof is None or not W._session_can_use_profile(prof.profile_id):
        # Same message for "doesn't exist" and "members-only" so the
        # picker can't be used to probe which orgs exist (ADR-0014).
        session["sign_in_error"] = (
            f"Couldn't find a profile with id '{pid}'. It may have been deleted."
        )
        return _back_to_picker()
    W._pin_active_profile(prof.profile_id)
    session.pop("sign_in_error", None)
    return redirect(_nxt or url_for("home"))


def sign_out():
    """Clear the active profile pin and return to the sign-in picker.

    POST-only for the state change (same CSRF rationale as /logout);
    GET renders a confirmation. Only anonymous pilot sessions and the
    dev operator see this control — a member's org access is bound to
    their account, so their exit is /logout.
    """
    if request.method == "GET":
        body = (
            '<div class="card" style="max-width:420px;margin:40px auto;padding:24px 28px">'
            "<h2>Leave this organisation?</h2>"
            '<p class="dim" style="font-size:13px">Your work is kept — you can '
            "re-enter the organisation from the picker at any time.</p>"
            f'<form method="post" action="{url_for("sign_out")}">'
            '<button type="submit" class="btn" style="margin-top:12px;width:100%">'
            "Leave organisation</button></form>"
            f'<div class="dim" style="font-size:13px;margin-top:14px;text-align:center">'
            f'<a href="{url_for("home")}" style="color:var(--accent)">Cancel</a></div>'
            "</div>"
        )
        return W._layout("Leave organisation", body, active="")
    session.pop("active_profile_id", None)
    session.pop("login_seen_at", None)
    session.pop("sign_in_error", None)
    return redirect(url_for("sign_in_page"))


def sign_in_delete():
    """Delete the profile JSON from disk and clear the session pin
    if it was the active one. Runs (under DATA_DIR/runs_v4) are NOT
    removed — they're orphaned but recoverable.
    """
    pid = (request.form.get("profile_id") or "").strip()
    if not pid:
        return redirect(url_for("sign_in_page"))
    if W._tenancy.MembershipStore().is_bound(pid) and not W._session_owns_profile(pid):
        # Deleting a bound workspace is owner/operator-only (ADR-0014). E-8:
        # tell the member why the button did nothing instead of a silent bounce
        # (reusing the existing sign_in_error flash).
        session["sign_in_error"] = "Only the workspace owner can delete this organisation."
        return redirect(url_for("sign_in_page"))
    from .club_profile import _profiles_dir

    p = _profiles_dir() / f"{pid}.json"
    try:
        if p.exists():
            p.unlink()
    except OSError:
        pass
    # Deleting the file is a mid-request mutation the save hook can't see
    # (it bypasses save_profile), so drop the cached copy here — otherwise
    # the _active_profile_id() check below could read the just-deleted org.
    W._invalidate_profile_cache(pid)
    if W._active_profile_id() == pid:
        session.pop("active_profile_id", None)
    return redirect(url_for("sign_in_page"))


def register(app):
    """Attach this surface's routes with their ORIGINAL endpoint names."""
    app.add_url_rule(
        "/onboarding/sample",
        endpoint="onboarding_sample",
        view_func=onboarding_sample,
        methods=["POST"],
    )
    app.add_url_rule(
        "/account/export", endpoint="account_export_route", view_func=account_export_route
    )
    app.add_url_rule(
        "/account/delete", endpoint="account_delete", view_func=account_delete, methods=["POST"]
    )
    app.add_url_rule("/signup", endpoint="signup_page", view_func=signup_page, methods=["GET"])
    app.add_url_rule("/signup", endpoint="signup_post", view_func=signup_post, methods=["POST"])
    app.add_url_rule("/login", endpoint="login_page", view_func=login_page, methods=["GET"])
    app.add_url_rule("/login", endpoint="login_post", view_func=login_post, methods=["POST"])
    app.add_url_rule(
        "/login/2fa", endpoint="login_2fa", view_func=login_2fa, methods=["GET", "POST"]
    )
    app.add_url_rule(
        "/account/2fa", endpoint="account_2fa", view_func=account_2fa, methods=["GET", "POST"]
    )
    app.add_url_rule("/logout", endpoint="logout", view_func=logout, methods=["GET", "POST"])
    app.add_url_rule(
        "/password/forgot",
        endpoint="password_forgot",
        view_func=password_forgot,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/password/reset/<token>",
        endpoint="password_reset",
        view_func=password_reset,
        methods=["GET", "POST"],
    )
    app.add_url_rule("/verify-email/<token>", endpoint="verify_email", view_func=verify_email)
    app.add_url_rule("/sign-in", endpoint="sign_in_page", view_func=sign_in_page, methods=["GET"])
    app.add_url_rule("/sign-in", endpoint="sign_in_post", view_func=sign_in_post, methods=["POST"])
    app.add_url_rule("/sign-out", endpoint="sign_out", view_func=sign_out, methods=["GET", "POST"])
    app.add_url_rule(
        "/sign-in/delete", endpoint="sign_in_delete", view_func=sign_in_delete, methods=["POST"]
    )
