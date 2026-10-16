import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import unittest
from fastapi.testclient import TestClient
from uuid import UUID
import uuid

os.environ["ALLOW_SQLITE_FALLBACK"] = "true"
os.environ["ALLOW_SEED"] = "true"

from packages.database.session import engine, Base, SessionLocal
from packages.database.models import Tenant, User, KBArticle, AuditEvent
from apps.core_gateway.main import app

from apps.core_gateway.security import get_password_hash

class TestKBArticles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)
        res = cls.client.post("/api/seed")
        assert res.status_code == 200

        # Create Tenant B and Admin B for cross-tenant testing
        db = SessionLocal()
        existing_b = db.query(Tenant).filter(Tenant.id == UUID("00000000-0000-0000-0000-00000000000b")).first()
        if not existing_b:
            tenant_b = Tenant(id=UUID("00000000-0000-0000-0000-00000000000b"), name="Tenant B", status="active")
            db.add(tenant_b)
            user_b = User(
                id=UUID("00000000-0000-0000-0000-00000000002b"),
                tenant_id=tenant_b.id,
                email="adminb@tenantb.com",
                password_hash=get_password_hash("password"),
                full_name="Admin B",
                role="tenant_admin",
                is_active=True
            )
            db.add(user_b)
            db.commit()
        db.close()

    @classmethod
    def tearDownClass(cls):
        pass

    def get_token(self, email, password="password"):
        res = self.client.post("/api/auth/login", data={"username": email, "password": password})
        self.assertEqual(res.status_code, 200, f"Login failed for {email}: {res.text}")
        return res.json()["access_token"]

    def test_01_create_kb_article_draft(self):
        admin_token = self.get_token("admin@nationalwireless.com")
        headers = {"Authorization": f"Bearer {admin_token}"}
        
        payload = {
            "title": "FBR Invoice Timeout Guide",
            "content": "Step 1: Check gateway URL. Step 2: Restart Oracle listener.",
            "product": "FBR Digital Invoicing",
            "risk_level": "medium"
        }
        res = self.client.post("/api/kb-articles", json=payload, headers=headers)
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["title"], payload["title"])
        self.assertEqual(data["review_status"], "draft")
        self.assertIn("id", data)
        self.kb_id = data["id"]

        # Check audit event for creation
        db = SessionLocal()
        audit = db.query(AuditEvent).filter(AuditEvent.action_name == "create_kb_article", AuditEvent.entity_id == UUID(data["id"])).first()
        self.assertIsNotNone(audit, "Audit event for KB article creation missing!")
        self.assertEqual(audit.entity_name, "KBArticle")
        db.close()

    def test_02_draft_not_retrieved_until_approved(self):
        admin_token = self.get_token("admin@nationalwireless.com")
        headers = {"Authorization": f"Bearer {admin_token}"}

        # 1. Create a new article -> returns draft
        payload = {
            "title": "POS Barcode Calibration",
            "content": "Calibrate scanner frequency via settings menu.",
            "product": "POS",
            "risk_level": "low"
        }
        create_res = self.client.post("/api/kb-articles", json=payload, headers=headers)
        self.assertEqual(create_res.status_code, 201)
        article_id = create_res.json()["id"]
        self.assertEqual(create_res.json()["review_status"], "draft")

        # 2. Check /api/support/retrieve (vector/keyword search) -> Draft MUST NOT be returned
        retrieve_res = self.client.post(
            "/api/support/retrieve",
            json={"product": "POS", "query": "barcode"},
            headers=headers
        )
        self.assertEqual(retrieve_res.status_code, 200)
        articles = retrieve_res.json().get("articles", [])
        retrieved_ids = [a["article_id"] for a in articles]
        self.assertNotIn(article_id, retrieved_ids, "Draft article leaked into retrieval endpoint!")

        # 3. Approve article
        approve_res = self.client.post(f"/api/kb-articles/{article_id}/approve", headers=headers)
        self.assertEqual(approve_res.status_code, 200)
        self.assertEqual(approve_res.json()["review_status"], "approved")

        # Check audit event for approval
        db = SessionLocal()
        audit_approve = db.query(AuditEvent).filter(AuditEvent.action_name == "approve_kb_article", AuditEvent.entity_id == UUID(article_id)).first()
        self.assertIsNotNone(audit_approve, "Audit event for KB article approval missing!")
        self.assertEqual(audit_approve.entity_name, "KBArticle")
        db.close()

        # 4. Check /api/support/retrieve again -> Approved article MUST now be returned
        retrieve_res_after = self.client.post(
            "/api/support/retrieve",
            json={"product": "POS", "query": "barcode"},
            headers=headers
        )
        self.assertEqual(retrieve_res_after.status_code, 200)
        articles_after = retrieve_res_after.json().get("articles", [])
        retrieved_ids_after = [a["article_id"] for a in articles_after]
        self.assertIn(article_id, retrieved_ids_after, "Approved article missing from retrieval endpoint!")

    def test_03_role_permission_checks(self):
        designer_token = self.get_token("designer@nationalwireless.com")
        client_rep_token = self.get_token("client@acmewireless.com")

        payload = {"title": "Test Article", "content": "Test content"}

        # Designer creates KB article -> 403
        res = self.client.post("/api/kb-articles", json=payload, headers={"Authorization": f"Bearer {designer_token}"})
        self.assertEqual(res.status_code, 403)

        # Client Rep creates KB article -> 403
        res = self.client.post("/api/kb-articles", json=payload, headers={"Authorization": f"Bearer {client_rep_token}"})
        self.assertEqual(res.status_code, 403)

        # Create valid article with admin
        admin_token = self.get_token("admin@nationalwireless.com")
        art = self.client.post("/api/kb-articles", json=payload, headers={"Authorization": f"Bearer {admin_token}"}).json()
        art_id = art["id"]

        # Designer approves KB article -> 403
        res = self.client.post(f"/api/kb-articles/{art_id}/approve", headers={"Authorization": f"Bearer {designer_token}"})
        self.assertEqual(res.status_code, 403)

        # Client Rep approves KB article -> 403
        res = self.client.post(f"/api/kb-articles/{art_id}/approve", headers={"Authorization": f"Bearer {client_rep_token}"})
        self.assertEqual(res.status_code, 403)

    def test_04_cross_tenant_isolation(self):
        admin_a_token = self.get_token("admin@nationalwireless.com")
        admin_b_token = self.get_token("adminb@tenantb.com")

        # Admin A creates article in Tenant A
        art_a = self.client.post(
            "/api/kb-articles",
            json={"title": "Tenant A Secret Guide", "content": "Tenant A only"},
            headers={"Authorization": f"Bearer {admin_a_token}"}
        ).json()
        art_a_id = art_a["id"]

        # Admin B in Tenant B tries to approve Tenant A's article -> 404
        res = self.client.post(
            f"/api/kb-articles/{art_a_id}/approve",
            headers={"Authorization": f"Bearer {admin_b_token}"}
        )
        self.assertEqual(res.status_code, 404)

if __name__ == "__main__":
    unittest.main()
