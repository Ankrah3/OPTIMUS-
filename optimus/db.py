"""Core storage layer for the OPTIMUS helpdesk ticket tracker (SQLite)."""

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

PRIORITIES = ("low", "medium", "high", "critical")
STATUSES = ("open", "in_progress", "resolved", "closed")
CATEGORIES = ("hardware", "software", "network", "access", "security", "other")
DEFAULT_DB = Path.home() / ".optimus" / "tickets.db"


class TicketError(Exception):
    """Raised for invalid input or missing tickets."""


class TicketNotFound(TicketError):
    """Raised when a ticket id does not exist."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TicketStore:
    def __init__(self, path=DEFAULT_DB):
        path = str(path)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                requester TEXT NOT NULL,
                category TEXT NOT NULL,
                priority TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                assignee TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                resolved_at TEXT
            )
            """
        )
        self.conn.commit()

    # ---------- validation helpers ----------
    @staticmethod
    def _check(value, allowed, label):
        if value not in allowed:
            raise TicketError(f"Invalid {label} '{value}'. Choose from: {', '.join(allowed)}")

    # ---------- operations ----------
    def add(self, title, requester, category="other", priority="medium", description=""):
        if not title.strip():
            raise TicketError("Title cannot be empty.")
        if not requester.strip():
            raise TicketError("Requester cannot be empty.")
        self._check(category, CATEGORIES, "category")
        self._check(priority, PRIORITIES, "priority")
        now = _now()
        cur = self.conn.execute(
            "INSERT INTO tickets (title, description, requester, category, priority, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title.strip(), description.strip(), requester.strip(), category, priority, now, now),
        )
        self.conn.commit()
        return cur.lastrowid

    def get(self, ticket_id):
        row = self.conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            raise TicketNotFound(f"Ticket #{ticket_id} not found.")
        return dict(row)

    def list(self, status=None, priority=None, category=None, assignee=None):
        query, params = "SELECT * FROM tickets WHERE 1=1", []
        for column, value, allowed in (
            ("status", status, STATUSES),
            ("priority", priority, PRIORITIES),
            ("category", category, CATEGORIES),
        ):
            if value:
                self._check(value, allowed, column)
                query += f" AND {column} = ?"
                params.append(value)
        if assignee:
            query += " AND assignee = ?"
            params.append(assignee)
        # Most urgent first, then oldest first
        query += (
            " ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
            "WHEN 'medium' THEN 2 ELSE 3 END, created_at ASC"
        )
        return [dict(r) for r in self.conn.execute(query, params).fetchall()]

    def set_status(self, ticket_id, status):
        self._check(status, STATUSES, "status")
        self.get(ticket_id)  # raises if missing
        now = _now()
        resolved_at = now if status in ("resolved", "closed") else None
        self.conn.execute(
            "UPDATE tickets SET status = ?, updated_at = ?, "
            "resolved_at = CASE WHEN ? IS NULL THEN NULL ELSE COALESCE(resolved_at, ?) END "
            "WHERE id = ?",
            (status, now, resolved_at, resolved_at, ticket_id),
        )
        self.conn.commit()

    def assign(self, ticket_id, assignee):
        if not assignee.strip():
            raise TicketError("Assignee cannot be empty.")
        self.get(ticket_id)
        self.conn.execute(
            "UPDATE tickets SET assignee = ?, updated_at = ?, "
            "status = CASE WHEN status = 'open' THEN 'in_progress' ELSE status END "
            "WHERE id = ?",
            (assignee.strip(), _now(), ticket_id),
        )
        self.conn.commit()

    def stats(self):
        tickets = self.list()
        by_status = {s: 0 for s in STATUSES}
        by_priority = {p: 0 for p in PRIORITIES}
        hours = []
        for t in tickets:
            by_status[t["status"]] += 1
            by_priority[t["priority"]] += 1
            if t["resolved_at"]:
                delta = datetime.fromisoformat(t["resolved_at"]) - datetime.fromisoformat(t["created_at"])
                hours.append(delta.total_seconds() / 3600)
        return {
            "total": len(tickets),
            "by_status": by_status,
            "by_priority": by_priority,
            "avg_resolution_hours": round(sum(hours) / len(hours), 2) if hours else None,
        }

    def export_csv(self, filepath):
        tickets = self.list()
        if not tickets:
            raise TicketError("No tickets to export.")
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=tickets[0].keys())
            writer.writeheader()
            writer.writerows(tickets)
        return len(tickets)

    def close(self):
        self.conn.close()
