"""User accounts, password hashing and login throttling for OPTIMUS."""

import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

from .db import DEFAULT_DB, TicketError, TicketNotFound

ROLES = ("admin", "technician")
MIN_PASSWORD_LENGTH = 8
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")

# Public demo accounts. Only created when the app runs in demo mode.
DEMO_ADMIN = ("admin", "DemoAdmin#2026")
DEMO_TECH = ("tech", "DemoTech#2026")

# Used to keep login timing similar whether or not the username exists.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


class UserError(TicketError):
    """Invalid user input (shown to the client as HTTP 400)."""


class UserNotFound(TicketNotFound):
    """User id does not exist (HTTP 404)."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class UserStore:
    def __init__(self, path=DEFAULT_DB):
        path = str(path)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    @staticmethod
    def _public(row):
        return {k: row[k] for k in ("id", "username", "role", "created_at")}

    def count(self):
        return self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def create(self, username, password, role="technician"):
        username = (username or "").strip()
        if not USERNAME_PATTERN.match(username):
            raise UserError("Username must be 3-30 characters: letters, numbers, dot, dash or underscore.")
        if role not in ROLES:
            raise UserError(f"Invalid role '{role}'. Choose from: {', '.join(ROLES)}")
        if len(password or "") < MIN_PASSWORD_LENGTH:
            raise UserError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        try:
            cur = self.conn.execute(
                "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                (username, generate_password_hash(password), role, _now()),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            raise UserError(f"Username '{username}' is already taken.") from None
        return cur.lastrowid

    def authenticate(self, username, password):
        row = self.conn.execute(
            "SELECT * FROM users WHERE username = ?", ((username or "").strip(),)
        ).fetchone()
        if row is None:
            check_password_hash(_DUMMY_HASH, password or "")
            return None
        if not check_password_hash(row["password_hash"], password or ""):
            return None
        return self._public(row)

    def get(self, user_id):
        row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._public(row) if row else None

    def get_by_username(self, username):
        row = self.conn.execute(
            "SELECT * FROM users WHERE username = ?", ((username or "").strip(),)
        ).fetchone()
        return self._public(row) if row else None

    def list(self):
        rows = self.conn.execute("SELECT * FROM users ORDER BY username COLLATE NOCASE").fetchall()
        return [self._public(r) for r in rows]

    def delete(self, user_id):
        user = self.get(user_id)
        if user is None:
            raise UserNotFound(f"User #{user_id} not found.")
        if user["role"] == "admin":
            admins = self.conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0]
            if admins <= 1:
                raise UserError("Cannot delete the last admin account.")
        self.conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self.conn.commit()

    def close(self):
        self.conn.close()


class LoginThrottle:
    """Blocks a (client, username) pair after too many failed logins in a time window."""

    def __init__(self, max_failures=5, window_seconds=300):
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures = {}
        self._lock = threading.Lock()

    def _recent(self, key):
        cutoff = time.monotonic() - self.window
        recent = [t for t in self._failures.get(key, []) if t > cutoff]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def blocked(self, key):
        with self._lock:
            return len(self._recent(key)) >= self.max_failures

    def record_failure(self, key):
        with self._lock:
            self._recent(key)
            self._failures.setdefault(key, []).append(time.monotonic())

    def reset(self, key):
        with self._lock:
            self._failures.pop(key, None)
