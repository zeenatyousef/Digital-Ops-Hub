"""
apps/asma-service/seed_test_data.py

One-off script to create a test Tenant -> Client -> BrandProfile chain,
plus a test Campaign, so you have real IDs to use when testing
/marketing/brief, /marketing/calendar, and /marketing/content locally.

Run from the repo root:
    python apps/asma-service/seed_test_data.py

Delete this file (or just don't commit it) once you're done testing —
it's a dev helper, not part of the actual service.
"""

import os
import sys

# Make sure the repo root is on sys.path even if this is run directly
# (python apps/asma-service/seed_test_data.py) instead of as a module.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from packages.database.session import SessionLocal
from packages.database import models

db = SessionLocal()

try:
    tenant = models.Tenant(name="Test Tenant")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    print("tenant_id:", tenant.id)

    client = models.Client(
        tenant_id=tenant.id,
        company_name="Test Client Co",
        contact_email="test@example.com",
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    print("client_id:", client.id)

    bp = models.BrandProfile(
        tenant_id=tenant.id,
        client_id=client.id,
        brand_name="Test Brand",
        brand_voice="Friendly",
        required_wording="halal",
        prohibited_wording="guaranteed,best in the world",
    )
    db.add(bp)
    db.commit()
    db.refresh(bp)
    print("brand_profile_id:", bp.id)

    campaign = models.Campaign(
        client_id=client.id,
        tenant_id=tenant.id,
        name="Test Campaign",
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    print("campaign_id:", campaign.id)

finally:
    db.close()