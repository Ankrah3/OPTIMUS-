import os
import tempfile
import unittest

from optimus.auth import LoginThrottle, UserError, UserStore
from tests.test_web import ADMIN_PASSWORD, login, make_client


class UserStoreTests(unittest.TestCase):
    def setUp(self):
        self.users = UserStore(":memory:")

    def tearDown(self):
        self.users.close()

    def test_passwords_are_hashed(self):
        self.users.create("david", "correct-horse", "admin")
        stored = self.users.conn.execute("SELECT password_hash FROM users").fetchone()[0]
        self.assertNotIn("correct-horse", stored)

    def test_authenticate(self):
        self.users.create("david", "correct-horse", "admin")
        self.assertEqual(self.users.authenticate("david", "correct-horse")["role"], "admin")
        self.assertEqual(self.users.authenticate("DAVID", "correct-horse")["username"], "david")
        self.assertIsNone(self.users.authenticate("david", "wrong"))
        self.assertIsNone(self.users.authenticate("nobody", "whatever"))

    def test_validation(self):
        with self.assertRaises(UserError):
            self.users.create("ab", "long-enough-pass")
        with self.assertRaises(UserError):
            self.users.create("david", "short")
        with self.assertRaises(UserError):
            self.users.create("david", "long-enough-pass", role="superuser")

    def test_duplicate_username_case_insensitive(self):
        self.users.create("david", "long-enough-pass")
        with self.assertRaises(UserError):
            self.users.create("David", "another-long-pass")

    def test_cannot_delete_last_admin(self):
        uid = self.users.create("boss", "long-enough-pass", "admin")
        with self.assertRaises(UserError):
            self.users.delete(uid)


class ThrottleTests(unittest.TestCase):
    def test_blocks_after_max_failures_and_resets(self):
        t = LoginThrottle(max_failures=3, window_seconds=60)
        for _ in range(3):
            self.assertFalse(t.blocked("k"))
            t.record_failure("k")
        self.assertTrue(t.blocked("k"))
        t.reset("k")
        self.assertFalse(t.blocked("k"))


class AccessControlTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.admin = make_client(self.folder.name)
        login(self.admin)
        self.admin.post("/api/users", json={"username": "kofi", "password": "tech-pass-123", "role": "technician"})
        self.admin.post("/api/tickets", json={"title": "VPN issue", "requester": "Ama"})
        # a second client sharing the same database, logged in as the technician
        self.tech = make_client(self.folder.name)
        self.assertEqual(login(self.tech, "kofi", "tech-pass-123").status_code, 200)

    def tearDown(self):
        self.folder.cleanup()

    def test_anonymous_gets_401_and_redirect(self):
        anon = make_client(self.folder.name)
        self.assertEqual(anon.get("/api/tickets").status_code, 401)
        self.assertEqual(anon.post("/api/tickets", json={"title": "x", "requester": "y"}).status_code, 401)
        self.assertEqual(anon.get("/").status_code, 302)
        self.assertEqual(anon.get("/login").status_code, 200)

    def test_wrong_password_rejected(self):
        res = login(make_client(self.folder.name), "admin", "wrong-password")
        self.assertEqual(res.status_code, 401)

    def test_login_is_throttled(self):
        client = make_client(self.folder.name)
        for _ in range(5):
            login(client, "admin", "nope")
        self.assertEqual(login(client, "admin", ADMIN_PASSWORD).status_code, 429)

    def test_logout_ends_session(self):
        self.tech.post("/api/logout")
        self.assertEqual(self.tech.get("/api/tickets").status_code, 401)

    def test_technician_cannot_use_admin_features(self):
        self.assertEqual(self.tech.get("/api/export.csv").status_code, 403)
        self.assertEqual(self.tech.get("/api/users").status_code, 403)
        res = self.tech.post("/api/users", json={"username": "evil", "password": "evil-pass-123", "role": "admin"})
        self.assertEqual(res.status_code, 403)

    def test_technician_can_only_assign_to_self(self):
        self.assertEqual(self.tech.patch("/api/tickets/1", json={"assignee": "admin"}).status_code, 403)
        res = self.tech.patch("/api/tickets/1", json={"assignee": "kofi"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["assignee"], "kofi")

    def test_technician_can_work_tickets(self):
        self.assertEqual(self.tech.post("/api/tickets", json={"title": "New", "requester": "Esi"}).status_code, 201)
        self.assertEqual(self.tech.patch("/api/tickets/1", json={"status": "resolved"}).status_code, 200)

    def test_admin_cannot_delete_self_but_can_delete_others(self):
        users = self.admin.get("/api/users").get_json()
        me = next(u for u in users if u["username"] == "admin")
        kofi = next(u for u in users if u["username"] == "kofi")
        self.assertEqual(self.admin.delete(f"/api/users/{me['id']}").status_code, 400)
        self.assertEqual(self.admin.delete(f"/api/users/{kofi['id']}").status_code, 200)

    def test_deleted_user_loses_access_immediately(self):
        kofi = next(u for u in self.admin.get("/api/users").get_json() if u["username"] == "kofi")
        self.admin.delete(f"/api/users/{kofi['id']}")
        self.assertEqual(self.tech.get("/api/tickets").status_code, 401)

    def test_demo_mode_seeds_accounts_and_sample_data(self):
        from optimus.web import create_app

        path = os.path.join(self.folder.name, "demo.db")
        client = create_app(path, secret_key="k", demo=True).test_client()
        self.assertEqual(login(client, "admin", "DemoAdmin#2026").status_code, 200)
        self.assertGreaterEqual(len(client.get("/api/tickets").get_json()), 5)
        fresh = create_app(path, secret_key="k", demo=True).test_client()
        self.assertIn(b"DemoTech#2026", fresh.get("/login").data)


if __name__ == "__main__":
    unittest.main()
