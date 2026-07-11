"""Plain session-based auth: no Flask-Login needed for two roles and one DB table."""

import functools

from flask import g, redirect, session, url_for

from .db import get_db


def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = None
    if user_id is not None:
        g.user = get_db().execute(
            "SELECT u.id AS id, u.username AS username, u.role AS role, u.resident_id AS resident_id, r.full_name AS full_name "
            "FROM users u "
            "LEFT JOIN residents r ON r.id = u.resident_id "
            "WHERE u.id = ?", (user_id,)
        ).fetchone()


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login"))
        if g.user["role"] != "admin":
            return "Forbidden: admin access only", 403
        return view(*args, **kwargs)

    return wrapped
