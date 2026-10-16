import os
import sys
import time
from pathlib import Path

# Add project root to sys.path so 'packages' and 'apps' can be resolved
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import unittest
from fastapi.testclient import TestClient
from uuid import UUID
import uuid
from datetime import datetime

# Set database URL to temp_test.db for clean testing isolation
os.environ["DATABASE_URL"] = "sqlite:///temp_test_ops.db"

from packages.database.session import get_db, engine, Base
from packages.database.models import Tenant, Client, User, ClientRoom, Message, Campaign, ContentVersion, PublishingJob, Defect
from apps.core_gateway.main import app
from apps.core_gateway.scheduler import start_scheduler, stop_scheduler, process_queued_jobs

class TestOperationalHub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Remove any leftover test database
        if os.path.exists("temp_test_ops.db"):
            try:
                os.remove("temp_test_ops.db")
            except Exception:
                pass
                
        # Create all tables in test database
        Base.metadata.create_all(bind=engine)
        
        # Start background scheduler manually for testing
        start_scheduler()
        
        cls.client = TestClient(app)
        
        # Run seeding route to ensure demo users exist
        res = cls.client.post("/api/seed")
        assert res.status_code == 200, "Seeding failed"

    @classmethod
    def tearDownClass(cls):
        # Stop background scheduler
        stop_scheduler()
        
        # Clean up database tables
        Base.metadata.drop_all(bind=engine)
        if os.path.exists("temp_test_ops.db"):
            try:
                os.remove("temp_test_ops.db")
            except Exception:
                pass

    def _get_token(self, email, password):
        res = self.client.post(
            "/api/auth/login",
            data={"username": email, "password": password}
        )
        return res.json()["access_token"]

    def test_01_client_room_privacy(self):
        # 1. Login as designer and client rep
        designer_token = self._get_token("designer@nationalwireless.com", "password")
        client_token = self._get_token("client@acmewireless.com", "password")
        
        room_id = "00000000-0000-0000-0000-0000000000a1"
        
        # 2. Designer sends an external message (visible to client)
        res = self.client.post(
            f"/api/client-rooms/{room_id}/messages",
            json={"content": "Hello client, here is the draft.", "visibility": "external"},
            headers={"Authorization": f"Bearer {designer_token}"}
        )
        self.assertEqual(res.status_code, 201)
        
        # 3. Designer sends an internal note (hidden from client)
        res = self.client.post(
            f"/api/client-rooms/{room_id}/messages",
            json={"content": "Internal note: client voice requirements are high.", "visibility": "internal"},
            headers={"Authorization": f"Bearer {designer_token}"}
        )
        self.assertEqual(res.status_code, 201)
        
        # 4. Retrieve messages as Client Representative (should see 1 message)
        res = self.client.get(
            f"/api/client-rooms/{room_id}/messages",
            headers={"Authorization": f"Bearer {client_token}"}
        )
        self.assertEqual(res.status_code, 200)
        messages = res.json()
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["content"], "Hello client, here is the draft.")
        self.assertEqual(messages[0]["visibility"], "external")
        
        # 5. Retrieve messages as Designer (should see 2 messages)
        res = self.client.get(
            f"/api/client-rooms/{room_id}/messages",
            headers={"Authorization": f"Bearer {designer_token}"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()), 2)

    def test_02_dm_privacy(self):
        # 1. Login as admin, designer and client
        admin_token = self._get_token("atif@nationalwireless.com", "password")
        designer_token = self._get_token("designer@nationalwireless.com", "password")
        client_token = self._get_token("client@acmewireless.com", "password")
        
        # 2. Create DM between Admin and Designer
        res = self.client.post(
            "/api/conversations",
            json={"participant_ids": ["00000000-0000-0000-0000-00000000000e"]}, # Designer ID
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        self.assertEqual(res.status_code, 201)
        conv_id = res.json()["id"]
        
        # 3. Admin sends a DM message
        res = self.client.post(
            f"/api/conversations/{conv_id}/messages",
            json={"content": "Private admin-designer note.", "visibility": "internal"},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        self.assertEqual(res.status_code, 201)
        
        # 4. Client tries to read messages (should fail with 403 Forbidden)
        res = self.client.get(
            f"/api/conversations/{conv_id}/messages",
            headers={"Authorization": f"Bearer {client_token}"}
        )
        self.assertEqual(res.status_code, 403)
        
        # 5. Designer reads messages (should succeed and see the message)
        res = self.client.get(
            f"/api/conversations/{conv_id}/messages",
            headers={"Authorization": f"Bearer {designer_token}"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()[0]["content"], "Private admin-designer note.")

    def test_03_message_workitem_conversion(self):
        # 1. Login as designer
        designer_token = self._get_token("designer@nationalwireless.com", "password")
        room_id = "00000000-0000-0000-0000-0000000000a1"
        
        # 2. Designer sends a bug report message in the client room
        res = self.client.post(
            f"/api/client-rooms/{room_id}/messages",
            json={"content": "There is a layout error in the navbar.", "visibility": "internal"},
            headers={"Authorization": f"Bearer {designer_token}"}
        )
        msg_id = res.json()["id"]
        
        # 3. Convert message to defect
        res = self.client.post(
            f"/api/messages/{msg_id}/convert",
            json={"target_type": "defect", "severity": "high"},
            headers={"Authorization": f"Bearer {designer_token}"}
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["status"], "converted")
        self.assertEqual(data["target_type"], "defect")
        
        # 4. Verify system notification was added to the room stream
        res = self.client.get(
            f"/api/client-rooms/{room_id}/messages",
            headers={"Authorization": f"Bearer {designer_token}"}
        )
        messages = res.json()
        # The last message should be a system notification
        self.assertEqual(messages[-1]["content_type"], "system")
        self.assertIn("Converted message into defect", messages[-1]["content"])

    def test_04_scheduler_daemon_execution(self):
        # 1. Login as admin and designer
        admin_token = self._get_token("atif@nationalwireless.com", "password")
        designer_token = self._get_token("designer@nationalwireless.com", "password")
        client_token = self._get_token("client@acmewireless.com", "password")
        
        # 2. Create campaign
        campaign_payload = {
            "name": "Auto-Publish Campaign",
            "client_id": "00000000-0000-0000-0000-00000000000b",
            "platform": "LinkedIn",
            "language": "English",
            "caption": "Publish this automatically!",
            "cta": "Click now"
        }
        res = self.client.post(
            "/api/campaigns",
            json=campaign_payload,
            headers={"Authorization": f"Bearer {designer_token}"}
        )
        self.assertEqual(res.status_code, 200)
        campaign_id = res.json()["id"]
        version_id = res.json()["versions"][0]["id"]
        
        # 3. Submit for approval
        res = self.client.post(
            f"/api/campaigns/{campaign_id}/submit",
            headers={"Authorization": f"Bearer {designer_token}"}
        )
        self.assertEqual(res.status_code, 200)
        
        # 4. Approve campaign (by Client)
        res = self.client.post(
            f"/api/campaigns/{campaign_id}/approve?version_id={version_id}",
            headers={"Authorization": f"Bearer {client_token}"}
        )
        self.assertEqual(res.status_code, 200)
        
        # 5. Schedule campaign to publish immediately
        res = self.client.post(
            f"/api/campaigns/{campaign_id}/schedule",
            json={},
            headers={"Authorization": f"Bearer {designer_token}"}
        )
        self.assertEqual(res.status_code, 200)
        job_data = res.json()
        self.assertEqual(job_data["status"], "queued")
        job_id = job_data["id"]
        
        # 6. Process queued job via scheduler logic
        process_queued_jobs()
        
        # 7. Check that campaign status remains "scheduled" without proof (Rule 3)
        res = self.client.get(
            f"/api/campaigns/{campaign_id}",
            headers={"Authorization": f"Bearer {designer_token}"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "scheduled")

        # 8. Submit manual proof for the job -> transitions campaign to "published"
        admin_token = self._get_token("admin@nationalwireless.com", "password")
        res = self.client.post(
            f"/api/publishing/jobs/{job_id}/manual-handoff",
            json={"manual_proof": "https://instagram.com/p/manual_proof_123"},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        self.assertEqual(res.status_code, 200)

        # 9. Verify campaign status is now "published"
        res = self.client.get(
            f"/api/campaigns/{campaign_id}",
            headers={"Authorization": f"Bearer {designer_token}"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "published")

if __name__ == "__main__":
    unittest.main()
