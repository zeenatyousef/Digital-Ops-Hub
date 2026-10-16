import os
import sys
from pathlib import Path

# Add project root to sys.path so 'packages' can be resolved
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import unittest
from fastapi.testclient import TestClient
from uuid import UUID
import uuid

# Set database URL to temp_test.db or use existing SQLite for testing
os.environ["DATABASE_URL"] = "sqlite:///temp_test.db"

# Now import session, models and app
from packages.database.session import get_db, engine, Base
from packages.database.models import Tenant, Client, User, Campaign
from apps.core_gateway.main import app

class TestAuthTenancy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Remove any leftover test database to ensure clean schema generation
        if os.path.exists("temp_test.db"):
            try:
                os.remove("temp_test.db")
            except Exception:
                pass
        # Create all tables in test database
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)
        
        # Run seeding route to ensure demo users exist
        res = cls.client.post("/api/seed")
        assert res.status_code == 200, "Seeding failed"

    @classmethod
    def tearDownClass(cls):
        # Clean up database tables
        Base.metadata.drop_all(bind=engine)
        if os.path.exists("temp_test.db"):
            try:
                os.remove("temp_test.db")
            except Exception:
                pass

    def test_01_login_success(self):
        # Test login for different roles
        users = [
            ("atif@nationalwireless.com", "password", "super_admin"),
            ("designer@nationalwireless.com", "password", "designer"),
            ("client@acmewireless.com", "password", "client_rep")
        ]
        for email, pwd, role in users:
            res = self.client.post(
                "/api/auth/login",
                data={"username": email, "password": pwd}
            )
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("access_token", data)
            self.assertEqual(data["token_type"], "bearer")

    def test_02_login_failure(self):
        # Wrong password
        res = self.client.post(
            "/api/auth/login",
            data={"username": "atif@nationalwireless.com", "password": "wrongpassword"}
        )
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["detail"], "Incorrect email or password")

    def test_03_campaign_auth_missing(self):
        # Request campaigns without authorization header
        res = self.client.get("/api/campaigns")
        self.assertEqual(res.status_code, 401)

    def test_04_campaign_role_permissions(self):
        # 1. Login as client rep
        res = self.client.post(
            "/api/auth/login",
            data={"username": "client@acmewireless.com", "password": "password"}
        )
        client_token = res.json()["access_token"]
        
        # 2. Login as designer
        res = self.client.post(
            "/api/auth/login",
            data={"username": "designer@nationalwireless.com", "password": "password"}
        )
        designer_token = res.json()["access_token"]

        # Client representative tries to create a campaign (should fail with 403)
        campaign_payload = {
            "name": "Acme New Promo",
            "client_id": "00000000-0000-0000-0000-00000000000b",
            "platform": "LinkedIn",
            "language": "English",
            "caption": "Test caption",
            "cta": "Test CTA"
        }
        res = self.client.post(
            "/api/campaigns",
            json=campaign_payload,
            headers={"Authorization": f"Bearer {client_token}"}
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("does not have permission", res.json()["detail"])

        # Designer tries to create a campaign (should succeed with 200)
        res = self.client.post(
            "/api/campaigns",
            json=campaign_payload,
            headers={"Authorization": f"Bearer {designer_token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["name"], "Acme New Promo")
        self.assertEqual(data["status"], "draft")

    def test_05_tenant_isolation(self):
        # 1. Create a second Tenant and User in the second tenant
        db = next(get_db())
        second_tenant_id = uuid.uuid4()
        tenant = Tenant(id=second_tenant_id, name="Second Corp", status="active")
        db.add(tenant)
        db.commit()

        # Register User in second tenant
        register_payload = {
            "email": "user@secondcorp.com",
            "password": "password123",
            "full_name": "Second Corp User",
            "role": "designer",
            "tenant_id": str(second_tenant_id)
        }
        res = self.client.post("/api/auth/register", json=register_payload)
        self.assertEqual(res.status_code, 201)

        # 2. Login as user from Second Corp
        res = self.client.post(
            "/api/auth/login",
            data={"username": "user@secondcorp.com", "password": "password123"}
        )
        second_token = res.json()["access_token"]

        # 3. Retrieve campaigns list for Second Corp (should be empty, ensuring isolation from Tenant 1's campaigns)
        res = self.client.get(
            "/api/campaigns",
            headers={"Authorization": f"Bearer {second_token}"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()), 0)

        # Clean up second tenant
        db.delete(tenant)
        db.commit()

if __name__ == "__main__":
    unittest.main()
