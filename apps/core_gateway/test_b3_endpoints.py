import os
import sys
from pathlib import Path
from datetime import datetime

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import unittest
from fastapi.testclient import TestClient
import uuid

os.environ["DATABASE_URL"] = "sqlite:///temp_test_b3.db"
os.environ["LOGIN_RATE_LIMIT"] = "5"
os.environ["ALLOW_SEED"] = "true"

from packages.database.session import get_db, engine, Base, SessionLocal
from packages.database.models import Tenant, User, Client, ClientRoom, Message, Campaign, PublishingJob
from apps.core_gateway.main import app
from apps.core_gateway.security import get_password_hash, failed_login_attempts


class TestB3Endpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            Base.metadata.drop_all(bind=engine)
        except Exception:
            pass
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)

        # Seed data
        res = cls.client.post("/api/seed")
        assert res.status_code == 200, f"Seeding failed: {res.text}"

    @classmethod
    def tearDownClass(cls):
        pass

    def _get_token(self, email="admin@nationalwireless.com", password="password"):
        res = self.client.post("/api/auth/login", data={"username": email, "password": password})
        if res.status_code == 200:
            return res.json()["access_token"]
        return None

    def test_01_admin_create_user(self):
        token = self._get_token()
        self.assertIsNotNone(token)
        new_email = f"newuser_{uuid.uuid4().hex[:6]}@nationalwireless.com"

        # Success: admin creates user
        res = self.client.post(
            "/api/admin/users",
            json={"email": new_email, "full_name": "New Designer User", "password": "Password123!", "role": "designer"},
            headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(res.status_code, 201, res.text)
        data = res.json()
        self.assertEqual(data["email"], new_email)
        self.assertEqual(data["role"], "designer")
        self.assertTrue(data["is_active"])

        # Non-admin creates user -> 403
        designer_token = self._get_token("designer@nationalwireless.com", "password")
        res_fail = self.client.post(
            "/api/admin/users",
            json={"email": f"fail_{uuid.uuid4().hex[:6]}@nationalwireless.com", "full_name": "Fail User", "password": "Password123!", "role": "designer"},
            headers={"Authorization": f"Bearer {designer_token}"}
        )
        self.assertEqual(res_fail.status_code, 403)

    def test_02_user_disable_enable(self):
        admin_token = self._get_token()

        # Create a user to disable
        email = f"target_{uuid.uuid4().hex[:6]}@nationalwireless.com"
        res_create = self.client.post(
            "/api/admin/users",
            json={"email": email, "full_name": "Target User", "password": "Password123!", "role": "designer"},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        target_id = res_create.json()["id"]

        # Disable user
        res_dis = self.client.patch(
            f"/api/users/{target_id}/disable",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        self.assertEqual(res_dis.status_code, 200)
        self.assertFalse(res_dis.json()["is_active"])

        # Disabled user cannot login
        res_login = self.client.post("/api/auth/login", data={"username": email, "password": "Password123!"})
        self.assertEqual(res_login.status_code, 401)
        self.assertIn("deactivated", res_login.json()["detail"].lower())

        # Enable user
        res_en = self.client.patch(
            f"/api/users/{target_id}/enable",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        self.assertEqual(res_en.status_code, 200)
        self.assertTrue(res_en.json()["is_active"])

        # Admin self-disable -> 400
        res_me = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
        admin_id = res_me.json()["id"]
        res_self = self.client.patch(
            f"/api/users/{admin_id}/disable",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        self.assertEqual(res_self.status_code, 400)

    def test_03_logout_and_jwt_denylist(self):
        token = self._get_token()
        self.assertIsNotNone(token)

        # Me request works
        res_prof = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res_prof.status_code, 200)

        # Logout
        res_logout = self.client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res_logout.status_code, 200)

        # Subsequent me request with denylisted token -> 401
        res_denied = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res_denied.status_code, 401)

    def test_04_auth_refresh(self):
        token = self._get_token()
        self.assertIsNotNone(token)

        # Refresh token
        res_ref = self.client.post("/api/auth/refresh", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res_ref.status_code, 200)
        new_token = res_ref.json()["access_token"]
        self.assertIsNotNone(new_token)

        # New token works
        res_prof = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"})
        self.assertEqual(res_prof.status_code, 200)

    def test_05_login_rate_limiting(self):
        # Clear rate limit memory first
        failed_login_attempts.clear()
        bad_email = "ratelimit_test@nationalwireless.com"

        # Perform 5 failed attempts
        for _ in range(5):
            res = self.client.post("/api/auth/login", data={"username": bad_email, "password": "wrongpassword"})
            self.assertEqual(res.status_code, 401)

        # 6th failed attempt -> 429
        res_429 = self.client.post("/api/auth/login", data={"username": bad_email, "password": "wrongpassword"})
        self.assertEqual(res_429.status_code, 429)

        # Reset rate limit dictionary after test
        failed_login_attempts.clear()

    def test_06_message_edit_delete_and_read_masking(self):
        designer_token = self._get_token("designer@nationalwireless.com", "password")
        self.assertIsNotNone(designer_token)

        # Ensure a client room exists
        db = SessionLocal()
        tenant = db.query(Tenant).first()
        client_row = db.query(Client).first()
        room = db.query(ClientRoom).filter(ClientRoom.client_id == client_row.id).first()
        if not room:
            room = ClientRoom(id=uuid.uuid4(), tenant_id=tenant.id, client_id=client_row.id, room_type="general", created_at=datetime.utcnow())
            db.add(room)
            db.commit()
        room_id = str(room.id)
        db.close()

        # Post message
        res_post = self.client.post(
            f"/api/client-rooms/{room_id}/messages",
            json={"content": "Original message content"},
            headers={"Authorization": f"Bearer {designer_token}"}
        )
        self.assertEqual(res_post.status_code, 201, res_post.text)
        msg_id = res_post.json()["id"]

        # Edit message by sender
        res_edit = self.client.patch(
            f"/api/messages/{msg_id}",
            json={"content": "Updated message content"},
            headers={"Authorization": f"Bearer {designer_token}"}
        )
        self.assertEqual(res_edit.status_code, 200, res_edit.text)
        self.assertEqual(res_edit.json()["content"], "Updated message content")
        self.assertIsNotNone(res_edit.json()["edited_at"])

        # Edit by non-sender -> 403
        other_token = self._get_token("admin@nationalwireless.com", "password")
        res_edit_fail = self.client.patch(
            f"/api/messages/{msg_id}",
            json={"content": "Hacked content"},
            headers={"Authorization": f"Bearer {other_token}"}
        )
        self.assertEqual(res_edit_fail.status_code, 403)

        # Soft delete message by sender
        res_del = self.client.delete(
            f"/api/messages/{msg_id}",
            headers={"Authorization": f"Bearer {designer_token}"}
        )
        self.assertEqual(res_del.status_code, 200, res_del.text)
        self.assertIsNotNone(res_del.json()["deleted_at"])

        # Read room messages -> deleted content replaced with "[deleted]"
        res_read = self.client.get(f"/api/client-rooms/{room_id}/messages", headers={"Authorization": f"Bearer {designer_token}"})
        self.assertEqual(res_read.status_code, 200)
        messages = res_read.json()
        deleted_msg = next((m for m in messages if m["id"] == msg_id), None)
        self.assertIsNotNone(deleted_msg)
        self.assertEqual(deleted_msg["content"], "[deleted]")

    def test_07_job_cancel(self):
        admin_token = self._get_token()

        db = SessionLocal()
        tenant = db.query(Tenant).first()
        client_row = db.query(Client).first()
        campaign = Campaign(id=uuid.uuid4(), tenant_id=tenant.id, client_id=client_row.id, name="Cancel Job Campaign", status="scheduled")
        db.add(campaign)
        db.flush()

        job = PublishingJob(id=uuid.uuid4(), campaign_id=campaign.id, status="queued", idempotency_key=str(uuid.uuid4()), scheduled_at=datetime.utcnow())
        db.add(job)
        db.commit()
        job_id = str(job.id)
        db.close()

        # Non-admin attempt -> 403
        client_token = self._get_token("client_rep@acme.com", "password")
        if client_token:
            res_fail = self.client.post(f"/api/publishing/jobs/{job_id}/cancel", headers={"Authorization": f"Bearer {client_token}"})
            self.assertEqual(res_fail.status_code, 403)

        # Admin cancels job
        res_cancel = self.client.post(f"/api/publishing/jobs/{job_id}/cancel", headers={"Authorization": f"Bearer {admin_token}"})
        self.assertEqual(res_cancel.status_code, 200)
        self.assertEqual(res_cancel.json()["status"], "cancelled")

        # Cancel already cancelled job -> 400
        res_cancel_twice = self.client.post(f"/api/publishing/jobs/{job_id}/cancel", headers={"Authorization": f"Bearer {admin_token}"})
        self.assertEqual(res_cancel_twice.status_code, 400)

    def test_08_rule3_proof_enforcement(self):
        admin_token = self._get_token()

        db = SessionLocal()
        tenant = db.query(Tenant).first()
        client_row = db.query(Client).first()
        campaign = Campaign(id=uuid.uuid4(), tenant_id=tenant.id, client_id=client_row.id, name="Rule3 Proof Campaign", status="scheduled")
        db.add(campaign)
        db.flush()
        campaign_id = str(campaign.id)

        job = PublishingJob(id=uuid.uuid4(), campaign_id=campaign.id, status="failed", idempotency_key=str(uuid.uuid4()), scheduled_at=datetime.utcnow())
        db.add(job)
        db.commit()
        job_id = str(job.id)
        db.close()

        # Manual handoff without proof -> 422
        res_no_proof = self.client.post(
            f"/api/publishing/jobs/{job_id}/manual-handoff",
            json={},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        self.assertEqual(res_no_proof.status_code, 422)

        # Manual handoff with proof -> 200 and campaign status becomes published
        res_proof = self.client.post(
            f"/api/publishing/jobs/{job_id}/manual-handoff",
            json={"manual_proof": "https://linkedin.com/posts/proof_123"},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        self.assertEqual(res_proof.status_code, 200)
        self.assertEqual(res_proof.json()["manual_proof"], "https://linkedin.com/posts/proof_123")

        # Verify campaign is published
        res_camp = self.client.get(f"/api/campaigns/{campaign_id}", headers={"Authorization": f"Bearer {admin_token}"})
        self.assertEqual(res_camp.status_code, 200)
        self.assertEqual(res_camp.json()["status"], "published")


if __name__ == "__main__":
    unittest.main()
