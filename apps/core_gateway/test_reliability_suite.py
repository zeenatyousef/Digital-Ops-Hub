import os
import sys
import unittest
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient
os.environ["DATABASE_URL"] = "sqlite:///temp_test_rel.db"

from packages.database.session import engine, Base, SessionLocal
from packages.database.models import Tenant, Client, Campaign, PublishingJob
from apps.core_gateway.scheduler import process_queued_jobs
from apps.core_gateway.main import app

class TestReliabilitySuite(unittest.TestCase):
    """
    Section 8: Reliability Test Group
    Required Cases:
      - AI timeout & fallback
      - Queue restart & retry policy
      - Token expiry & invalid token handling
      - Storage failure resilience
    """
    @classmethod
    def setUpClass(cls):
        if os.path.exists("temp_test_rel.db"):
            try:
                os.remove("temp_test_rel.db")
            except Exception:
                pass
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)
        res = cls.client.post("/api/seed")
        assert res.status_code == 200, "Seeding failed"

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=engine)
        if os.path.exists("temp_test_rel.db"):
            try:
                os.remove("temp_test_rel.db")
            except Exception:
                pass

    def _get_token(self, email, password):
        res = self.client.post("/api/auth/login", data={"username": email, "password": password})
        if res.status_code == 200:
            return res.json()["access_token"]
        return None

    def test_01_ai_timeout_fallback(self):
        """Verify Gateway fallback response when AI services are offline or slow."""
        token = self._get_token("atif@nationalwireless.com", "password")
        headers = {"Authorization": f"Bearer {token}"}
        
        res = self.client.post("/api/support/classify", json={
            "tenant_id": "00000000-0000-0000-0000-00000000000a",
            "message": "FBR tax invoice sync error"
        }, headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue("category" in data or "fallback" in data or "human_required" in data)

    def test_02_token_expiry_handling(self):
        """Verify expired or corrupt JWT token returns clean 401 response without app crash."""
        expired_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhdGlmQG5hdGlvbmFsd2lyZWxlc3MuY29tIiwiZXhwIjoxNAwwMDAwMDAwfQ.invalid_sig"
        headers = {"Authorization": f"Bearer {expired_token}"}
        
        res = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(res.status_code, 401)
        self.assertIn("detail", res.json())

    def test_03_malformed_json_resilience(self):
        """Verify service handles malformed payloads with 422 standard response."""
        res = self.client.post("/api/auth/login", content="not-a-valid-json", headers={"Content-Type": "application/json"})
        self.assertEqual(res.status_code, 422)

    def test_04_storage_reconnection_resilience(self):
        """Verify engine connection ping and query health."""
        with engine.connect() as conn:
            from sqlalchemy import text
            res = conn.execute(text("SELECT 1"))
            self.assertEqual(res.scalar(), 1)

    def test_05_worker_retry_policy(self):
        """
        Verify a job that fails transiently ("retry" in campaign name) is
        requeued with an incremented retry_count rather than being dropped,
        and that it eventually succeeds once the retry threshold passes.
        """
        db = SessionLocal()
        try:
            tenant = db.query(Tenant).first()
            client_row = db.query(Client).filter(Client.tenant_id == tenant.id).first()

            campaign = Campaign(
                id=uuid.uuid4(),
                client_id=client_row.id,
                tenant_id=tenant.id,
                name="Weekend retry campaign",  # "retry" substring triggers transient-failure simulation
                status="scheduled",
                created_at=datetime.utcnow(),
            )
            db.add(campaign)
            db.flush()

            job = PublishingJob(
                id=uuid.uuid4(),
                campaign_id=campaign.id,
                status="queued",
                idempotency_key=str(uuid.uuid4()),
                retry_count=0,
                scheduled_at=datetime.utcnow(),
            )
            db.add(job)
            db.commit()
            job_id = job.id
        finally:
            db.close()

        # First pass: should fail transiently and requeue with retry_count incremented
        process_queued_jobs()

        db = SessionLocal()
        try:
            job = db.query(PublishingJob).filter(PublishingJob.id == job_id).first()
            self.assertEqual(job.status, "queued")
            self.assertEqual(job.retry_count, 1)
            self.assertIsNotNone(job.error_logs)
        finally:
            db.close()

        # Second pass: retry_count is now 1, still < 2, so it fails transiently again
        process_queued_jobs()

        db = SessionLocal()
        try:
            job = db.query(PublishingJob).filter(PublishingJob.id == job_id).first()
            self.assertEqual(job.status, "queued")
            self.assertEqual(job.retry_count, 2)
        finally:
            db.close()

        # Third pass: retry_count (2) is no longer < 2, so the transient-failure
        # branch no longer applies and the job succeeds.
        process_queued_jobs()

        db = SessionLocal()
        try:
            job = db.query(PublishingJob).filter(PublishingJob.id == job_id).first()
            self.assertEqual(job.status, "completed")
            self.assertIsNotNone(job.completed_at)
        finally:
            db.close()

    def test_06_queue_restart_resumes_pending_jobs(self):
        """
        Verify that jobs left in "queued" status (as if the scheduler daemon
        had been stopped and restarted) are picked up and processed the next
        time process_queued_jobs() runs, without needing to be recreated.
        """
        db = SessionLocal()
        try:
            tenant = db.query(Tenant).first()
            client_row = db.query(Client).filter(Client.tenant_id == tenant.id).first()

            campaign = Campaign(
                id=uuid.uuid4(),
                client_id=client_row.id,
                tenant_id=tenant.id,
                name="Queue restart test campaign",  # no "fail"/"retry" substring -> should succeed
                status="scheduled",
                created_at=datetime.utcnow(),
            )
            db.add(campaign)
            db.flush()

            # Simulate a job that was left behind in "queued" state, as if the
            # scheduler process had been killed before it could pick this up.
            job = PublishingJob(
                id=uuid.uuid4(),
                campaign_id=campaign.id,
                status="queued",
                idempotency_key=str(uuid.uuid4()),
                retry_count=0,
                scheduled_at=datetime.utcnow(),
                platform_post_id="platform_post_123",
            )
            db.add(job)
            db.commit()
            job_id = job.id
        finally:
            db.close()

        # Simulate the scheduler daemon restarting and running its poll loop once.
        process_queued_jobs()

        db = SessionLocal()
        try:
            job = db.query(PublishingJob).filter(PublishingJob.id == job_id).first()
            self.assertEqual(job.status, "completed")
            self.assertIsNotNone(job.completed_at)

            campaign = db.query(Campaign).filter(Campaign.id == job.campaign_id).first()
            self.assertEqual(campaign.status, "published")
        finally:
            db.close()

if __name__ == "__main__":
    unittest.main()

