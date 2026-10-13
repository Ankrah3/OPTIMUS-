"""Flask web app and JSON API for OPTIMUS (with login and roles).

Run with:  python -m optimus.web
"""

import csv
import io
import os
import secrets
from datetime import timedelta
from functools import wraps

from flask import Flask, Response, g, jsonify, redirect, render_template, request, session

from .auth import (
    DEMO_ADMIN,
    DEMO_TECH,
    ROLES,
    LoginThrottle,
    UserError,
    UserStore,
)
from .db import (
    CATEGORIES,
    DEFAULT_DB,
    PRIORITIES,
    STATUSES,
    TicketError,
    TicketNotFound,
    TicketStore,
)

SAMPLE_TICKETS = [
    ("Suspicious login alert on finance account", "Esi", "security", "critical", "Multiple failed sign-ins from an unknown location."),
    ("Cannot connect to office WiFi", "Ama", "network", "high", "Laptop sees the network but authentication fails."),
    ("Install Office on new laptop", "Kofi", "software", "low", ""),
    ("Printer on 2nd floor is jammed", "Yaw", "hardware", "medium", "Paper tray error on the shared printer."),
    ("Password reset for HR system", "Abena", "access", "medium", ""),
]


def create_app(db_path=None, secret_key=None, admin_password=None, demo=None):
    app = Flask(__name__)
    db_path = str(db_path or os.environ.get("OPTIMUS_DB") or DEFAULT_DB)
    app.config["DB_PATH"] = db_path
    app.config["DEMO"] = demo if demo is not None else os.environ.get("OPTIMUS_DEMO") == "1"

    key = secret_key or os.environ.get("OPTIMUS_SECRET_KEY")
    if not key:
        key = secrets.token_hex(32)
        print("WARNING: OPTIMUS_SECRET_KEY is not set; using a temporary key (logins reset on restart).")
    app.config.update(
        SECRET_KEY=key,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),  # HTTPS-only cookie when hosted
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    throttle = LoginThrottle()

    _seed(app, admin_password)

    # ---------- per-request resources ----------
    def store():
        if "store" not in g:
            g.store = TicketStore(db_path)
        return g.store

    def users():
        if "users" not in g:
            g.users = UserStore(db_path)
        return g.users

    def current_user():
        if "user" not in g:
            uid = session.get("uid")
            g.user = users().get(uid) if uid else None
            if uid and g.user is None:
                session.clear()  # account was deleted
        return g.user

    @app.teardown_appcontext
    def close_resources(_exc):
        for name in ("store", "users"):
            resource = g.pop(name, None)
            if resource is not None:
                resource.close()

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    # ---------- access control ----------
    def login_required(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if current_user() is None:
                return jsonify(error="Please log in."), 401
            return fn(*args, **kwargs)
        return wrapper

    def admin_required(fn):
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            if current_user()["role"] != "admin":
                return jsonify(error="Admin access required."), 403
            return fn(*args, **kwargs)
        return wrapper

    @app.errorhandler(TicketNotFound)
    def not_found(err):
        return jsonify(error=str(err)), 404

    @app.errorhandler(TicketError)
    def bad_request(err):
        return jsonify(error=str(err)), 400

    # ---------- pages ----------
    @app.get("/")
    def index():
        if current_user() is None:
            return redirect("/login")
        return render_template("index.html", statuses=STATUSES, priorities=PRIORITIES,
                               categories=CATEGORIES, roles=ROLES)

    @app.get("/login")
    def login_page():
        if current_user() is not None:
            return redirect("/")
        return render_template("login.html", demo=app.config["DEMO"],
                               demo_admin=DEMO_ADMIN, demo_tech=DEMO_TECH)

    # ---------- auth API ----------
    @app.post("/api/login")
    def login():
        data = request.get_json(silent=True) or {}
        username = str(data.get("username", "")).strip()
        throttle_key = (request.remote_addr, username.lower())
        if throttle.blocked(throttle_key):
            return jsonify(error="Too many failed attempts. Try again in a few minutes."), 429
        user = users().authenticate(username, str(data.get("password", "")))
        if user is None:
            throttle.record_failure(throttle_key)
            return jsonify(error="Invalid username or password."), 401
        throttle.reset(throttle_key)
        session.clear()
        session["uid"] = user["id"]
        session.permanent = True
        return jsonify(user)

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/me")
    @login_required
    def me():
        return jsonify({**current_user(), "demo": app.config["DEMO"]})

    # ---------- user management (admin only) ----------
    @app.get("/api/users")
    @admin_required
    def list_users():
        return jsonify(users().list())

    @app.post("/api/users")
    @admin_required
    def create_user():
        data = request.get_json(silent=True) or {}
        uid = users().create(str(data.get("username", "")), str(data.get("password", "")),
                             data.get("role", "technician"))
        return jsonify(users().get(uid)), 201

    @app.delete("/api/users/<int:user_id>")
    @admin_required
    def delete_user(user_id):
        if user_id == current_user()["id"]:
            raise UserError("You cannot delete your own account.")
        users().delete(user_id)
        return jsonify(ok=True)

    # ---------- tickets ----------
    @app.get("/api/tickets")
    @login_required
    def list_tickets():
        a = request.args
        return jsonify(store().list(
            status=a.get("status") or None,
            priority=a.get("priority") or None,
            category=a.get("category") or None,
            assignee=a.get("assignee") or None,
        ))

    @app.post("/api/tickets")
    @login_required
    def create_ticket():
        data = request.get_json(silent=True) or {}
        tid = store().add(
            title=str(data.get("title", "")),
            requester=str(data.get("requester", "")),
            category=data.get("category", "other"),
            priority=data.get("priority", "medium"),
            description=str(data.get("description", "")),
        )
        return jsonify(store().get(tid)), 201

    @app.get("/api/tickets/<int:ticket_id>")
    @login_required
    def get_ticket(ticket_id):
        return jsonify(store().get(ticket_id))

    @app.patch("/api/tickets/<int:ticket_id>")
    @login_required
    def update_ticket(ticket_id):
        data = request.get_json(silent=True) or {}
        user = current_user()
        store().get(ticket_id)  # 404 before any change is made
        if "assignee" in data:
            wanted = users().get_by_username(str(data["assignee"]))
            if wanted is None:
                raise UserError("Assignee must be an existing user.")
            if user["role"] != "admin" and wanted["id"] != user["id"]:
                return jsonify(error="Technicians can only assign tickets to themselves."), 403
            store().assign(ticket_id, wanted["username"])
        if "status" in data:
            store().set_status(ticket_id, data["status"])
        return jsonify(store().get(ticket_id))

    @app.get("/api/stats")
    @login_required
    def stats():
        return jsonify(store().stats())

    @app.get("/api/export.csv")
    @admin_required
    def export_csv():
        tickets = store().list()
        out = io.StringIO()
        if tickets:
            writer = csv.DictWriter(out, fieldnames=tickets[0].keys())
            writer.writeheader()
            writer.writerows(tickets)
        return Response(out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=tickets.csv"})

    return app


def _seed(app, admin_password):
    """Create the first accounts (and demo data) when the database is empty."""
    db_path = app.config["DB_PATH"]
    users = UserStore(db_path)
    try:
        if users.count() > 0:
            return
        if app.config["DEMO"]:
            users.create(*DEMO_ADMIN, role="admin")
            users.create(*DEMO_TECH, role="technician")
            tickets = TicketStore(db_path)
            try:
                if not tickets.list():
                    for title, requester, category, priority, description in SAMPLE_TICKETS:
                        tickets.add(title, requester, category, priority, description)
                    tickets.assign(2, DEMO_TECH[0])
                    tickets.set_status(3, "resolved")
            finally:
                tickets.close()
            print("Demo mode: created demo accounts and sample tickets.")
        else:
            password = admin_password or os.environ.get("OPTIMUS_ADMIN_PASSWORD")
            generated = password is None
            if generated:
                password = secrets.token_urlsafe(12)
            users.create("admin", password, role="admin")
            if generated:
                print(f"First run: created user 'admin' with password: {password}")
                print("Save it now. It is shown only once. Set OPTIMUS_ADMIN_PASSWORD to choose your own.")
    finally:
        users.close()


def main():
    app = create_app()
    print("OPTIMUS running at http://127.0.0.1:5000  (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
