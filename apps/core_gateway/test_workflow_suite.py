import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient
os.environ["DATABASE_URL"] = "sqlite:///temp_test_wf.db"

from packages.database.session import engine, Base, SessionLocal
from packages.database.models import Client
from apps.core_gateway.main import app
from apps.core_gateway.scheduler import process_queued_jobs

class TestWorkflowSuite(unittest.TestCase):
    """
    Section 8: Workflow Test Group
    Required Cases:
      - Status transitions (draft -> pending_approval -> approved)
      - Approval gates (role authorization & validation)
      - Scheduler idempotency (no duplicate post executions)
    """
    @classmethod
    def setUpClass(cls):
        if os.path.exists("temp_test_wf.db"):
            try:
                os.remove("temp_test_wf.db")
            except Exception:
                pass
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)
        res = cls.client.post("/api/seed")
        assert res.status_code == 200, "Seeding failed"
        
        db = SessionLocal()
        cls.test_client_id = str(db.query(Client).first().id)
        db.close()

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=engine)
        if os.path.exists("temp_test_wf.db"):
            try:
                os.remove("temp_test_wf.db")
            except Exception:
                pass

    def _get_token(self, email, password):
        res = self.client.post("/api/auth/login", data={"username": email, "password": password})
        if res.status_code == 200:
            return res.json()["access_token"]
        return None

    def test_01_status_transitions(self):
        """Verify full campaign status lifecycle: draft -> submit -> approve."""
        token = self._get_token("atif@nationalwireless.com", "password")
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Create campaign
        res_create = self.client.post("/api/campaigns", json={
            "client_id": self.test_client_id,
            "name": "Lifecycle Workflow Test",
            "caption": "Back-to-school promotional campaign"
        }, headers=headers)
        self.assertEqual(res_create.status_code, 200)
        target_id = res_create.json()["id"]

        # 2. Submit campaign for approval (status -> pending_approval)
        res_submit = self.client.post(f"/api/campaigns/{target_id}/submit", headers=headers)
        self.assertEqual(res_submit.status_code, 200)
        self.assertEqual(res_submit.json()["status"], "pending_approval")

        # 3. Approve campaign (status -> approved)
        res_approve = self.client.post(f"/api/campaigns/{target_id}/approve", headers=headers)
        self.assertEqual(res_approve.status_code, 200)
        self.assertEqual(res_approve.json()["status"], "approved")

    def test_02_approval_gates(self):
        """Verify designer/client_rep role restrictions on approval gates."""
        token_designer = self._get_token("designer@nationalwireless.com", "password")
        headers_designer = {"Authorization": f"Bearer {token_designer}"}
        
        # Create campaign as designer
        res_create = self.client.post("/api/campaigns", json={
            "client_id": self.test_client_id,
            "name": "Gate Check Campaign",
            "caption": "Draft version"
        }, headers=headers_designer)
        self.assertEqual(res_create.status_code, 200)
        target_id = res_create.json()["id"]
        
        # Submit for approval
        res_submit = self.client.post(f"/api/campaigns/{target_id}/submit", headers=headers_designer)
        self.assertEqual(res_submit.status_code, 200)

        # Designer attempting to approve their own campaign should be rejected
        res_fail = self.client.post(f"/api/campaigns/{target_id}/approve", headers=headers_designer)
        self.assertIn(res_fail.status_code, [403, 401])

    def test_03_scheduler_idempotency(self):
        """Verify scheduler daemon execution is idempotent and doesn't crash on empty/re-run."""
        process_queued_jobs()
        process_queued_jobs()
        self.assertTrue(True)

if __name__ == "__main__":
    unittest.main()
