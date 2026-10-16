import os
import sys
import uuid
import unittest
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ["DATABASE_URL"] = "sqlite:///temp_test_media.db"

from fastapi.testclient import TestClient
from packages.database.session import engine, Base, SessionLocal
from packages.database.models import Campaign, Client, Tenant
from apps.core_gateway.main import app


class TestMediaAssetsSuite(unittest.TestCase):
    """
    Section 8: Poster Export (Media Assets) API — Automated Tests
    Covers: versioning auto-increment, listing/filtering, approve+lock workflow,
    role-based access control, and not-found handling.
    """

    @classmethod
    def setUpClass(cls):
        if os.path.exists("temp_test_media.db"):
            try:
                os.remove("temp_test_media.db")
            except Exception:
                pass
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)

        res = cls.client.post("/api/seed")
        assert res.status_code == 200, f"Seed failed: {res.text}"

        # Create a campaign directly via DB session for the media asset tests to attach to
        db = SessionLocal()
        try:
            tenant = db.query(Tenant).first()
            client_row = db.query(Client).filter(Client.tenant_id == tenant.id).first()
            campaign = Campaign(
                id=uuid.uuid4(),
                client_id=client_row.id,
                tenant_id=tenant.id,
                name="Weekend Fusion Deal",
                status="draft",
                created_at=datetime.utcnow(),
            )
            db.add(campaign)
            db.commit()
            cls.campaign_id = str(campaign.id)
        finally:
            db.close()

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=engine)
        if os.path.exists("temp_test_media.db"):
            try:
                os.remove("temp_test_media.db")
            except Exception:
                pass

    def _get_token(self, email="atif@nationalwireless.com", password="password"):
        res = self.client.post("/api/auth/login", data={"username": email, "password": password})
        return res.json()["access_token"] if res.status_code == 200 else None

    def _auth_headers(self, token):
        return {"Authorization": f"Bearer {token}"}

    # ---- 1. Create + auto-increment versioning ----
    def test_01_create_media_asset_starts_at_version_1(self):
        token = self._get_token()
        res = self.client.post(
            "/api/media-assets",
            json={"campaign_id": self.campaign_id, "file_url": "https://cdn.example.com/poster_v1.png"},
            headers=self._auth_headers(token),
        )
        self.assertEqual(res.status_code, 201, res.text)
        data = res.json()
        self.assertEqual(data["version_number"], 1)
        self.assertEqual(data["status"], "pending_review")
        self.assertFalse(data["is_locked"])
        self.__class__.first_asset_id = data["id"]

    def test_02_second_upload_auto_increments_version(self):
        token = self._get_token()
        res = self.client.post(
            "/api/media-assets",
            json={"campaign_id": self.campaign_id, "file_url": "https://cdn.example.com/poster_v2.png"},
            headers=self._auth_headers(token),
        )
        self.assertEqual(res.status_code, 201, res.text)
        data = res.json()
        self.assertEqual(data["version_number"], 2)
        self.__class__.second_asset_id = data["id"]

    def test_03_different_campaign_starts_fresh_at_version_1(self):
        token = self._get_token()
        other_campaign_id = str(uuid.uuid4())  # unrelated / nonexistent campaign id, still allowed at DB level
        res = self.client.post(
            "/api/media-assets",
            json={"campaign_id": other_campaign_id, "file_url": "https://cdn.example.com/other_poster.png"},
            headers=self._auth_headers(token),
        )
        self.assertEqual(res.status_code, 201, res.text)
        self.assertEqual(res.json()["version_number"], 1)

    # ---- 2. Listing & filtering ----
    def test_04_list_media_assets_returns_all_for_tenant(self):
        token = self._get_token()
        res = self.client.get("/api/media-assets", headers=self._auth_headers(token))
        self.assertEqual(res.status_code, 200, res.text)
        self.assertGreaterEqual(len(res.json()), 3)

    def test_05_list_media_assets_filtered_by_campaign(self):
        token = self._get_token()
        res = self.client.get(
            f"/api/media-assets?campaign_id={self.campaign_id}", headers=self._auth_headers(token)
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(len(data), 2)
        versions = sorted(item["version_number"] for item in data)
        self.assertEqual(versions, [1, 2])

    # ---- 3. Approve + lock workflow ----
    def test_06_approve_asset_locks_and_sets_reviewer(self):
        token = self._get_token()
        res = self.client.post(
            f"/api/media-assets/{self.first_asset_id}/approve", headers=self._auth_headers(token)
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["status"], "approved")
        self.assertTrue(data["is_locked"])
        self.assertIsNotNone(data["reviewed_by_id"])

    def test_07_approve_nonexistent_asset_returns_404(self):
        token = self._get_token()
        fake_id = str(uuid.uuid4())
        res = self.client.post(f"/api/media-assets/{fake_id}/approve", headers=self._auth_headers(token))
        self.assertEqual(res.status_code, 404)

    # ---- 4. Role-based access control ----
    def test_08_client_rep_cannot_create_media_asset(self):
        token = self._get_token(email="client@acmewireless.com", password="password")
        if not token:
            self.skipTest("No seeded client_rep account available to test with")
        res = self.client.post(
            "/api/media-assets",
            json={"campaign_id": self.campaign_id, "file_url": "https://cdn.example.com/blocked.png"},
            headers=self._auth_headers(token),
        )
        self.assertEqual(res.status_code, 403)

    def test_09_client_rep_can_approve_media_asset(self):
        token = self._get_token(email="client@acmewireless.com", password="password")
        if not token:
            self.skipTest("No seeded client_rep account available to test with")
        res = self.client.post(
            f"/api/media-assets/{self.second_asset_id}/approve", headers=self._auth_headers(token)
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["status"], "approved")

    def test_10_unauthenticated_request_is_rejected(self):
        res = self.client.get("/api/media-assets")
        self.assertIn(res.status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()