"""
One-time migration for DEF-007 — moves esha-service's existing data from
any orphaned/drifted "esha-dev-tenant" row(s) over to the canonical demo
tenant UUID (00000000-0000-0000-0000-00000000000a), so data seeded before
the get_or_create_dev_tenant() fix (main.py / seed_data.py) becomes visible
under the real demo Super Admin login instead of staying orphaned.

IMPORTANT: this handles BOTH cases —
1. Canonical tenant does not exist yet -> old row's id is reassigned in place.
2. Canonical tenant ALREADY exists (e.g. auto-created fresh by the fixed
   get_or_create_dev_tenant() during a test run) AND an old drifted row
   with a different id also exists -> child rows (clients, hashtag_sets,
   quality_runs, analytics_events, report_snapshots) are individually
   re-pointed from the old tenant_id to the canonical one, then the old,
   now-empty tenant row is deleted. This second case is the one the
   original version of this script silently missed — it exited early as
   soon as it saw the canonical tenant present, without checking whether
   an orphaned row (and orphaned data) also still existed alongside it.

Safe to run multiple times — becomes a no-op once there is exactly one
tenant row and no drifted duplicates remain.

Run with:  python -m migrate_tenant_to_canonical
(from inside apps/esha-service, with venv active and Docker's Postgres running)
"""
import sys
import os
from uuid import UUID

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from packages.database.session import SessionLocal
from packages.database.models import (
    Tenant, Client, HashtagSet, QualityRun, AnalyticsEvent, ReportSnapshot
)

CANONICAL_TENANT_ID = UUID("00000000-0000-0000-0000-00000000000a")

# Every model that carries a tenant_id FK and needs re-pointing if an
# orphaned tenant row is found. Add to this list if the shared schema adds
# more tenant-scoped tables later.
TENANT_SCOPED_MODELS = [Client, HashtagSet, QualityRun, AnalyticsEvent, ReportSnapshot]


def _migrate_child_rows(db, old_id, new_id):
    """Re-points every tenant-scoped row from old_id to new_id. Returns a
    dict of model name -> rows moved, so the operator can see exactly what
    was touched before trusting the demo data."""
    moved = {}
    for model in TENANT_SCOPED_MODELS:
        rows = db.query(model).filter(model.tenant_id == old_id).all()
        for row in rows:
            row.tenant_id = new_id
        moved[model.__name__] = len(rows)
    return moved


def main():
    db = SessionLocal()
    try:
        canonical = db.query(Tenant).filter(Tenant.id == CANONICAL_TENANT_ID).first()

        # Any tenant row named "esha-dev-tenant" that is NOT the canonical
        # row is orphaned/drifted — this is the exact bug DEF-007 describes.
        drifted_rows = (
            db.query(Tenant)
            .filter(Tenant.name == "esha-dev-tenant", Tenant.id != CANONICAL_TENANT_ID)
            .all()
        )

        if not canonical and not drifted_rows:
            print("No existing 'esha-dev-tenant' row found at all. "
                  "get_or_create_dev_tenant() will create the canonical tenant on next run.")
            return

        if not canonical and len(drifted_rows) == 1:
            # Simple case: no canonical row yet, exactly one drifted row —
            # just reassign its id in place.
            old_id = drifted_rows[0].id
            print(f"Reassigning tenant id {old_id} -> {CANONICAL_TENANT_ID} ...")
            drifted_rows[0].id = CANONICAL_TENANT_ID
            db.commit()
            print("Done.")
            return

        if not drifted_rows:
            print(f"Canonical tenant present ({CANONICAL_TENANT_ID}) and no orphaned "
                  f"'esha-dev-tenant' rows found under a different id. Nothing to do.")
            return

        # Canonical exists AND one or more orphaned rows also exist — this is
        # the case the original script silently missed. Migrate every
        # tenant-scoped child row off each orphaned id onto the canonical one.
        print(f"Canonical tenant present ({CANONICAL_TENANT_ID}). "
              f"Found {len(drifted_rows)} orphaned 'esha-dev-tenant' row(s) with different ids:")
        for row in drifted_rows:
            print(f"  - {row.id}")

        for row in drifted_rows:
            print(f"\nMigrating child rows from {row.id} -> {CANONICAL_TENANT_ID} ...")
            moved = _migrate_child_rows(db, row.id, CANONICAL_TENANT_ID)
            for model_name, count in moved.items():
                if count:
                    print(f"  {model_name}: {count} row(s) re-pointed")
            db.delete(row)  # now-empty orphaned tenant row

        db.commit()
        print("\nDone. Verify with:")
        print("  SELECT id, name FROM tenants WHERE name = 'esha-dev-tenant';")
        print("  -- should return exactly ONE row, with the canonical id.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
