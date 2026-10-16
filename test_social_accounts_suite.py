import os
import sys
import uuid
import unittest
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ["DATABASE_URL"] = "sqlite:///temp_test_social.db"
os.environ.setdefault("ENCRYPTION_KEY", "vbJSxMGY_fa6hVBiGOR1NKUH-jOA-sSRdRCcfi994LU=")  # test-only Fernet key

from fastapi.testclient import TestClient
from packages.database.session import engine, Base, SessionLocal
from packages.database.models import Campaign, Client, Tenant, PublishingJob
from apps.core_gateway.main import app
from apps.core_gateway.token_encryption import decrypt_token


class TestSocialAccountsSuite(unittest.TestCase):
    """
    Section 8: Queue Settings / Social Accounts API — Automated Tests
    Covers: connect (token encryption), listing, disconnect, manual handoff
    for failed publishing jobs, and role-based access control.
    """

    @classmethod
    def setUpClass(cls):
        if os.path.exists("temp_test_social.db"):
            try:
                os.remove("temp_test_social.db")
            except Exception:
                pass
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)

        res = cls.client.post("/api/seed")
        assert res.status_code == 200, f"Seed failed: {res.text}"

        # Create a campaign + a failed publishing job directly via DB for manual-handoff tests
        db = SessionLocal()
        try:
            tenant = db.query(Tenant).first()
            client_row = db.query(Client).filter(Client.tenant_id == tenant.id).first()
            campaign = Campaign(
                id=uuid.uuid4(),
                client_id=client_row.id,
                tenant_id=tenant.id,
                name="Queue Test Campaign",
                status="scheduled",
                created_at=datetime.utcnow(),
            )
            db.add(campaign)
            db.flush()

            job = PublishingJob(
                id=uuid.uuid4(),
                campaign_id=campaign.id,
                status="failed",
                idempotency_key=str(uuid.uuid4()),
                retry_count=3,
                error_logs="Platform API timeout after 3 retries",
                scheduled_at=datetime.utcnow(),
            )
            db.add(job)
            db.commit()
            cls.failed_job_id = str(job.id)
        finally:
            db.close()

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=engine)
        if os.path.exists("temp_test_social.db"):
            try:
                os.remove("temp_test_social.db")
            except Exception:
                pass

    def _get_token(self, email="atif@nationalwireless.com", password="password"):
        res = self.client.post("/api/auth/login", data={"username": email, "password": password})
        return res.json()["access_token"] if res.status_code == 200 else None

    def _auth_headers(self, token):
        return {"Authorization": f"Bearer {token}"}

    # ---- 1. Connect account + token encryption ----
    def test_01_connect_social_account_encrypts_token(self):
        token = self._get_token()
        raw_token = "raw-secret-access-token-12345"
        res = self.client.post(
            "/api/social-accounts",
            json={"platform": "instagram", "account_identifier": "nw_official", "access_token": raw_token},
            headers=self._auth_headers(token),
        )
        self.assertEqual(res.status_code, 201, res.text)
        data = res.json()
        self.assertEqual(data["platform"], "instagram")
        self.assertEqual(data["status"], "connected")
        self.__class__.account_id = data["id"]

        # Verify the raw token is never returned, and what's stored is genuinely encrypted
        self.assertNotIn("access_token", data)
        self.assertNotIn(raw_token, str(data))

        db = SessionLocal()
        try:
            from packages.database.models import SocialAccount
            row = db.query(SocialAccount).filter(SocialAccount.id == uuid.UUID(data["id"])).first()
            self.assertNotEqual(row.access_token_encrypted, raw_token)
            self.assertEqual(decrypt_token(row.access_token_encrypted), raw_token)
        finally:
            db.close()

    # ---- 2. Listing ----
    def test_02_list_social_accounts(self):
        token = self._get_token()
        res = self.client.get("/api/social-accounts", headers=self._auth_headers(token))
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertGreaterEqual(len(data), 1)
        self.assertTrue(any(a["id"] == self.account_id for a in data))

    # ---- 3. Disconnect ----
    def test_03_disconnect_social_account(self):
        token = self._get_token()
        res = self.client.delete(f"/api/social-accounts/{self.account_id}", headers=self._auth_headers(token))
        self.assertEqual(res.status_code, 204)

        # Confirm it's actually gone from the list
        res2 = self.client.get("/api/social-accounts", headers=self._auth_headers(token))
        ids = [a["id"] for a in res2.json()]
        self.assertNotIn(self.account_id, ids)

    def test_04_disconnect_nonexistent_account_returns_404(self):
        token = self._get_token()
        fake_id = str(uuid.uuid4())
        res = self.client.delete(f"/api/social-accounts/{fake_id}", headers=self._auth_headers(token))
        self.assertEqual(res.status_code, 404)

    # ---- 4. Manual handoff for failed publishing jobs ----
    def test_05_manual_handoff_marks_job_for_human_review(self):
        token = self._get_token()
        res = self.client.post(
            f"/api/publishing/jobs/{self.failed_job_id}/manual-handoff",
            json={"manual_proof": "https://instagram.com/p/12345_proof_note"},
            headers=self._auth_headers(token)
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["status"], "manual_handoff")
        self.assertEqual(data["manual_proof"], "https://instagram.com/p/12345_proof_note")

    def test_06_manual_handoff_nonexistent_job_returns_404(self):
        token = self._get_token()
        fake_id = str(uuid.uuid4())
        res = self.client.post(
            f"/api/publishing/jobs/{fake_id}/manual-handoff", headers=self._auth_headers(token)
        )
        self.assertEqual(res.status_code, 404)

    # ---- 5. Role-based access control ----
    def test_07_designer_cannot_connect_social_account(self):
        token = self._get_token(email="designer@nationalwireless.com", password="password")
        if not token:
            self.skipTest("No seeded designer account available to test with")
        res = self.client.post(
            "/api/social-accounts",
            json={"platform": "tiktok", "account_identifier": "blocked_handle", "access_token": "x"},
            headers=self._auth_headers(token),
        )
        self.assertEqual(res.status_code, 403)

    def test_08_designer_can_list_but_not_disconnect(self):
        token = self._get_token(email="designer@nationalwireless.com", password="password")
        if not token:
            self.skipTest("No seeded designer account available to test with")
        list_res = self.client.get("/api/social-accounts", headers=self._auth_headers(token))
        self.assertEqual(list_res.status_code, 200)

        fake_id = str(uuid.uuid4())
        del_res = self.client.delete(f"/api/social-accounts/{fake_id}", headers=self._auth_headers(token))
        self.assertEqual(del_res.status_code, 403)

    def test_09_unauthenticated_request_is_rejected(self):
        res = self.client.get("/api/social-accounts")
        self.assertIn(res.status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()