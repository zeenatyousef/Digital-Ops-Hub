import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import unittest
from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite:///temp_test_clients.db"
os.environ["VISHAQA_API_URL"] = "http://localhost:59991"
os.environ["ASMA_API_URL"] = "http://localhost:59992"
os.environ["ESHA_API_URL"] = "http://localhost:59993"

from packages.database.session import get_db, engine, Base
from apps.core_gateway.main import app
from apps.core_gateway.scheduler import start_scheduler, stop_scheduler


class TestClientsAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists("temp_test_clients.db"):
            try:
                os.remove("temp_test_clients.db")
            except Exception:
                pass
        Base.metadata.create_all(bind=engine)
        start_scheduler()
        cls.client = TestClient(app)
        res = cls.client.post("/api/seed")
        assert res.status_code == 200, "Seeding failed"

    @classmethod
    def tearDownClass(cls):
        stop_scheduler()
        Base.metadata.drop_all(bind=engine)
        if os.path.exists("temp_test_clients.db"):
            try:
                os.remove("temp_test_clients.db")
            except Exception:
                pass

    def _get_token(self, email, password):
        res = self.client.post(
            "/api/auth/login",
            data={"username": email, "password": password}
        )
        return res.json()["access_token"]

    def _auth_header(self):
        token = self._get_token("atif@nationalwireless.com", "password")
        return {"Authorization": f"Bearer {token}"}

    def test_create_client_success(self):
        res = self.client.post(
            "/api/clients",
            json={"company_name": "Acme Test Co", "industry": "Retail", "contact_email": "acme_unique@test.com"},
            headers=self._auth_header()
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["company_name"], "Acme Test Co")
        self.assertIn("id", data)

    def test_create_client_duplicate_email_rejected(self):
        headers = self._auth_header()
        self.client.post(
            "/api/clients",
            json={"company_name": "Dup Co 1", "industry": "Retail", "contact_email": "dup_test@test.com"},
            headers=headers
        )
        res = self.client.post(
            "/api/clients",
            json={"company_name": "Dup Co 2", "industry": "Retail", "contact_email": "dup_test@test.com"},
            headers=headers
        )
        self.assertEqual(res.status_code, 409)

    def test_list_clients_requires_auth(self):
        res = self.client.get("/api/clients")
        self.assertIn(res.status_code, (401, 403))

    def test_update_client(self):
        headers = self._auth_header()
        create_res = self.client.post(
            "/api/clients",
            json={"company_name": "Old Name", "industry": "Retail", "contact_email": "update_test@test.com"},
            headers=headers
        )
        client_id = create_res.json()["id"]

        update_res = self.client.patch(
            f"/api/clients/{client_id}",
            json={"company_name": "New Name", "industry": "Tech", "contact_email": "update_test@test.com"},
            headers=headers
        )
        self.assertEqual(update_res.status_code, 200)
        self.assertEqual(update_res.json()["company_name"], "New Name")

    def test_delete_client(self):
        headers = self._auth_header()
        create_res = self.client.post(
            "/api/clients",
            json={"company_name": "To Delete", "industry": "Retail", "contact_email": "delete_test@test.com"},
            headers=headers
        )
        client_id = create_res.json()["id"]

        delete_res = self.client.delete(f"/api/clients/{client_id}", headers=headers)
        self.assertEqual(delete_res.status_code, 204)

        get_res = self.client.get(f"/api/clients/{client_id}", headers=headers)
        self.assertEqual(get_res.status_code, 404)


if __name__ == "__main__":
    unittest.main()