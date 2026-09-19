"""Application factory. Startup never creates or migrates a database."""

from datetime import timedelta
from pathlib import Path
import sqlite3

from flask import Flask, g, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException

from . import db

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def create_app(data_dir=None, *, trusted_hosts=None, test_config=None):
    app = Flask(__name__)
    folder = Path(data_dir) if data_dir else PROJECT_ROOT / "data"
    database = folder.resolve() / "inventory.sqlite3"
    with_db = db.connect_database(database)
    try:
        found_version = with_db.execute("PRAGMA user_version").fetchone()[0]
        if found_version != db.SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version {found_version} is unsupported; preserve it and "
                f"initialize schema version {db.SCHEMA_VERSION} separately."
            )
        identity = with_db.execute(
            "SELECT value FROM settings WHERE key = 'schema_identity'"
        ).fetchone()
        if identity is None or identity["value"] != db.SCHEMA_IDENTITY:
            raise RuntimeError("This database does not use the Phase 3A.1 measurement-template and rate foundation.")
        setting = with_db.execute("SELECT value FROM settings WHERE key = 'secret_key'").fetchone()
        if setting is None or len(setting["value"]) < 32:
            raise RuntimeError("Database has no valid session secret. Restore a complete backup.")
        secret_key = setting["value"]
    finally:
        with_db.close()
    app.config.update(
        DATABASE=str(database),
        SECRET_KEY=secret_key,
        TRUSTED_HOSTS=trusted_hosts or ["localhost", "127.0.0.1"],
        MAX_CONTENT_LENGTH=32 * 1024,
        MAX_FORM_MEMORY_SIZE=32 * 1024,
        MAX_FORM_PARTS=30,
        SESSION_COOKIE_NAME="shop_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        SESSION_REFRESH_EACH_REQUEST=False,
    )
    if test_config:
        app.config.update(test_config)
    app.teardown_appcontext(db.close_db)

    from .auth import bp as auth_bp, csrf_token, verify_csrf
    from .inventory import format_pkr, format_quantity
    from .web import bp as web_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(web_bp)
    app.jinja_env.globals.update(
        csrf_token=csrf_token,
        unit_labels={"metre": "metres", "pair": "pairs", "piece": "pieces"},
    )
    app.jinja_env.filters["quantity"] = format_quantity
    app.jinja_env.filters["pkr"] = format_pkr

    @app.before_request
    def protect_records():
        g.user = None
        if request.endpoint == "static":
            return None
        user_id = session.get("user_id")
        if isinstance(user_id, int):
            user = db.get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if user and user["session_version"] == session.get("session_version"):
                g.user = user
        if request.endpoint != "auth.login" and g.user is None:
            return redirect(url_for("auth.login"))
        if request.method == "POST":
            verify_csrf()
        return None

    @app.after_request
    def security_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return render_template("error.html", message=error.description, status=error.code), error.code

    @app.errorhandler(sqlite3.Error)
    def database_error(error):
        app.logger.exception("Database request failed")
        busy = isinstance(error, sqlite3.OperationalError) and (
            "locked" in str(error).lower() or "busy" in str(error).lower()
        )
        message = (
            "The database is busy. Go back and retry the same form; keep its original submission key."
            if busy else
            "The database request could not be completed. Keep your form and check the server terminal."
        )
        return render_template("error.html", message=message, status=503 if busy else 500), 503 if busy else 500

    return app
