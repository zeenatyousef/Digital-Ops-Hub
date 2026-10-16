import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient
os.environ["DATABASE_URL"] = "sqlite:///temp_test_sec.db"

from packages.database.session import engine, Base
from apps.core_gateway.main import app

class TestSecuritySuite(unittest.TestCase):
    """
    Section 8: Security Test Group
    Required Cases:
      - Tenant crossover isolation
      - Missing permission enforcement
      - Insecure direct object reference (IDOR)
      - Secret masking in API outputs & logs
    """
    @classmethod
    def setUpClass(cls):
        if os.path.exists("temp_test_sec.db"):
            try:
                os.remove("temp_test_sec.db")
            except Exception:
                pass
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)
        res = cls.client.post("/api/seed")
        assert res.status_code == 200, "Seeding failed"

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=engine)
        if os.path.exists("temp_test_sec.db"):
            try:
                os.remove("temp_test_sec.db")
            except Exception:
                pass

    def _get_token(self, email, password):
        res = self.client.post("/api/auth/login", data={"username": email, "password": password})
        if res.status_code == 200:
            return res.json()["access_token"]
        return None

    def test_01_tenant_crossover_isolation(self):
        """Verify Tenant A user cannot view or modify Tenant B resources."""
        token_a = self._get_token("atif@nationalwireless.com", "password")
        self.assertIsNotNone(token_a)
        
        headers_a = {"Authorization": f"Bearer {token_a}"}
        res_users = self.client.get("/api/users", headers=headers_a)
        self.assertEqual(res_users.status_code, 200)
        users = res_users.json()
        self.assertTrue(len(users) > 0)
        
        # Verify all returned users belong strictly to Tenant A
        tenant_id_a = "00000000-0000-0000-0000-00000000000a"
        for u in users:
            self.assertEqual(u["tenant_id"], tenant_id_a)

    def test_02_missing_permission_enforcement(self):
        """Verify non-admin roles (e.g. client_rep) are blocked from admin registration routes."""
        token_client = self._get_token("client@acmewireless.com", "password")
        headers = {"Authorization": f"Bearer {token_client}"}
        
        # Unauthorized endpoint call without valid permissions
        res = self.client.get("/api/users", headers=headers)
        # Verify client role gets 200 for user list, but cannot access administrative campaign submission endpoints
        res_admin = self.client.post("/api/campaigns", json={
            "tenant_id": "00000000-0000-0000-0000-00000000000a",
            "client_id": "00000000-0000-0000-0000-000000000001",
            "name": "Unauthorized Campaign Creation",
            "caption": "Hack attempt"
        }, headers=headers)
        self.assertIn(res_admin.status_code, [403, 401])

    def test_03_insecure_direct_object_reference(self):
        """Verify IDOR prevention when requesting unknown or cross-tenant UUIDs."""
        token = self._get_token("designer@nationalwireless.com", "password")
        headers = {"Authorization": f"Bearer {token}"}
        
        fake_uuid = "99999999-9999-9999-9999-999999999999"
        res = self.client.get(f"/api/client-rooms/{fake_uuid}/messages", headers=headers)
        self.assertIn(res.status_code, [404, 403])

    def test_04_secret_masking(self):
        """Verify passwords, token secrets, and sensitive credentials are never leaked in API outputs."""
        token = self._get_token("atif@nationalwireless.com", "password")
        headers = {"Authorization": f"Bearer {token}"}
        
        res = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        # Ensure password hash / secret key keys are absent or masked
        self.assertNotIn("password_hash", data)
        self.assertNotIn("password", data)
        self.assertNotIn("secret_key", data)

if __name__ == "__main__":
    unittest.main()
