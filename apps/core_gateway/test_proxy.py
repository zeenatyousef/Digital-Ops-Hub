import os
import sys
from pathlib import Path

# Add project root to sys.path so 'packages' and 'apps' can be resolved
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import unittest
from fastapi.testclient import TestClient
from uuid import UUID
import uuid

# Set database URL to temp_test.db for clean testing isolation
os.environ["DATABASE_URL"] = "sqlite:///temp_test_ops.db"

# Set downstream service URLs to ports that are guaranteed to be empty/offline during this test
os.environ["VISHAQA_API_URL"] = "http://localhost:59991"
os.environ["ASMA_API_URL"] = "http://localhost:59992"
os.environ["ESHA_API_URL"] = "http://localhost:59993"

from packages.database.session import get_db, engine, Base
from apps.core_gateway.main import app
from apps.core_gateway.scheduler import start_scheduler, stop_scheduler


class TestIntegrationProxy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Remove any leftover test database
        try:
            Base.metadata.drop_all(bind=engine)
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

    def test_support_classify_offline_fallback(self):
        # 1. Login as designer
        token = self._get_token("designer@nationalwireless.com", "password")
        
        # 2. Call support classify endpoint (downstream vishaqa-service is offline)
        res = self.client.post(
            "/api/support/classify",
            json={"tenant_id": "00000000-0000-0000-0000-000000000000", "message": "Production system is down!"},
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # 3. Verify it falls back successfully to the default offline state
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["product"], "Unclassified")
        self.assertEqual(data["category"], "General Support / Service Offline Fallback")
        self.assertEqual(data["severity"], "Medium")
        self.assertTrue(data["human_required"])
        self.assertEqual(data["service_version"], "v1.0-fallback")

    def test_support_predictions_correct_offline_fallback(self):
        token = self._get_token("designer@nationalwireless.com", "password")
        prediction_uuid = str(uuid.uuid4())
        
        # Call corrections endpoint while offline
        res = self.client.post(
            "/api/support/predictions/correct",
            json={
                "tenant_id": "00000000-0000-0000-0000-000000000000",
                "prediction_id": prediction_uuid,
                "actual_category": "POS device offline"
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Verify it falls back safely to corrected=False
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["prediction_id"], prediction_uuid)
        self.assertEqual(data["actual_category"], "POS device offline")
        self.assertFalse(data["corrected"])

    def test_marketing_brief_offline_error(self):
        token = self._get_token("designer@nationalwireless.com", "password")
        
        # Call marketing brief endpoint (downstream asma-service is offline)
        res = self.client.post(
            "/api/marketing/brief",
            json={
                "client_id": "00000000-0000-0000-0000-00000000000b",
                "brand_profile_id": "00000000-0000-0000-0000-00000000000c", # dummy uuid
                "source_message_ids": [],
                "raw_text": "Sample campaign launch text."
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Verify it returns 502 Bad Gateway with user-facing message instead of raw server error
        self.assertEqual(res.status_code, 502)
        data = res.json()
        self.assertIn("offline", data["detail"])

    def test_qa_analyze_offline_fallback(self):
        token = self._get_token("designer@nationalwireless.com", "password")
        
        # Call Esha's QA analyze endpoint (downstream esha-service is offline)
        res = self.client.post(
            "/api/qa/analyze",
            json={"text": "Click here to buy our next-gen wireless plans!", "platform": "LinkedIn"},
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Verify it falls back to passing all checks
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["score"], 1.0)
        self.assertTrue(all(c["passed"] for c in data["checks"]))
        self.assertEqual(data["issues"][0]["severity"], "low")
        self.assertIn("offline", data["issues"][0]["message"])

    def test_analytics_monthly_report_query_params_forwarding(self):
        token = self._get_token("atif@nationalwireless.com", "password")
        from unittest.mock import patch
        
        with patch("apps.core_gateway.routers.proxy._forward_get") as mock_forward:
            mock_forward.return_value = {"status": "success"}
            
            res = self.client.get(
                "/api/analytics/monthly-report?client=bebop&month=2026-08",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            self.assertEqual(res.status_code, 200)
            mock_forward.assert_called_once()
            called_args = mock_forward.call_args
            params = called_args[0][3]
            self.assertEqual(params["client"], "bebop")
            self.assertEqual(params["month"], "2026-08")
            self.assertIn("tenant_id", params)

    def test_analytics_dashboard_query_params_forwarding(self):
        token = self._get_token("atif@nationalwireless.com", "password")
        from unittest.mock import patch
        
        with patch("apps.core_gateway.routers.proxy._forward_get") as mock_forward:
            mock_forward.return_value = {"status": "success"}
            
            res = self.client.get(
                "/api/analytics/dashboard?client=bebop&metric=reach",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            self.assertEqual(res.status_code, 200)
            mock_forward.assert_called_once()
            called_args = mock_forward.call_args
            params = called_args[0][3]
            self.assertEqual(params["client"], "bebop")
            self.assertEqual(params["metric"], "reach")
            self.assertIn("tenant_id", params)

    def test_analytics_client_health_offline_fallback(self):
        token = self._get_token("atif@nationalwireless.com", "password")
        res = self.client.get(
            "/api/analytics/client-health",
            headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total_reach"], 184000)
        self.assertEqual(data["engagement_rate"], 6.8)
        self.assertIn("client_signals", data)
        self.assertIn("performance_trend", data)
        self.assertEqual(data["service_version"], "v1.0-fallback")


if __name__ == "__main__":
    unittest.main()

