import csv
import os
import tempfile
import unittest

from optimus.db import TicketError, TicketStore


class TicketStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = TicketStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_add_and_get(self):
        tid = self.store.add("Printer jammed", "Ama", category="hardware", priority="high")
        ticket = self.store.get(tid)
        self.assertEqual(ticket["title"], "Printer jammed")
        self.assertEqual(ticket["status"], "open")
        self.assertEqual(ticket["priority"], "high")

    def test_rejects_invalid_input(self):
        with self.assertRaises(TicketError):
            self.store.add("", "Ama")
        with self.assertRaises(TicketError):
            self.store.add("WiFi down", "Kofi", priority="urgent!!")
        with self.assertRaises(TicketError):
            self.store.add("WiFi down", "Kofi", category="magic")

    def test_missing_ticket(self):
        with self.assertRaises(TicketError):
            self.store.get(999)

    def test_assign_moves_open_to_in_progress(self):
        tid = self.store.add("VPN issue", "Esi", category="network")
        self.store.assign(tid, "David")
        ticket = self.store.get(tid)
        self.assertEqual(ticket["assignee"], "David")
        self.assertEqual(ticket["status"], "in_progress")

    def test_resolve_and_reopen_sets_resolved_at(self):
        tid = self.store.add("Email not syncing", "Yaw", category="software")
        self.store.set_status(tid, "resolved")
        self.assertIsNotNone(self.store.get(tid)["resolved_at"])
        self.store.set_status(tid, "open")
        self.assertIsNone(self.store.get(tid)["resolved_at"])

    def test_list_orders_by_priority(self):
        self.store.add("Low one", "A", priority="low")
        self.store.add("Critical one", "B", priority="critical")
        self.store.add("Medium one", "C", priority="medium")
        titles = [t["title"] for t in self.store.list()]
        self.assertEqual(titles, ["Critical one", "Medium one", "Low one"])

    def test_list_filters(self):
        a = self.store.add("One", "A", category="network")
        self.store.add("Two", "B", category="software")
        self.store.set_status(a, "closed")
        self.assertEqual(len(self.store.list(status="closed")), 1)
        self.assertEqual(len(self.store.list(category="software")), 1)

    def test_stats(self):
        a = self.store.add("One", "A", priority="high")
        self.store.add("Two", "B", priority="low")
        self.store.set_status(a, "resolved")
        stats = self.store.stats()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["by_status"]["resolved"], 1)
        self.assertEqual(stats["by_priority"]["high"], 1)
        self.assertIsNotNone(stats["avg_resolution_hours"])

    def test_export_csv(self):
        self.store.add("One", "A")
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "out.csv")
            self.assertEqual(self.store.export_csv(path), 1)
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["title"], "One")


if __name__ == "__main__":
    unittest.main()
