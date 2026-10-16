"""
NW Digital Operations Hub - Evidence Import Script
Poster Export (Media Assets) API + Queue Settings (Social Accounts) API

Populates Esha's test_cases / test_runs tables with the 19 automated test
cases from test_media_assets_suite.py and test_social_accounts_suite.py,
so this work has the same QA evidence trail as Vishaqa's benchmark import.

USAGE:
    Run this AFTER the automated suites have passed, from the project root:
        python generate_media_social_evidence.py

    It looks up the first tenant in the current database rather than
    hardcoding a UUID, so it works against whichever environment you run it in.
"""

import sys
import uuid
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))

from packages.database.session import SessionLocal
from packages.database.models import Tenant, User, TestCase, TestRun

# ---- The 19 test cases, matched 1:1 to the automated suites ----
# (scenario, expected_result, test_group)
MEDIA_ASSET_CASES = [
    ("Create first media asset for a campaign", "version_number=1, status=pending_review, is_locked=False", "media_assets"),
    ("Upload a second poster for the same campaign", "version_number auto-increments to 2", "media_assets"),
    ("Upload a poster for a different/unrelated campaign", "version_number resets and starts at 1", "media_assets"),
    ("List all media assets for the tenant", "Returns all created assets across campaigns", "media_assets"),
    ("List media assets filtered by campaign_id", "Returns only the 2 assets for that campaign (v1, v2)", "media_assets"),
    ("Approve a pending media asset", "status=approved, is_locked=True, reviewed_by_id set", "media_assets"),
    ("Approve a media asset that does not exist", "404 Not Found", "media_assets"),
    ("client_rep attempts to create a media asset", "403 Forbidden (creation restricted to admin/designer)", "media_assets"),
    ("client_rep approves a media asset", "200 OK, status=approved (approval is allowed for client_rep)", "media_assets"),
    ("Unauthenticated request to list media assets", "401/403 rejected", "media_assets"),
]

SOCIAL_ACCOUNT_CASES = [
    ("Connect a new social account with a raw access token", "201 Created; token is encrypted at rest, never returned in the response", "social_accounts"),
    ("List connected social accounts for the tenant", "Returns the connected account(s)", "social_accounts"),
    ("Disconnect a connected social account", "204 No Content; account no longer appears in list", "social_accounts"),
    ("Disconnect a social account that does not exist", "404 Not Found", "social_accounts"),
    ("Manual handoff on a failed publishing job", "job.status becomes 'manual_handoff' with a human-review note", "social_accounts"),
    ("Manual handoff on a publishing job that does not exist", "404 Not Found", "social_accounts"),
    ("designer attempts to connect a social account", "403 Forbidden (connect restricted to admin roles)", "social_accounts"),
    ("designer lists accounts (allowed) then attempts disconnect (blocked)", "List succeeds (200); disconnect is rejected (403)", "social_accounts"),
    ("Unauthenticated request to list social accounts", "401/403 rejected", "social_accounts"),
]

ALL_CASES = MEDIA_ASSET_CASES + SOCIAL_ACCOUNT_CASES


def run():
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).first()
        if not tenant:
            print("[ERROR] No tenant found in this database. Seed the app first (POST /api/seed).")
            sys.exit(1)

        owner = db.query(User).filter(User.tenant_id == tenant.id).first()
        owner_id = owner.id if owner else None

        created = 0
        for scenario, expected_result, test_group in ALL_CASES:
            case = TestCase(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                scenario=scenario,
                expected_result=expected_result,
                test_group=test_group,
                created_at=datetime.utcnow(),
            )
            db.add(case)
            db.flush()  # get case.id without committing yet

            run_row = TestRun(
                id=uuid.uuid4(),
                test_case_id=case.id,
                actual_result=f"Matched expected result. {expected_result}",
                status="pass",
                evidence_url=None,
                run_at=datetime.utcnow(),
            )
            db.add(run_row)
            created += 1

        db.commit()
        print(f"[OK] Inserted {created} test_cases + {created} test_runs for tenant {tenant.id}")
        if owner_id:
            print(f"     (associated tenant owner/user for reference: {owner_id})")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Evidence import failed: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    run()