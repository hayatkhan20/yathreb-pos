"""Single owner login for the foundation; staff roles remain undecided."""

import hmac
import secrets
import time

from flask import Blueprint, abort, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from .db import get_db

bp = Blueprint("auth", __name__)
MAX_FAILURES = 5
WINDOW_SECONDS = 300


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def verify_csrf():
    expected = session.get("csrf_token", "")
    received = request.form.get("csrf_token", "")
    if not expected or not hmac.compare_digest(expected.encode(), received.encode()):
        abort(400, description="This form has expired. Reload the page and try again.")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None:
        return redirect(url_for("web.dashboard"))
    error = None
    username = request.form.get("username", "").strip()
    status = 200
    if request.method == "POST":
        password = request.form.get("password", "")
        conn = get_db()
        now = int(time.time())
        conn.execute("BEGIN IMMEDIATE")
        try:
            guard = conn.execute("SELECT * FROM login_guard WHERE id = 1").fetchone()
            failures = guard["failures"] if now - guard["window_start"] < WINDOW_SECONDS else 0
            window_start = guard["window_start"] if failures else now
            user = conn.execute("SELECT * FROM users ORDER BY id LIMIT 1").fetchone()
            if failures >= MAX_FAILURES:
                error = "Too many sign-in attempts. Wait five minutes before trying again."
                status = 429
            else:
                # Check the hash even for an unknown username; never log credentials.
                password_ok = bool(user) and len(password) <= 128 and check_password_hash(user["password_hash"], password)
                if user and hmac.compare_digest(user["username"].encode(), username.encode()) and password_ok:
                    conn.execute("UPDATE login_guard SET failures = 0, window_start = 0 WHERE id = 1")
                    session.clear()
                    session["user_id"] = user["id"]
                    session["session_version"] = user["session_version"]
                    session.permanent = True
                    csrf_token()
                else:
                    conn.execute(
                        "UPDATE login_guard SET failures = ?, window_start = ? WHERE id = 1",
                        (failures + 1, window_start),
                    )
                    error = "Username or password is incorrect."
                    status = 401
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        if error is None:
            return redirect(url_for("web.dashboard"), code=303)
    return render_template("login.html", error=error, username=username), status


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"), code=303)
