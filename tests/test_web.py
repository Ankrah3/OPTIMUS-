import os
import tempfile
import unittest

from optimus.web import create_app

ADMIN_PASSWORD = "test-admin-pass"


def make_client(folder):
    app = create_app(
        os.path.join(folder, "test.db"), secret_key="test-key", admin_password=ADMIN_PASSWORD, demo=False
    )
    return app.test_client()


def login(client, username="admin", password=ADMIN_PASSWORD):
    return client.post("/api/login", json={"username": username, "password": password})


class WebApiTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.client = make_client(self.folder.name)
        self.assertEqual(login(self.client).status_code, 200)

    def tearDown(self):
        self.folder.cleanup()

    def make(self, **overrides):
        body = {"title": "WiFi down", "requester": "Ama", "category": "network", "priority": "high"}
        body.update(overrides)
        return self.client.post("/api/tickets", json=body)

    def test_home_page_loads_when_logged_in(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"OPTIMUS", res.data)

    def test_create_and_list(self):
        res = self.make()
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.get_json()["status"], "open")
        self.assertEqual(len(self.client.get("/api/tickets").get_json()), 1)

    def test_validation_error_returns_400(self):
        res = self.make(priority="urgent!!")
        self.assertEqual(res.status_code, 400)
        self.assertIn("error", res.get_json())
        self.assertEqual(self.make(title="  ").status_code, 400)

    def test_missing_ticket_returns_404(self):
        self.assertEqual(self.client.get("/api/tickets/999").status_code, 404)
        self.assertEqual(self.client.patch("/api/tickets/999", json={"status": "closed"}).status_code, 404)

    def test_assign_and_resolve(self):
        tid = self.make().get_json()["id"]
        res = self.client.patch(f"/api/tickets/{tid}", json={"assignee": "admin"})
        self.assertEqual(res.get_json()["status"], "in_progress")
        res = self.client.patch(f"/api/tickets/{tid}", json={"status": "resolved"})
        self.assertIsNotNone(res.get_json()["resolved_at"])

    def test_assignee_must_be_existing_user(self):
        tid = self.make().get_json()["id"]
        res = self.client.patch(f"/api/tickets/{tid}", json={"assignee": "ghost"})
        self.assertEqual(res.status_code, 400)

    def test_filters_and_stats(self):
        self.make(priority="critical")
        self.make(priority="low")
        self.assertEqual(len(self.client.get("/api/tickets?priority=critical").get_json()), 1)
        self.assertEqual(self.client.get("/api/stats").get_json()["total"], 2)

    def test_csv_export_for_admin(self):
        self.make()
        res = self.client.get("/api/export.csv")
        self.assertEqual(res.mimetype, "text/csv")
        self.assertIn(b"WiFi down", res.data)


if __name__ == "__main__":
    unittest.main()
