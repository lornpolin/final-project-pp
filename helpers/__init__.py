"""
Helpers package – decorators, CSRF protection, template filters and error handlers.
"""
import functools
import secrets
from datetime import timedelta, timezone
from decimal import Decimal

from flask import (
    session, redirect, url_for, flash, abort, render_template, request,
)
from werkzeug.exceptions import RequestEntityTooLarge


# ── Decorators ───────────────────────────────────────────────────────

def admin_required(f):
    """Redirect to the admin login page unless an ADMIN is signed in."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to access the admin area.", "warning")
            return redirect(url_for("admin.login", next=request.path))
        if session.get("role") != "ADMIN":
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ── CSRF protection (lightweight, session based) ─────────────────────

CSRF_SESSION_KEY = "_csrf_token"


def generate_csrf_token():
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def register_csrf(app):
    app.jinja_env.globals["csrf_token"] = generate_csrf_token

    @app.before_request
    def _csrf_protect():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            expected = session.get(CSRF_SESSION_KEY)
            if not sent or not expected or not secrets.compare_digest(sent, expected):
                abort(400, description="Your session expired or the form is invalid. Please try again.")


# ── Template filters ─────────────────────────────────────────────────

def register_template_filters(app):
    @app.template_filter("money")
    def money(value, currency=None):
        currency = (currency or app.config.get("CURRENCY", "USD")).upper()
        value = Decimal(str(value or 0))
        if currency == "KHR":
            return f"{value:,.0f} ៛"
        return f"${value:,.2f}"

    @app.template_filter("datetime")
    def fmt_datetime(value, fmt="%d %b %Y, %H:%M"):
        """Format a UTC datetime in the shop's local time (Cambodia = UTC+7)."""
        if not value:
            return "—"
        if value.tzinfo is None:  # SQLite returns naive UTC datetimes
            value = value.replace(tzinfo=timezone.utc)
        local = timezone(timedelta(hours=app.config.get("DISPLAY_UTC_OFFSET_HOURS", 7)))
        return value.astimezone(local).strftime(fmt)


# ── Error Handlers ───────────────────────────────────────────────────

def register_error_handlers(app):
    """Register custom error handlers on the Flask app."""

    def render(code, title, message):
        return render_template("errors.html", code=code, title=title, message=message), code

    @app.errorhandler(400)
    def bad_request(e):
        return render(400, "Bad Request",
                      getattr(e, "description", None) or "The server could not understand your request.")

    @app.errorhandler(403)
    def forbidden(e):
        return render(403, "Access Denied", "You do not have permission to view this page.")

    @app.errorhandler(404)
    def not_found(e):
        return render(404, "Page Not Found", "The page you are looking for does not exist.")

    @app.errorhandler(413)
    @app.errorhandler(RequestEntityTooLarge)
    def file_too_large(e):
        return render(413, "File Too Large", "The uploaded file exceeds the 10 MB limit.")

    @app.errorhandler(429)
    def too_many_requests(e):
        return render(429, "Too Many Requests", "Too many attempts. Please wait a minute and try again.")

    @app.errorhandler(500)
    def internal_error(e):
        return render(500, "Internal Server Error", "Something went wrong on our end.")
