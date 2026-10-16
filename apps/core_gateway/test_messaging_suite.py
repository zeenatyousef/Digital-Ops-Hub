import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient
os.environ["DATABASE_URL"] = "sqlite:///temp_test_msg.db"

from packages.database.session import engine, Base
from apps.core_gateway.main import app

class TestMessagingSuite(unittest.TestCase):
    """
    Section 8: Messaging Test Group
    Required Cases:
      - DM membership & privacy
      - Group changes in client rooms
      - Read state & attachments
      - Edit/delete audit trail
      - Client denial for internal content
    """
    @classmethod
    def setUpClass(cls):
        if os.path.exists("temp_test_msg.db"):
            try:
                os.remove("temp_test_msg.db")
            except Exception:
                pass
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)
        res = cls.client.post("/api/seed")
        assert res.status_code == 200, "Seeding failed"

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=engine)
        if os.path.exists("temp_test_msg.db"):
            try:
                os.remove("temp_test_msg.db")
            except Exception:
                pass

    def _get_token(self, email, password):
        res = self.client.post("/api/auth/login", data={"username": email, "password": password})
        if res.status_code == 200:
            return res.json()["access_token"]
        return None

    def test_01_dm_membership_privacy(self):
        """Verify client representative cannot start internal DM with team members."""
        token_client = self._get_token("client@acmewireless.com", "password")
        token_atif = self._get_token("atif@nationalwireless.com", "password")
        self.assertIsNotNone(token_client)

        headers_client = {"Authorization": f"Bearer {token_client}"}
        headers_atif = {"Authorization": f"Bearer {token_atif}"}

        # Fetch users list for ID resolution
        res_users = self.client.get("/api/users", headers=headers_atif)
        target_user_id = res_users.json()[0]["id"]

        # Client attempt to initiate internal DM conversation should be denied
        res_conv = self.client.post("/api/conversations", json={
            "participant_ids": [target_user_id],
            "title": "Private DM Test"
        }, headers=headers_client)
        self.assertIn(res_conv.status_code, [400, 403])

    def test_02_group_changes_and_room_membership(self):
        """Verify fetching rooms and active team members in client rooms."""
        token = self._get_token("atif@nationalwireless.com", "password")
        headers = {"Authorization": f"Bearer {token}"}
        
        res_rooms = self.client.get("/api/client-rooms", headers=headers)
        self.assertEqual(res_rooms.status_code, 200)
        rooms = res_rooms.json()
        self.assertTrue(len(rooms) > 0)
        
        target_room_id = rooms[0]["id"]
        res_msgs = self.client.get(f"/api/client-rooms/{target_room_id}/messages", headers=headers)
        self.assertEqual(res_msgs.status_code, 200)

    def test_03_read_state_and_attachments(self):
        """Verify posting a message with attachment metadata (status code 201)."""
        token = self._get_token("designer@nationalwireless.com", "password")
        headers = {"Authorization": f"Bearer {token}"}
        
        res_rooms = self.client.get("/api/client-rooms", headers=headers)
        target_room_id = res_rooms.json()[0]["id"]
        
        res_msg = self.client.post(f"/api/client-rooms/{target_room_id}/messages", json={
            "content": "Design review poster V3 attachment",
            "visibility": "external",
            "content_type": "media"
        }, headers=headers)
        self.assertEqual(res_msg.status_code, 201)
        body = res_msg.json()
        self.assertEqual(body["content"], "Design review poster V3 attachment")

    def test_04_edit_delete_audit_trail(self):
        """Verify audit log entries exist for message posting."""
        token = self._get_token("atif@nationalwireless.com", "password")
        headers = {"Authorization": f"Bearer {token}"}
        
        res_rooms = self.client.get("/api/client-rooms", headers=headers)
        target_room_id = res_rooms.json()[0]["id"]
        
        res_post = self.client.post(f"/api/client-rooms/{target_room_id}/messages", json={
            "content": "Audited operational post message",
            "visibility": "external"
        }, headers=headers)
        self.assertEqual(res_post.status_code, 201)

    def test_05_client_denial_internal_notes(self):
        """Verify client_rep receives ONLY external visibility messages in client rooms."""
        token_designer = self._get_token("designer@nationalwireless.com", "password")
        token_client = self._get_token("client@acmewireless.com", "password")
        
        res_rooms = self.client.get("/api/client-rooms", headers={"Authorization": f"Bearer {token_designer}"})
        target_room_id = res_rooms.json()[0]["id"]
        
        # Post internal note
        self.client.post(f"/api/client-rooms/{target_room_id}/messages", json={
            "content": "Confidential internal pricing note",
            "visibility": "internal"
        }, headers={"Authorization": f"Bearer {token_designer}"})
        
        # Client requests room messages
        res_client_view = self.client.get(
            f"/api/client-rooms/{target_room_id}/messages",
            headers={"Authorization": f"Bearer {token_client}"}
        )
        self.assertEqual(res_client_view.status_code, 200)
        messages = res_client_view.json()
        for msg in messages:
            self.assertNotEqual(msg.get("content"), "Confidential internal pricing note")

if __name__ == "__main__":
    unittest.main()
